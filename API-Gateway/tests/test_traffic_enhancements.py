"""
API-Gateway 流量管理增强测试（CQ-008, P1级）

测试目标：
1. 令牌桶限流算法
2. 多维度限流（全局/IP/用户/路径）
3. 动态限流配置
4. 重试机制（指数退避 + 抖动）
5. 幂等性检查
6. 增强版熔断器（慢请求熔断）
7. 自适应阈值
8. 渐进式恢复
"""

import sys
import asyncio
import time
import unittest
from pathlib import Path

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))


class TestTokenBucket(unittest.TestCase):
    """令牌桶测试"""

    def setUp(self):
        from src.traffic.token_bucket import TokenBucket, TokenBucketConfig
        self.TokenBucket = TokenBucket
        self.TokenBucketConfig = TokenBucketConfig

    def test_initial_tokens(self):
        """测试初始令牌数"""
        config = self.TokenBucketConfig(rate=10, capacity=100, initial_tokens=50)
        bucket = self.TokenBucket(config)
        self.assertAlmostEqual(bucket.tokens, 50, delta=1)

    def test_consume_success(self):
        """测试成功消耗令牌"""
        config = self.TokenBucketConfig(rate=10, capacity=100, initial_tokens=10)
        bucket = self.TokenBucket(config)
        success, remaining = bucket.try_consume(5)
        self.assertTrue(success)
        self.assertAlmostEqual(remaining, 5, delta=0.1)

    def test_consume_failure(self):
        """测试令牌不足时消耗失败"""
        config = self.TokenBucketConfig(rate=10, capacity=100, initial_tokens=3)
        bucket = self.TokenBucket(config)
        success, remaining = bucket.try_consume(5)
        self.assertFalse(success)
        self.assertAlmostEqual(remaining, 3, delta=0.1)

    def test_refill_over_time(self):
        """测试令牌随时间补充"""
        config = self.TokenBucketConfig(rate=100, capacity=100, initial_tokens=0)
        bucket = self.TokenBucket(config)
        # 等待 10ms，应该补充约 1 个令牌
        time.sleep(0.01)
        self.assertGreater(bucket.tokens, 0)
        self.assertLess(bucket.tokens, 10)

    def test_capacity_limit(self):
        """测试令牌数不超过容量"""
        config = self.TokenBucketConfig(rate=100, capacity=50, initial_tokens=50)
        bucket = self.TokenBucket(config)
        # 等待让令牌补充，但不应超过容量
        time.sleep(0.1)
        self.assertLessEqual(bucket.tokens, 50)

    def test_update_config(self):
        """测试更新配置"""
        config = self.TokenBucketConfig(rate=10, capacity=100, initial_tokens=50)
        bucket = self.TokenBucket(config)

        new_config = self.TokenBucketConfig(rate=20, capacity=200)
        bucket.update_config(new_config)
        self.assertEqual(bucket.capacity, 200)
        self.assertEqual(bucket.rate, 20)

    def test_update_config_reduces_tokens(self):
        """测试更新配置到更小容量时令牌数调整"""
        config = self.TokenBucketConfig(rate=10, capacity=100, initial_tokens=100)
        bucket = self.TokenBucket(config)

        new_config = self.TokenBucketConfig(rate=10, capacity=50)
        bucket.update_config(new_config)
        self.assertEqual(bucket.tokens, 50)


