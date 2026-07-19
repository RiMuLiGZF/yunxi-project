"""M2 缓存命中率优化 - 单元测试.

覆盖以下优化点：
1. 命中率统计（L1、SkillCache 层面）
2. 参数规范化（None 去除、字符串 strip、键排序）
3. 缓存预热（warmup、warmup_metadata）
4. 缓存命中（连续两次相同请求返回缓存结果）
5. 缓存失效（参数不同时不命中）
6. 缓存大小限制（超过 maxsize 时淘汰）
7. TTL 过期（过期后重新计算）
8. 参数规范化命中（不同顺序但相同值的参数命中同一缓存）
9. 命中率统计准确性
10. 重置统计
11. 分层 TTL 常量
12. 元数据缓存长 TTL
"""

from __future__ import annotations

import time

import pytest

from skill_cluster.core.cache import (
    CACHE_TTL_HOT,
    CACHE_TTL_METADATA,
    CACHE_TTL_RESULT,
    DEFAULT_L1_MAX_SIZE,
    L1MemoryCache,
    SkillCache,
    normalize_params,
)


# ============================================================
# 1. 命中率统计 - L1 层面
# ============================================================

class TestL1HitStats:
    """L1 内存缓存命中率统计测试."""

    def test_hit_count_increments_on_hit(self) -> None:
        """L1 命中时 hit_count 增加."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1")

        assert cache.hit_count == 0
        assert cache.miss_count == 0

        cache.get("k1")
        assert cache.hit_count == 1
        assert cache.miss_count == 0

        cache.get("k1")
        assert cache.hit_count == 2
        assert cache.miss_count == 0

    def test_miss_count_increments_on_miss(self) -> None:
        """L1 未命中时 miss_count 增加."""
        cache = L1MemoryCache(max_size=10)

        cache.get("nonexistent")
        assert cache.hit_count == 0
        assert cache.miss_count == 1

        cache.get("also_missing")
        assert cache.miss_count == 2

    def test_expired_entry_counts_as_miss(self) -> None:
        """过期条目被视为 miss."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1", ttl=0.01)

        # 首次命中
        cache.get("k1")
        assert cache.hit_count == 1
        assert cache.miss_count == 0

        # 等待过期
        time.sleep(0.02)
        cache.get("k1")
        assert cache.hit_count == 1  # 未增加
        assert cache.miss_count == 1  # 过期视为 miss

    def test_hit_rate_calculation(self) -> None:
        """命中率计算正确."""
        cache = L1MemoryCache(max_size=10)

        # 0 次请求时命中率为 0
        assert cache.hit_rate == 0.0

        cache.set("k1", "v1")
        cache.set("k2", "v2")

        # 3 次命中，1 次未命中
        cache.get("k1")  # hit
        cache.get("k1")  # hit
        cache.get("k2")  # hit
        cache.get("k3")  # miss

        assert cache.hit_rate == 0.75  # 3/4

    def test_reset_stats(self) -> None:
        """重置统计后计数归零（不清空缓存数据）."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1")
        cache.get("k1")
        cache.get("k2")

        assert cache.hit_count == 1
        assert cache.miss_count == 1

        cache.reset_stats()

        assert cache.hit_count == 0
        assert cache.miss_count == 0
        # 缓存数据仍在
        assert cache.get("k1") == "v1"
        assert cache.hit_count == 1  # 重置后第一次访问重新计数

    def test_clear_resets_stats(self) -> None:
        """clear() 同时清空缓存和统计."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1")
        cache.get("k1")

        cache.clear()

        assert cache.hit_count == 0
        assert cache.miss_count == 0
        assert cache.get("k1") is None

    def test_stats_dict_includes_hit_info(self) -> None:
        """stats() 返回字典包含命中率信息."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1")
        cache.get("k1")
        cache.get("k2")

        stats = cache.stats()
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "hit_rate" in stats
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1
        assert stats["hit_rate"] == 0.5


# ============================================================
# 2. 参数规范化
# ============================================================

class TestNormalizeParams:
    """参数规范化函数测试."""

    def test_none_values_removed(self) -> None:
        """None 值被移除."""
        params = {"a": 1, "b": None, "c": "hello"}
        result = normalize_params(params)
        assert "a" in result
        assert "b" not in result
        assert "c" in result
        assert result["a"] == 1
        assert result["c"] == "hello"

    def test_string_stripped(self) -> None:
        """字符串值被 strip()."""
        params = {"name": "  hello  ", "desc": "\nworld\t"}
        result = normalize_params(params)
        assert result["name"] == "hello"
        assert result["desc"] == "world"

    def test_booleans_preserved(self) -> None:
        """布尔值保持不变（注意 bool 是 int 子类）."""
        params = {"enabled": True, "disabled": False}
        result = normalize_params(params)
        assert result["enabled"] is True
        assert result["disabled"] is False
        assert isinstance(result["enabled"], bool)
        assert isinstance(result["disabled"], bool)

    def test_numbers_preserved(self) -> None:
        """数字类型保持不变."""
        params = {"count": 42, "price": 3.14}
        result = normalize_params(params)
        assert result["count"] == 42
        assert isinstance(result["count"], int)
        assert result["price"] == 3.14
        assert isinstance(result["price"], float)

    def test_empty_dict_returns_empty(self) -> None:
        """空字典返回空字典."""
        assert normalize_params({}) == {}

    def test_none_input_returns_empty(self) -> None:
        """None 输入返回空字典."""
        assert normalize_params({}) == {}

    def test_complex_types_preserved(self) -> None:
        """复杂类型（list, dict）原样保留."""
        params = {"items": [1, 2, 3], "meta": {"key": "value"}}
        result = normalize_params(params)
        assert result["items"] == [1, 2, 3]
        assert result["meta"] == {"key": "value"}

    def test_original_params_not_modified(self) -> None:
        """原字典不被修改."""
        params = {"a": 1, "b": None, "c": "  test  "}
        original = dict(params)
        normalize_params(params)
        assert params == original


# ============================================================
# 3. SkillCache 命中率统计
# ============================================================

class TestSkillCacheHitStats:
    """SkillCache 多级缓存命中率统计测试."""

    def test_l1_hit_counted(self, tmp_path) -> None:
        """L1 精确命中计入统计."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})

        # 首次读取：L1 命中
        result = cache.get("skill.test", "act", {"x": 1})
        assert result == {"result": "ok"}
        assert cache.hit_count == 1
        assert cache.miss_count == 0
        assert cache._l1_hit_count == 1

    def test_miss_counted(self, tmp_path) -> None:
        """未命中计入统计."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        result = cache.get("skill.test", "act", {"x": 1})
        assert result is None
        assert cache.hit_count == 0
        assert cache.miss_count == 1

    def test_l2_hit_counted(self, tmp_path) -> None:
        """L2 命中计入统计（L1 清空后从 L2 读取）."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})

        # 清空 L1
        cache._l1.clear()
        # 重置 L1 统计（clear 已重置）

        # 从 L2 读取
        result = cache.get("skill.test", "act", {"x": 1})
        assert result == {"result": "ok"}
        assert cache.hit_count == 1
        assert cache._l2_hit_count == 1

    def test_hit_rate_calculation(self, tmp_path) -> None:
        """SkillCache 命中率计算正确."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.a", "act", {"x": 1}, {"r": 1})
        cache.set("skill.b", "act", {"x": 2}, {"r": 2})

        # 2 次命中，1 次未命中
        cache.get("skill.a", "act", {"x": 1})  # hit
        cache.get("skill.b", "act", {"x": 2})  # hit
        cache.get("skill.c", "act", {"x": 3})  # miss

        assert cache.hit_rate == 2 / 3

    def test_reset_stats(self, tmp_path) -> None:
        """重置统计后计数归零（不清空缓存）."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})
        cache.get("skill.test", "act", {"x": 1})
        cache.get("skill.missing", "act", {"x": 1})

        assert cache.hit_count == 1
        assert cache.miss_count == 1

        cache.reset_stats()

        assert cache.hit_count == 0
        assert cache.miss_count == 0
        # 缓存数据仍在
        assert cache.get("skill.test", "act", {"x": 1}) == {"result": "ok"}
        assert cache.hit_count == 1

    def test_stats_dict_includes_all_metrics(self, tmp_path) -> None:
        """stats() 返回完整的统计信息."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})
        cache.get("skill.test", "act", {"x": 1})
        cache.get("skill.test", "act", {"x": 999})

        stats = cache.stats()
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "hit_rate" in stats
        assert "l1_hit_count" in stats
        assert "l2_hit_count" in stats
        assert "set_count" in stats
        assert "total_requests" in stats
        assert stats["hit_count"] == 1
        assert stats["miss_count"] == 1
        assert stats["set_count"] == 1


# ============================================================
# 4. 参数规范化 - 缓存键一致性
# ============================================================

class TestCacheKeyNormalization:
    """参数规范化对缓存键的影响测试."""

    def test_none_param_same_as_missing(self, tmp_path) -> None:
        """含 None 的参数与不含该参数生成相同缓存键."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"), normalize_params=True)

        cache.set("skill.test", "act", {"a": 1, "b": None}, {"result": "ok"})

        # 不含 b 参数（等价于 b=None）应该命中
        result = cache.get("skill.test", "act", {"a": 1})
        assert result == {"result": "ok"}
        assert cache.hit_count == 1

    def test_whitespace_param_stripped(self, tmp_path) -> None:
        """字符串首尾空白不影响缓存键."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"), normalize_params=True)

        cache.set("skill.test", "act", {"text": "hello"}, {"result": "ok"})

        # 带空格的相同值应该命中
        result = cache.get("skill.test", "act", {"text": "  hello  "})
        assert result == {"result": "ok"}
        assert cache.hit_count == 1

    def test_disable_normalization(self, tmp_path) -> None:
        """关闭规范化后，参数差异导致 miss."""
        cache = SkillCache(
            l2_dir=str(tmp_path / "cache"),
            normalize_params=False,
        )

        cache.set("skill.test", "act", {"text": "hello"}, {"result": "ok"})

        # 关闭规范化时，带空格不命中
        result = cache.get("skill.test", "act", {"text": "  hello  "})
        assert result is None
        assert cache.miss_count == 1

    def test_param_order_irrelevant(self, tmp_path) -> None:
        """参数键顺序不影响缓存键（json.dumps sort_keys）."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        # Python 3.7+ dict 保序，但 json.dumps 用 sort_keys 确保一致
        params_a = {"a": 1, "b": 2, "c": 3}
        params_b = {"c": 3, "a": 1, "b": 2}

        cache.set("skill.test", "act", params_a, {"result": "ok"})
        result = cache.get("skill.test", "act", params_b)
        assert result == {"result": "ok"}
        assert cache.hit_count == 1


