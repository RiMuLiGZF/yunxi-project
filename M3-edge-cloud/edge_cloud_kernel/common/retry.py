"""全局重试协调器.

为端云协同内核提供统一的重试机制，支持可配置的指数退避、
熔断器协同、命名策略注册和重试统计。

设计要点：
- 基于 dataclass 的 RetryPolicy 配置，支持多维度重试条件
- 指数退避 + 抖动，避免惊群效应
- 熔断器惰性导入，防止循环依赖
- 命名策略注册表，不同模块可注册独立策略
- 完整的重试统计（成功率、错误分布、per-policy 统计）
- with_retry 装饰器，方便函数级集成

Usage::

    # 1. 直接使用协调器
    coordinator = RetryCoordinator()
    result = await coordinator.execute(my_func, arg1, policy_name="cloud_gateway")

    # 2. 注册自定义策略
    policy = RetryPolicy(max_retries=5, base_delay=0.3, retryable_exceptions=(TimeoutError,))
    coordinator.register_policy("my_policy", policy)

    # 3. 装饰器方式
    @with_retry(policy="cloud_gateway", max_retries=3)
    async def my_function():
        ...

    # 4. 熔断器协同
    coordinator.set_circuit_breaker(cb)
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 默认可重试异常类型（网络层、连接层错误）
DEFAULT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
    asyncio.TimeoutError,
)

# 默认可重试 HTTP 状态码
DEFAULT_RETRYABLE_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)

# 默认可重试业务错误码（M3 错误码中 5xx 类错误）
DEFAULT_RETRYABLE_ERROR_CODES: tuple[int, ...] = (
    30005,  # ERR_SERVICE_UNAVAILABLE
    30100,  # ERR_SYNC_FAILED
    30104,  # ERR_SYNC_NETWORK_ERROR
    30500,  # ERR_QUEUE_FULL
    30501,  # ERR_QUEUE_CORRUPTED
    30502,  # ERR_QUEUE_REPLAY_FAILED
    30600,  # ERR_VRAM_OVERFLOW
    30601,  # ERR_RATE_LIMITED
)


# ---------------------------------------------------------------------------
# 重试策略配置
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """重试策略配置.

    定义重试的行为参数，包括最大重试次数、退避策略和
    可重试条件（异常类型、HTTP 状态码、业务错误码）。

    Attributes:
        max_retries: 最大重试次数（不含首次请求），默认 3.
        base_delay: 初始延迟（秒），默认 0.5.
        max_delay: 最大延迟（秒），默认 10.0.
        backoff_factor: 退避因子，默认 2.0（指数退避）.
        jitter: 是否添加随机抖动，默认 True.
        retryable_exceptions: 可重试的异常类型元组.
        retryable_status_codes: 可重试的 HTTP 状态码元组.
        retryable_error_codes: 可重试的业务错误码元组.
    """

    max_retries: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    backoff_factor: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_EXCEPTIONS
    )
    retryable_status_codes: tuple[int, ...] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_STATUS_CODES
    )
    retryable_error_codes: tuple[int, ...] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_ERROR_CODES
    )

    def calculate_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的延迟时间.

        Args:
            attempt: 当前重试次数（从 0 开始）.

        Returns:
            延迟时间（秒），已应用退避和抖动.
        """
        delay = self.base_delay * (self.backoff_factor ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # 添加 ±25% 的随机抖动，避免重试风暴
            jitter_range = delay * 0.25
            delay = delay + random.uniform(-jitter_range, jitter_range)
            delay = max(0.0, delay)

        return delay


# ---------------------------------------------------------------------------
# 重试统计数据类
# ---------------------------------------------------------------------------

@dataclass
class _PolicyStats:
    """单策略重试统计.

    Attributes:
        total_calls: 总调用次数.
        total_retries: 总重试次数.
        total_failures: 最终失败次数（重试耗尽后）.
        retry_successes: 重试后成功的次数.
        error_counter: 可重试错误计数（按错误类型名）.
    """

    total_calls: int = 0
    total_retries: int = 0
    total_failures: int = 0
    retry_successes: int = 0
    error_counter: Counter = field(default_factory=Counter)


# ---------------------------------------------------------------------------
# RetryCoordinator 核心类
# ---------------------------------------------------------------------------

class RetryCoordinator:
    """全局重试协调器.

    统一管理端云协同内核中的所有重试操作，支持：
    - 命名策略注册表，不同模块可配置独立的重试策略
    - 指数退避 + 抖动，自适应延迟
    - 熔断器协同（OPEN 状态直接拒绝，HALF_OPEN 减少重试）
    - 完整的重试统计和可观测性
    - 异步安全（单线程事件循环，无需额外锁）

    Attributes:
        default_policy: 默认重试策略.
    """

    def __init__(self, default_policy: RetryPolicy | None = None) -> None:
        """初始化重试协调器.

        Args:
            default_policy: 默认重试策略，为 None 时使用 RetryPolicy 默认值.
        """
        self.default_policy: RetryPolicy = default_policy or RetryPolicy()
        self._policies: dict[str, RetryPolicy] = {}
        self._stats: _PolicyStats = _PolicyStats()
        self._per_policy_stats: dict[str, _PolicyStats] = {}

        # 熔断器引用（惰性设置，避免循环依赖）
        self._circuit_breaker: Any = None

        logger.info(
            "retry_coordinator.init",
            max_retries=self.default_policy.max_retries,
            base_delay=self.default_policy.base_delay,
        )

    # ------------------------------------------------------------------
    # 策略管理
    # ------------------------------------------------------------------

    def register_policy(self, name: str, policy: RetryPolicy) -> None:
        """注册命名重试策略.

        Args:
            name: 策略名称（唯一标识）.
            policy: 重试策略配置.

        Raises:
            ValueError: 当 name 为空或已存在时.
        """
        if not name or not isinstance(name, str):
            raise ValueError("policy name must be a non-empty string")

        if name in self._policies:
            logger.warning(
                "retry_coordinator.policy_overwrite",
                name=name,
            )

        self._policies[name] = policy
        self._per_policy_stats[name] = _PolicyStats()

        logger.info(
            "retry_coordinator.policy_registered",
            name=name,
            max_retries=policy.max_retries,
        )

    def get_policy(self, name: str) -> RetryPolicy:
        """获取命名策略.

        Args:
            name: 策略名称.

        Returns:
            对应的 RetryPolicy 实例.

        Raises:
            KeyError: 当策略不存在时.
        """
        if name not in self._policies:
            raise KeyError(f"retry policy '{name}' not found")
        return self._policies[name]

    def get_policy_or_default(self, name: str | None) -> RetryPolicy:
        """获取命名策略，不存在时返回默认策略.

        Args:
            name: 策略名称，为 None 时返回默认策略.

        Returns:
            RetryPolicy 实例.
        """
        if name is None:
            return self.default_policy
        return self._policies.get(name, self.default_policy)

    # ------------------------------------------------------------------
    # 熔断器协同
    # ------------------------------------------------------------------

    def set_circuit_breaker(self, circuit_breaker: Any) -> None:
        """设置熔断器实例（惰性绑定，避免循环依赖）.

        熔断器协同规则：
        - OPEN 状态：直接拒绝，不进入重试循环
        - HALF_OPEN 状态：仅允许 1 次重试（保守探测）
        - CLOSED 状态：正常重试

        Args:
            circuit_breaker: 熔断器实例，需实现 allow_request() 和 state 属性.
        """
        self._circuit_breaker = circuit_breaker
        logger.info("retry_coordinator.circuit_breaker_set")

    def _check_circuit_breaker(self) -> tuple[bool, int]:
        """检查熔断器状态，返回是否允许请求和调整后的重试次数.

        Returns:
            (是否允许请求, 调整后的最大重试次数) 元组.
            - OPEN 状态：不允许，返回 (False, 0)
            - HALF_OPEN 状态：允许，重试次数减为 1，返回 (True, 1)
            - CLOSED 状态或无熔断器：允许，返回 (True, -1) 表示不调整
        """
        if self._circuit_breaker is None:
            return True, -1

        # 惰性导入状态枚举，避免循环依赖
        try:
            from edge_cloud_kernel.gateway.circuit_breaker import CircuitState
        except ImportError:
            # 如果导入失败，尝试直接通过属性判断
            state_value = getattr(self._circuit_breaker, "state", None)
            state_str = str(state_value) if state_value else "closed"
        else:
            state = self._circuit_breaker.state
            state_str = state.value if hasattr(state, "value") else str(state)

        if state_str == "open":
            return False, 0

        if state_str == "half_open":
            return True, 1

        return True, -1

    # ------------------------------------------------------------------
    # 核心执行方法
    # ------------------------------------------------------------------

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        policy_name: str | None = None,
        policy: RetryPolicy | None = None,
        **kwargs: Any,
    ) -> Any:
        """带重试执行异步函数.

        根据策略配置自动重试可重试的异常，支持指数退避和抖动。

        Args:
            func: 要执行的异步函数.
            *args: 传递给 func 的位置参数.
            policy_name: 使用的命名策略名称，为 None 时使用默认策略.
            policy: 临时策略（优先级高于 policy_name）.
            **kwargs: 传递给 func 的关键字参数.

        Returns:
            函数执行结果.

        Raises:
            Exception: 重试耗尽后抛出最后一次异常.
            CircuitBreakerError: 熔断器 OPEN 状态时抛出.
        """
        # 确定使用的策略
        active_policy = policy or self.get_policy_or_default(policy_name)
        stats_key = policy_name or "_default_"
        policy_stats = self._get_policy_stats(stats_key)

        # 检查熔断器
        allowed, adjusted_retries = self._check_circuit_breaker()
        if not allowed:
            self._stats.total_failures += 1
            policy_stats.total_failures += 1
            self._raise_circuit_breaker_error()

        effective_max_retries = (
            adjusted_retries if adjusted_retries >= 0 else active_policy.max_retries
        )

        policy_stats.total_calls += 1
        self._stats.total_calls += 1

        last_exception: Exception | None = None

        for attempt in range(effective_max_retries + 1):
            try:
                result = await func(*args, **kwargs)

                # 如果不是首次尝试，说明重试后成功
                if attempt > 0:
                    policy_stats.retry_successes += 1
                    self._stats.retry_successes += 1

                return result

            except Exception as e:
                last_exception = e
                error_name = type(e).__name__

                # 判断是否可重试
                if not self._is_exception_retryable(e, active_policy):
                    policy_stats.total_failures += 1
                    self._stats.total_failures += 1
                    policy_stats.error_counter[error_name] += 1
                    self._stats.error_counter[error_name] += 1
                    raise

                # 已经是最后一次尝试，不再重试
                if attempt >= effective_max_retries:
                    policy_stats.total_failures += 1
                    self._stats.total_failures += 1
                    policy_stats.error_counter[error_name] += 1
                    self._stats.error_counter[error_name] += 1

                    logger.error(
                        "retry_coordinator.exhausted",
                        func_name=getattr(func, "__name__", str(func)),
                        policy=policy_name or "default",
                        retries=attempt,
                        error=error_name,
                        error_message=str(e),
                    )
                    raise

                # 计算延迟并重试
                delay = active_policy.calculate_delay(attempt)
                policy_stats.total_retries += 1
                self._stats.total_retries += 1
                policy_stats.error_counter[error_name] += 1
                self._stats.error_counter[error_name] += 1

                logger.warning(
                    "retry_coordinator.attempt",
                    func_name=getattr(func, "__name__", str(func)),
                    policy=policy_name or "default",
                    attempt=attempt + 1,
                    max_attempts=effective_max_retries,
                    delay_s=round(delay, 3),
                    error=error_name,
                    error_message=str(e),
                )

                await asyncio.sleep(delay)

        # 理论上不会执行到这里
        if last_exception:
            raise last_exception
        raise RuntimeError("retry loop exited without result or exception")

    async def execute_with_fallback(
        self,
        func: Callable[..., Awaitable[Any]],
        fallback: Callable[..., Any] | Callable[..., Awaitable[Any]],
        *args: Any,
        policy_name: str | None = None,
        policy: RetryPolicy | None = None,
        fallback_args: tuple[Any, ...] | None = None,
        fallback_kwargs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """带重试和降级的执行.

        重试耗尽后，调用 fallback 函数返回降级结果，而不是抛出异常。

        Args:
            func: 要执行的主函数.
            fallback: 降级函数（重试耗尽时调用）.
            *args: 传递给 func 的位置参数.
            policy_name: 使用的命名策略名称.
            policy: 临时策略.
            fallback_args: 传递给 fallback 的位置参数，为 None 时使用 *args.
            fallback_kwargs: 传递给 fallback 的关键字参数，为 None 时使用 **kwargs.
            **kwargs: 传递给 func 的关键字参数.

        Returns:
            函数执行结果或降级结果.
        """
        try:
            return await self.execute(
                func,
                *args,
                policy_name=policy_name,
                policy=policy,
                **kwargs,
            )
        except Exception as e:
            logger.warning(
                "retry_coordinator.fallback",
                func_name=getattr(func, "__name__", str(func)),
                fallback_name=getattr(fallback, "__name__", str(fallback)),
                error=type(e).__name__,
            )

            fb_args = fallback_args if fallback_args is not None else args
            fb_kwargs = fallback_kwargs if fallback_kwargs is not None else kwargs

            if asyncio.iscoroutinefunction(fallback):
                return await fallback(*fb_args, **fb_kwargs)
            return fallback(*fb_args, **fb_kwargs)

    # ------------------------------------------------------------------
    # 可重试判断
    # ------------------------------------------------------------------

    def is_retryable(self, exception: Exception) -> bool:
        """判断异常是否可重试（使用默认策略）.

        Args:
            exception: 待判断的异常对象.

        Returns:
            True 表示可重试.
        """
        return self._is_exception_retryable(exception, self.default_policy)

    def _is_exception_retryable(
        self,
        exception: Exception,
        policy: RetryPolicy,
    ) -> bool:
        """判断异常是否符合策略的可重试条件.

        判断逻辑：
        1. 检查异常类型是否在 retryable_exceptions 中
        2. 如果异常有 status_code 属性，检查状态码
        3. 如果异常有 error_code 属性且为数字，检查业务错误码

        Args:
            exception: 待判断的异常对象.
            policy: 重试策略.

        Returns:
            True 表示可重试.
        """
        # 1. 异常类型匹配
        if isinstance(exception, policy.retryable_exceptions):
            return True

        # 2. HTTP 状态码匹配（ProviderError 等带有 status_code 属性）
        status_code = getattr(exception, "status_code", None)
        if status_code is not None and isinstance(status_code, int):
            if status_code in policy.retryable_status_codes:
                return True

        # 3. 业务错误码匹配（error_code 可能是字符串或数字）
        error_code = getattr(exception, "error_code", None)
        if error_code is not None:
            if isinstance(error_code, int):
                if error_code in policy.retryable_error_codes:
                    return True
            elif isinstance(error_code, str):
                # 尝试从字符串错误码中提取数字部分
                try:
                    code_int = int(error_code)
                    if code_int in policy.retryable_error_codes:
                        return True
                except (ValueError, TypeError):
                    pass

        return False

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取重试统计信息.

        Returns:
            包含全局统计、per-policy 统计和错误分布的字典.
        """
        total = self._stats
        retry_success_rate = (
            total.retry_successes / total.total_retries
            if total.total_retries > 0
            else 0.0
        )

        # 最常见的可重试错误（Top 10）
        most_common = total.error_counter.most_common(10)

        # per-policy 统计
        per_policy: dict[str, dict[str, Any]] = {}
        for name, stats in self._per_policy_stats.items():
            policy_rate = (
                stats.retry_successes / stats.total_retries
                if stats.total_retries > 0
                else 0.0
            )
            per_policy[name] = {
                "total_calls": stats.total_calls,
                "total_retries": stats.total_retries,
                "total_failures": stats.total_failures,
                "retry_successes": stats.retry_successes,
                "retry_success_rate": round(policy_rate, 4),
            }

        return {
            "total_calls": total.total_calls,
            "total_retries": total.total_retries,
            "total_failures": total.total_failures,
            "retry_successes": total.retry_successes,
            "retry_success_rate": round(retry_success_rate, 4),
            "most_common_retryable_errors": [
                {"error": err, "count": cnt} for err, cnt in most_common
            ],
            "per_policy": per_policy,
            "registered_policies": list(self._policies.keys()),
        }

    def reset_stats(self) -> None:
        """重置所有统计信息."""
        self._stats = _PolicyStats()
        self._per_policy_stats = {
            name: _PolicyStats() for name in self._per_policy_stats
        }
        logger.info("retry_coordinator.stats_reset")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_policy_stats(self, key: str) -> _PolicyStats:
        """获取指定策略的统计对象（不存在则创建）.

        Args:
            key: 策略标识键.

        Returns:
            _PolicyStats 实例.
        """
        if key not in self._per_policy_stats:
            self._per_policy_stats[key] = _PolicyStats()
        return self._per_policy_stats[key]

    def _raise_circuit_breaker_error(self) -> None:
        """抛出熔断器 OPEN 异常.

        优先使用 CircuitBreakerError，如果不可用则抛出 RuntimeError.
        """
        try:
            from edge_cloud_kernel.models.exceptions import CircuitBreakerError

            cb = self._circuit_breaker
            cb_name = getattr(cb, "name", "unknown") if cb else "unknown"
            reset_timeout = getattr(cb, "_reset_timeout_s", 0.0) if cb else 0.0

            raise CircuitBreakerError(
                message=f"Circuit breaker '{cb_name}' is open, retry rejected",
                error_code="CIRCUIT_OPEN",
                circuit_name=cb_name,
                reset_in=reset_timeout,
            )
        except ImportError:
            raise RuntimeError("Circuit breaker is open, retry rejected")


# ---------------------------------------------------------------------------
# 装饰器支持
# ---------------------------------------------------------------------------

# 全局默认协调器实例（供装饰器使用）
_default_coordinator: RetryCoordinator | None = None


def get_default_coordinator() -> RetryCoordinator:
    """获取全局默认重试协调器（单例）.

    Returns:
        全局 RetryCoordinator 实例.
    """
    global _default_coordinator
    if _default_coordinator is None:
        _default_coordinator = RetryCoordinator()
    return _default_coordinator


def with_retry(
    policy: str | None = None,
    max_retries: int | None = None,
    base_delay: float | None = None,
    max_delay: float | None = None,
    backoff_factor: float | None = None,
    jitter: bool | None = None,
    coordinator: RetryCoordinator | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """重试装饰器.

    为异步函数添加自动重试能力。可以通过命名策略引用已注册的策略，
    也可以直接传入参数覆盖默认策略。

    Args:
        policy: 命名策略名称.
        max_retries: 最大重试次数（覆盖策略配置）.
        base_delay: 初始延迟秒数（覆盖策略配置）.
        max_delay: 最大延迟秒数（覆盖策略配置）.
        backoff_factor: 退避因子（覆盖策略配置）.
        jitter: 是否添加抖动（覆盖策略配置）.
        coordinator: 使用的协调器实例，为 None 时使用全局默认协调器.

    Returns:
        装饰器函数.

    Usage::

        @with_retry(policy="cloud_gateway", max_retries=5)
        async def fetch_data(url: str) -> dict:
            ...

        @with_retry(max_retries=2, base_delay=0.3)
        async def send_request():
            ...
    """
    coord = coordinator or get_default_coordinator()

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 确定使用的策略
            active_policy = coord.get_policy_or_default(policy)

            # 如果有覆盖参数，创建临时策略
            if any(
                p is not None
                for p in (max_retries, base_delay, max_delay, backoff_factor, jitter)
            ):
                from dataclasses import replace

                overrides: dict[str, Any] = {}
                if max_retries is not None:
                    overrides["max_retries"] = max_retries
                if base_delay is not None:
                    overrides["base_delay"] = base_delay
                if max_delay is not None:
                    overrides["max_delay"] = max_delay
                if backoff_factor is not None:
                    overrides["backoff_factor"] = backoff_factor
                if jitter is not None:
                    overrides["jitter"] = jitter

                active_policy = replace(active_policy, **overrides)

            return await coord.execute(
                func,
                *args,
                policy=active_policy,
                **kwargs,
            )

        return wrapper

    return decorator
