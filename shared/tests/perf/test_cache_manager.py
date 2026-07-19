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

    def test_cache_result_invalidate_pattern(self):
        """测试 @cache_result 装饰器的 invalidate_pattern 方法"""
        cm = CacheManager(l1_max_size=100, l1_default_ttl=60)
        call_count = 0

        @cache_result(ttl=30, key_prefix="test_item", cache_manager=cm)
        def get_item(item_id):
            nonlocal call_count
            call_count += 1
            return {"id": item_id, "name": f"item_{item_id}"}

        # 写入多个缓存
        get_item(1)
        get_item(2)
        get_item(3)
        assert call_count == 3

        # 再次调用，应该命中缓存
        get_item(1)
        get_item(2)
        assert call_count == 3

        # 按模式批量失效
        get_item.invalidate_pattern("test_item:*")

        # 再次调用，应该重新执行
        get_item(1)
        get_item(2)
        assert call_count == 5

        cm.shutdown()

    def test_cache_result_cache_none_false(self):
        """测试 cache_none=False 时空值不缓存"""
        cm = CacheManager(l1_max_size=100, l1_default_ttl=60)
        call_count = 0

        @cache_result(ttl=30, key_prefix="test_none", cache_manager=cm, cache_none=False)
        def get_none():
            nonlocal call_count
            call_count += 1
            return None

        # 第一次调用
        result1 = get_none()
        assert result1 is None
        assert call_count == 1

        # 第二次调用，cache_none=False 应该不缓存空值，重新执行
        result2 = get_none()
        assert result2 is None
        assert call_count == 2

        cm.shutdown()

    def test_cache_result_empty_list_handling(self):
        """测试空列表/空字典的缓存处理（穿透防护）"""
        cm = CacheManager(l1_max_size=100, l1_default_ttl=60, enable_penetration_guard=True)
        call_count = 0

        @cache_result(ttl=30, key_prefix="test_empty", cache_manager=cm)
        def get_empty_list():
            nonlocal call_count
            call_count += 1
            return []

        # 第一次调用
        result1 = get_empty_list()
        assert result1 == []
        assert call_count == 1

        # 第二次调用，空列表应该被缓存（穿透防护）
        result2 = get_empty_list()
        assert result2 == []
        assert call_count == 1

        cm.shutdown()

    def test_cache_result_kwargs_different_keys(self):
        """测试不同 kwargs 产生不同缓存 key"""
        call_count = 0

        @cache_result(ttl=60, key_prefix="test_kwargs")
        def search(query: str, page: int = 1, page_size: int = 20):
            nonlocal call_count
            call_count += 1
            return f"search:{query}:p{page}:ps{page_size}"

        # 相同参数
        search("hello", page=1, page_size=20)
        search("hello", page=1, page_size=20)
        assert call_count == 1

        # 不同查询词
        search("world", page=1, page_size=20)
        assert call_count == 2

        # 不同分页
        search("hello", page=2, page_size=20)
        assert call_count == 3

        # 不同 page_size
        search("hello", page=1, page_size=50)
        assert call_count == 4

        reset_default_cache_manager()


# ============================================================
# 并发安全测试
# ============================================================

class TestConcurrency:
    """并发安全测试"""

    def test_concurrent_set_get(self, cache_manager):
        """测试并发读写的线程安全"""
        import threading

        cm = cache_manager
        num_threads = 10
        num_ops = 100
        errors = []

        def writer(thread_id):
            try:
                for i in range(num_ops):
                    key = f"thread_{thread_id}_key_{i}"
                    cm.set(key, f"value_{thread_id}_{i}")
            except Exception as e:
                errors.append(str(e))

        def reader(thread_id):
            try:
                for i in range(num_ops):
                    key = f"thread_{thread_id}_key_{i}"
                    cm.get(key)
            except Exception as e:
                errors.append(str(e))

        threads = []
        for i in range(num_threads):
            t1 = threading.Thread(target=writer, args=(i,))
            t2 = threading.Thread(target=reader, args=(i,))
            threads.extend([t1, t2])

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"并发错误: {errors}"

    def test_concurrent_get_or_set(self, cache_manager):
        """测试 get_or_set 的击穿防护（单飞锁）"""
        import threading

        cm = cache_manager
        call_count = 0
        call_lock = threading.Lock()
        num_threads = 20

        def loader():
            nonlocal call_count
            with call_lock:
                call_count += 1
            # 模拟慢查询
            time.sleep(0.1)
            return "shared_value"

        results = []
        results_lock = threading.Lock()

        def worker():
            result = cm.get_or_set("hot_key", loader)
            with results_lock:
                results.append(result)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # 所有线程应该得到相同结果
        assert all(r == "shared_value" for r in results)
        assert len(results) == num_threads
        # 击穿防护：loader 应该只被调用一次
        assert call_count == 1, f"loader 被调用了 {call_count} 次，期望 1 次"