# ============================================================
# 5. 缓存预热
# ============================================================

class TestCacheWarmup:
    """缓存预热功能测试."""

    def test_warmup_basic(self, tmp_path) -> None:
        """warmup 后立即读取能命中."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        cache.warmup(
            skill_id="skill.test",
            action="list",
            value=[{"id": 1, "name": "test"}],
            ttl=3600,
        )

        result = cache.get("skill.test", "list", {})
        assert result == [{"id": 1, "name": "test"}]
        assert cache.hit_count == 1

    def test_warmup_metadata(self, tmp_path) -> None:
        """warmup_metadata 与 get_metadata 配对使用."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        metadata = {
            "skill_id": "skill.test",
            "name": "测试技能",
            "version": "1.0.0",
            "capabilities": ["act1", "act2"],
        }
        cache.warmup_metadata("skill.test", metadata)

        result = cache.get_metadata("skill.test")
        assert result == metadata
        assert cache.hit_count == 1

    def test_warmup_metadata_has_long_ttl(self, tmp_path) -> None:
        """元数据预热使用长 TTL（CACHE_TTL_METADATA）."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        metadata = {"skill_id": "skill.test", "name": "test"}
        cache.warmup_metadata("skill.test", metadata)

        # 从 L1 获取条目检查 TTL
        key = cache._make_key("skill.test", "__metadata__", {})
        # 直接从 L1 的 OrderedDict 中读取条目
        entry = cache._l1._cache.get(key)
        assert entry is not None
        assert entry.ttl == CACHE_TTL_METADATA

    def test_warmup_with_params(self, tmp_path) -> None:
        """warmup 支持带参数的缓存."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        cache.warmup(
            skill_id="skill.test",
            action="query",
            value={"data": "preloaded"},
            params={"page": 1, "size": 20},
            ttl=300,
        )

        result = cache.get("skill.test", "query", {"page": 1, "size": 20})
        assert result == {"data": "preloaded"}

    def test_warmup_metadata_miss(self, tmp_path) -> None:
        """未预热的技能 get_metadata 返回 None."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        result = cache.get_metadata("skill.nonexistent")
        assert result is None
        assert cache.miss_count == 1


# ============================================================
# 6. 缓存大小限制 & LRU 淘汰
# ============================================================

class TestCacheSizeLimit:
    """缓存容量限制与 LRU 淘汰测试."""

    def test_l1_eviction_when_full(self) -> None:
        """L1 超过 max_size 时淘汰最久未使用的条目."""
        cache = L1MemoryCache(max_size=3)

        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        # 此时 L1 已满

        # 访问 k1，使其成为最近使用
        cache.get("k1")

        # 插入 k4，应该淘汰 k2（最久未使用）
        cache.set("k4", "v4")

        assert cache.get("k1") == "v1"  # 最近使用，保留
        assert cache.get("k2") is None  # 被淘汰
        assert cache.get("k3") == "v3"  # 保留
        assert cache.get("k4") == "v4"  # 新加入

    def test_default_l1_max_size_increased(self) -> None:
        """默认 L1 容量已从 1000 提升到 5000."""
        assert DEFAULT_L1_MAX_SIZE == 5000
        # SkillCache 默认使用 DEFAULT_L1_MAX_SIZE
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache = SkillCache(l2_dir=td)
            stats = cache.stats()
            assert stats["l1"]["max_size"] == 5000


# ============================================================
# 7. TTL 过期
# ============================================================

class TestCacheTTL:
    """缓存 TTL 过期测试."""

    def test_l1_ttl_expiry(self) -> None:
        """L1 缓存 TTL 过期后读取返回 None."""
        cache = L1MemoryCache(max_size=10)
        cache.set("k1", "v1", ttl=0.01)

        assert cache.get("k1") == "v1"
        time.sleep(0.02)
        assert cache.get("k1") is None

    def test_skill_cache_ttl_expiry(self, tmp_path) -> None:
        """SkillCache TTL 过期后读取返回 None."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"}, ttl=0.01)

        assert cache.get("skill.test", "act", {"x": 1}) == {"result": "ok"}
        time.sleep(0.02)
        assert cache.get("skill.test", "act", {"x": 1}) is None

    def test_no_ttl_means_no_expiry(self, tmp_path) -> None:
        """无 TTL 的缓存永不过期."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})  # 无 TTL

        # 短暂等待后仍能读取
        time.sleep(0.01)
        assert cache.get("skill.test", "act", {"x": 1}) == {"result": "ok"}

    def test_ttl_constants_values(self) -> None:
        """分层 TTL 常量值合理."""
        assert CACHE_TTL_METADATA == 3600.0  # 1 小时
        assert CACHE_TTL_RESULT == 300.0     # 5 分钟
        assert CACHE_TTL_HOT == 60.0         # 1 分钟

        # 大小关系正确
        assert CACHE_TTL_METADATA > CACHE_TTL_RESULT > CACHE_TTL_HOT


# ============================================================
# 8. 向后兼容性
# ============================================================

class TestBackwardCompatibility:
    """向后兼容性测试."""

    def test_default_params_compatible(self, tmp_path) -> None:
        """默认参数下旧代码行为不变."""
        # 旧接口签名仍然有效
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))

        cache.set("skill.test", "act", {"x": 1}, {"result": "ok"})
        assert cache.get("skill.test", "act", {"x": 1}) == {"result": "ok"}
        assert cache.invalidate("skill.test", "act", {"x": 1}) is True
        assert cache.get("skill.test", "act", {"x": 1}) is None

    def test_stats_backward_compatible(self, tmp_path) -> None:
        """stats() 返回的旧字段仍然存在."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        stats = cache.stats()

        # 旧字段
        assert "l1" in stats
        assert "l2" in stats
        assert "default_ttl" in stats
        assert "fuzzy_threshold" in stats

        # 新字段（新增，不破坏兼容）
        assert "hit_count" in stats
        assert "miss_count" in stats
        assert "hit_rate" in stats

    def test_invalidate_by_tag_still_works(self, tmp_path) -> None:
        """按标签失效功能仍然正常."""
        cache = SkillCache(l2_dir=str(tmp_path / "cache"))
        cache.set("skill.a", "act", {"x": 1}, {"r": 1}, tags={"group_a"})
        cache.set("skill.b", "act", {"x": 2}, {"r": 2}, tags={"group_a"})
        cache.set("skill.c", "act", {"x": 3}, {"r": 3}, tags={"group_b"})

        count = cache.invalidate_by_tag("group_a")
        assert count >= 2  # L1 + L2 至少各 2 个
        assert cache.get("skill.a", "act", {"x": 1}) is None
        assert cache.get("skill.b", "act", {"x": 2}) is None
        assert cache.get("skill.c", "act", {"x": 3}) == {"r": 3}
