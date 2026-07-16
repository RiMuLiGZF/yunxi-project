"""全局重试协调器.

提供统一的重试机制、熔断器和降级策略，用于 MCP 调用、LLM 调用等外部依赖。

使用方式::

    from src.common.retry import RetryCoordinator, RetryPolicy, with_retry

    # 方式1：直接使用协调器
    coordinator = RetryCoordinator()
    result = await coordinator.execute(
        some_async_func,
        policy_name="mcp_call",
        arg1="value",
    )

    # 方式2：装饰器
    @with_retry(policy_name="llm_call")
    async def call_llm(prompt: str) -> str:
        ...
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 重试策略
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """重试策略配置.

    Attributes:
        max_retries: 最大重试次数（不含首次调用）.
        base_delay: 初始延迟秒数.
        max_delay: 最大延迟秒数.
        backoff_factor: 退避因子.
        jitter: 是否添加随机抖动.
        retryable_exceptions: 可重试的异常类型元组.
        retryable_status_codes: 可重试的HTTP状态码.
        retryable_error_codes: 可重试的业务错误码.
        fallback: 降级回调函数，重试耗尽后调用.
    """
    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)
    retryable_error_codes: tuple[int, ...] = ()
    fallback: Callable[..., Any] | None = None


# ---------------------------------------------------------------------------
# 熔断器状态
# ---------------------------------------------------------------------------

class CircuitState:
    """熔断器状态枚举."""
    CLOSED = "closed"           # 正常，请求通过
    OPEN = "open"               # 熔断，请求直接失败
    HALF_OPEN = "half_open"     # 半开，试探性通过少量请求


@dataclass
class CircuitBreaker:
    """熔断器实现.

    Args:
        failure_threshold: 触发熔断的连续失败次数.
        recovery_timeout: 熔断后恢复等待时间（秒）.
        half_open_max_calls: 半开状态允许通过的请求数.
    """
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

    _state: str = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_count: int = 0
    _half_open_success: int = 0

    def can_execute(self) -> bool:
        """判断是否允许执行请求.

        Returns:
            True 表示允许执行，False 表示熔断中.
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # 检查是否过了恢复时间
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_count = 0
                self._half_open_success = 0
                logger.info(
                    "circuit_breaker.half_open",
                    failure_threshold=self.failure_threshold,
                    recovery_timeout=self.recovery_timeout,
                )
                return True
            return False

        if self._state == CircuitState.HALF_OPEN:
            return self._half_open_count < self.half_open_max_calls

        return True

    def record_success(self) -> None:
        """记录一次成功调用."""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_success += 1
            if self._half_open_success >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_count = 0
                self._half_open_success = 0
                logger.info("circuit_breaker.closed", reason="half_open_success")
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        """记录一次失败调用."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._last_failure_time = time.time()
            self._half_open_count = 0
            self._half_open_success = 0
            logger.warning(
                "circuit_breaker.open",
                reason="half_open_failure",
                recovery_timeout=self.recovery_timeout,
            )
            return

        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker.open",
                failure_count=self._failure_count,
                failure_threshold=self.failure_threshold,
                recovery_timeout=self.recovery_timeout,
            )

    @property
    def state(self) -> str:
        """当前熔断器状态."""
        return self._state

    @property
    def failure_count(self) -> int:
        """当前连续失败次数."""
        return self._failure_count

    def get_stats(self) -> dict[str, Any]:
        """获取熔断器统计信息."""
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
            "half_open_count": self._half_open_count,
        }


# ---------------------------------------------------------------------------
# 重试协调器
# ---------------------------------------------------------------------------

class RetryCoordinator:
    """全局重试协调器.

    集中管理重试策略，支持熔断器联动、指数退避+抖动、降级回调。

    Args:
        default_policy: 默认重试策略.
    """

    def __init__(self, default_policy: RetryPolicy | None = None):
        self.default_policy = default_policy or RetryPolicy()
        self._policies: dict[str, RetryPolicy] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._stats: dict[str, Any] = self._init_stats()

        # 注册内置策略
        self._register_builtin_policies()

    def _init_stats(self) -> dict[str, Any]:
        return {
            "total_calls": 0,
            "total_success": 0,
            "total_failures": 0,
            "total_retries": 0,
            "total_fallbacks": 0,
            "circuit_breaker_triggers": 0,
        }

    def _register_builtin_policies(self) -> None:
        """注册内置的重试策略."""
        # MCP 工具调用
        self.register_policy(
            "mcp_call",
            RetryPolicy(
                max_retries=2,
                base_delay=0.3,
                max_delay=5.0,
                backoff_factor=2.0,
                jitter=True,
                retryable_status_codes=(429, 500, 502, 503, 504),
            ),
        )

        # LLM 调用
        self.register_policy(
            "llm_call",
            RetryPolicy(
                max_retries=3,
                base_delay=1.0,
                max_delay=15.0,
                backoff_factor=2.0,
                jitter=True,
                retryable_status_codes=(429, 500, 502, 503, 504),
            ),
        )

        # 数据库操作
        self.register_policy(
            "db_operation",
            RetryPolicy(
                max_retries=3,
                base_delay=0.1,
                max_delay=2.0,
                backoff_factor=2.0,
                jitter=True,
                retryable_exceptions=(Exception,),
            ),
        )

        # 网络请求（通用）
        self.register_policy(
            "http_request",
            RetryPolicy(
                max_retries=3,
                base_delay=0.5,
                max_delay=10.0,
                backoff_factor=2.0,
                jitter=True,
                retryable_status_codes=(429, 500, 502, 503, 504),
            ),
        )

    def register_policy(self, name: str, policy: RetryPolicy) -> None:
        """注册命名重试策略.

        Args:
            name: 策略名称.
            policy: 重试策略.
        """
        self._policies[name] = policy
        logger.debug("retry_policy.registered", name=name)

    def get_policy(self, name: str | None = None) -> RetryPolicy:
        """获取重试策略.

        Args:
            name: 策略名称，None 则返回默认策略.

        Returns:
            重试策略实例.
        """
        if name is None:
            return self.default_policy
        return self._policies.get(name, self.default_policy)

    def register_circuit_breaker(self, name: str, breaker: CircuitBreaker) -> None:
        """注册熔断器.

        Args:
            name: 熔断器名称（通常与策略名一致）.
            breaker: 熔断器实例.
        """
        self._circuit_breakers[name] = breaker
        logger.debug("circuit_breaker.registered", name=name)

    def get_circuit_breaker(self, name: str | None) -> CircuitBreaker | None:
        """获取熔断器.

        Args:
            name: 熔断器名称.

        Returns:
            熔断器实例，不存在则返回 None.
        """
        if name is None:
            return None
        return self._circuit_breakers.get(name)

    def _calc_delay(self, attempt: int, policy: RetryPolicy) -> float:
        """计算第 N 次重试的延迟时间.

        Args:
            attempt: 当前重试次数（从 1 开始）.
            policy: 重试策略.

        Returns:
            延迟秒数.
        """
        delay = policy.base_delay * (policy.backoff_factor ** (attempt - 1))
        delay = min(delay, policy.max_delay)

        if policy.jitter:
            # 加减 ±20% 的随机抖动
            jitter_range = delay * 0.2
            delay += random.uniform(-jitter_range, jitter_range)
            delay = max(0, delay)

        return delay

    def _is_retryable(self, exc: Exception, policy: RetryPolicy) -> bool:
        """判断异常是否可重试.

        Args:
            exc: 异常实例.
            policy: 重试策略.

        Returns:
            True 表示可重试.
        """
        # 检查异常类型
        if not isinstance(exc, policy.retryable_exceptions):
            return False

        # 检查 HTTP 状态码（httpx 等库的异常）
        if hasattr(exc, "status_code"):
            return exc.status_code in policy.retryable_status_codes

        # 检查业务错误码
        if hasattr(exc, "code") and isinstance(exc.code, int):
            if policy.retryable_error_codes and exc.code not in policy.retryable_error_codes:
                return False

        return True

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        policy_name: str | None = None,
        policy: RetryPolicy | None = None,
        circuit_key: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """执行带重试的异步函数.

        Args:
            func: 要执行的异步函数.
            *args: 位置参数.
            policy_name: 使用的命名策略名称.
            policy: 自定义重试策略（优先级高于 policy_name）.
            circuit_key: 熔断器键名（默认与 policy_name 相同）.
            **kwargs: 关键字参数.

        Returns:
            函数执行结果.

        Raises:
            Exception: 重试耗尽后的最后一个异常（无 fallback 时）.
        """
        if policy is None:
            policy = self.get_policy(policy_name)

        ck = circuit_key or policy_name
        breaker = self.get_circuit_breaker(ck) if ck else None

        # 熔断器检查
        if breaker and not breaker.can_execute():
            self._stats["circuit_breaker_triggers"] += 1
            self._stats["total_failures"] += 1
            # 如果有 fallback，直接走降级
            if policy.fallback:
                self._stats["total_fallbacks"] += 1
                logger.warning(
                    "retry.circuit_open_fallback",
                    circuit_key=ck,
                    func=func.__name__,
                )
                return policy.fallback(*args, **kwargs)
            raise RuntimeError(
                f"Circuit breaker '{ck}' is open, request rejected"
            )

        self._stats["total_calls"] += 1
        last_exc: Exception | None = None

        for attempt in range(policy.max_retries + 1):
            try:
                result = await func(*args, **kwargs)

                # 记录成功
                if breaker:
                    breaker.record_success()
                self._stats["total_success"] += 1

                if attempt > 0:
                    logger.info(
                        "retry.success_after_retry",
                        func=func.__name__,
                        attempt=attempt,
                        policy=policy_name,
                    )

                return result

            except Exception as exc:
                last_exc = exc
                self._stats["total_failures"] += 1

                # 判断是否可重试
                if not self._is_retryable(exc, policy):
                    logger.warning(
                        "retry.not_retryable",
                        func=func.__name__,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    break

                # 最后一次重试失败，不再重试
                if attempt >= policy.max_retries:
                    logger.error(
                        "retry.exhausted",
                        func=func.__name__,
                        retries=attempt,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        policy=policy_name,
                    )
                    break

                # 计算延迟并重试
                delay = self._calc_delay(attempt + 1, policy)
                self._stats["total_retries"] += 1

                logger.warning(
                    "retry.attempting",
                    func=func.__name__,
                    attempt=attempt + 1,
                    max_retries=policy.max_retries,
                    delay=round(delay, 3),
                    error_type=type(exc).__name__,
                    error=str(exc)[:100],
                    policy=policy_name,
                )

                await asyncio.sleep(delay)

        # 记录熔断器失败
        if breaker and last_exc:
            breaker.record_failure()

        # 尝试降级
        if policy.fallback and last_exc:
            self._stats["total_fallbacks"] += 1
            logger.warning(
                "retry.fallback",
                func=func.__name__,
                policy=policy_name,
            )
            return policy.fallback(*args, **kwargs)

        # 抛出最后一个异常
        if last_exc:
            raise last_exc
        raise RuntimeError("Retry failed with no exception")

    def get_stats(self) -> dict[str, Any]:
        """获取全局统计信息."""
        breaker_stats = {
            name: breaker.get_stats()
            for name, breaker in self._circuit_breakers.items()
        }
        return {
            **self._stats,
            "policies": list(self._policies.keys()),
            "circuit_breakers": breaker_stats,
        }

    def reset_stats(self) -> None:
        """重置统计信息."""
        self._stats = self._init_stats()


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------

_global_coordinator: RetryCoordinator | None = None


def get_retry_coordinator() -> RetryCoordinator:
    """获取全局重试协调器单例."""
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = RetryCoordinator()
    return _global_coordinator


def with_retry(
    policy_name: str | None = None,
    policy: RetryPolicy | None = None,
    circuit_key: str | None = None,
    fallback: Callable[..., Any] | None = None,
):
    """重试装饰器.

    Args:
        policy_name: 命名策略名称.
        policy: 自定义策略（优先级更高）.
        circuit_key: 熔断器键名.
        fallback: 降级回调函数.

    Returns:
        装饰器函数.

    使用::

        @with_retry(policy_name="mcp_call")
        async def call_mcp_tool(tool_name: str, args: dict) -> dict:
            ...
    """
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            coordinator = get_retry_coordinator()

            # 如果传入了 fallback，使用覆盖策略
            effective_policy = policy
            if effective_policy is None and fallback is not None:
                base_policy = coordinator.get_policy(policy_name)
                effective_policy = RetryPolicy(
                    max_retries=base_policy.max_retries,
                    base_delay=base_policy.base_delay,
                    max_delay=base_policy.max_delay,
                    backoff_factor=base_policy.backoff_factor,
                    jitter=base_policy.jitter,
                    retryable_exceptions=base_policy.retryable_exceptions,
                    retryable_status_codes=base_policy.retryable_status_codes,
                    fallback=fallback,
                )

            return await coordinator.execute(
                func,
                *args,
                policy_name=policy_name,
                policy=effective_policy,
                circuit_key=circuit_key,
                **kwargs,
            )

        # 保留原函数元数据
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__

        return wrapper

    return decorator
