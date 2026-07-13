"""
云汐内核 V4 - 熔断器系统

灵感来源：Netflix Hystrix / Resilience4j Circuit Breaker Pattern

保护 Agent 集群免受级联故障影响。
当某个 Agent 连续失败达到一定阈值时，熔断器打开，
后续请求快速失败，给故障 Agent 恢复时间。

状态机：
CLOSED   -> 正常通行，记录失败率
OPEN     -> 快速失败，拒绝请求
HALF_OPEN -> 允许试探请求，验证是否恢复
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger(__name__)


class CircuitState(str, Enum):
    """熔断器状态"""

    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断
    HALF_OPEN = "half_open" # 半开（试探）


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""

    failure_threshold: int = 5          # 触发熔断的连续失败次数
    recovery_timeout: float = 30.0      # 熔断后等待恢复时间（秒）
    half_open_max_calls: int = 3        # 半开状态允许的最大试探次数
    success_threshold: int = 2          # 半开状态连续成功次数，恢复 CLOSED
    exclusion_statuses: set[str] = field(default_factory=lambda: {"not_found"})
    # 不计入失败的错误状态


class CircuitBreakerError(Exception):
    """熔断器拦截异常"""

    def __init__(self, agent_id: str, state: CircuitState, message: str = "") -> None:
        self.agent_id = agent_id
        self.state = state
        super().__init__(message or f"Circuit breaker is {state.value} for agent '{agent_id}'")


class CircuitBreaker:
    """熔断器

    为单个 Agent 提供故障保护。
    """

    def __init__(self, agent_id: str, config: CircuitBreakerConfig | None = None) -> None:
        self.agent_id = agent_id
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED

        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float | None = None
        self._logger = logger.bind(service="circuit_breaker", agent_id=agent_id)

    # ── 核心执行接口 ────────────────────────────────────

    async def call(self, func: Callable[[], Awaitable[Any]], context: dict[str, Any] | None = None) -> Any:
        """在熔断器保护下执行函数

        Args:
            func: 被保护的异步函数
            context: 可选上下文

        Returns:
            func 的返回值

        Raises:
            CircuitBreakerError: 熔断器处于 OPEN 状态
        """
        self._transition_state()

        if self.state == CircuitState.OPEN:
            raise CircuitBreakerError(self.agent_id, self.state)

        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.config.half_open_max_calls:
                raise CircuitBreakerError(
                    self.agent_id, self.state, "Half-open max calls exceeded"
                )
            self._half_open_calls += 1

        try:
            result = await func()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            raise

    def _transition_state(self) -> None:
        """根据时间和状态自动转换"""
        if self.state == CircuitState.OPEN:
            if self._last_failure_time is None:
                return
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                self._logger.info(
                    "circuit_breaker_half_open",
                    agent_id=self.agent_id,
                    recovery_timeout=self.config.recovery_timeout,
                )

    def _on_success(self) -> None:
        """成功回调"""
        if self.state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._reset_to_closed()
        else:
            self._failure_count = 0

    def _on_failure(self, exc: Exception) -> None:
        """失败回调"""
        # 排除不计入的错误
        error_str = str(exc).lower()
        for excluded in self.config.exclusion_statuses:
            if excluded.lower() in error_str:
                return

        self._failure_count += 1
        self._last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # 半开状态失败，重新熔断
            self._open_circuit()
        elif self._failure_count >= self.config.failure_threshold:
            self._open_circuit()

    def _open_circuit(self) -> None:
        """打开熔断器"""
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self._logger.warning(
                "circuit_breaker_opened",
                agent_id=self.agent_id,
                failure_count=self._failure_count,
                recovery_timeout=self.config.recovery_timeout,
            )

    def _reset_to_closed(self) -> None:
        """恢复为关闭状态"""
        old_state = self.state
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = None
        self._logger.info(
            "circuit_breaker_closed",
            agent_id=self.agent_id,
            previous_state=old_state.value,
        )

    # ── 状态查询 ────────────────────────────────────────

    def get_state(self) -> CircuitState:
        """获取当前状态"""
        self._transition_state()
        return self.state

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "agent_id": self.agent_id,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_max_calls": self.config.half_open_max_calls,
                "success_threshold": self.config.success_threshold,
            },
        }

    def reset(self) -> None:
        """手动重置熔断器"""
        self._reset_to_closed()


class CircuitBreakerRegistry:
    """熔断器注册中心

    为所有 Agent 统一管理熔断器实例。
    """

    def __init__(self, default_config: CircuitBreakerConfig | None = None) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = default_config or CircuitBreakerConfig()
        self._logger = logger.bind(service="circuit_breaker_registry")

    def get(self, agent_id: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        if agent_id not in self._breakers:
            self._breakers[agent_id] = CircuitBreaker(agent_id, self._default_config)
        return self._breakers[agent_id]

    def remove(self, agent_id: str) -> None:
        """移除熔断器"""
        self._breakers.pop(agent_id, None)

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器统计"""
        return {
            agent_id: breaker.get_stats()
            for agent_id, breaker in self._breakers.items()
        }

    def reset_all(self) -> None:
        """重置所有熔断器"""
        for breaker in self._breakers.values():
            breaker.reset()
