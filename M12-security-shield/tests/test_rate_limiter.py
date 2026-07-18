"""
M12-security-shield - 速率限制单元测试

覆盖令牌桶算法、正常请求放行、超限拦截、窗口重置、
不同 key 独立计数、边界值、重置功能等测试场景。
"""

import sys
import os
import time
import unittest
from unittest.mock import patch
from services.rate_limiter import RateLimiter, TokenBucket


class TestTokenBucket(unittest.TestCase):
    """令牌桶单元测试"""

    def test_token_bucket_initial_tokens(self):
        """测试令牌桶初始令牌数等于容量"""
        bucket = TokenBucket(capacity=10.0, rate=1.0, tokens=10.0)
        self.assertEqual(bucket.tokens, 10.0)
        self.assertEqual(bucket.capacity, 10.0)

    def test_token_bucket_consume_success(self):
        """测试正常消耗令牌"""
        bucket = TokenBucket(capacity=10.0, rate=1.0, tokens=5.0)
        result = bucket.consume(1.0)
        self.assertTrue(result)
        self.assertEqual(bucket.tokens, 4.0)

    def test_token_bucket_consume_fail_when_empty(self):
        """测试令牌不足时消耗失败"""
        bucket = TokenBucket(capacity=10.0, rate=1.0, tokens=0.5)
        result = bucket.consume(1.0)
        self.assertFalse(result)
        # 令牌不足，不消耗
        self.assertLess(bucket.tokens, 1.0)

    def test_token_bucket_refill_over_time(self):
        """测试令牌随时间补充"""
        bucket = TokenBucket(capacity=10.0, rate=2.0, tokens=0.0)
        # 将 last_refill 设为 1 秒前
        bucket.last_refill = time.time() - 1.0
        bucket.refill()
        # 1 秒 * 2 速率 = 2 个令牌
        self.assertAlmostEqual(bucket.tokens, 2.0, delta=0.1)

    def test_token_bucket_capacity_limit(self):
        """测试令牌数不超过桶容量"""
        bucket = TokenBucket(capacity=10.0, rate=10.0, tokens=5.0)
        # 将 last_refill 设为很久以前，确保补充量远超容量
        bucket.last_refill = time.time() - 100.0
        bucket.refill()
        self.assertEqual(bucket.tokens, 10.0)

    def test_token_bucket_retry_after_when_empty(self):
        """测试令牌为空时的重试等待时间"""
        bucket = TokenBucket(capacity=10.0, rate=2.0, tokens=0.0)
        # 令牌为 0，需要 1 个令牌，速率 2/s，需要等 0.5 秒
        retry = bucket.get_retry_after()
        self.assertGreater(retry, 0)
        self.assertAlmostEqual(retry, 0.5, delta=0.1)

    def test_token_bucket_retry_after_when_available(self):
        """测试有可用令牌时重试时间为 0"""
        bucket = TokenBucket(capacity=10.0, rate=1.0, tokens=5.0)
        retry = bucket.get_retry_after()
        self.assertEqual(retry, 0)


class TestRateLimiterBasic(unittest.TestCase):
    """速率限制器基础功能测试"""

    def setUp(self):
        """每个测试创建新的速率限制器，小容量便于测试"""
        self.rl = RateLimiter(default_rate_per_minute=60, burst_size=10)

    def test_normal_request_allowed(self):
        """测试正常请求（令牌充足时）被允许"""
        allowed = self.rl.allow_request("192.168.1.1")
        self.assertTrue(allowed, "令牌充足时请求应被允许")

    def test_rate_limit_blocks_after_burst(self):
        """测试达到突发限制后请求被拒绝"""
        key = "test_ip_limit"
        # 突发容量为 10，连续发 10 次应该都通过
        for i in range(10):
            allowed = self.rl.allow_request(key)
            self.assertTrue(allowed, f"第 {i+1} 次请求应被允许（在突发容量内）")
        # 第 11 次应该被拒绝
        allowed = self.rl.allow_request(key)
        self.assertFalse(allowed, "超出突发容量后请求应被拒绝")

    def test_different_keys_independent(self):
        """测试不同 key 的计数器相互独立"""
        key_a = "ip_a"
        key_b = "ip_b"

        # 消耗完 key_a 的所有令牌
        for _ in range(10):
            self.rl.allow_request(key_a)

        # key_a 应该被限制
        self.assertFalse(self.rl.allow_request(key_a), "key_a 应被限制")

        # key_b 应该仍然正常
        stats_b = self.rl.get_stats(key_b)
        # key_b 还没有被访问过，首次查询会创建桶
        allowed_b = self.rl.allow_request(key_b)
        self.assertTrue(allowed_b, "不同 key 应独立计数，key_b 不应被 key_a 影响")

    def test_check_available_does_not_consume(self):
        """测试 check_available 不消耗令牌"""
        key = "check_only"
        # 检查两次可用状态，令牌不应减少
        available1, tokens1 = self.rl.check_available(key)
        self.assertTrue(available1)
        available2, tokens2 = self.rl.check_available(key)
        self.assertTrue(available2)
        # 两次检查令牌数应相同（因为没有消耗）
        self.assertAlmostEqual(tokens1, tokens2, delta=0.01)

    def test_reset_key_restores_tokens(self):
        """测试重置指定 key 后令牌恢复"""
        key = "reset_test"
        # 消耗一些令牌
        for _ in range(5):
            self.rl.allow_request(key)

        stats_before = self.rl.get_stats(key)
        self.assertLess(stats_before["tokens"], stats_before["capacity"])

        # 重置
        self.rl.reset(key)

        # 重置后首次访问会重新创建桶，令牌数 = 容量
        self.rl.allow_request(key)  # 触发创建
        stats_after = self.rl.get_stats(key)
        # 消耗了 1 个，所以应该是 capacity - 1
        self.assertEqual(stats_after["tokens"], stats_after["capacity"] - 1)

    def test_reset_all_clears_buckets(self):
        """测试重置所有令牌桶"""
        self.rl.allow_request("key1")
        self.rl.allow_request("key2")

        all_stats_before = self.rl.get_all_stats()
        self.assertEqual(len(all_stats_before), 2)

        self.rl.reset_all()

        all_stats_after = self.rl.get_all_stats()
        self.assertEqual(len(all_stats_after), 0)

    def test_rate_limiter_disable_bypasses(self):
        """测试禁用后所有请求都通过"""
        self.rl.disable()
        key = "disabled_test"
        # 即使发很多次也应该通过
        for _ in range(100):
            self.assertTrue(self.rl.allow_request(key))

    def test_rate_limiter_enable_after_disable(self):
        """测试重新启用后恢复限流"""
        key = "re_enable_test"
        self.rl.disable()
        self.assertTrue(self.rl.allow_request(key))

        self.rl.enable()
        # 启用后继续测试限流功能
        for _ in range(10):
            self.rl.allow_request(key)
        self.assertFalse(self.rl.allow_request(key), "重新启用后应恢复限流")

    def test_toggle_switch(self):
        """测试 toggle 切换限流开关"""
        initial = self.rl.is_active()
        new_state = self.rl.toggle()
        self.assertNotEqual(initial, new_state)
        new_state2 = self.rl.toggle()
        self.assertEqual(initial, new_state2)


