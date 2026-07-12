"""三态熔断器.

实现 Closed -> Open -> HalfOpen 三态熔断保护。
区分 retryable/non_retryable 错误类型，仅 retryable 错误计入熔断统计。
使用滑动窗口计算实时错误率。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from enum import Enum
from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)

# 错误类型常量
ErrorType = Literal["retryable", "non_retryable"]


class CircuitState(str, Enum):
    """熔断器状态枚举.

    Attributes:
        CLOSED: 正常状态，允许请求通过.
        OPEN: 熔断状态，拒绝所有请求.
        HALF_OPEN: 半开状态，允许少量探测请求.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# 默认非重试错误状态码
NON_RETRYABLE_STATUS_CODES: set[int] = {401, 403, 404}

# 可重试错误状态码
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}


def classify_http_error(status_code: int) -> ErrorType:
    """根据 HTTP 状态码分类错误类型.

    Args:
        status_code: HTTP 状态码.

    Returns:
        "retryable" 或 "non_retryable".
    """
    if status_code in NON_RETRYABLE_STATUS_CODES:
        return "non_retryable"
    return "retryable"


class CircuitBreaker:
    """三态熔断器（区分错误类型）.

    实现经典的 Circuit Breaker 模式：
    - Closed（正常）：请求正常通过，监控错误率
    - Open（熔断）：达到错误率阈值后触发，拒绝请求
    - HalfOpen（半开）：超时后进入，允许少量探测请求验证恢复

    仅 retryable 错误（如 429/5xx）计入熔断统计，
    non_retryable 错误（如 401/403）不影响熔断器状态。
    使用滑动窗口计算实时错误率。

    Attributes:
        name: 熔断器名称.
        state: 当前状态.
        volume_threshold: 触发判断的最小请求数.
        error_threshold_pct: 错误率阈值（百分比）.
        reset_timeout_s: 熔断恢复超时（秒）.
    """

    def __init__(
        self,
        name: str = "default",
        volume_threshold: int = 20,
        error_threshold_pct: float = 50.0,
        reset_timeout_s: float = 10.0,
        window_size: int = 100,
    ) -> None:
        """初始化 CircuitBreaker.

        Args:
            name: 熔断器名称.
            volume_threshold: 熔断触发最小请求数（默认20）.
            error_threshold_pct: 错误率阈值百分比（默认50）.
            reset_timeout_s: 从 Open 到 HalfOpen 的等待时间（默认10秒）.
            window_size: 滑动窗口大小（记录的请求数上限，默认100）.
        """
        self.name = name
        self.state = CircuitState.CLOSED
        self._volume_threshold = volume_threshold
        self._error_threshold_pct = error_threshold_pct
        self._reset_timeout_s = reset_timeout_s
        self._window_size = window_size

        # 滑动窗口：记录最近的请求结果 (timestamp, is_retryable_failure)
        self._window: deque[tuple[float, bool]] = deque(maxlen=window_size)

        # 总统计（累计，用于 get_stats）
        self._total_requests: int = 0
        self._failed_requests: int = 0

        # 状态转换时间戳
        self._last_failure_time: float = 0.0
        self._opened_at: float = 0.0

        # HalfOpen 探测计数
        self._half_open_successes: int = 0
        self._half_open_probes: int = 0
        self._half_open_max_probes: int = 3

        logger.info(
            "circuit_breaker.init",
            name=name,
            volume_threshold=volume_threshold,
            error_threshold_pct=error_threshold_pct,
            reset_timeout_s=reset_timeout_s,
            window_size=window_size,
        )

    def allow_request(self) -> bool:
        """判断是否允许请求通过.

        Returns:
            True 表示允许，False 表示拒绝（熔断中）.
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # 检查是否可以转到 HalfOpen
            elapsed = time.time() - self._opened_at
            if elapsed >= self._reset_timeout_s:
                self._transition_to_half_open()
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # 半开状态下限制探测请求数
            return self._half_open_probes < self._half_open_max_probes

        return False

    def record_success(self, latency_ms: float = 0.0) -> None:
        """记录一次成功请求.

        Args:
            latency_ms: 请求延迟（毫秒）.
        """
        self._total_requests += 1
        # 记录到滑动窗口（成功 = 非失败）
        self._window.append((time.time(), False))

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            self._half_open_probes += 1
            if self._half_open_successes >= self._half_open_max_probes:
                self._transition_to_closed()
                logger.info("circuit_breaker.closed", name=self.name)

        logger.debug(
            "circuit_breaker.success",
            name=self.name,
            state=self.state.value,
            latency_ms=latency_ms,
        )

    def record_failure(
        self,
        latency_ms: float = 0.0,
        error_type: ErrorType = "retryable",
    ) -> None:
        """记录一次失败请求.

        仅 retryable 错误计入熔断统计。non_retryable 错误
        （如 401/403 认证失败）不影响熔断器状态。

        Args:
            latency_ms: 请求延迟（毫秒）.
            error_type: 错误类型，"retryable" 或 "non_retryable".
        """
        self._total_requests += 1

        if error_type == "non_retryable":
            # non_retryable 错误不计入熔断
            self._window.append((time.time(), False))
            logger.debug(
                "circuit_breaker.non_retryable_failure",
                name=self.name,
                error_type=error_type,
                latency_ms=latency_ms,
            )
            return

        # retryable 错误计入熔断统计
        self._failed_requests += 1
        self._last_failure_time = time.time()
        self._window.append((time.time(), True))

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_probes += 1
            self._transition_to_open()
            logger.warning("circuit_breaker.re_opened", name=self.name)

        elif self.state == CircuitState.CLOSED:
            if self._should_open():
                self._transition_to_open()
                logger.warning(
                    "circuit_breaker.opened",
                    name=self.name,
                    error_rate=self._sliding_window_error_rate,
                )

        logger.debug(
            "circuit_breaker.failure",
            name=self.name,
            state=self.state.value,
            latency_ms=latency_ms,
            error_type=error_type,
        )

    def _should_open(self) -> bool:
        """判断是否应该触发熔断.

        使用滑动窗口错误率判断。

        Returns:
            是否满足熔断条件.
        """
        window_requests = len(self._window)
        if window_requests < self._volume_threshold:
            return False
        return self._sliding_window_error_rate >= self._error_threshold_pct

    def _transition_to_open(self) -> None:
        """转换到 Open 状态."""
        self.state = CircuitState.OPEN
        self._opened_at = time.time()

    def _transition_to_half_open(self) -> None:
        """转换到 HalfOpen 状态."""
        self.state = CircuitState.HALF_OPEN
        self._half_open_successes = 0
        self._half_open_probes = 0
        logger.info("circuit_breaker.half_open", name=self.name)

    def _transition_to_closed(self) -> None:
        """转换到 Closed 状态."""
        self.state = CircuitState.CLOSED
        self._total_requests = 0
        self._failed_requests = 0
        self._window.clear()

    @property
    def _sliding_window_error_rate(self) -> float:
        """基于滑动窗口计算实时错误率.

        仅计算 retryable 失败占总请求数的比例。

        Returns:
            错误率百分比（0.0-100.0）.
        """
        if not self._window:
            return 0.0
        failures = sum(1 for _, is_failure in self._window if is_failure)
        return (failures / len(self._window)) * 100.0

    @property
    def _error_rate(self) -> float:
        """计算全局错误率（兼容旧接口）.

        Returns:
            错误率百分比（0.0-100.0）.
        """
        return self._sliding_window_error_rate

    def get_stats(self) -> dict[str, float | str | int]:
        """获取熔断器统计信息.

        Returns:
            包含状态、请求数、错误率等信息的字典.
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "total_requests": self._total_requests,
            "failed_requests": self._failed_requests,
            "error_rate_pct": round(self._sliding_window_error_rate, 2),
            "window_size": len(self._window),
            "last_failure_time": self._last_failure_time,
        }

    def reset(self) -> None:
        """手动重置熔断器到 Closed 状态."""
        self._transition_to_closed()
        logger.info("circuit_breaker.reset", name=self.name)
