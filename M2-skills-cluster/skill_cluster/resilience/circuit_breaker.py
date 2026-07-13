from __future__ import annotations

"""Circuit Breaker 熔断与重试机制.

为 Skill 调用提供生产级容错能力：熔断器防止级联故障，指数退避重试提高可用性。

【M2 优化】
- 熔断器状态联动重试策略（HALF_OPEN 减少重试、OPEN 直接拒绝）
- 智能错误分类（瞬时/永久错误分离，熔断错误独立判断）
- 熔断恢复后逐步放量（渐进式 HALF_OPEN 探测）
- 统计指标增强（连续成功/失败、重试成功率等）
- 错误分类器配置化（自定义异常类型、错误码、关键词）
"""

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from skill_cluster.exceptions import CircuitBreakerOpenError as _BaseCircuitBreakerOpenError

logger = structlog.get_logger()


# ============================================================================
#  描述符：同时支持实例方法和类方法调用
# ============================================================================


class _DualMethod:
    """描述符：支持同一方法名同时作为实例方法和"类方法"调用.

    当通过类访问时，使用默认实例；当通过实例访问时，使用实例自身。
    用于保持 ErrorClassifier 的向后兼容（旧代码用 ErrorClassifier.classify(exc)）。
    """

    def __init__(self, method_name: str) -> None:
        self._method_name = method_name

    def __get__(self, instance: Any, owner: type) -> Any:
        if instance is None:
            # 通过类访问：使用默认实例
            target = owner._default_instance
        else:
            # 通过实例访问：使用实例自身
            target = instance
        return getattr(target, self._method_name)


# ============================================================================
#  错误分类器
# ============================================================================