class TestRateLimiterEdgeCases(unittest.TestCase):
    """速率限制边界值测试"""

    def test_burst_size_one(self):
        """测试边界值：burst_size=1"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=1)
        key = "burst_one"

        # 第一次应该通过
        self.assertTrue(rl.allow_request(key))
        # 第二次应该被拒绝
        self.assertFalse(rl.allow_request(key))

    def test_zero_rate_key(self):
        """测试自定义速率为 0 时的行为（令牌不增长）"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=5)
        key = "zero_rate"
        rl.set_custom_rate(key, rate_per_minute=0, burst=1)

        # 消耗初始令牌
        self.assertTrue(rl.allow_request(key))
        # 令牌用完后，因为速率为 0，永远无法补充
        self.assertFalse(rl.allow_request(key))
        # 重试时间应为无穷大
        retry = rl.get_retry_after(key)
        self.assertEqual(retry, float("inf"))

    def test_custom_rate(self):
        """测试自定义速率配置"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=10)
        key = "custom_key"
        # 自定义速率：每分钟 6 次，突发 3 次
        rl.set_custom_rate(key, rate_per_minute=6, burst=3)

        stats = rl.get_stats(key)
        self.assertEqual(stats["capacity"], 3.0)
        self.assertAlmostEqual(stats["rate_per_minute"], 6.0, delta=0.01)

        # 3 次突发请求
        for i in range(3):
            self.assertTrue(rl.allow_request(key), f"第 {i+1} 次应被允许")
        # 第 4 次应被拒绝
        self.assertFalse(rl.allow_request(key))

    def test_remove_custom_rate(self):
        """测试移除自定义速率配置"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=10)
        key = "remove_custom"
        rl.set_custom_rate(key, rate_per_minute=5, burst=2)

        # 验证自定义配置
        stats_before = rl.get_stats(key)
        self.assertEqual(stats_before["capacity"], 2.0)

        # 移除自定义配置
        rl.remove_custom_rate(key)

        # 移除后再请求，应该使用默认配置（burst=10）
        allowed = rl.allow_request(key)
        self.assertTrue(allowed)
        stats_after = rl.get_stats(key)
        self.assertEqual(stats_after["capacity"], 10.0)

    def test_get_stats_nonexistent_key(self):
        """测试查询不存在的 key 的统计信息"""
        stats = self.rl.get_stats("nonexistent_key")
        self.assertEqual(stats["tokens"], 0)
        self.assertEqual(stats["capacity"], 0)
        self.assertEqual(stats["rate"], 0)

    def setUp(self):
        self.rl = RateLimiter(default_rate_per_minute=60, burst_size=10)


class TestRateLimiterTimeBased(unittest.TestCase):
    """基于时间的速率限制测试（使用 mock time）"""

    def test_tokens_refill_after_time_passes(self):
        """测试时间流逝后令牌自动补充"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=10)  # 每秒 1 个令牌
        key = "refill_test"

        # 消耗所有令牌
        for _ in range(10):
            rl.allow_request(key)

        # 确认令牌耗尽
        self.assertFalse(rl.allow_request(key))

        # 获取当前时间作为基准
        base_time = time.time()

        # mock 时间前进 2 秒
        with patch("services.rate_limiter.time.time", return_value=base_time + 2.0):
            # 检查可用令牌（应该补充了约 2 个）
            available, tokens = rl.check_available(key)
            self.assertTrue(available, "2 秒后应补充了令牌")
            self.assertGreaterEqual(tokens, 1.5)
            self.assertLessEqual(tokens, 2.5)

    def test_retry_after_calculation(self):
        """测试重试等待时间计算正确性"""
        rl = RateLimiter(default_rate_per_minute=60, burst_size=10)  # 1 token/s
        key = "retry_test"

        # 消耗所有令牌
        for _ in range(10):
            rl.allow_request(key)

        # 此时令牌应该接近 0，重试时间约为 1 秒
        retry = rl.get_retry_after(key)
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 1.5)  # 应该接近 1 秒


if __name__ == "__main__":
    unittest.main(verbosity=2)
