"""
重试与熔断模块

提供指数退避+抖动的重试策略、三态熔断器（closed/open/half-open）、
以及全局重试协调器，支持熔断器联动、降级回调等高级特性。

使用方式：
    from tide_memory.common.retry import get_retry_coordinator, RetryPolicy

    coordinator = get_retry_coordinator()
    result = await coordinator.execute_with_retry(
        func=my_async_func,
        policy=RetryPolicy(max_attempts=3),
        circuit_key="my_service",
        fallback=lambda: default_value,
    )
"""

from __future__ import annotations

import asyncio
import enum
import random
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Type

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 熔断器状态枚举
# ---------------------------------------------------------------------------


class CircuitState(enum.Enum):
    """熔断器状态枚举

    - CLOSED: 闭合状态，请求正常通过，统计失败率
    - OPEN: 打开状态，请求直接被拒绝（熔断）
    - HALF_OPEN: 半开状态，放行少量请求探测服务是否恢复
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# RetryPolicy 重试策略
# ---------------------------------------------------------------------------


class RetryPolicy:
    """
    重试策略配置

    支持指数退避 + 随机抖动，避免重试风暴（thundering herd）。

    Args:
        max_attempts: 最大尝试次数（含首次），默认 3
        initial_delay: 初始延迟（秒），默认 0.1
        max_delay: 最大延迟（秒），默认 10.0
        backoff_factor: 退避因子，默认 2.0（指数退避底数）
        jitter: 是否启用随机抖动，默认 True
        retry_on_exceptions: 需要重试的异常类型元组，默认 (Exception,)
        retry_on_result: 自定义判断函数，接收返回值返回 True 表示需要重试
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        retry_on_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
        retry_on_result: Optional[Callable[[Any], bool]] = None,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if initial_delay < 0:
            raise ValueError("initial_delay must be >= 0")
        if max_delay < initial_delay:
            raise ValueError("max_delay must be >= initial_delay")
        if backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")

        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.retry_on_exceptions = retry_on_exceptions
        self.retry_on_result = retry_on_result

    def calculate_delay(self, attempt: int) -> float:
        """
        计算第 attempt 次重试前的等待延迟

        Args:
            attempt: 当前尝试次数（从 1 开始，1 表示首次重试前的等待）

        Returns:
            延迟秒数
        """
        # 指数退避: initial_delay * (backoff_factor ^ (attempt - 1))
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        delay = min(delay, self.max_delay)

        # 添加随机抖动（0 ~ delay * 0.5）
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        return delay

    def should_retry_exception(self, exc: BaseException) -> bool:
        """判断异常是否需要重试"""
        return isinstance(exc, self.retry_on_exceptions)

    def should_retry_result(self, result: Any) -> bool:
        """判断返回结果是否需要重试"""
        if self.retry_on_result is None:
            return False
        try:
            return bool(self.retry_on_result(result))
        except Exception:
            return False

    def __repr__(self) -> str:
        return (
            f"RetryPolicy(max_attempts={self.max_attempts}, "
            f"initial_delay={self.initial_delay}, "
            f"max_delay={self.max_delay}, "
            f"backoff_factor={self.backoff_factor}, "
            f"jitter={self.jitter})"
        )


