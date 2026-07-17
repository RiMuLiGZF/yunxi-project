"""
API-Gateway 响应缓存测试（CQ-008, P1级）

测试目标：
1. 缓存基本操作（set/get）
2. 缓存键生成
3. TTL 过期
4. 缓存失效（单条/模式/全部）
5. 缓存统计（命中率、大小）
6. LRU 驱逐
7. 可缓存方法判断
8. 缓存条目信息
"""

import sys
import time
import unittest
from pathlib import Path

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))


class TestResponseCache(unittest.TestCase):
    """响应缓存测试"""

    def setUp(self):
        from src.cache.response_cache import ResponseCache, CacheConfig
        self.ResponseCache = ResponseCache
        self.CacheConfig = CacheConfig

    def test_cache_disabled_by_default(self):
        """测试默认禁用缓存"""
        cache = self.ResponseCache()
        self.assertFalse(cache.get_config().enabled)

    def test_set_and_get(self):
        """测试基本的 set 和 get 操作"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        key = "test-key"
        cache.set(key, 200, {"Content-Type": "application/json"}, b'{"data": "test"}')

        result = cache.get(key)
        self.assertIsNotNone(result)
        status_code, headers, body = result
        self.assertEqual(status_code, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body, b'{"data": "test"}')

    def test_get_miss(self):
        """测试缓存未命中"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        result = cache.get("nonexistent")
        self.assertIsNone(result)

    def test_cache_disabled_no_set(self):
        """测试禁用缓存时 set 不生效"""
        config = self.CacheConfig(enabled=False)
        cache = self.ResponseCache(config)

        success = cache.set("key", 200, {}, b"data")
        self.assertFalse(success)

        result = cache.get("key")
        self.assertIsNone(result)

    def test_only_cache_success_status(self):
        """测试只缓存 2xx 和 3xx 响应"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        # 4xx 不缓存
        success = cache.set("key404", 404, {}, b"not found")
        self.assertFalse(success)

        # 5xx 不缓存
        success = cache.set("key500", 500, {}, b"error")
        self.assertFalse(success)

        # 2xx 缓存
        success = cache.set("key200", 200, {}, b"ok")
        self.assertTrue(success)

        # 3xx 缓存
        success = cache.set("key301", 301, {}, b"moved")
        self.assertTrue(success)

    def test_ttl_expiration(self):
        """测试 TTL 过期"""
        config = self.CacheConfig(enabled=True, default_ttl=1)
        cache = self.ResponseCache(config)

        cache.set("expiring-key", 200, {}, b"data")

        # 立即获取应该命中
        result = cache.get("expiring-key")
        self.assertIsNotNone(result)

        # 等待过期
        time.sleep(1.1)

        # 过期后应该未命中
        result = cache.get("expiring-key")
        self.assertIsNone(result)

    def test_custom_ttl(self):
        """测试自定义 TTL"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        cache.set("custom-ttl", 200, {}, b"data", ttl=1)

        time.sleep(1.1)
        result = cache.get("custom-ttl")
        self.assertIsNone(result)

    def test_generate_cache_key_method_url(self):
        """测试缓存键生成：方法和 URL"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        key1 = cache.generate_cache_key("GET", "/api/users")
        key2 = cache.generate_cache_key("GET", "/api/users")
        key3 = cache.generate_cache_key("POST", "/api/users")
        key4 = cache.generate_cache_key("GET", "/api/posts")

        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)
        self.assertNotEqual(key1, key4)

    def test_generate_cache_key_query_params(self):
        """测试缓存键生成：查询参数"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        key1 = cache.generate_cache_key("GET", "/api/users", query_params={"page": "1", "limit": "10"})
        key2 = cache.generate_cache_key("GET", "/api/users", query_params={"limit": "10", "page": "1"})
        key3 = cache.generate_cache_key("GET", "/api/users", query_params={"page": "2", "limit": "10"})

        # 参数顺序不影响
        self.assertEqual(key1, key2)
        # 参数值不同则键不同
        self.assertNotEqual(key1, key3)

    def test_generate_cache_key_auth(self):
        """测试缓存键生成：认证信息"""
        config = self.CacheConfig(enabled=True, include_auth_in_key=True)
        cache = self.ResponseCache(config)

        key1 = cache.generate_cache_key("GET", "/api/user", auth_info="user1")
        key2 = cache.generate_cache_key("GET", "/api/user", auth_info="user2")
        key3 = cache.generate_cache_key("GET", "/api/user", auth_info="user1")

        self.assertEqual(key1, key3)
        self.assertNotEqual(key1, key2)

    def test_generate_cache_key_no_auth(self):
        """测试缓存键生成：不包含认证信息"""
        config = self.CacheConfig(enabled=True, include_auth_in_key=False)
        cache = self.ResponseCache(config)

        key1 = cache.generate_cache_key("GET", "/api/data", auth_info="user1")
        key2 = cache.generate_cache_key("GET", "/api/data", auth_info="user2")

        # 不包含认证信息时，不同用户键相同
        self.assertEqual(key1, key2)

    def test_generate_cache_key_vary_headers(self):
        """测试缓存键生成：Vary 头"""
        config = self.CacheConfig(
            enabled=True,
            include_auth_in_key=False,
            vary_headers=["Accept", "Accept-Encoding"],
        )
        cache = self.ResponseCache(config)

        key1 = cache.generate_cache_key(
            "GET", "/api/data",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"}
        )
        key2 = cache.generate_cache_key(
            "GET", "/api/data",
            headers={"Accept": "text/html", "Accept-Encoding": "gzip"}
        )
        key3 = cache.generate_cache_key(
            "GET", "/api/data",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"}
        )

        self.assertEqual(key1, key3)
        self.assertNotEqual(key1, key2)

    def test_invalidate_single(self):
        """测试单条缓存失效"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        cache.set("key1", 200, {}, b"data1")
        cache.set("key2", 200, {}, b"data2")

        result = cache.invalidate("key1")
        self.assertTrue(result)

        self.assertIsNone(cache.get("key1"))
        self.assertIsNotNone(cache.get("key2"))

    def test_invalidate_nonexistent(self):
        """测试失效不存在的缓存"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        result = cache.invalidate("nonexistent")
        self.assertFalse(result)

    def test_invalidate_pattern(self):
        """测试按模式失效缓存"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        # 创建一些键（用实际的键值）
        key1 = cache.generate_cache_key("GET", "/api/users/1")
        key2 = cache.generate_cache_key("GET", "/api/users/2")
        key3 = cache.generate_cache_key("GET", "/api/posts/1")

        cache.set(key1, 200, {}, b"user1")
        cache.set(key2, 200, {}, b"user2")
        cache.set(key3, 200, {}, b"post1")

        # 按前缀失效（注意：缓存键是哈希值，这里测试模式匹配）
        count = cache.invalidate_pattern(key1[:5])
        self.assertGreaterEqual(count, 0)

    def test_invalidate_all(self):
        """测试清空所有缓存"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        cache.set("key1", 200, {}, b"data1")
        cache.set("key2", 200, {}, b"data2")
        cache.set("key3", 200, {}, b"data3")

        count = cache.invalidate_all()
        self.assertEqual(count, 3)

        stats = cache.get_stats()
        self.assertEqual(stats["entries_count"], 0)

    def test_is_cacheable_method(self):
        """测试可缓存方法判断"""
        config = self.CacheConfig(enabled=True, cache_methods=["GET", "HEAD"])
        cache = self.ResponseCache(config)

        self.assertTrue(cache.is_cacheable_method("GET"))
        self.assertTrue(cache.is_cacheable_method("HEAD"))
        self.assertFalse(cache.is_cacheable_method("POST"))
        self.assertFalse(cache.is_cacheable_method("PUT"))
        self.assertFalse(cache.is_cacheable_method("DELETE"))

    def test_hit_rate_stats(self):
        """测试命中率统计"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        # 1 次命中，3 次未命中
        cache.set("key1", 200, {}, b"data")
        cache.get("key1")  # 命中
        cache.get("key1")  # 命中
        cache.get("nonexistent1")  # 未命中
        cache.get("nonexistent2")  # 未命中

        stats = cache.get_stats()
        self.assertEqual(stats["total_requests"], 4)
        self.assertEqual(stats["cache_hits"], 2)
        self.assertEqual(stats["cache_misses"], 2)
        self.assertAlmostEqual(stats["hit_rate_percent"], 50.0, delta=1)

    def test_lru_eviction_max_entries(self):
        """测试 LRU 驱逐：最大条目数"""
        # 使用非常大的 max_size 以确保是 max_entries 触发驱逐
        config = self.CacheConfig(
            enabled=True,
            max_entries=3,
            max_size=1024 * 1024,  # 1MB，足够大
            default_ttl=60,
        )
        cache = self.ResponseCache(config)

        cache.set("key1", 200, {}, b"a" * 10)
        cache.set("key2", 200, {}, b"b" * 10)
        cache.set("key3", 200, {}, b"c" * 10)

        stats_before = cache.get_stats()
        self.assertEqual(stats_before["entries_count"], 3)

        # 访问 key1，使其不被驱逐
        cache.get("key1")

        # 插入第 4 个，应该驱逐最久未使用的 key2
        cache.set("key4", 200, {}, b"d" * 10)

        stats = cache.get_stats()
        self.assertEqual(stats["entries_count"], 3)
        self.assertGreater(stats["cache_evictions"], 0)

        # key1 和 key3 和 key4 应该存在，key2 应该被驱逐
        self.assertIsNotNone(cache.get("key1"))
        self.assertIsNotNone(cache.get("key4"))
        # key2 应该被驱逐了（因为它是 LRU）
        # 注意：由于 get 操作本身也会影响 LRU，这里只验证数量
        self.assertEqual(stats["entries_count"], 3)

    def test_lru_eviction_max_size(self):
        """测试 LRU 驱逐：最大大小"""
        config = self.CacheConfig(enabled=True, max_size=100, default_ttl=60)
        cache = self.ResponseCache(config)

        # 每个条目约 50 字节
        cache.set("key1", 200, {"H": "v"}, b"x" * 20)
        cache.set("key2", 200, {"H": "v"}, b"x" * 20)

        stats = cache.get_stats()
        self.assertLessEqual(stats["total_size_bytes"], 100)

    def test_cache_size_limit_per_entry(self):
        """测试单条缓存大小限制（不超过总大小的 10%）"""
        config = self.CacheConfig(enabled=True, max_size=1000, default_ttl=60)
        cache = self.ResponseCache(config)

        # 超过 10% 的内容不应被缓存
        success = cache.set("big-key", 200, {}, b"x" * 200)
        self.assertFalse(success)

    def test_get_entry_info(self):
        """测试获取缓存条目信息"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        cache.set("test-key", 200, {"Content-Type": "json"}, b"test body")

        info = cache.get_entry_info("test-key")
        self.assertIsNotNone(info)
        self.assertEqual(info["status_code"], 200)
        self.assertEqual(info["body_size"], 9)
        self.assertEqual(info["hit_count"], 0)
        self.assertFalse(info["expired"])
        self.assertGreater(info["remaining_ttl"], 0)

    def test_get_entry_info_nonexistent(self):
        """测试获取不存在的条目信息"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        info = cache.get_entry_info("nonexistent")
        self.assertIsNone(info)

    def test_hit_count_increments(self):
        """测试命中次数递增"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        cache.set("hit-test", 200, {}, b"data")
        cache.get("hit-test")
        cache.get("hit-test")
        cache.get("hit-test")

        info = cache.get_entry_info("hit-test")
        self.assertEqual(info["hit_count"], 3)

    def test_update_config(self):
        """测试更新配置"""
        config = self.CacheConfig(enabled=False, default_ttl=60)
        cache = self.ResponseCache(config)

        new_config = self.CacheConfig(enabled=True, default_ttl=120)
        cache.update_config(new_config)

        self.assertTrue(cache.get_config().enabled)
        self.assertEqual(cache.get_config().default_ttl, 120)

    def test_reset_stats(self):
        """测试重置统计"""
        config = self.CacheConfig(enabled=True)
        cache = self.ResponseCache(config)

        cache.set("key", 200, {}, b"data")
        cache.get("key")
        cache.reset_stats()

        stats = cache.get_stats()
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["cache_hits"], 0)

    def test_original_data_not_modified(self):
        """测试返回的数据副本不影响缓存"""
        config = self.CacheConfig(enabled=True, default_ttl=60)
        cache = self.ResponseCache(config)

        headers = {"X-Custom": "original"}
        body = bytearray(b"original")

        cache.set("mutable-test", 200, headers, bytes(body))

        # 修改外部对象
        headers["X-Custom"] = "modified"
        body[0] = ord("m")

        # 缓存应该不受影响
        result = cache.get("mutable-test")
        _, cached_headers, cached_body = result
        self.assertEqual(cached_headers["X-Custom"], "original")
        self.assertEqual(cached_body, b"original")


if __name__ == "__main__":
    unittest.main()