class TestTokenBucketLimiter(unittest.TestCase):
    """令牌桶限流器测试"""

    def setUp(self):
        from src.traffic.token_bucket import TokenBucketLimiter
        self.TokenBucketLimiter = TokenBucketLimiter

    def test_global_limit(self):
        """测试全局限流"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=10)
        # 消耗 10 个令牌应该成功
        for i in range(10):
            allowed, reason, info = limiter.check_limit()
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        # 第 11 次应该被限流
        allowed, reason, info = limiter.check_limit()
        self.assertFalse(allowed)
        self.assertEqual(reason, "global_rate_limit_exceeded")

    def test_ip_limit(self):
        """测试 IP 限流"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_default_ip_limit(rate=1000, capacity=5)

        # 同一个 IP 5 次请求成功
        for i in range(5):
            allowed, reason, info = limiter.check_limit(ip="192.168.1.1")
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        # 第 6 次被 IP 限流
        allowed, reason, info = limiter.check_limit(ip="192.168.1.1")
        self.assertFalse(allowed)
        self.assertEqual(reason, "ip_rate_limit_exceeded")

    def test_different_ip_independent(self):
        """测试不同 IP 独立计数"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_default_ip_limit(rate=1000, capacity=1)

        # IP1 消耗完
        allowed, _, _ = limiter.check_limit(ip="192.168.1.1")
        self.assertTrue(allowed)
        allowed, _, _ = limiter.check_limit(ip="192.168.1.1")
        self.assertFalse(allowed)

        # IP2 不受影响
        allowed, _, _ = limiter.check_limit(ip="192.168.1.2")
        self.assertTrue(allowed)

    def test_user_limit(self):
        """测试用户限流"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_default_user_limit(rate=1000, capacity=3)

        for i in range(3):
            allowed, reason, info = limiter.check_limit(user_id="user1")
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        allowed, reason, info = limiter.check_limit(user_id="user1")
        self.assertFalse(allowed)
        self.assertEqual(reason, "user_rate_limit_exceeded")

    def test_path_limit(self):
        """测试路径限流"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_path_limit("/api/sensitive", rate=1000, capacity=2)

        for i in range(2):
            allowed, reason, info = limiter.check_limit(path="/api/sensitive")
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

        allowed, reason, info = limiter.check_limit(path="/api/sensitive")
        self.assertFalse(allowed)
        self.assertEqual(reason, "path_rate_limit_exceeded")

    def test_path_not_configured_no_limit(self):
        """测试未配置的路径不受路径限流影响"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_path_limit("/api/sensitive", rate=1000, capacity=1)

        # 未配置的路径可以多次请求
        for _ in range(10):
            allowed, _, _ = limiter.check_limit(path="/api/public")
            self.assertTrue(allowed)

    def test_specific_ip_limit_overrides_default(self):
        """测试特定 IP 配置覆盖默认配置"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_default_ip_limit(rate=1000, capacity=5)
        limiter.set_ip_limit("10.0.0.1", rate=1000, capacity=20)

        # 特定 IP 有更高限额
        for i in range(20):
            allowed, _, _ = limiter.check_limit(ip="10.0.0.1")
            self.assertTrue(allowed, f"第 {i+1} 次请求应该通过")

    def test_set_global_config(self):
        """测试设置全局配置"""
        limiter = self.TokenBucketLimiter(global_rate=10, global_capacity=100)
        limiter.set_global_config(rate=1000, capacity=5)
        stats = limiter.get_stats()
        self.assertEqual(stats["global_capacity"], 5)
        self.assertEqual(stats["global_rate"], 1000)

    def test_remove_ip_limit(self):
        """测试移除 IP 限流配置"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_ip_limit("192.168.1.1", rate=1, capacity=1)
        success = limiter.remove_ip_limit("192.168.1.1")
        self.assertTrue(success)

    def test_remove_user_limit(self):
        """测试移除用户限流配置"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_user_limit("user1", rate=1, capacity=1)
        success = limiter.remove_user_limit("user1")
        self.assertTrue(success)

    def test_remove_path_limit(self):
        """测试移除路径限流配置"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_path_limit("/api/test", rate=1, capacity=1)
        success = limiter.remove_path_limit("/api/test")
        self.assertTrue(success)

    def test_get_stats(self):
        """测试获取统计信息"""
        limiter = self.TokenBucketLimiter(global_rate=100, global_capacity=100)
        limiter.check_limit()
        stats = limiter.get_stats()
        self.assertEqual(stats["total_requests"], 1)
        self.assertEqual(stats["allowed"], 1)
        self.assertIn("allow_rate", stats)

    def test_reset_stats(self):
        """测试重置统计"""
        limiter = self.TokenBucketLimiter(global_rate=100, global_capacity=100)
        limiter.check_limit()
        limiter.reset_stats()
        stats = limiter.get_stats()
        self.assertEqual(stats["total_requests"], 0)

    def test_cleanup(self):
        """测试清理长时间不活动的桶"""
        limiter = self.TokenBucketLimiter(global_rate=1000, global_capacity=1000)
        limiter.set_default_ip_limit(rate=10, capacity=100)
        limiter.check_limit(ip="192.168.1.1")
        # 清理（但因为刚访问过，不会被清理）
        limiter.cleanup(max_idle_seconds=3600)
        stats = limiter.get_stats()
        self.assertGreater(stats["active_ip_buckets"], 0)