# ---------------------------------------------------------------------------
# CircuitBreaker 熔断器
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """
    熔断器（三态模式）

    监控调用失败率，当失败次数达到阈值时自动熔断（OPEN 状态），
    在恢复超时后进入半开状态（HALF_OPEN），放行少量探测请求，
    若探测成功则闭合熔断器（CLOSED），失败则重新打开。

    Args:
        name: 熔断器名称（用于日志和标识）
        failure_threshold: 失败次数阈值，达到后熔断，默认 5
        recovery_timeout: 恢复超时（秒），熔断后等待多久进入半开，默认 30
        half_open_max_calls: 半开状态允许的最大探测请求数，默认 1
        window_size: 滑动窗口大小（秒），统计最近 window_size 秒的失败数，默认 60
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        window_size: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.window_size = window_size

        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

        # 失败时间戳列表（滑动窗口）
        self._failures: list[float] = []
        # 成功时间戳列表（半开状态探测用）
        self._successes: list[float] = []
        # 熔断开始时间
        self._opened_at: float = 0.0
        # 半开状态已放行的请求数
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态（线程安全读取）"""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def failure_count(self) -> int:
        """当前窗口内的失败次数"""
        with self._lock:
            self._prune_failures()
            return len(self._failures)

    def _prune_failures(self) -> None:
        """清理超出滑动窗口的失败记录"""
        now = time.time()
        cutoff = now - self.window_size
        while self._failures and self._failures[0] < cutoff:
            self._failures.pop(0)

    def _maybe_transition_to_half_open(self) -> None:
        """
        检查是否需要从 OPEN 过渡到 HALF_OPEN
        注意：调用者应持有 _lock
        """
        if self._state == CircuitState.OPEN:
            now = time.time()
            if now - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._successes.clear()
                logger.info(
                    "circuit_breaker.half_open",
                    name=self.name,
                    open_duration=now - self._opened_at,
                )

    def allow_request(self) -> bool:
        """
        判断是否允许请求通过

        Returns:
            True 表示允许通过，False 表示被熔断
        """
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                return False

            # HALF_OPEN: 只放行有限数量的探测请求
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    def record_success(self) -> None:
        """记录一次成功调用"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._successes.append(time.time())
                # 半开状态下探测全部成功 -> 闭合熔断器
                if len(self._successes) >= self.half_open_max_calls:
                    self._transition_to_closed()
            elif self._state == CircuitState.CLOSED:
                # 闭合状态下，成功可以适当减少失败计数（温和恢复）
                if self._failures:
                    self._failures.pop(0)

    def record_failure(self) -> None:
        """记录一次失败调用"""
        now = time.time()
        with self._lock:
            self._prune_failures()
            self._failures.append(now)

            if self._state == CircuitState.HALF_OPEN:
                # 半开状态下有失败 -> 立即重新熔断
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED:
                if len(self._failures) >= self.failure_threshold:
                    self._transition_to_open()

    def _transition_to_open(self) -> None:
        """切换到熔断状态（调用者应持有 _lock）"""
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._half_open_calls = 0
        self._successes.clear()
        logger.warning(
            "circuit_breaker.open",
            name=self.name,
            failure_count=len(self._failures),
            threshold=self.failure_threshold,
            recovery_timeout=self.recovery_timeout,
        )

    def _transition_to_closed(self) -> None:
        """切换到闭合状态（调用者应持有 _lock）"""
        self._state = CircuitState.CLOSED
        self._failures.clear()
        self._half_open_calls = 0
        self._successes.clear()
        logger.info(
            "circuit_breaker.closed",
            name=self.name,
        )

    def reset(self) -> None:
        """重置熔断器到初始闭合状态"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures.clear()
            self._successes.clear()
            self._opened_at = 0.0
            self._half_open_calls = 0
            logger.info("circuit_breaker.reset", name=self.name)

    def get_stats(self) -> Dict[str, Any]:
        """获取熔断器统计信息"""
        with self._lock:
            self._prune_failures()
            self._maybe_transition_to_half_open()
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": len(self._failures),
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "window_size": self.window_size,
                "half_open_calls": self._half_open_calls,
                "half_open_max_calls": self.half_open_max_calls,
                "opened_at": self._opened_at if self._state == CircuitState.OPEN else None,
            }

    def __repr__(self) -> str:
        return f"CircuitBreaker(name={self.name!r}, state={self._state.value})"


# ---------------------------------------------------------------------------
# RetryCoordinator 全局重试协调器
# ---------------------------------------------------------------------------


