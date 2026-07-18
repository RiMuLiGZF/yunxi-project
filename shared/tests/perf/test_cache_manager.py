"""
缓存管理器测试

测试覆盖:
- CRUD 操作 (get/set/delete/exists/clear)
- TTL 过期
- LRU 淘汰
- 命中率统计
- 缓存装饰器 (@cache_result / @cache_invalidate)
- 模式匹配清空
- get_or_set (击穿防护)
- 多级缓存 (L1 + L2)
"""

import sys
import os
import time
import tempfile
import pytest
from pathlib import Path

# 确保路径正确
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.perf.cache_manager import (
    CacheManager,
    cache_result,
    cache_invalidate,
    NULL_VALUE,
    _LRUCache,
    _FileCache,
    reset_default_cache_manager,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def l1_cache():
    """L1 内存缓存"""
    cache = _LRUCache(max_size=100, default_ttl=60, cleanup_interval=0)
    yield cache
    cache.shutdown()


@pytest.fixture
def l2_cache():
    """L2 文件缓存"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _FileCache(
            cache_dir=tmpdir,
            max_size_mb=10,
            max_files=100,
            default_ttl=300,
            ttl_multiplier=1.0,
        )
        yield cache


@pytest.fixture
def cache_manager():
    """多级缓存管理器 (仅 L1)"""
    cm = CacheManager(
        l1_enabled=True,
        l1_max_size=100,
        l1_default_ttl=60,
        l2_enabled=False,
        l3_enabled=False,
        enable_penetration_guard=True,
    )
    yield cm
    cm.shutdown()
    reset_default_cache_manager()


@pytest.fixture
def multi_level_cache():
    """多级缓存管理器 (L1 + L2)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = CacheManager(
            l1_enabled=True,
            l1_max_size=50,
            l1_default_ttl=60,
            l2_enabled=True,
            l2_dir=os.path.join(tmpdir, "cache_l2"),
            l2_max_size_mb=10,
            l2_max_files=100,
            l2_default_ttl=300,
            l3_enabled=False,
        )
        yield cm
        cm.shutdown()


# ============================================================
# L1 缓存测试
# ============================================================

class TestL1Cache:
    """L1 内存缓存测试"""

    def test_set_and_get(self, l1_cache):
        """测试基本的 set 和 get"""
        l1_cache.set("key1", "value1")
        assert l1_cache.get("key1") == "value1"

    def test_get_nonexistent(self, l1_cache):
        """测试获取不存在的 key"""
        assert l1_cache.get("nonexistent") is None
        assert l1_cache.get("nonexistent", "default") == "default"

    def test_overwrite(self, l1_cache):
        """测试覆盖已有 key"""
        l1_cache.set("key", "value1")
        l1_cache.set("key", "value2")
        assert l1_cache.get("key") == "value2"

    def test_delete(self, l1_cache):
        """测试删除"""
        l1_cache.set("key", "value")
        assert l1_cache.delete("key") is True
        assert l1_cache.get("key") is None
        assert l1_cache.delete("key") is False

    def test_has(self, l1_cache):
        """测试 exists/has"""
        assert l1_cache.has("key") is False
        l1_cache.set("key", "value")
        assert l1_cache.has("key") is True

    def test_size(self, l1_cache):
        """测试 size"""
        assert l1_cache.size() == 0
        l1_cache.set("k1", "v1")
        l1_cache.set("k2", "v2")
        assert l1_cache.size() == 2

    def test_clear(self, l1_cache):
        """测试清空"""
        l1_cache.set("k1", "v1")
        l1_cache.set("k2", "v2")
        count = l1_cache.clear()
        assert count == 2
        assert l1_cache.size() == 0

    def test_ttl_expiry(self, l1_cache):
        """测试 TTL 过期"""
        l1_cache.set("key", "value", ttl=0.1)
        assert l1_cache.get("key") == "value"
        time.sleep(0.15)
        assert l1_cache.get("key") is None

    def test_lru_eviction(self, l1_cache):
        """测试 LRU 淘汰"""
        cache = _LRUCache(max_size=10, default_ttl=60, cleanup_interval=0)
        for i in range(10):
            cache.set(f"key{i}", f"value{i}")
        assert cache.size() == 10

        # 访问 key0，使其变成最近使用
        cache.get("key0")

        # 添加新 key，应该淘汰最久未使用的 (key1)
        cache.set("key10", "value10")
        assert cache.size() == 10
        assert cache.get("key1") is None  # 被淘汰
        assert cache.get("key0") == "value0"  # 还在
        cache.shutdown()

    def test_clear_pattern(self, l1_cache):
        """测试模式匹配清空"""
        l1_cache.set("user:1", "a")
        l1_cache.set("user:2", "b")
        l1_cache.set("post:1", "c")

        count = l1_cache.clear_pattern("user:*")
        assert count == 2
        assert l1_cache.get("user:1") is None
        assert l1_cache.get("post:1") == "c"

    def test_null_value_caching(self, l1_cache):
        """测试空值缓存 (穿透防护)"""
        l1_cache.set("empty", None)
        # has 应该返回 True (空值缓存)
        assert l1_cache.has("empty") is True
        # get 应该返回 None
        assert l1_cache.get("empty") is None

    def test_stats(self, l1_cache):
        """测试统计信息"""
        l1_cache.set("k1", "v1")
        l1_cache.get("k1")
        l1_cache.get("k1")
        l1_cache.get("nonexistent")

        stats = l1_cache.stats.to_dict()
        assert stats["sets"] == 1
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert abs(stats["hit_rate"] - 2 / 3) < 0.01


# ============================================================
# L2 文件缓存测试
# ============================================================

class TestL2FileCache:
    """L2 文件缓存测试"""

    def test_set_and_get(self, l2_cache):
        """测试基本读写"""
        l2_cache.set("key1", "value1")
        assert l2_cache.get("key1") == "value1"

    def test_get_nonexistent(self, l2_cache):
        """测试获取不存在的 key"""
        assert l2_cache.get("nonexistent") is None

    def test_delete(self, l2_cache):
        """测试删除"""
        l2_cache.set("key", "value")
        assert l2_cache.delete("key") is True
        assert l2_cache.get("key") is None

    def test_has(self, l2_cache):
        """测试 has"""
        assert l2_cache.has("key") is False
        l2_cache.set("key", "value")
        assert l2_cache.has("key") is True

    def test_dict_value(self, l2_cache):
        """测试字典值序列化"""
        data = {"name": "test", "value": 123, "nested": {"a": 1}}
        l2_cache.set("dict_key", data)
        result = l2_cache.get("dict_key")
        assert result == data

    def test_list_value(self, l2_cache):
        """测试列表值序列化"""
        data = [1, 2, 3, "four", {"five": 5}]
        l2_cache.set("list_key", data)
        result = l2_cache.get("list_key")
        assert result == data

    def test_clear(self, l2_cache):
        """测试清空"""
        l2_cache.set("k1", "v1")
        l2_cache.set("k2", "v2")
        count = l2_cache.clear()
        assert count >= 2
        assert l2_cache.get("k1") is None


# ============================================================
# 多级缓存管理器测试
# ============================================================

class TestCacheManager:
    """多级缓存管理器测试"""

    def test_basic_operations(self, cache_manager):
        """测试基本 CRUD"""
        cm = cache_manager
        assert cm.get("key") is None

        cm.set("key", "value")
        assert cm.get("key") == "value"
        assert cm.exists("key") is True

        cm.delete("key")
        assert cm.exists("key") is False
        assert cm.get("key") is None

    def test_clear_all(self, cache_manager):
        """测试全部清空"""
        cm = cache_manager
        cm.set("k1", "v1")
        cm.set("k2", "v2")
        cm.clear()
        assert cm.exists("k1") is False
        assert cm.exists("k2") is False

    def test_clear_pattern(self, cache_manager):
        """测试模式匹配清空"""
        cm = cache_manager
        cm.set("user:1", "a")
        cm.set("user:2", "b")
        cm.set("post:1", "c")

        cm.clear(pattern="user:*")
        assert cm.exists("user:1") is False
        assert cm.exists("post:1") is True

    def test_get_or_set(self, cache_manager):
        """测试 get_or_set"""
        cm = cache_manager
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return "loaded_value"

        # 第一次调用应该执行 loader
        result1 = cm.get_or_set("key", loader)
        assert result1 == "loaded_value"
        assert call_count == 1

        # 第二次调用应该从缓存返回
        result2 = cm.get_or_set("key", loader)
        assert result2 == "loaded_value"
        assert call_count == 1  # 没有再次调用

    def test_get_or_set_null(self, cache_manager):
        """测试 get_or_set 空值 (穿透防护)"""
        cm = cache_manager
        call_count = 0

        def loader():
            nonlocal call_count
            call_count += 1
            return None

        result1 = cm.get_or_set("empty_key", loader)
        assert result1 is None
        assert call_count == 1

        result2 = cm.get_or_set("empty_key", loader)
        assert result2 is None
        assert call_count == 1  # 空值也被缓存了

    def test_get_many(self, cache_manager):
        """测试批量读取"""
        cm = cache_manager
        cm.set("k1", "v1")
        cm.set("k2", "v2")

        result = cm.get_many(["k1", "k2", "k3"])
        assert result["k1"] == "v1"
        assert result["k2"] == "v2"
        assert "k3" not in result

    def test_set_many(self, cache_manager):
        """测试批量写入"""
        cm = cache_manager
        cm.set_many({"k1": "v1", "k2": "v2"})
        assert cm.get("k1") == "v1"
        assert cm.get("k2") == "v2"

    def test_stats(self, cache_manager):
        """测试统计信息"""
        cm = cache_manager
        cm.set("k1", "v1")
        cm.get("k1")
        cm.get("k1")
        cm.get("nonexistent")

        stats = cm.get_stats()
        assert stats["total_requests"] == 3
        assert "l1" in stats
        assert "levels_enabled" in stats
        assert stats["levels_enabled"]["l1"] is True

    def test_reset_stats(self, cache_manager):
        """测试重置统计"""
        cm = cache_manager
        cm.set("k1", "v1")
        cm.get("k1")

        stats1 = cm.get_stats()
        assert stats1["total_requests"] > 0

        cm.reset_stats()
        stats2 = cm.get_stats()
        assert stats2["total_requests"] == 0

    def test_multi_level_l2_write_back(self, multi_level_cache):
        """测试多级缓存 L2 回写 L1"""
        cm = multi_level_cache

        # 写入 (应该写入 L1 和 L2)
        cm.set("key", "value")
        assert cm.get("key") == "value"

        # 手动清除 L1，验证 L2 还在，并能回写到 L1
        if cm.l1:
            cm.l1.clear()

        # 从 L2 读取并回写 L1
        result = cm.get("key")
        assert result == "value"

        # L1 现在应该有了
        if cm.l1:
            assert cm.l1.has("key") is True

    def test_from_env(self):
        """测试从环境变量创建"""
        import os
        os.environ["PERF_CACHE_L1_MAX_SIZE"] = "200"
        os.environ["PERF_CACHE_L1_TTL"] = "120"

        cm = CacheManager.from_env(namespace="test_env")
        assert cm.l1 is not None
        assert cm.l1.max_size == 200

        cm.shutdown()
        del os.environ["PERF_CACHE_L1_MAX_SIZE"]
        del os.environ["PERF_CACHE_L1_TTL"]


# ============================================================
# 缓存装饰器测试
# ============================================================

class TestCacheDecorators:
    """缓存装饰器测试"""

    def test_cache_result_decorator(self):
        """测试 @cache_result 装饰器"""
        call_count = 0

        @cache_result(ttl=60, key_prefix="test_func")
        def add(a: int, b: int) -> int:
            nonlocal call_count
            call_count += 1
            return a + b

        # 第一次调用
        result1 = add(1, 2)
        assert result1 == 3
        assert call_count == 1

        # 第二次调用 (相同参数)，应该命中缓存
        result2 = add(1, 2)
        assert result2 == 3
        assert call_count == 1

        # 不同参数，应该重新执行
        result3 = add(3, 4)
        assert result3 == 7
        assert call_count == 2

        # 手动失效
        add.invalidate(1, 2)
        result4 = add(1, 2)
        assert result4 == 3
        assert call_count == 3

        # 清理
        reset_default_cache_manager()

    def test_cache_result_key_prefix(self):
        """测试不同 key_prefix 的缓存隔离"""
        call_count_a = 0
        call_count_b = 0

        @cache_result(ttl=60, key_prefix="func_a")
        def func_a(x):
            nonlocal call_count_a
            call_count_a += 1
            return x * 2

        @cache_result(ttl=60, key_prefix="func_b")
        def func_b(x):
            nonlocal call_count_b
            call_count_b += 1
            return x * 3

        func_a(5)
        func_b(5)
        func_a(5)
        func_b(5)

        assert call_count_a == 1
        assert call_count_b == 1

        reset_default_cache_manager()

    def test_cache_invalidate_decorator(self):
        """测试 @cache_invalidate 装饰器"""
        cm = CacheManager(l1_max_size=100, l1_default_ttl=60)

        cm.set("user:1", "data1")
        cm.set("user:2", "data2")
        cm.set("post:1", "post1")

        assert cm.exists("user:1") is True

        @cache_invalidate("user:*", cache_manager=cm)
        def update_user(user_id):
            return f"updated user {user_id}"

        update_user(1)

        assert cm.exists("user:1") is False
        assert cm.exists("user:2") is False
        assert cm.exists("post:1") is True

        cm.shutdown()

    def test_cache_result_with_custom_manager(self):
        """测试使用自定义 CacheManager 的装饰器"""
        cm = CacheManager(l1_max_size=50, l1_default_ttl=30)
        call_count = 0

        @cache_result(ttl=30, key_prefix="custom", cache_manager=cm)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x ** 2

        compute(5)
        compute(5)
        assert call_count == 1

        cm.shutdown()
