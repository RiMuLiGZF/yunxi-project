"""
M6 硬件外设 - 轻量级熔断器

P2-2 改造：为外部调用（传感器采集、设备控制等）提供自动熔断保护，
避免级联故障拖垮整个服务。
"""

import time
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """轻量级熔断器

    状态机:
    - CLOSED (正常): 允许调用，连续失败达到阈值后转入 OPEN
    - OPEN  (熔断):  拒绝调用，超时恢复期后转入 HALF_OPEN
    - HALF_OPEN (半开试探): 允许单次试探，成功恢复 CLOSED，失败回到 OPEN

    Attributes:
        name: 熔断器名称，用于日志和指标
        failure_threshold: 连续失败阈值（默认 5）
        recovery_timeout: 熔断恢复超时秒数（默认 30s）
    """

    CLOSED = "closed"        # 正常状态
    OPEN = "open"            # 熔断状态
    HALF_OPEN = "half-open"  # 半开试探

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._total_calls = 0
        self._total_failures = 0

    async def call(
        self,
        func: Callable,
        fallback: Optional[Callable] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """执行调用，失败时自动熔断

        Args:
            func: 待执行的异步函数
            fallback: 熔断时的降级回调（同步函数）
            *args, **kwargs: 传递给 func 的参数

        Returns:
            func 的返回值；熔断时返回 fallback() 的结果或 None
        """
        # ---- OPEN 状态检查 ----
        if self._state == self.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = self.HALF_OPEN
                logger.info(
                    "[CircuitBreaker] %s 进入半开试探状态", self.name
                )
            else:
                self._total_calls += 1
                logger.warning(
                    "[CircuitBreaker] %s 熔断中，拒绝调用 (连续失败 %d/%d)",
                    self.name,
                    self._failure_count,
                    self.failure_threshold,
                )
                return fallback() if fallback else None

        # ---- 正常 / 半开执行 ----
        try:
            self._total_calls += 1
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._total_failures += 1
            self._on_failure()
            logger.error(
                "[CircuitBreaker] %s 调用失败: %s", self.name, e
            )
            return fallback() if fallback else None

    def _on_success(self) -> None:
        """成功回调：重置计数，恢复 CLOSED"""
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            logger.info(
                "[CircuitBreaker] %s 半开试探成功，恢复关闭", self.name
            )
        self._failure_count = 0

    def _on_failure(self) -> None:
        """失败回调：累加计数，必要时熔断"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            logger.warning(
                "[CircuitBreaker] %s 半开试探失败，重新熔断", self.name
            )
        elif self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            logger.warning(
                "[CircuitBreaker] %s 达到失败阈值 (%d)，进入熔断状态",
                self.name,
                self.failure_threshold,
            )

    @property
    def state(self) -> str:
        """当前熔断状态"""
        return self._state

    @property
    def stats(self) -> dict:
        """熔断器统计信息"""
        return {
            "name": self.name,
            "state": self._state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
        }
