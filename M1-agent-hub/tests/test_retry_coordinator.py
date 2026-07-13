"""
测试：RetryCoordinator 统一重试协调器（P2-011）
"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")

from unittest.mock import MagicMock
from retry_coordinator import RetryCoordinator, RetryStrategy


def test_first_retry_is_immediate():
    coord = RetryCoordinator()
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    assert decision.allowed is True
    assert decision.strategy == RetryStrategy.IMMEDIATE
    assert decision.delay_seconds == 0.0


def test_second_retry_is_exponential():
    coord = RetryCoordinator()
    coord.record_retry("task_1")
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    assert decision.allowed is True
    assert decision.strategy == RetryStrategy.EXPONENTIAL
    assert decision.delay_seconds > 0.0


def test_max_retries_exceeded():
    coord = RetryCoordinator(max_retries=2)
    coord.record_retry("task_1")
    coord.record_retry("task_1")
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    assert decision.allowed is False
    assert decision.strategy == RetryStrategy.ABANDON


def test_circuit_breaker_open_rejects_retry():
    coord = RetryCoordinator()
    mock_breaker = MagicMock()
    mock_state = MagicMock()
    mock_state.value = "open"
    mock_breaker.get_state.return_value = mock_state
    decision = coord.check_can_retry("task_1", agent_id="agent_a", circuit_breaker=mock_breaker)
    assert decision.allowed is False
    assert decision.strategy == RetryStrategy.ABANDON
    assert "open" in decision.reason


def test_circuit_breaker_closed_allows_retry():
    coord = RetryCoordinator()
    mock_breaker = MagicMock()
    mock_state = MagicMock()
    mock_state.value = "closed"
    mock_breaker.get_state.return_value = mock_state
    decision = coord.check_can_retry("task_1", agent_id="agent_a", circuit_breaker=mock_breaker)
    assert decision.allowed is True


def test_dlq_max_retries_rejects():
    coord = RetryCoordinator()
    decision = coord.check_can_retry("task_1", agent_id="agent_a", dlq_retry_count=3, dlq_max_retries=3)
    assert decision.allowed is False
    assert "DLQ" in decision.reason


def test_record_success_clears_state():
    coord = RetryCoordinator()
    coord.record_retry("task_1")
    coord.record_retry("task_1")
    coord.record_success("task_1")
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    assert decision.retry_count == 0


def test_reset_clears_state():
    coord = RetryCoordinator()
    coord.record_retry("task_1")
    coord.reset("task_1")
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    assert decision.retry_count == 0


def test_stats():
    coord = RetryCoordinator()
    coord.record_retry("task_1")
    coord.record_retry("task_2")
    stats = coord.stats()
    assert stats["active_tasks"] == 2
    assert stats["max_retries"] == 3


def test_exponential_backoff_calculation():
    coord = RetryCoordinator(base_delay=1.0, backoff_multiplier=2.0)
    coord.record_retry("task_1")  # retry_count = 1
    coord.record_retry("task_1")  # retry_count = 2
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    # [V9.7] 自适应退避：delay 使用实例配置与 learned_multiplier 的混合
    # next_count = 3, effective_multiplier ≈ 2.0
    assert decision.delay_seconds > 3.5
    assert decision.delay_seconds <= 5.0


def test_max_delay_cap():
    coord = RetryCoordinator(base_delay=1.0, backoff_multiplier=10.0, max_delay=5.0, max_retries=5)
    coord.record_retry("task_1")  # 1
    coord.record_retry("task_1")  # 2
    coord.record_retry("task_1")  # 3
    coord.record_retry("task_1")  # 4
    decision = coord.check_can_retry("task_1", agent_id="agent_a")
    # next_count = 5, delay = 1.0 * 10^4 = 10000, capped at 5.0
    assert decision.allowed is True
    assert decision.delay_seconds == 5.0


def test_multiple_tasks_independent():
    coord = RetryCoordinator(max_retries=1)
    coord.record_retry("task_a")
    coord.record_retry("task_a")
    # task_a should be exhausted
    decision_a = coord.check_can_retry("task_a", agent_id="agent_a")
    assert decision_a.allowed is False
    # task_b should be fresh
    decision_b = coord.check_can_retry("task_b", agent_id="agent_b")
    assert decision_b.allowed is True


def test_record_retry_increments():
    coord = RetryCoordinator()
    coord.record_retry("task_1", error="timeout")
    state = coord.get_state("task_1")
    assert state is not None
    assert state.retry_count == 1
    assert state.last_error == "timeout"
    coord.record_retry("task_1", error="failure")
    assert state.retry_count == 2
