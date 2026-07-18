"""M11 MCP Bus - 限流器单元测试.

测试 MemoryRateLimiter 的限流逻辑、窗口重置、剩余次数、边界值等。
"""

import os
import sys
import time
import unittest

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
from src.services.rate_limiter import MemoryRateLimiter


class TestRateLimiterNormalRequests(unittest.TestCase):
    """测试正常请求不超限的场景."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_single_request_allowed(self) -> None:
        """测试单个请求允许通过."""
        result = self.limiter.check_rate("test-key", 10, 60)
        self.assertTrue(result)

    def test_multiple_requests_within_limit(self) -> None:
        """测试在限制次数内的请求都被允许."""
        for i in range(5):
            result = self.limiter.check_rate("test-key", 10, 60)
            self.assertTrue(result, f"第 {i+1} 次请求应该被允许")

    def test_requests_equal_to_limit_allowed(self) -> None:
        """测试恰好达到限制次数的请求都被允许."""
        limit = 5
        for i in range(limit):
            result = self.limiter.check_rate("test-key", limit, 60)
            self.assertTrue(result, f"第 {i+1} 次请求应该被允许")


class TestRateLimiterExceedLimit(unittest.TestCase):
    """测试达到限制后被拒绝的场景."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_exceeding_limit_rejected(self) -> None:
        """测试超过限制后请求被拒绝."""
        limit = 3
        # 先消耗完所有令牌
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, 60)
        # 第 limit+1 次请求应该被拒绝
        result = self.limiter.check_rate("test-key", limit, 60)
        self.assertFalse(result)

    def test_multiple_exceeding_requests_rejected(self) -> None:
        """测试超限后多次请求都被拒绝."""
        limit = 2
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, 60)
        # 连续多次超限请求都应被拒绝
        for i in range(5):
            result = self.limiter.check_rate("test-key", limit, 60)
            self.assertFalse(result, f"第 {limit+i+1} 次超限请求应该被拒绝")


class TestRateLimiterWindowReset(unittest.TestCase):
    """测试窗口过期后重置."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_window_expires_resets_count(self) -> None:
        """测试窗口过期后计数重置，可以再次请求."""
        limit = 2
        window = 1  # 1 秒窗口

        # 消耗完令牌
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, window)
        # 确认超限
        self.assertFalse(self.limiter.check_rate("test-key", limit, window))

        # 等待窗口过期
        time.sleep(window + 0.1)

        # 窗口过期后应该可以再次请求
        result = self.limiter.check_rate("test-key", limit, window)
        self.assertTrue(result, "窗口过期后计数应该重置")

    def test_window_resets_full_limit_available(self) -> None:
        """测试窗口过期后完整限制次数可用."""
        limit = 3
        window = 1

        # 消耗完
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, window)

        # 等待过期
        time.sleep(window + 0.1)

        # 应该可以再次发出 limit 次请求
        for i in range(limit):
            result = self.limiter.check_rate("test-key", limit, window)
            self.assertTrue(result, f"窗口重置后第 {i+1} 次请求应该被允许")


class TestRateLimiterIndependentKeys(unittest.TestCase):
    """测试不同 key 独立计数."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_different_keys_independent(self) -> None:
        """测试不同 key 的计数互不影响."""
        limit = 3
        # key-a 消耗完
        for i in range(limit):
            self.limiter.check_rate("key-a", limit, 60)
        self.assertFalse(self.limiter.check_rate("key-a", limit, 60))

        # key-b 应该不受影响，仍然可以请求
        for i in range(limit):
            result = self.limiter.check_rate("key-b", limit, 60)
            self.assertTrue(result, f"key-b 第 {i+1} 次请求应该被允许")

    def test_many_keys_all_independent(self) -> None:
        """测试多个 key 都独立计数."""
        limit = 5
        keys = [f"key-{i}" for i in range(10)]

        # 每个 key 都发 limit 次请求
        for key in keys:
            for i in range(limit):
                result = self.limiter.check_rate(key, limit, 60)
                self.assertTrue(result)

        # 每个 key 都应该超限
        for key in keys:
            result = self.limiter.check_rate(key, limit, 60)
            self.assertFalse(result)


