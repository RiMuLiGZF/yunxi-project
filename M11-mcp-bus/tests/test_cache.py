"""M11 MCP Bus - 缓存服务单元测试.

测试 McpCache 的工具列表缓存、工具结果缓存、TTL、清理等功能。
"""

import os
import sys
import time
import unittest

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.cache import McpCache, MemoryCache


class TestToolListCache(unittest.TestCase):
    """测试工具列表缓存."""

    def setUp(self) -> None:
        """每个测试前创建新的缓存实例."""
        # 由于 CacheService 是单例模式，先清空避免测试间污染
        cache = McpCache(tool_list_ttl=300, tool_result_ttl=60)
        cache.clear_all()
        self.cache = cache

    def test_set_and_get_tool_list(self) -> None:
        """测试设置和获取工具列表缓存."""
        tools = [
            {"name": "tool1", "description": "Tool 1"},
            {"name": "tool2", "description": "Tool 2"},
        ]
        self.cache.set_tool_list_cache(tools)
        result = self.cache.get_tool_list_cache()
        self.assertEqual(result, tools)
        self.assertEqual(len(result), 2)

    def test_get_tool_list_not_cached(self) -> None:
        """测试未设置缓存时获取返回 None."""
        result = self.cache.get_tool_list_cache()
        self.assertIsNone(result)

    def test_invalidate_tool_list(self) -> None:
        """测试失效工具列表缓存."""
        tools = [{"name": "tool1"}]
        self.cache.set_tool_list_cache(tools)
        self.assertIsNotNone(self.cache.get_tool_list_cache())
        self.cache.invalidate_tool_list_cache()
        self.assertIsNone(self.cache.get_tool_list_cache())

    def test_tool_list_ttl_expiry(self) -> None:
        """测试工具列表缓存 TTL 过期后失效."""
        cache = McpCache(tool_list_ttl=1, tool_result_ttl=60)
        cache.clear_all()
        tools = [{"name": "test_tool"}]
        cache.set_tool_list_cache(tools)
        # 立即可用
        self.assertIsNotNone(cache.get_tool_list_cache())
        # 等待过期
        time.sleep(1.1)
        # 过期后返回 None
        result = cache.get_tool_list_cache()
        self.assertIsNone(result)


class TestToolResultCache(unittest.TestCase):
    """测试工具结果缓存."""

    def setUp(self) -> None:
        """每个测试前创建新的缓存实例并清空."""
        self.cache = McpCache(tool_list_ttl=300, tool_result_ttl=60)
        self.cache.clear_all()

    def test_set_and_get_result(self) -> None:
        """测试设置和获取工具调用结果缓存."""
        args_hash = self.cache.make_args_hash({"param1": "value1"})
        result_data = {"output": "hello world"}
        self.cache.set_tool_result_cache("my_tool", args_hash, result_data)
        cached = self.cache.get_tool_result_cache("my_tool", args_hash)
        self.assertEqual(cached, result_data)

    def test_get_nonexistent_result(self) -> None:
        """测试获取不存在的 key 返回 None."""
        result = self.cache.get_tool_result_cache("nonexistent", "hash123")
        self.assertIsNone(result)

    def test_delete_result(self) -> None:
        """测试删除指定的结果缓存."""
        args_hash = self.cache.make_args_hash({"x": 1})
        self.cache.set_tool_result_cache("tool1", args_hash, "result")
        self.assertIsNotNone(self.cache.get_tool_result_cache("tool1", args_hash))
        # 删除
        deleted = self.cache.invalidate_tool_result("tool1", args_hash)
        self.assertTrue(deleted)
        self.assertIsNone(self.cache.get_tool_result_cache("tool1", args_hash))

    def test_delete_nonexistent_result(self) -> None:
        """测试删除不存在的缓存返回 False."""
        result = self.cache.invalidate_tool_result("nonexistent", "hash")
        self.assertFalse(result)

    def test_invalidate_all_results(self) -> None:
        """测试清空所有结果缓存."""
        self.cache.set_tool_result_cache("tool1", "hash1", "result1")
        self.cache.set_tool_result_cache("tool2", "hash2", "result2")
        self.cache.set_tool_result_cache("tool3", "hash3", "result3")
        self.cache.invalidate_all_results()
        self.assertIsNone(self.cache.get_tool_result_cache("tool1", "hash1"))
        self.assertIsNone(self.cache.get_tool_result_cache("tool2", "hash2"))
        self.assertIsNone(self.cache.get_tool_result_cache("tool3", "hash3"))

    def test_invalidate_tool_results(self) -> None:
        """测试失效某个工具的所有结果缓存."""
        self.cache.set_tool_result_cache("tool_a", "h1", "r1")
        self.cache.set_tool_result_cache("tool_a", "h2", "r2")
        self.cache.set_tool_result_cache("tool_b", "h3", "r3")
        # 失效 tool_a 的所有缓存
        count = self.cache.invalidate_tool_results("tool_a")
        self.assertEqual(count, 2)
        self.assertIsNone(self.cache.get_tool_result_cache("tool_a", "h1"))
        self.assertIsNone(self.cache.get_tool_result_cache("tool_a", "h2"))
        # tool_b 不受影响
        self.assertEqual(
            self.cache.get_tool_result_cache("tool_b", "h3"), "r3"
        )

    def test_result_ttl_expiry(self) -> None:
        """测试结果缓存 TTL 过期后失效."""
        cache = McpCache(tool_list_ttl=300, tool_result_ttl=1)
        cache.clear_all()
        cache.set_tool_result_cache("tool1", "hash1", "result")
        # 立即可用
        self.assertEqual(cache.get_tool_result_cache("tool1", "hash1"), "result")
        # 等待过期
        time.sleep(1.1)
        # 过期后返回 None
        result = cache.get_tool_result_cache("tool1", "hash1")
        self.assertIsNone(result)