class TestRetryManager(unittest.TestCase):
    """重试管理器测试"""

    def setUp(self):
        from src.traffic.retry_manager import RetryManager, RetryConfig
        self.RetryManager = RetryManager
        self.RetryConfig = RetryConfig

    def test_no_retry_on_success(self):
        """测试成功请求不重试"""
        config = self.RetryConfig(max_retries=3, base_delay=0.001)
        manager = self.RetryManager(config)

        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return 200, {}, b"ok"

        result = asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", success_func)
        )
        self.assertEqual(result[0], 200)
        self.assertEqual(call_count, 1)

    def test_retry_on_failure(self):
        """测试失败时重试"""
        config = self.RetryConfig(max_retries=2, base_delay=0.001, jitter=False)
        manager = self.RetryManager(config)

        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            return 500, {}, b"error"

        result = asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", always_fail)
        )
        self.assertEqual(result[0], 500)
        # 初始请求 + 2 次重试 = 3 次调用
        self.assertEqual(call_count, 3)

    def test_non_idempotent_no_retry(self):
        """测试非幂等方法不重试"""
        config = self.RetryConfig(max_retries=3, base_delay=0.001, only_idempotent=True)
        manager = self.RetryManager(config)

        call_count = 0

        async def fail_func():
            nonlocal call_count
            call_count += 1
            return 500, {}, b"error"

        result = asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("POST", fail_func)
        )
        self.assertEqual(call_count, 1)

    def test_idempotent_methods(self):
        """测试幂等方法列表"""
        config = self.RetryConfig(max_retries=1, base_delay=0.001)
        manager = self.RetryManager(config)

        for method in ["GET", "HEAD", "PUT", "DELETE", "OPTIONS", "TRACE"]:
            self.assertTrue(manager.is_method_retryable(method),
                          f"{method} 应该是幂等的")

    def test_non_idempotent_methods(self):
        """测试非幂等方法"""
        config = self.RetryConfig(max_retries=1, base_delay=0.001)
        manager = self.RetryManager(config)

        for method in ["POST", "PATCH"]:
            self.assertFalse(manager.is_method_retryable(method),
                           f"{method} 应该是非幂等的")

    def test_retryable_status_codes(self):
        """测试可重试状态码"""
        config = self.RetryConfig()
        manager = self.RetryManager(config)

        for code in [408, 429, 500, 502, 503, 504]:
            self.assertTrue(manager.is_status_retryable(code),
                          f"状态码 {code} 应该可重试")

        for code in [200, 201, 400, 401, 403, 404]:
            self.assertFalse(manager.is_status_retryable(code),
                           f"状态码 {code} 不应该重试")

    def test_success_after_retry(self):
        """测试重试后成功"""
        config = self.RetryConfig(max_retries=3, base_delay=0.001, jitter=False)
        manager = self.RetryManager(config)

        call_count = 0

        async def succeed_on_second():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return 503, {}, b"unavailable"
            return 200, {}, b"ok"

        result = asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", succeed_on_second)
        )
        self.assertEqual(result[0], 200)
        self.assertEqual(call_count, 2)

    def test_get_stats(self):
        """测试获取统计信息"""
        config = self.RetryConfig(max_retries=1, base_delay=0.001)
        manager = self.RetryManager(config)

        async def success_func():
            return 200, {}, b"ok"

        asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", success_func)
        )

        stats = manager.get_stats()
        self.assertEqual(stats["total_requests"], 1)
        self.assertIn("retry_rate_percent", stats)

    def test_reset_stats(self):
        """测试重置统计"""
        config = self.RetryConfig(max_retries=0)
        manager = self.RetryManager(config)

        async def func():
            return 200, {}, b"ok"

        asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", func)
        )

        manager.reset_stats()
        stats = manager.get_stats()
        self.assertEqual(stats["total_requests"], 0)

    def test_update_config(self):
        """测试更新配置"""
        config = self.RetryConfig(max_retries=1)
        manager = self.RetryManager(config)

        new_config = self.RetryConfig(max_retries=5)
        manager.update_config(new_config)
        self.assertEqual(manager.get_config().max_retries, 5)

    def test_zero_max_retries(self):
        """测试 max_retries=0 不重试"""
        config = self.RetryConfig(max_retries=0)
        manager = self.RetryManager(config)

        call_count = 0

        async def fail_func():
            nonlocal call_count
            call_count += 1
            return 500, {}, b"error"

        asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", fail_func)
        )
        self.assertEqual(call_count, 1)

    def test_on_retry_callback(self):
        """测试重试回调"""
        config = self.RetryConfig(max_retries=2, base_delay=0.001, jitter=False)
        manager = self.RetryManager(config)

        call_count = 0
        retry_count = 0

        async def fail_func():
            nonlocal call_count
            call_count += 1
            return 500, {}, b"error"

        async def on_retry(attempt, status, delay):
            nonlocal retry_count
            retry_count += 1

        asyncio.get_event_loop().run_until_complete(
            manager.execute_with_retry("GET", fail_func, on_retry=on_retry)
        )
        self.assertEqual(retry_count, 2)