class ErrorClassifier:
    """错误分类器：区分瞬时错误与永久错误，判断是否计入熔断、是否可重试.

    分类规则：
    - 瞬时错误（transient）：网络超时、连接重置、5xx、429 等 → 计入熔断 + 可重试
    - 永久错误（permanent）：参数错误、权限不足、4xx（除429）等 → 不计入熔断 + 不可重试

    支持实例化配置，也保留类方法调用以兼容旧代码。

    用法：
        # 旧代码（类方法风格，向后兼容）
        ErrorClassifier.classify(exc)

        # 新代码（实例化配置）
        ec = ErrorClassifier(transient_keywords=("custom_err",))
        ec.classify(exc)
    """

    # --- 默认可重试异常类型 ---
    DEFAULT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
        asyncio.TimeoutError,
        ConnectionError,
        OSError,
    )

    # --- 默认瞬时错误关键词 ---
    DEFAULT_TRANSIENT_KEYWORDS: tuple[str, ...] = (
        "timeout",
        "connection",
        "refused",
        "reset",
        "temporary",
        "unavailable",
        "rate limit",
        "rate_limited",
        "429",
        "500",
        "502",
        "503",
        "504",
        "server error",
        "busy",
    )

    # --- 默认永久错误关键词 ---
    DEFAULT_PERMANENT_KEYWORDS: tuple[str, ...] = (
        "invalid param",
        "invalid_params",
        "bad request",
        "400",
        "unauthorized",
        "401",
        "forbidden",
        "403",
        "not found",
        "404",
        "permission",
        "argument",
        "valueerror",
        "typeerror",
        "validation",
    )

    # --- 默认可重试错误码（来自 error_codes.py） ---
    DEFAULT_RETRYABLE_ERROR_CODES: tuple[int, ...] = (
        20006,  # RATE_LIMITED
        20007,  # SERVICE_UNAVAILABLE
        20008,  # TIMEOUT
        20009,  # INTERNAL_ERROR
        22001,  # EXECUTION_FAILED
        22002,  # EXECUTION_TIMEOUT
        24002,  # MCP_SERVER_UNAVAILABLE
        24004,  # MCP_CALL_FAILED
        24006,  # MCP_CONNECTION_FAILED
    )

    def __init__(
        self,
        retryable_exceptions: tuple[type[Exception], ...] | None = None,
        transient_keywords: tuple[str, ...] | None = None,
        permanent_keywords: tuple[str, ...] | None = None,
        retryable_error_codes: tuple[int, ...] | None = None,
    ) -> None:
        """初始化错误分类器.

        Args:
            retryable_exceptions: 自定义可重试异常类型列表.
            transient_keywords: 自定义瞬时错误关键词列表.
            permanent_keywords: 自定义永久错误关键词列表.
            retryable_error_codes: 自定义可重试错误码列表.
        """
        self._retryable_exceptions = (
            retryable_exceptions
            if retryable_exceptions is not None
            else self.DEFAULT_RETRYABLE_EXCEPTIONS
        )
        self._transient_keywords = (
            transient_keywords
            if transient_keywords is not None
            else self.DEFAULT_TRANSIENT_KEYWORDS
        )
        self._permanent_keywords = (
            permanent_keywords
            if permanent_keywords is not None
            else self.DEFAULT_PERMANENT_KEYWORDS
        )
        self._retryable_error_codes = (
            retryable_error_codes
            if retryable_error_codes is not None
            else self.DEFAULT_RETRYABLE_ERROR_CODES
        )

    # ---- 核心分类方法 ----

    def classify(self, exc: Exception) -> tuple[str, bool]:
        """分类异常.

        Args:
            exc: 待分类的异常.

        Returns:
            (错误类型标识, 是否可重试).
        """
        if self._is_permanent_error(exc):
            return self._error_type_name(exc, "permanent"), False
        if self._is_transient_error(exc):
            return self._error_type_name(exc, "transient"), True
        # 默认按业务错误处理，不可重试
        return self._error_type_name(exc, "business"), False

    def is_retryable(self, exc: Exception) -> bool:
        """判断异常是否可重试.

        Args:
            exc: 待判断的异常.

        Returns:
            True 表示可重试.
        """
        _, retryable = self.classify(exc)
        return retryable

    def is_circuit_breaker_error(self, exc: Exception) -> bool:
        """判断异常是否计入熔断失败统计.

        瞬时错误计入熔断（后端可能故障），永久错误不计入（调用方问题）。

        Args:
            exc: 待判断的异常.

        Returns:
            True 表示应计入熔断失败次数.
        """
        # 永久错误不计入熔断
        if self._is_permanent_error(exc):
            return False
        # 瞬时错误或未知错误都计入熔断
        return True

    def is_transient(self, exc: Exception) -> bool:
        """判断是否为瞬时错误.

        Args:
            exc: 待判断的异常.

        Returns:
            True 表示瞬时错误.
        """
        return self._is_transient_error(exc)

    def is_permanent(self, exc: Exception) -> bool:
        """判断是否为永久错误.

        Args:
            exc: 待判断的异常.

        Returns:
            True 表示永久错误.
        """
        return self._is_permanent_error(exc)

    # ---- 内部判断方法 ----

    def _is_transient_error(self, exc: Exception) -> bool:
        """判断是否为瞬时错误."""
        # 1. 异常类型匹配
        if isinstance(exc, self._retryable_exceptions):
            return True

        # 2. 错误消息关键词匹配
        msg = str(exc).lower()
        if any(kw.lower() in msg for kw in self._transient_keywords):
            # 但如果同时匹配永久关键词，则不算（永久优先级更高）
            if not any(kw.lower() in msg for kw in self._permanent_keywords):
                return True

        # 3. 错误码匹配（如果异常有 error_code 属性）
        error_code = getattr(exc, "error_code", None)
        if error_code is not None and isinstance(error_code, int):
            if error_code in self._retryable_error_codes:
                return True

        return False

    def _is_permanent_error(self, exc: Exception) -> bool:
        """判断是否为永久错误."""
        # 常见的永久错误异常类型
        permanent_types = (ValueError, TypeError, KeyError, AttributeError)
        if isinstance(exc, permanent_types):
            # 但 OSError 子类可能是瞬时的，排除掉
            if not isinstance(exc, OSError):
                return True

        # 错误消息关键词匹配
        msg = str(exc).lower()
        if any(kw.lower() in msg for kw in self._permanent_keywords):
            return True

        # 错误码匹配（4xx 风格的错误码通常是永久错误）
        error_code = getattr(exc, "error_code", None)
        if error_code is not None and isinstance(error_code, int):
            # 参数错误、权限错误、不存在等属于永久错误
            permanent_code_ranges = [
                (20002, 20005),  # INVALID_PARAMS ~ NOT_FOUND
                (21000, 21009),  # 技能相关错误（大多是配置/定义问题）
                (23000, 23005),  # 权限相关错误
            ]
            for start, end in permanent_code_ranges:
                if start <= error_code <= end:
                    # 但可重试错误码列表中的除外
                    if error_code not in self._retryable_error_codes:
                        return True

        return False

    @staticmethod
    def _error_type_name(exc: Exception, category: str) -> str:
        """生成错误类型标识."""
        return f"{category}:{type(exc).__name__}"

    # ---- 向后兼容：类方法风格的调用 ----
    #
    # 通过 _DualMethod 描述符，以下方法既可通过类调用（使用默认实例），
    # 也可通过实例调用（使用实例自身的配置）。
    # 内部实现统一带 _ 前缀，描述符负责路由。

    def _classify(self, exc: Exception) -> tuple[str, bool]:
        """分类异常（内部实现）."""
        if self._is_permanent_error(exc):
            return self._error_type_name(exc, "permanent"), False
        if self._is_transient_error(exc):
            return self._error_type_name(exc, "transient"), True
        return self._error_type_name(exc, "business"), False

    def _is_retryable(self, exc: Exception) -> bool:
        """判断是否可重试（内部实现）."""
        _, retryable = self._classify(exc)
        return retryable

    def _is_circuit_breaker_error(self, exc: Exception) -> bool:
        """判断是否计入熔断失败（内部实现）."""
        if self._is_permanent_error(exc):
            return False
        return True

    def _is_transient(self, exc: Exception) -> bool:
        """判断是否瞬时错误（内部实现）."""
        return self._is_transient_error(exc)

    def _is_permanent(self, exc: Exception) -> bool:
        """判断是否永久错误（内部实现）."""
        return self._is_permanent_error(exc)

    # 描述符：对外暴露的公共方法名
    classify = _DualMethod("_classify")
    is_retryable = _DualMethod("_is_retryable")
    is_circuit_breaker_error = _DualMethod("_is_circuit_breaker_error")
    is_transient = _DualMethod("_is_transient")
    is_permanent = _DualMethod("_is_permanent")