class RetryCoordinator:
    """
    全局重试协调器

    整合重试策略与熔断器，提供统一的带重试执行入口，支持：
    - 同步/异步函数执行
    - 指数退避 + 抖动
    - 熔断器联动（失败累计到熔断器，熔断时跳过重试）
    - 降级回调（fallback）
    - 结构化日志记录

    Args:
        default_policy: 默认重试策略
    """

    def __init__(self, default_policy: Optional[RetryPolicy] = None):
        self._default_policy = default_policy or RetryPolicy()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
        logger.info(
            "retry_coordinator.initialized",
            default_policy=repr(self._default_policy),
        )

    def get_or_create_circuit_breaker(
        self,
        key: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        window_size: float = 60.0,
    ) -> CircuitBreaker:
        """
        获取或创建熔断器

        Args:
            key: 熔断器标识键
            failure_threshold: 失败阈值
            recovery_timeout: 恢复超时（秒）
            half_open_max_calls: 半开最大探测数
            window_size: 滑动窗口大小（秒）

        Returns:
            CircuitBreaker 实例
        """
        with self._lock:
            if key not in self._circuit_breakers:
                self._circuit_breakers[key] = CircuitBreaker(
                    name=key,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max_calls=half_open_max_calls,
                    window_size=window_size,
                )
            return self._circuit_breakers[key]

    def get_circuit_breaker(self, key: str) -> Optional[CircuitBreaker]:
        """获取已存在的熔断器，不存在返回 None"""
        with self._lock:
            return self._circuit_breakers.get(key)

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        policy: Optional[RetryPolicy] = None,
        circuit_key: Optional[str] = None,
        fallback: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        异步执行函数，带重试和熔断器

        Args:
            func: 要执行的异步函数
            *args: 位置参数
            policy: 重试策略，为 None 时使用默认策略
            circuit_key: 熔断器键，为 None 时不使用熔断器
            fallback: 降级回调，所有重试失败后调用
            **kwargs: 关键字参数

        Returns:
            函数执行结果或 fallback 结果

        Raises:
            最后一次异常（如果没有 fallback）
        """
        effective_policy = policy or self._default_policy
        circuit_breaker = None
        if circuit_key:
            circuit_breaker = self.get_or_create_circuit_breaker(circuit_key)

        last_exc: Optional[BaseException] = None
        func_name = getattr(func, "__name__", repr(func))

        for attempt in range(1, effective_policy.max_attempts + 1):
            # 检查熔断器
            if circuit_breaker and not circuit_breaker.allow_request():
                logger.warning(
                    "retry.circuit_open",
                    func=func_name,
                    circuit_key=circuit_key,
                    attempt=attempt,
                    max_attempts=effective_policy.max_attempts,
                )
                if fallback is not None:
                    return self._invoke_fallback(fallback, func_name, circuit_key)
                raise CircuitBreakerOpenError(
                    circuit_key=circuit_key,
                    message=f"熔断器 {circuit_key} 已打开，请求被拒绝",
                )

            try:
                result = await func(*args, **kwargs)

                # 检查返回值是否需要重试
                if effective_policy.should_retry_result(result):
                    logger.debug(
                        "retry.on_result",
                        func=func_name,
                        attempt=attempt,
                        max_attempts=effective_policy.max_attempts,
                    )
                    if circuit_breaker:
                        circuit_breaker.record_failure()
                    if attempt < effective_policy.max_attempts:
                        delay = effective_policy.calculate_delay(attempt)
                        await asyncio.sleep(delay)
                        continue
                    # 最后一次也失败
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    return result

                # 成功
                if circuit_breaker:
                    circuit_breaker.record_success()
                if attempt > 1:
                    logger.info(
                        "retry.succeeded",
                        func=func_name,
                        attempt=attempt,
                        max_attempts=effective_policy.max_attempts,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                should_retry = effective_policy.should_retry_exception(exc)

                if circuit_breaker:
                    circuit_breaker.record_failure()

                if not should_retry:
                    logger.warning(
                        "retry.not_retriable",
                        func=func_name,
                        attempt=attempt,
                        error_type=exc.__class__.__name__,
                        error=str(exc),
                    )
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    raise

                if attempt >= effective_policy.max_attempts:
                    logger.error(
                        "retry.exhausted",
                        func=func_name,
                        max_attempts=effective_policy.max_attempts,
                        error_type=exc.__class__.__name__,
                        error=str(exc),
                        circuit_key=circuit_key,
                    )
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    raise

                delay = effective_policy.calculate_delay(attempt)
                logger.warning(
                    "retry.retrying",
                    func=func_name,
                    attempt=attempt,
                    max_attempts=effective_policy.max_attempts,
                    delay_seconds=round(delay, 3),
                    error_type=exc.__class__.__name__,
                    error=str(exc),
                    circuit_key=circuit_key,
                )
                await asyncio.sleep(delay)

        # 理论上不会执行到这里
        if fallback is not None:
            return self._invoke_fallback(fallback, func_name, circuit_key)
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected retry exhaustion")

    def execute_with_retry_sync(
        self,
        func: Callable[..., Any],
        *args: Any,
        policy: Optional[RetryPolicy] = None,
        circuit_key: Optional[str] = None,
        fallback: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        同步执行函数，带重试和熔断器

        Args:
            func: 要执行的同步函数
            *args: 位置参数
            policy: 重试策略
            circuit_key: 熔断器键
            fallback: 降级回调
            **kwargs: 关键字参数

        Returns:
            函数执行结果或 fallback 结果
        """
        effective_policy = policy or self._default_policy
        circuit_breaker = None
        if circuit_key:
            circuit_breaker = self.get_or_create_circuit_breaker(circuit_key)

        last_exc: Optional[BaseException] = None
        func_name = getattr(func, "__name__", repr(func))

        for attempt in range(1, effective_policy.max_attempts + 1):
            if circuit_breaker and not circuit_breaker.allow_request():
                logger.warning(
                    "retry.circuit_open_sync",
                    func=func_name,
                    circuit_key=circuit_key,
                    attempt=attempt,
                )
                if fallback is not None:
                    return self._invoke_fallback(fallback, func_name, circuit_key)
                raise CircuitBreakerOpenError(
                    circuit_key=circuit_key,
                    message=f"熔断器 {circuit_key} 已打开，请求被拒绝",
                )

            try:
                result = func(*args, **kwargs)

                if effective_policy.should_retry_result(result):
                    if circuit_breaker:
                        circuit_breaker.record_failure()
                    if attempt < effective_policy.max_attempts:
                        delay = effective_policy.calculate_delay(attempt)
                        time.sleep(delay)
                        continue
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    return result

                if circuit_breaker:
                    circuit_breaker.record_success()
                if attempt > 1:
                    logger.info(
                        "retry.succeeded_sync",
                        func=func_name,
                        attempt=attempt,
                        max_attempts=effective_policy.max_attempts,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                should_retry = effective_policy.should_retry_exception(exc)

                if circuit_breaker:
                    circuit_breaker.record_failure()

                if not should_retry:
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    raise

                if attempt >= effective_policy.max_attempts:
                    logger.error(
                        "retry.exhausted_sync",
                        func=func_name,
                        max_attempts=effective_policy.max_attempts,
                        error_type=exc.__class__.__name__,
                        error=str(exc),
                        circuit_key=circuit_key,
                    )
                    if fallback is not None:
                        return self._invoke_fallback(fallback, func_name, circuit_key)
                    raise

                delay = effective_policy.calculate_delay(attempt)
                logger.warning(
                    "retry.retrying_sync",
                    func=func_name,
                    attempt=attempt,
                    max_attempts=effective_policy.max_attempts,
                    delay_seconds=round(delay, 3),
                    error_type=exc.__class__.__name__,
                    circuit_key=circuit_key,
                )
                time.sleep(delay)

        if fallback is not None:
            return self._invoke_fallback(fallback, func_name, circuit_key)
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected retry exhaustion")

    def _invoke_fallback(
        self,
        fallback: Callable[[], Any],
        func_name: str,
        circuit_key: Optional[str],
    ) -> Any:
        """调用降级回调"""
        try:
            result = fallback()
            logger.info(
                "retry.fallback_used",
                func=func_name,
                circuit_key=circuit_key,
            )
            return result
        except Exception as exc:
            logger.error(
                "retry.fallback_failed",
                func=func_name,
                circuit_key=circuit_key,
                error_type=exc.__class__.__name__,
                error=str(exc),
            )
            raise

    def get_all_circuit_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器的统计信息"""
        with self._lock:
            return {
                key: breaker.get_stats()
                for key, breaker in self._circuit_breakers.items()
            }

    def reset_circuit_breaker(self, key: str) -> bool:
        """重置指定熔断器，返回是否成功"""
        with self._lock:
            breaker = self._circuit_breakers.get(key)
            if breaker:
                breaker.reset()
                return True
            return False

    def reset_all(self) -> None:
        """重置所有熔断器"""
        with self._lock:
            for breaker in self._circuit_breakers.values():
                breaker.reset()
            logger.info("retry_coordinator.all_circuits_reset")


# ---------------------------------------------------------------------------
# 熔断器打开异常
# ---------------------------------------------------------------------------


class CircuitBreakerOpenError(Exception):
    """
    熔断器打开异常

    当熔断器处于 OPEN 状态时抛出，表示请求被熔断拒绝。
    """

    def __init__(self, circuit_key: str = "", message: str = ""):
        self.circuit_key = circuit_key
        self.message = message or f"熔断器 {circuit_key} 已打开"
        super().__init__(self.message)

    def __repr__(self) -> str:
        return f"CircuitBreakerOpenError(circuit_key={self.circuit_key!r})"


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: Optional[RetryCoordinator] = None
_instance_lock = threading.Lock()


def get_retry_coordinator(
    default_policy: Optional[RetryPolicy] = None,
) -> RetryCoordinator:
    """
    获取全局重试协调器单例

    首次调用时创建单例，后续调用直接返回已创建的实例。

    Args:
        default_policy: 默认重试策略，仅首次调用有效

    Returns:
        全局 RetryCoordinator 单例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RetryCoordinator(default_policy=default_policy)
    return _instance


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------

__all__ = [
    "CircuitState",
    "RetryPolicy",
    "CircuitBreaker",
    "RetryCoordinator",
    "CircuitBreakerOpenError",
    "get_retry_coordinator",
]
# vim: set et ts=4 sw=4:
