from __future__ import annotations

"""Circuit Breaker 熔断与重试机制.

为 Skill 调用提供生产级容错能力：熔断器防止级联故障，指数退避重试提高可用性。
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class CircuitState(Enum):
    """熔断器状态."""

    CLOSED = "closed"       # 正常，允许请求通过
    OPEN = "open"           # 熔断，拒绝请求
    HALF_OPEN = "half_open" # 半开，允许探测请求


@dataclass
class CircuitBreakerConfig:
    """熔断器配置."""

    failure_threshold: int = 5          # 连续失败次数阈值
    recovery_timeout: float = 30.0      # 熔断后恢复等待（秒）
    half_open_max_calls: int = 3        # 半开状态最大探测请求数
    success_threshold: int = 2          # 半开状态成功次数阈值


@dataclass
class RetryConfig:
    """重试配置."""

    max_retries: int = 3                # 最大重试次数
    base_delay: float = 1.0             # 基础延迟（秒）
    max_delay: float = 60.0             # 最大延迟（秒）
    exponential_base: float = 2.0       # 指数基数
    jitter: bool = True                 # 是否添加随机抖动
    retry_on: tuple[str, ...] = ("failure", "timeout")  # 哪些状态触发重试


class CircuitBreaker:
    """熔断器.

    基于 Martin Fowler 的 Circuit Breaker 模式实现。
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(
        self, coro_factory: Any, fallback_factory: Any | None = None
    ) -> Any:
        """执行受熔断保护的调用（支持降级策略）.

        Args:
            coro_factory: 返回协程的可调用对象.
            fallback_factory: 降级工厂函数，熔断时调用替代逻辑.

        Returns:
            调用结果或降级结果.

        Raises:
            CircuitBreakerOpenError: 熔断器打开且无降级策略时.
            Exception: 原始异常（半开状态探测失败时）.
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
                    logger.info(
                        "circuit_breaker_half_open",
                        name=self._name,
                    )
                else:
                    if fallback_factory is not None:
                        logger.info(
                            "circuit_breaker_fallback",
                            name=self._name,
                        )
                        return await fallback_factory()
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self._name}' is OPEN"
                    )
            elif self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    if fallback_factory is not None:
                        return await fallback_factory()
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self._name}' half-open limit reached"
                    )
                self._half_open_calls += 1

        # 在锁外执行实际调用
        try:
            result = await coro_factory()
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(
                        "circuit_breaker_closed",
                        name=self._name,
                    )
            else:
                self._failure_count = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened_half",
                    name=self._name,
                    failure_count=self._failure_count,
                )
            elif self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker_opened",
                    name=self._name,
                    failure_count=self._failure_count,
                )

    def _should_attempt_reset(self) -> bool:
        if self._last_failure_time is None:
            return True
        return (time.time() - self._last_failure_time) >= self._config.recovery_timeout

    def get_metrics(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
        }


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常."""

    pass


class RetryExecutor:
    """重试执行器.

    支持指数退避 + 抖动的重试策略。
    """

    def __init__(self, config: RetryConfig | None = None) -> None:
        self._config = config or RetryConfig()

    async def execute(self, coro_factory: Any) -> Any:
        """执行带重试的调用.

        Args:
            coro_factory: 返回协程的可调用对象.

        Returns:
            调用结果.

        Raises:
            Exception: 最后一次重试的异常.
        """
        last_exception: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_exception = e
                if attempt >= self._config.max_retries:
                    break
                delay = self._calculate_delay(attempt)
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_retries=self._config.max_retries,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)
        raise last_exception  # type: ignore[misc]

    def _calculate_delay(self, attempt: int) -> float:
        """计算退避延迟."""
        delay = self._config.base_delay * (
            self._config.exponential_base ** attempt
        )
        delay = min(delay, self._config.max_delay)
        if self._config.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return delay


class ResilientSkillInvoker:
    """弹性 Skill 调用器.

    组合熔断器 + 重试，为 Skill 调用提供生产级容错。
    """

    def __init__(
        self,
        circuit_config: CircuitBreakerConfig | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._circuit_config = circuit_config or CircuitBreakerConfig()
        self._retry_config = retry_config or RetryConfig()

    def get_breaker(self, skill_id: str) -> CircuitBreaker:
        """获取或创建熔断器."""
        if skill_id not in self._breakers:
            self._breakers[skill_id] = CircuitBreaker(
                name=skill_id,
                config=self._circuit_config,
            )
        return self._breakers[skill_id]

    async def invoke(self, skill_id: str, coro_factory: Any) -> Any:
        """弹性调用 Skill.

        先经过熔断器检查，再通过重试执行器调用。
        """
        breaker = self.get_breaker(skill_id)
        retry = RetryExecutor(self._retry_config)

        async def _with_retry() -> Any:
            return await retry.execute(coro_factory)

        return await breaker.call(_with_retry)

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器指标."""
        return {
            sid: breaker.get_metrics()
            for sid, breaker in self._breakers.items()
        }