# 默认实例，供类方法风格调用使用
ErrorClassifier._default_instance = ErrorClassifier()  # type: ignore[attr-defined]


# ============================================================================
#  熔断器状态 & 配置
# ============================================================================


class CircuitState(Enum):
    """熔断器状态."""

    CLOSED = "closed"       # 正常，允许请求通过
    OPEN = "open"           # 熔断，拒绝请求
    HALF_OPEN = "half_open" # 半开，允许探测请求


@dataclass
class CircuitBreakerConfig:
    """熔断器配置.

    【新增字段】
    - half_open_steps: 逐步放量步骤，如 [1, 2, 5] 表示依次允许 1/2/5 个请求
    - error_rate_window: 错误率统计窗口大小（最近 N 次调用）
    - error_rate_warning_threshold: 错误率预报警阈值（0~1），达到后重试间隔加大
    - enable_gradual_recovery: 是否启用渐进式恢复
    """

    failure_threshold: int = 5          # 连续失败次数阈值
    recovery_timeout: float = 30.0      # 熔断后恢复等待（秒）
    half_open_max_calls: int = 3        # 半开状态最大探测请求数
    success_threshold: int = 2          # 半开状态成功次数阈值

    # --- 新增：渐进式恢复 ---
    enable_gradual_recovery: bool = False
    half_open_steps: tuple[int, ...] = (1, 2, 5)

    # --- 新增：错误率统计（用于预报警） ---
    error_rate_window: int = 20          # 最近 N 次调用的滑动窗口
    error_rate_warning_threshold: float = 0.3  # 错误率预警阈值