class TestMakeArgsHash(unittest.TestCase):
    """测试参数哈希功能."""

    def setUp(self) -> None:
        """每个测试前创建新的缓存实例."""
        self.cache = McpCache()

    def test_make_args_hash_returns_string(self) -> None:
        """测试返回值为字符串."""
        h = self.cache.make_args_hash({"a": 1})
        self.assertIsInstance(h, str)

    def test_make_args_hash_deterministic(self) -> None:
        """测试相同参数产生相同哈希（确定性）."""
        args = {"name": "test", "value": 42}
        h1 = self.cache.make_args_hash(args)
        h2 = self.cache.make_args_hash(args)
        self.assertEqual(h1, h2)

    def test_make_args_hash_order_independent(self) -> None:
        """测试参数顺序不影响哈希结果."""
        args1 = {"a": 1, "b": 2, "c": 3}
        args2 = {"c": 3, "a": 1, "b": 2}
        h1 = self.cache.make_args_hash(args1)
        h2 = self.cache.make_args_hash(args2)
        self.assertEqual(h1, h2)

    def test_make_args_hash_different_args(self) -> None:
        """测试不同参数产生不同哈希."""
        h1 = self.cache.make_args_hash({"a": 1})
        h2 = self.cache.make_args_hash({"a": 2})
        self.assertNotEqual(h1, h2)

    def test_make_args_hash_md5_length(self) -> None:
        """测试哈希值为 32 位十六进制（MD5）."""
        h = self.cache.make_args_hash({"test": True})
        self.assertEqual(len(h), 32)
        int(h, 16)  # 验证是合法十六进制


class TestClearAll(unittest.TestCase):
    """测试清空所有缓存."""

    def setUp(self) -> None:
        """每个测试前创建新的缓存实例."""
        self.cache = McpCache()
        self.cache.clear_all()

    def test_clear_all(self) -> None:
        """测试清空所有缓存（工具列表 + 结果）."""
        self.cache.set_tool_list_cache([{"name": "tool1"}])
        self.cache.set_tool_result_cache("t1", "h1", "r1")
        self.cache.set_tool_result_cache("t2", "h2", "r2")

        self.cache.clear_all()

        self.assertIsNone(self.cache.get_tool_list_cache())
        self.assertIsNone(self.cache.get_tool_result_cache("t1", "h1"))
        self.assertIsNone(self.cache.get_tool_result_cache("t2", "h2"))