class TestRateLimiterGetRemaining(unittest.TestCase):
    """测试 get_remaining 返回正确剩余次数."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_remaining_starts_at_limit(self) -> None:
        """测试初始剩余次数等于限制次数."""
        remaining = self.limiter.get_remaining("test-key", 10, 60)
        self.assertEqual(remaining, 10)

    def test_remaining_decreases_after_requests(self) -> None:
        """测试请求后剩余次数减少."""
        limit = 10
        self.limiter.check_rate("test-key", limit, 60)
        remaining = self.limiter.get_remaining("test-key", limit, 60)
        self.assertEqual(remaining, 9)

    def test_remaining_zero_when_exceeded(self) -> None:
        """测试超限后剩余次数为 0."""
        limit = 3
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, 60)
        remaining = self.limiter.get_remaining("test-key", limit, 60)
        self.assertEqual(remaining, 0)

    def test_remaining_resets_after_window(self) -> None:
        """测试窗口过期后剩余次数恢复为限制次数."""
        limit = 5
        window = 1
        for i in range(limit):
            self.limiter.check_rate("test-key", limit, window)

        time.sleep(window + 0.1)

        remaining = self.limiter.get_remaining("test-key", limit, window)
        self.assertEqual(remaining, limit)


class TestRateLimiterBoundaryValues(unittest.TestCase):
    """测试边界值情况."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_limit_equals_one(self) -> None:
        """测试 limit=1 的边界情况：第一次允许，第二次拒绝."""
        result1 = self.limiter.check_rate("test-key", 1, 60)
        self.assertTrue(result1)
        result2 = self.limiter.check_rate("test-key", 1, 60)
        self.assertFalse(result2)

    def test_limit_equals_zero(self) -> None:
        """测试 limit=0 的边界情况：所有请求都被拒绝."""
        result = self.limiter.check_rate("test-key", 0, 60)
        self.assertFalse(result)

    def test_remaining_with_limit_zero(self) -> None:
        """测试 limit=0 时剩余次数为 0."""
        remaining = self.limiter.get_remaining("test-key", 0, 60)
        self.assertEqual(remaining, 0)


class TestRateLimiterReset(unittest.TestCase):
    """测试重置功能."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_reset_key(self) -> None:
        """测试重置指定 key 的计数."""
        limit = 5
        # 消耗一些令牌
        for i in range(3):
            self.limiter.check_rate("test-key", limit, 60)
        # 重置
        self.limiter.reset("test-key")
        # 重置后应该可以重新发出 limit 次请求
        for i in range(limit):
            result = self.limiter.check_rate("test-key", limit, 60)
            self.assertTrue(result, f"重置后第 {i+1} 次请求应该被允许")

    def test_reset_all(self) -> None:
        """测试重置所有计数."""
        limit = 5
        self.limiter.check_rate("key-a", limit, 60)
        self.limiter.check_rate("key-b", limit, 60)
        self.limiter.reset_all()
        # 两个 key 都应该重置
        self.assertEqual(self.limiter.get_remaining("key-a", limit, 60), limit)
        self.assertEqual(self.limiter.get_remaining("key-b", limit, 60), limit)


class TestRateLimiterStats(unittest.TestCase):
    """测试统计信息."""

    def setUp(self) -> None:
        """每个测试前创建新的限流器实例."""
        self.limiter = MemoryRateLimiter(cleanup_interval=60)

    def test_stats_initial(self) -> None:
        """测试初始统计信息."""
        stats = self.limiter.get_stats()
        self.assertEqual(stats["active_keys"], 0)
        self.assertEqual(stats["total_tracked_requests"], 0)
        self.assertEqual(stats["backend"], "memory")

    def test_stats_after_requests(self) -> None:
        """测试请求后的统计信息."""
        self.limiter.check_rate("key-a", 10, 60)
        self.limiter.check_rate("key-a", 10, 60)
        self.limiter.check_rate("key-b", 10, 60)
        stats = self.limiter.get_stats()
        self.assertEqual(stats["active_keys"], 2)
        self.assertEqual(stats["total_tracked_requests"], 3)


class TestRateLimiterFactory(unittest.TestCase):
    """测试限流器工厂函数."""

    def test_get_rate_limiter_returns_memory_by_default(self) -> None:
        """测试默认配置下 get_rate_limiter 返回内存限流器."""
        from src.services.rate_limiter import get_rate_limiter

        limiter = get_rate_limiter()
        self.assertIsInstance(limiter, MemoryRateLimiter)

    def test_global_rate_limiter_is_memory(self) -> None:
        """测试全局限流器单例是 MemoryRateLimiter."""
        from src.services.rate_limiter import rate_limiter

        self.assertIsInstance(rate_limiter, MemoryRateLimiter)


if __name__ == "__main__":
    unittest.main()