@dataclass
class RetryConfig:
    """重试配置.

    【新增字段】
    - error_classifier: 错误分类器实例，None 则用默认
    - half_open_max_retries: HALF_OPEN 状态下的最大重试次数
    - warning_delay_multiplier: 错误率预警时的延迟倍数
    - enable_state_aware_retry: 是否启用熔断器状态感知的重试策略
    """

    max_retries: int = 3                # 最大重试次数
    base_delay: float = 1.0             # 基础延迟（秒）
    max_delay: float = 60.0             # 最大延迟（秒）
    exponential_base: float = 2.0       # 指数基数
    jitter: bool = True                 # 是否添加随机抖动
    retry_on: tuple[str, ...] = ("failure", "timeout")  # 哪些状态触发重试

    # --- 新增：状态感知重试 ---
    enable_state_aware_retry: bool = False
    half_open_max_retries: int = 1      # HALF_OPEN 状态下重试次数
    warning_delay_multiplier: float = 2.0  # 预警时延迟倍数

    # --- 新增：错误分类器（默认不启用，保持向后兼容） ---
    enable_error_classification: bool = False  # 是否启用错误分类判断重试
    error_classifier: ErrorClassifier | None = None


# ============================================================================
#  熔断器统计
# ============================================================================


@dataclass
class CircuitBreakerStats:
    """熔断器统计指标.

    【新增字段】
    - consecutive_successes: 连续成功次数
    - consecutive_failures: 连续失败次数
    - total_calls: 总调用次数
    - total_successes: 总成功次数
    - total_failures: 总失败次数
    - circuit_breaker_rejections: 熔断拒绝次数
    """

    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    circuit_breaker_rejections: int = 0
    state_transitions: int = 0


# ============================================================================
#  熔断器
# ============================================================================


