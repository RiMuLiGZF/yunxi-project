"""M11 MCP Bus - 熔断器单元测试.

测试 CircuitBreaker 的状态转换：Closed → Open → Half-Open → Closed。
CircuitBreaker 类定义在 services/router.py 中。
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
from src.services.router import CircuitBreaker


class TestCircuitBreakerInitialState(unittest.TestCase):
    """测试熔断器初始状态."""

    def test_initial_state_is_closed(self) -> None:
        """测试初始状态为 Closed."""
        breaker = CircuitBreaker(server_id=1)
        self.assertEqual(breaker.state, CircuitBreaker.STATE_CLOSED)

    def test_initial_consecutive_failures_zero(self) -> None:
        """测试初始连续失败次数为 0."""
        breaker = CircuitBreaker(server_id=1)
        self.assertEqual(breaker.consecutive_failures, 0)

    def test_initial_can_execute_true(self) -> None:
        """测试初始状态下 can_execute 返回 True."""
        breaker = CircuitBreaker(server_id=1)
        self.assertTrue(breaker.can_execute())


class TestCircuitBreakerClosedState(unittest.TestCase):
    """测试 Closed 状态行为."""

    def test_failure_below_threshold_stays_closed(self) -> None:
        """测试失败次数未达阈值时保持 Closed."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=5)
        # 记录 4 次失败（未达阈值）
        for i in range(4):
            breaker.record_failure()
        self.assertEqual(breaker.state, CircuitBreaker.STATE_CLOSED)
        self.assertEqual(breaker.consecutive_failures, 4)

    def test_can_execute_in_closed_state(self) -> None:
        """测试 Closed 状态下 can_execute 始终返回 True."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=10)
        for i in range(5):
            self.assertTrue(breaker.can_execute())

    def test_success_resets_failure_count(self) -> None:
        """测试成功调用重置失败计数."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=5)
        # 记录几次失败
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.consecutive_failures, 2)
        # 记录一次成功
        breaker.record_success()
        self.assertEqual(breaker.consecutive_failures, 0)
        self.assertEqual(breaker.state, CircuitBreaker.STATE_CLOSED)


class TestCircuitBreakerOpenState(unittest.TestCase):
    """测试 Open 状态行为."""

    def test_reach_threshold_opens_circuit(self) -> None:
        """测试达到失败阈值后变为 Open 状态."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitBreaker.STATE_OPEN)

    def test_open_state_rejects_requests(self) -> None:
        """测试 Open 状态下拒绝请求（can_execute 返回 False）."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitBreaker.STATE_OPEN)
        self.assertFalse(breaker.can_execute())

    def test_failure_in_open_state_increments_count(self) -> None:
        """测试 Open 状态下继续记录失败，计数继续增加."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=2)
        breaker.record_failure()
        breaker.record_failure()
        # 已经 Open，再记录一次失败
        breaker.record_failure()
        self.assertEqual(breaker.consecutive_failures, 3)


class TestCircuitBreakerHalfOpenState(unittest.TestCase):
    """测试 Half-Open 状态行为."""

    def test_open_timeout_transitions_to_half_open(self) -> None:
        """测试 Open 超时后进入 Half-Open 状态."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=1, open_duration=0.1)
        breaker.record_failure()  # 触发熔断
        self.assertEqual(breaker.state, CircuitBreaker.STATE_OPEN)
        # 等待超时
        time.sleep(0.15)
        self.assertEqual(breaker.state, CircuitBreaker.STATE_HALF_OPEN)

    def test_half_open_success_returns_to_closed(self) -> None:
        """测试 Half-Open 状态下成功调用后回到 Closed."""
        breaker = CircuitBreaker(
            server_id=1, fail_threshold=1, open_duration=0.1, half_open_limit=1
        )
        breaker.record_failure()  # 触发熔断
        time.sleep(0.15)  # 等待进入 Half-Open
        self.assertEqual(breaker.state, CircuitBreaker.STATE_HALF_OPEN)
        # 成功调用
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitBreaker.STATE_CLOSED)
        self.assertEqual(breaker.consecutive_failures, 0)

    def test_half_open_failure_returns_to_open(self) -> None:
        """测试 Half-Open 状态下失败后回到 Open."""
        breaker = CircuitBreaker(
            server_id=1, fail_threshold=1, open_duration=0.1, half_open_limit=1
        )
        breaker.record_failure()  # 触发熔断
        time.sleep(0.15)  # 等待进入 Half-Open
        self.assertEqual(breaker.state, CircuitBreaker.STATE_HALF_OPEN)
        # 再次失败
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitBreaker.STATE_OPEN)

    def test_half_open_allows_limited_requests(self) -> None:
        """测试 Half-Open 状态下只允许 half_open_limit 个请求."""
        breaker = CircuitBreaker(
            server_id=1, fail_threshold=1, open_duration=0.1, half_open_limit=2
        )
        breaker.record_failure()  # 触发熔断
        time.sleep(0.15)  # 等待进入 Half-Open
        # 前 2 个请求应该被允许
        self.assertTrue(breaker.can_execute())
        self.assertTrue(breaker.can_execute())
        # 第 3 个请求应该被拒绝
        self.assertFalse(breaker.can_execute())