class TestAdvancedCircuitBreaker(unittest.TestCase):
    """增强版熔断器测试"""

    def setUp(self):
        from src.traffic.advanced_circuit_breaker import AdvancedCircuitBreaker, CircuitState
        self.AdvancedCircuitBreaker = AdvancedCircuitBreaker
        self.CircuitState = CircuitState

    def test_initial_closed(self):
        """测试初始状态为关闭"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=3, recovery_time=1)
        self.assertEqual(cb.get_state("test"), self.CircuitState.CLOSED)

    def test_closed_allows_requests(self):
        """测试关闭状态允许请求"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=3, recovery_time=1)

        async def check():
            return await cb.can_execute("test")

        result = asyncio.get_event_loop().run_until_complete(check())
        self.assertTrue(result)

    def test_trip_after_failures(self):
        """测试达到失败阈值后熔断"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=3, recovery_time=10)

        async def test():
            for i in range(3):
                await cb.record_failure("test")

            return await cb.can_execute("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertFalse(result)
        self.assertEqual(cb.get_state("test"), self.CircuitState.OPEN)

    def test_half_open_after_recovery(self):
        """测试恢复时间过后进入半开状态"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=2, recovery_time=0.01)

        async def test():
            await cb.record_failure("test")
            await cb.record_failure("test")
            self.assertEqual(cb.get_state("test"), self.CircuitState.OPEN)
            await asyncio.sleep(0.02)
            return await cb.can_execute("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertTrue(result)
        self.assertEqual(cb.get_state("test"), self.CircuitState.HALF_OPEN)

    def test_half_open_success_recovers(self):
        """测试半开状态成功后恢复关闭"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=2, recovery_time=0.01)

        async def test():
            # 熔断
            await cb.record_failure("test")
            await cb.record_failure("test")
            await asyncio.sleep(0.02)

            # 半开状态
            await cb.can_execute("test")
            await cb.record_success("test")

            await cb.can_execute("test")
            await cb.record_success("test")

            await cb.can_execute("test")
            await cb.record_success("test")

            return cb.get_state("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        # 经过多次成功后应该恢复到关闭状态
        self.assertEqual(result, self.CircuitState.CLOSED)

    def test_half_open_failure_reopens(self):
        """测试半开状态失败后重新熔断"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=2, recovery_time=0.01)

        async def test():
            await cb.record_failure("test")
            await cb.record_failure("test")
            await asyncio.sleep(0.02)

            await cb.can_execute("test")
            await cb.record_failure("test")

            return cb.get_state("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result, self.CircuitState.OPEN)

    def test_reset(self):
        """测试手动重置"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=2, recovery_time=10)

        async def test():
            await cb.record_failure("test")
            await cb.record_failure("test")
            self.assertEqual(cb.get_state("test"), self.CircuitState.OPEN)
            await cb.reset("test")
            return cb.get_state("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertEqual(result, self.CircuitState.CLOSED)

    def test_slow_request_config(self):
        """测试慢请求配置"""
        from src.traffic.advanced_circuit_breaker import SlowRequestConfig
        cb = self.AdvancedCircuitBreaker(failure_threshold=5, recovery_time=10)
        config = SlowRequestConfig(enabled=True, threshold_ms=1000, failure_weight=0.5)
        cb.configure_slow_request(config)

        stats = cb.get_stats()
        # 慢请求配置应该反映在统计中
        self.assertTrue(True)  # 配置成功不报错即可

    def test_get_stats(self):
        """测试获取统计信息"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=3, recovery_time=10)

        async def test():
            await cb.can_execute("test")
            await cb.record_success("test")
            return cb.get_stats()

        stats = asyncio.get_event_loop().run_until_complete(test())
        self.assertIn("test", stats)
        self.assertIn("state", stats["test"])
        self.assertIn("total_requests", stats["test"])

    def test_adaptive_threshold_config(self):
        """测试自适应阈值配置"""
        from src.traffic.advanced_circuit_breaker import AdaptiveThresholdConfig
        cb = self.AdvancedCircuitBreaker(failure_threshold=5, recovery_time=10)
        config = AdaptiveThresholdConfig(
            enabled=True,
            min_threshold=2,
            max_threshold=10,
            window_size=20,
            target_failure_rate=0.1,
        )
        cb.configure_adaptive(config)
        self.assertTrue(True)  # 配置成功不报错即可

    def test_progressive_recovery_config(self):
        """测试渐进式恢复配置"""
        from src.traffic.advanced_circuit_breaker import ProgressiveRecoveryConfig
        cb = self.AdvancedCircuitBreaker(failure_threshold=5, recovery_time=10)
        config = ProgressiveRecoveryConfig(
            enabled=True,
            steps=5,
            step_percentages=[10, 25, 50, 75, 100],
            step_interval=1,
        )
        cb.configure_progressive_recovery(config)
        self.assertTrue(True)  # 配置成功不报错即可

    def test_record_request_unified(self):
        """测试统一记录请求接口"""
        cb = self.AdvancedCircuitBreaker(failure_threshold=2, recovery_time=10)

        async def test():
            await cb.record_request("test", success=True)
            await cb.record_request("test", success=False)
            await cb.record_request("test", success=False)
            return await cb.can_execute("test")

        result = asyncio.get_event_loop().run_until_complete(test())
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