class CircuitBreaker:
    """熔断器.

    基于 Martin Fowler 的 Circuit Breaker 模式实现。

    【M2 优化】
    - 渐进式 HALF_OPEN 恢复（逐步放量）
    - 瞬时/永久错误分离（永久错误不计入熔断）
    - 错误率滑动窗口统计（预报警）
    - 增强统计指标
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        error_classifier: ErrorClassifier | None = None,
    ) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._error_classifier = error_classifier or ErrorClassifier()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

        # --- 新增：统计指标 ---
        self._stats = CircuitBreakerStats()

        # --- 新增：错误率滑动窗口 ---
        self._result_window: deque[bool] = deque(
            maxlen=self._config.error_rate_window
        )

        # --- 新增：渐进式恢复 ---
        self._recovery_step_index: int = 0
        self._current_step_successes: int = 0

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def name(self) -> str:
        return self._name

    @property
    def error_classifier(self) -> ErrorClassifier:
        return self._error_classifier

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
        # 快速路径：检查是否允许通过
        allowed, reject_reason = await self._try_acquire()
        if not allowed:
            self._stats.circuit_breaker_rejections += 1
            if fallback_factory is not None:
                logger.info(
                    "circuit_breaker_fallback",
                    name=self._name,
                    state=self._state.value,
                    reason=reject_reason,
                )
                return await fallback_factory()
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self._name}' is {self._state.value}: {reject_reason}"
            )

        # 在锁外执行实际调用
        try:
            result = await coro_factory()
            await self._on_success()
            return result
        except Exception as e:
            # 判断是否计入熔断失败
            if self._error_classifier.is_circuit_breaker_error(e):
                await self._on_failure()
            else:
                # 永久错误：不计入熔断，但记录一次调用
                await self._on_neutral()
            raise

    async def _try_acquire(self) -> tuple[bool, str]:
        """尝试获取调用许可.

        Returns:
            (是否允许通过, 拒绝原因).
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                    return True, ""
                else:
                    return False, "circuit_open"

            elif self._state == CircuitState.HALF_OPEN:
                return self._check_half_open_allowance()

            # CLOSED 状态总是允许
            return True, ""

    def _check_half_open_allowance(self) -> tuple[bool, str]:
        """检查 HALF_OPEN 状态下是否允许调用（内部方法，需在锁内调用）."""
        if self._config.enable_gradual_recovery:
            # 渐进式恢复：根据当前 step 决定允许的并发数
            step_limit = self._get_current_step_limit()
            if self._half_open_calls >= step_limit:
                return False, f"half_open_step_limit_{step_limit}"
        else:
            # 原有逻辑：固定 half_open_max_calls
            if self._half_open_calls >= self._config.half_open_max_calls:
                return False, "half_open_limit_reached"

        self._half_open_calls += 1
        return True, ""

    def _get_current_step_limit(self) -> int:
        """获取当前渐进恢复步骤的请求上限（需在锁内调用）."""
        steps = self._config.half_open_steps
        if self._recovery_step_index < len(steps):
            return steps[self._recovery_step_index]
        # 超过步骤数后完全放开
        return self._config.half_open_max_calls

    # ---- 成功/失败处理 ----

    async def _on_success(self) -> None:
        """调用成功处理."""
        async with self._lock:
            self._stats.total_calls += 1
            self._stats.total_successes += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._result_window.append(True)

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1

                if self._config.enable_gradual_recovery:
                    self._current_step_successes += 1
                    current_limit = self._get_current_step_limit()

                    # 当前 step 的请求全部成功，进入下一步
                    if self._current_step_successes >= current_limit:
                        self._recovery_step_index += 1
                        self._current_step_successes = 0
                        self._half_open_calls = 0  # 重置计数，允许下一批

                        steps = self._config.half_open_steps
                        if self._recovery_step_index >= len(steps):
                            # 所有步骤完成，恢复 CLOSED
                            self._transition_to_closed()
                        else:
                            logger.info(
                                "circuit_breaker_recovery_step",
                                name=self._name,
                                step=self._recovery_step_index,
                                limit=self._get_current_step_limit(),
                            )
                else:
                    # 原有逻辑：达到 success_threshold 即恢复
                    if self._success_count >= self._config.success_threshold:
                        self._transition_to_closed()
            else:
                # CLOSED 状态：重置失败计数
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """调用失败处理（计入熔断的失败）."""
        async with self._lock:
            self._stats.total_calls += 1
            self._stats.total_failures += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._result_window.append(False)
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # HALF_OPEN 期间失败，回到 OPEN
                self._transition_to_open(
                    reason="half_open_failure",
                    failure_count=self._failure_count,
                )
            elif self._failure_count >= self._config.failure_threshold:
                self._transition_to_open(
                    reason="failure_threshold_exceeded",
                    failure_count=self._failure_count,
                )

    async def _on_neutral(self) -> None:
        """中性调用（永久错误）：记录调用但不影响熔断状态."""
        async with self._lock:
            self._stats.total_calls += 1
            # 永久错误不计入连续失败/成功计数的中断
            # 也不加入错误率窗口（因为不是后端问题）

    # ---- 状态转换 ----

    def _transition_to_open(self, reason: str, **kwargs: Any) -> None:
        """转换到 OPEN 状态（需在锁内调用）."""
        old_state = self._state
        self._state = CircuitState.OPEN
        self._stats.state_transitions += 1
        logger.warning(
            "circuit_breaker_opened",
            name=self._name,
            from_state=old_state.value,
            reason=reason,
            **kwargs,
        )

    def _transition_to_half_open(self) -> None:
        """转换到 HALF_OPEN 状态（需在锁内调用）."""
        self._state = CircuitState.HALF_OPEN
        self._half_open_calls = 0
        self._success_count = 0
        self._recovery_step_index = 0
        self._current_step_successes = 0
        self._stats.state_transitions += 1
        logger.info(
            "circuit_breaker_half_open",
            name=self._name,
            gradual_recovery=self._config.enable_gradual_recovery,
            steps=list(self._config.half_open_steps) if self._config.enable_gradual_recovery else None,
        )

    def _transition_to_closed(self) -> None:
        """转换到 CLOSED 状态（需在锁内调用）."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._stats.state_transitions += 1
        logger.info(
            "circuit_breaker_closed",
            name=self._name,
            total_failures=self._stats.total_failures,
        )

    def _should_attempt_reset(self) -> bool:
        """判断是否应该尝试从 OPEN 恢复到 HALF_OPEN."""
        if self._last_failure_time is None:
            return True
        return (time.time() - self._last_failure_time) >= self._config.recovery_timeout

    # ---- 错误率 & 状态查询 ----

    def get_error_rate(self) -> float:
        """获取当前错误率（基于滑动窗口）.

        Returns:
            0.0 ~ 1.0 的错误率，窗口为空时返回 0.0.
        """
        if not self._result_window:
            return 0.0
        failures = sum(1 for r in self._result_window if not r)
        return failures / len(self._result_window)

    def is_warning(self) -> bool:
        """判断是否处于错误率预警状态.

        Returns:
            True 表示错误率超过预警阈值.
        """
        return self.get_error_rate() >= self._config.error_rate_warning_threshold

    def get_adaptive_retry_count(self, base_max_retries: int) -> int:
        """根据熔断器状态获取自适应重试次数.

        Args:
            base_max_retries: 基础最大重试次数（CLOSED 正常状态）.

        Returns:
            调整后的最大重试次数.
        """
        if self._state == CircuitState.HALF_OPEN:
            return 1  # HALF_OPEN 只允许 1 次重试
        # CLOSED 或其他状态用基础值
        return base_max_retries

    def get_adaptive_delay_multiplier(self) -> float:
        """获取自适应延迟倍数（错误率预警时加大间隔）.

        Returns:
            延迟倍数.
        """
        if self._state == CircuitState.CLOSED and self.is_warning():
            return 2.0
        return 1.0

    # ---- 指标 ----

    def get_metrics(self) -> dict[str, Any]:
        """获取熔断器指标."""
        return {
            "name": self._name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
            # 新增指标
            "consecutive_successes": self._stats.consecutive_successes,
            "consecutive_failures": self._stats.consecutive_failures,
            "total_calls": self._stats.total_calls,
            "total_successes": self._stats.total_successes,
            "total_failures": self._stats.total_failures,
            "circuit_breaker_rejections": self._stats.circuit_breaker_rejections,
            "state_transitions": self._stats.state_transitions,
            "error_rate": self.get_error_rate(),
            "is_warning": self.is_warning(),
            "recovery_step": self._recovery_step_index if self._state == CircuitState.HALF_OPEN else -1,
        }


# ============================================================================
#  异常类型
# ============================================================================


class CircuitBreakerOpenError(_BaseCircuitBreakerOpenError):
    """熔断器打开异常.

    【向后兼容】原版本继承自 Exception，现升级为继承 M2BaseException，
    保留单字符串参数的构造方式，同时支持完整的 M2BaseException 参数。

    使用方式::

        # 旧方式（仍然支持）
        raise CircuitBreakerOpenError("Circuit breaker is OPEN")

        # 新方式（推荐）
        raise CircuitBreakerOpenError(
            detail="熔断器已打开",
            trace_id="xxx",
            data={"name": "skill.xxx"},
        )
    """

    def __init__(self, detail: str = "", **kwargs: Any) -> None:
        """初始化熔断器打开异常.

        兼容旧版单字符串调用方式：``CircuitBreakerOpenError("message")``.

        Args:
            detail: 错误详情
            **kwargs: 传递给 M2BaseException 的其他参数
        """
        super().__init__(detail=detail, **kwargs)


# ============================================================================
#  重试执行器
# ============================================================================


@dataclass
class RetryStats:
    """重试统计指标."""

    total_calls: int = 0
    retry_triggered: int = 0     # 触发了重试的调用数
    retry_saved: int = 0         # 重试后成功的调用数
    total_retries: int = 0       # 总重试次数
    retry_exhausted: int = 0     # 重试耗尽的调用数

    @property
    def retry_success_rate(self) -> float:
        """重试成功率（重试后成功的比例）."""
        if self.retry_triggered == 0:
            return 0.0
        return self.retry_saved / self.retry_triggered


class RetryExecutor:
    """重试执行器.

    支持指数退避 + 抖动的重试策略。

    【M2 优化】
    - 错误分类器驱动的可重试判断
    - 熔断器状态感知（HALF_OPEN 减少重试、预警加大间隔）
    - 增强统计指标
    """

    def __init__(
        self,
        config: RetryConfig | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._config = config or RetryConfig()
        self._circuit_breaker = circuit_breaker
        self._error_classifier = (
            self._config.error_classifier or ErrorClassifier()
        )
        self._stats = RetryStats()

    @property
    def stats(self) -> RetryStats:
        return self._stats

    async def execute(self, coro_factory: Any) -> Any:
        """执行带重试的调用.

        Args:
            coro_factory: 返回协程的可调用对象.

        Returns:
            调用结果.

        Raises:
            Exception: 最后一次重试的异常.
        """
        max_retries = self._get_effective_max_retries()
        delay_multiplier = self._get_effective_delay_multiplier()

        self._stats.total_calls += 1
        last_exception: Exception | None = None
        did_retry = False

        for attempt in range(max_retries + 1):
            try:
                result = await coro_factory()
                if did_retry:
                    self._stats.retry_saved += 1
                return result
            except Exception as e:
                last_exception = e

                # 判断是否可重试
                if not self._should_retry(e):
                    logger.debug(
                        "retry_skipped_permanent_error",
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    raise

                if attempt >= max_retries:
                    break

                did_retry = True
                self._stats.retry_triggered += 1 if attempt == 0 else 0
                self._stats.total_retries += 1

                delay = self._calculate_delay(attempt) * delay_multiplier
                logger.warning(
                    "retry_attempt",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=round(delay, 3),
                    error_type=type(e).__name__,
                    error=str(e)[:200],
                )
                await asyncio.sleep(delay)

        # 重试耗尽
        self._stats.retry_exhausted += 1
        logger.error(
            "retry_exhausted",
            max_retries=max_retries,
            error_type=type(last_exception).__name__ if last_exception else "unknown",
        )
        raise last_exception  # type: ignore[misc]

    def _should_retry(self, exc: Exception) -> bool:
        """判断异常是否应该重试.

        默认情况下（enable_error_classification=False），所有异常都重试，
        保持与旧版本的完全向后兼容。
        """
        if not self._config.enable_error_classification:
            return True
        return self._error_classifier.is_retryable(exc)

    def _get_effective_max_retries(self) -> int:
        """获取当前有效的最大重试次数（考虑熔断器状态）."""
        base = self._config.max_retries

        if (
            self._config.enable_state_aware_retry
            and self._circuit_breaker is not None
        ):
            return self._circuit_breaker.get_adaptive_retry_count(base)

        return base

    def _get_effective_delay_multiplier(self) -> float:
        """获取当前有效的延迟倍数（考虑错误率预警）."""
        if (
            self._config.enable_state_aware_retry
            and self._circuit_breaker is not None
        ):
            cb = self._circuit_breaker
            if cb.state == CircuitState.CLOSED and cb.is_warning():
                return self._config.warning_delay_multiplier
            if cb.state == CircuitState.HALF_OPEN:
                # HALF_OPEN 状态也加大间隔，避免加重后端压力
                return self._config.warning_delay_multiplier

        return 1.0

    def _calculate_delay(self, attempt: int) -> float:
        """计算退避延迟."""
        delay = self._config.base_delay * (
            self._config.exponential_base ** attempt
        )
        delay = min(delay, self._config.max_delay)
        if self._config.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return delay


# ============================================================================
#  弹性 Skill 调用器
# ============================================================================


@dataclass
class ResilientInvokerStats:
    """弹性调用器统计指标."""

    total_calls: int = 0
    circuit_breaker_rejections: int = 0
    retry_triggered: int = 0
    retry_saved: int = 0
    total_retry_count: int = 0

    @property
    def retry_success_rate(self) -> float:
        """重试成功率."""
        if self.retry_triggered == 0:
            return 0.0
        return self.retry_saved / self.retry_triggered


class ResilientSkillInvoker:
    """弹性 Skill 调用器.

    组合熔断器 + 重试，为 Skill 调用提供生产级容错。

    【M2 优化】
    - 熔断器与重试器状态联动
    - 增强统计指标（总调用、熔断拒绝、重试触发、重试挽救等）
    - 错误分类器统一配置
    """

    def __init__(
        self,
        circuit_config: CircuitBreakerConfig | None = None,
        retry_config: RetryConfig | None = None,
        error_classifier: ErrorClassifier | None = None,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._circuit_config = circuit_config or CircuitBreakerConfig()
        self._retry_config = retry_config or RetryConfig()
        self._error_classifier = error_classifier or ErrorClassifier()
        self._stats = ResilientInvokerStats()
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> ResilientInvokerStats:
        return self._stats

    def get_breaker(self, skill_id: str) -> CircuitBreaker:
        """获取或创建熔断器."""
        if skill_id not in self._breakers:
            self._breakers[skill_id] = CircuitBreaker(
                name=skill_id,
                config=self._circuit_config,
                error_classifier=self._error_classifier,
            )
        return self._breakers[skill_id]

    async def invoke(self, skill_id: str, coro_factory: Any) -> Any:
        """弹性调用 Skill.

        先经过熔断器检查，再通过重试执行器调用。
        熔断器状态会影响重试策略（状态感知）。
        """
        async with self._lock:
            breaker = self.get_breaker(skill_id)

        self._stats.total_calls += 1

        # 创建带熔断器感知的重试执行器
        retry = RetryExecutor(self._retry_config, circuit_breaker=breaker)

        async def _with_retry() -> Any:
            return await retry.execute(coro_factory)

        try:
            result = await breaker.call(_with_retry)
            # 累计重试统计
            self._stats.retry_triggered += retry.stats.retry_triggered
            self._stats.retry_saved += retry.stats.retry_saved
            self._stats.total_retry_count += retry.stats.total_retries
            return result
        except CircuitBreakerOpenError:
            self._stats.circuit_breaker_rejections += 1
            raise
        except Exception:
            # 其他异常也累计重试统计
            self._stats.retry_triggered += retry.stats.retry_triggered
            self._stats.retry_saved += retry.stats.retry_saved
            self._stats.total_retry_count += retry.stats.total_retries
            raise

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器指标."""
        return {
            sid: breaker.get_metrics()
            for sid, breaker in self._breakers.items()
        }

    def get_invoker_stats(self) -> dict[str, Any]:
        """获取弹性调用器统计指标."""
        return {
            "total_calls": self._stats.total_calls,
            "circuit_breaker_rejections": self._stats.circuit_breaker_rejections,
            "retry_triggered": self._stats.retry_triggered,
            "retry_saved": self._stats.retry_saved,
            "total_retry_count": self._stats.total_retry_count,
            "retry_success_rate": self._stats.retry_success_rate,
            "breaker_count": len(self._breakers),
        }