class TestCircuitBreakerCanExecute(unittest.TestCase):
    """测试 can_execute 在各状态下的返回值."""

    def test_can_execute_closed_returns_true(self) -> None:
        """测试 Closed 状态 can_execute 返回 True."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=10)
        for _ in range(10):
            self.assertTrue(breaker.can_execute())

    def test_can_execute_open_returns_false(self) -> None:
        """测试 Open 状态 can_execute 返回 False."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=1)
        breaker.record_failure()
        self.assertFalse(breaker.can_execute())

    def test_can_execute_half_open_allows_limited(self) -> None:
        """测试 Half-Open 状态 can_execute 有限放行."""
        breaker = CircuitBreaker(
            server_id=1, fail_threshold=1, open_duration=0.1, half_open_limit=3
        )
        breaker.record_failure()
        time.sleep(0.15)
        # Half-Open 状态下放行 3 个
        self.assertTrue(breaker.can_execute())
        self.assertTrue(breaker.can_execute())
        self.assertTrue(breaker.can_execute())
        self.assertFalse(breaker.can_execute())


class TestCircuitBreakerStatusDict(unittest.TestCase):
    """测试 get_status_dict 方法."""

    def test_status_dict_initial(self) -> None:
        """测试初始状态的 status_dict."""
        breaker = CircuitBreaker(server_id=42, fail_threshold=5, open_duration=30)
        status = breaker.get_status_dict()
        self.assertEqual(status["server_id"], 42)
        self.assertEqual(status["state"], CircuitBreaker.STATE_CLOSED)
        self.assertEqual(status["consecutive_failures"], 0)
        self.assertEqual(status["fail_threshold"], 5)
        self.assertEqual(status["open_duration"], 30)
        self.assertIsNone(status["open_at"])

    def test_status_dict_open_state(self) -> None:
        """测试 Open 状态的 status_dict."""
        breaker = CircuitBreaker(server_id=1, fail_threshold=1)
        breaker.record_failure()
        status = breaker.get_status_dict()
        self.assertEqual(status["state"], CircuitBreaker.STATE_OPEN)
        self.assertIsNotNone(status["open_at"])


class TestCircuitBreakerManager(unittest.TestCase):
    """测试熔断器管理器 CircuitBreakerManager."""

    def test_get_breaker_creates_instance(self) -> None:
        """测试 get_breaker 创建熔断器实例."""
        from src.services.router import CircuitBreakerManager

        # 使用 patch 避免依赖全局 settings
        with patch("src.services.router.get_settings") as mock_settings:
            mock_settings.return_value.circuit_breaker_fail_threshold = 5
            mock_settings.return_value.circuit_breaker_open_duration = 30
            mock_settings.return_value.circuit_breaker_half_open_limit = 1

            manager = CircuitBreakerManager()
            breaker = manager.get_breaker(1)
            self.assertIsInstance(breaker, CircuitBreaker)
            self.assertEqual(breaker.server_id, 1)

    def test_get_breaker_returns_same_instance(self) -> None:
        """测试同一 server_id 返回同一实例."""
        from src.services.router import CircuitBreakerManager

        with patch("src.services.router.get_settings") as mock_settings:
            mock_settings.return_value.circuit_breaker_fail_threshold = 5
            mock_settings.return_value.circuit_breaker_open_duration = 30
            mock_settings.return_value.circuit_breaker_half_open_limit = 1

            manager = CircuitBreakerManager()
            b1 = manager.get_breaker(1)
            b2 = manager.get_breaker(1)
            self.assertIs(b1, b2)

    def test_reset_removes_breaker(self) -> None:
        """测试 reset 移除指定熔断器."""
        from src.services.router import CircuitBreakerManager

        with patch("src.services.router.get_settings") as mock_settings:
            mock_settings.return_value.circuit_breaker_fail_threshold = 5
            mock_settings.return_value.circuit_breaker_open_duration = 30
            mock_settings.return_value.circuit_breaker_half_open_limit = 1

            manager = CircuitBreakerManager()
            manager.get_breaker(1)
            manager.get_breaker(2)
            self.assertEqual(len(manager.get_all_status()), 2)
            manager.reset(1)
            self.assertEqual(len(manager.get_all_status()), 1)
            # 重新获取是新的实例
            new_breaker = manager.get_breaker(1)
            self.assertEqual(new_breaker.state, CircuitBreaker.STATE_CLOSED)


if __name__ == "__main__":
    unittest.main()
