"""CircuitBreaker 单元测试.

验证三态熔断器（Closed -> Open -> HalfOpen）的状态转换、
探针机制、滑动窗口错误率及 HTTP 错误分类行为。

设计依据：M3 v2.1.0 评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

import asyncio

import pytest

from edge_cloud_kernel.gateway.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    classify_http_error,
)


class TestCircuitBreaker:
    """三态熔断器核心测试集."""

    @pytest.mark.asyncio
    async def test_half_open_allows_probe(self):
        """HalfOpen 状态下应允许探针请求."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=2,
            error_threshold_pct=100.0,
            reset_timeout_s=0.1,
        )
        cb.record_failure(error_type="retryable")
        cb.record_failure(error_type="retryable")
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        """HalfOpen 探针成功应恢复 Closed."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=2,
            error_threshold_pct=100.0,
            reset_timeout_s=0.1,
        )
        cb.record_failure(error_type="retryable")
        cb.record_failure(error_type="retryable")
        await asyncio.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN
        # 需要连续成功 max_probes(3) 次才恢复 Closed
        cb.record_success()
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        """HalfOpen 探针失败应回到 Open."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=2,
            error_threshold_pct=100.0,
            reset_timeout_s=0.1,
        )
        cb.record_failure(error_type="retryable")
        cb.record_failure(error_type="retryable")
        await asyncio.sleep(0.15)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure(error_type="retryable")
        assert cb.state == CircuitState.OPEN

    def test_classify_http_error(self):
        """HTTP 错误码应正确分类为 retryable / non_retryable."""
        assert classify_http_error(401) == "non_retryable"
        assert classify_http_error(403) == "non_retryable"
        assert classify_http_error(404) == "non_retryable"
        assert classify_http_error(500) == "retryable"
        assert classify_http_error(429) == "retryable"
        assert classify_http_error(502) == "retryable"
        assert classify_http_error(503) == "retryable"
        assert classify_http_error(504) == "retryable"

    def test_initially_closed(self):
        """熔断器初始状态应为 Closed."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_non_retryable_does_not_open(self):
        """non_retryable 错误不应触发熔断."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=2,
            error_threshold_pct=50.0,
        )
        cb.record_failure(error_type="non_retryable")
        cb.record_failure(error_type="non_retryable")
        cb.record_failure(error_type="non_retryable")
        assert cb.state == CircuitState.CLOSED

    def test_sliding_window_error_rate(self):
        """滑动窗口应正确计算错误率."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=50.0,
        )
        assert cb._sliding_window_error_rate == 0.0
        cb.record_failure(error_type="retryable")
        assert cb._sliding_window_error_rate == 100.0
        cb.record_success()
        assert cb._sliding_window_error_rate == 50.0

    def test_allow_request_blocks_when_open(self):
        """Open 状态下应拒绝请求."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=0.0,
            reset_timeout_s=60.0,
        )
        cb.record_failure(error_type="retryable")
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_reset(self):
        """手动重置应恢复到 Closed 状态并清空统计."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=0.0,
        )
        cb.record_failure(error_type="retryable")
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._total_requests == 0
        assert len(cb._window) == 0

    def test_get_stats(self):
        """get_stats 应返回包含状态、请求数、错误率的字典."""
        cb = CircuitBreaker(
            name="stats_test",
            volume_threshold=10,
            error_threshold_pct=50.0,
        )
        cb.record_success()
        cb.record_failure(error_type="retryable")
        stats = cb.get_stats()
        assert stats["name"] == "stats_test"
        assert stats["state"] == "closed"
        assert stats["total_requests"] == 2
        assert stats["failed_requests"] == 1
        assert stats["error_rate_pct"] == 50.0

    def test_half_open_probe_limit(self):
        """HalfOpen 状态应限制探针数量，足够成功后恢复 Closed."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=0.0,
            reset_timeout_s=0.0,
        )
        cb.record_failure(error_type="retryable")
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_window_size_limit(self):
        """滑动窗口应受 maxlen 限制."""
        cb = CircuitBreaker(name="test", window_size=5)
        for _ in range(10):
            cb.record_success()
        assert len(cb._window) == 5

    def test_non_retryable_ignored_in_window(self):
        """non_retryable 错误在滑动窗口中不计为失败."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=50.0,
        )
        cb.record_failure(error_type="non_retryable")
        assert cb._sliding_window_error_rate == 0.0
        cb.record_failure(error_type="retryable")
        assert cb._sliding_window_error_rate == 50.0

    def test_success_does_not_affect_failure_count(self):
        """成功请求不应影响失败计数."""
        cb = CircuitBreaker(
            name="test",
            volume_threshold=1,
            error_threshold_pct=50.0,
        )
        cb.record_success()
        cb.record_success()
        cb.record_success()
        assert cb._failed_requests == 0
        assert cb._total_requests == 3