# ============================================================
# 缓存 key 生成测试
# ============================================================

class TestCacheKeyGeneration:
    """缓存 key 生成测试"""

    def test_key_contains_all_params(self):
        """测试缓存 key 包含所有参数"""
        from shared.perf.cache_manager import _make_cache_key

        def sample_func(a, b, c=3):
            pass

        key1 = _make_cache_key(sample_func, (1, 2), {"c": 3}, "test")
        key2 = _make_cache_key(sample_func, (1, 2), {"c": 4}, "test")

        # 不同参数应该产生不同 key
        assert key1 != key2

    def test_key_deterministic(self):
        """测试相同参数产生相同 key（确定性）"""
        from shared.perf.cache_manager import _make_cache_key

        def sample_func(x, y=10):
            pass

        key1 = _make_cache_key(sample_func, (5,), {"y": 20}, "prefix")
        key2 = _make_cache_key(sample_func, (5,), {"y": 20}, "prefix")

        assert key1 == key2

    def test_long_key_hash_fallback(self):
        """测试超长 key 会被哈希截断"""
        from shared.perf.cache_manager import _make_cache_key

        def sample_func():
            pass

        # 构造一个超长的 kwargs
        long_str = "a" * 500
        key = _make_cache_key(sample_func, (), {"long_param": long_str}, "test_prefix")

        # key 不应该太长
        assert len(key) < 250
        assert "hash:" in key


# ============================================================
# 缓存命名规范测试
# ============================================================

class TestCacheNamingConvention:
    """缓存命名规范测试"""

    def test_m7_market_keys(self):
        """测试 M7 市场模块缓存 key 命名规范"""
        # 模拟生成的 key
        keys = [
            "m7:market:stats",
            "m7:market:categories",
            "m7:market:templates:list:cat=all:tag=all:p=1:ps=20",
            "m7:market:templates:detail:mkt_abc123",
            "m7:market:templates:search:q=test:p=1:ps=20",
            "m7:market:blocks:list:cat=all:p=1:ps=20",
            "m7:market:blocks:detail:mkb_xyz789",
            "m7:market:blocks:search:q=test:p=1:ps=20",
        ]

        # 验证都以 m7:market: 开头
        for key in keys:
            assert key.startswith("m7:market:"), f"Key 不符合命名规范: {key}"

    def test_m11_registry_keys(self):
        """测试 M11 注册中心模块缓存 key 命名规范"""
        keys = [
            "m11:registry:servers:status=all",
            "m11:registry:servers:id:1",
            "m11:registry:servers:name:test-server",
            "m11:registry:tools:sid=all:cat=all:kw=none:p=1:ps=50",
        ]

        for key in keys:
            assert key.startswith("m11:registry:"), f"Key 不符合命名规范: {key}"

    def test_m9_dashboard_keys(self):
        """测试 M9 仪表盘模块缓存 key 命名规范"""
        keys = [
            "m9:dashboard:overview",
            "m9:dashboard:today_activities:limit=20",
            "m9:dashboard:top_projects:limit=10",
            "m9:dashboard:activity_trend:days=7",
            "m9:dashboard:system_status",
        ]

        for key in keys:
            assert key.startswith("m9:dashboard:"), f"Key 不符合命名规范: {key}"

    def test_pattern_matching_covers_subkeys(self):
        """测试模式匹配能正确覆盖子 key"""
        cm = CacheManager(l1_max_size=100, l1_default_ttl=60)

        # 设置多个模板相关的 key
        cm.set("m7:market:templates:list:page=1", "list1")
        cm.set("m7:market:templates:list:page=2", "list2")
        cm.set("m7:market:templates:detail:tpl1", "detail1")
        cm.set("m7:market:templates:search:q=test", "search1")
        cm.set("m7:market:blocks:list:page=1", "blocks_list")  # 不应被删除

        # 按模板模式清理
        cm.clear(pattern="m7:market:templates:*")

        # 验证模板相关都被清理了
        assert cm.exists("m7:market:templates:list:page=1") is False
        assert cm.exists("m7:market:templates:list:page=2") is False
        assert cm.exists("m7:market:templates:detail:tpl1") is False
        assert cm.exists("m7:market:templates:search:q=test") is False

        # 验证积木相关不受影响
        assert cm.exists("m7:market:blocks:list:page=1") is True

        cm.shutdown()