class TestCacheStats(unittest.TestCase):
    """测试缓存统计信息."""

    def setUp(self) -> None:
        """每个测试前创建新的缓存实例并清空."""
        self.cache = McpCache(tool_list_ttl=300, tool_result_ttl=60)
        self.cache.clear_all()

    def test_stats_initial(self) -> None:
        """测试初始统计信息."""
        stats = self.cache.get_stats()
        self.assertFalse(stats["tool_list_cached"])
        self.assertEqual(stats["tool_list_ttl"], 300)
        self.assertEqual(stats["result_ttl"], 60)
        self.assertEqual(stats["cache_size"], 0)
        self.assertEqual(stats["backend"], "memory")

    def test_stats_after_caching(self) -> None:
        """测试缓存后的统计信息."""
        self.cache.set_tool_list_cache([{"name": "t1"}])
        self.cache.set_tool_result_cache("t1", "h1", "r1")
        self.cache.set_tool_result_cache("t1", "h2", "r2")

        stats = self.cache.get_stats()
        self.assertTrue(stats["tool_list_cached"])
        self.assertEqual(stats["cache_size"], 3)  # 工具列表 + 2 个结果


class TestMemoryCacheBackend(unittest.TestCase):
    """测试底层 MemoryCache 后端."""

    def setUp(self) -> None:
        """每个测试前创建新的内存缓存实例."""
        self.mem_cache = MemoryCache(max_entries=100)

    def test_set_and_get(self) -> None:
        """测试设置和获取缓存."""
        self.mem_cache.set("key1", "value1", 60)
        self.assertEqual(self.mem_cache.get("key1"), "value1")

    def test_get_nonexistent(self) -> None:
        """测试获取不存在的 key 返回 None."""
        self.assertIsNone(self.mem_cache.get("nonexistent"))

    def test_delete(self) -> None:
        """测试删除缓存."""
        self.mem_cache.set("key1", "value1", 60)
        self.assertTrue(self.mem_cache.delete("key1"))
        self.assertIsNone(self.mem_cache.get("key1"))

    def test_delete_nonexistent(self) -> None:
        """测试删除不存在的 key 返回 False."""
        self.assertFalse(self.mem_cache.delete("nonexistent"))

    def test_clear(self) -> None:
        """测试清空所有缓存."""
        self.mem_cache.set("k1", "v1", 60)
        self.mem_cache.set("k2", "v2", 60)
        self.mem_cache.clear()
        self.assertEqual(self.mem_cache.get_size(), 0)

    def test_delete_prefix(self) -> None:
        """测试按前缀删除缓存."""
        self.mem_cache.set("result:tool1:h1", "r1", 60)
        self.mem_cache.set("result:tool1:h2", "r2", 60)
        self.mem_cache.set("result:tool2:h1", "r3", 60)
        self.mem_cache.set("tool_list", "tools", 60)

        count = self.mem_cache.delete_prefix("result:tool1:")
        self.assertEqual(count, 2)
        self.assertIsNone(self.mem_cache.get("result:tool1:h1"))
        self.assertIsNone(self.mem_cache.get("result:tool1:h2"))
        self.assertEqual(self.mem_cache.get("result:tool2:h1"), "r3")
        self.assertEqual(self.mem_cache.get("tool_list"), "tools")

    def test_ttl_expiry(self) -> None:
        """测试 TTL 过期."""
        self.mem_cache.set("key1", "value1", 1)
        self.assertEqual(self.mem_cache.get("key1"), "value1")
        time.sleep(1.1)
        self.assertIsNone(self.mem_cache.get("key1"))

    def test_get_size(self) -> None:
        """测试获取缓存条目数."""
        self.assertEqual(self.mem_cache.get_size(), 0)
        self.mem_cache.set("k1", "v1", 60)
        self.assertEqual(self.mem_cache.get_size(), 1)
        self.mem_cache.set("k2", "v2", 60)
        self.assertEqual(self.mem_cache.get_size(), 2)

    def test_max_entries_eviction(self) -> None:
        """测试超过最大条目数时触发淘汰."""
        cache = MemoryCache(max_entries=10)
        # 写入超过限制的条目
        for i in range(15):
            cache.set(f"key_{i}", f"value_{i}", 300)
        # 应该已淘汰部分条目，不超过 max_entries
        self.assertLessEqual(cache.get_size(), 10)


class TestCacheServiceSingleton(unittest.TestCase):
    """测试 CacheService 单例模式."""

    def test_cache_service_is_singleton(self) -> None:
        """测试 CacheService 是单例."""
        from src.services.cache import CacheService

        cs1 = CacheService()
        cs2 = CacheService()
        self.assertIs(cs1, cs2)

    def test_cache_service_uses_memory_by_default(self) -> None:
        """测试默认配置下使用内存后端."""
        from src.services.cache import CacheService

        cs = CacheService()
        self.assertEqual(cs.backend_type, "memory")


if __name__ == "__main__":
    unittest.main()
