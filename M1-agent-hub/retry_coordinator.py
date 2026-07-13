"""
云汐内核 - 重试统一协调器（RetryCoordinator）

解决评审 P2-011：CircuitBreaker / DLQ / Ledger 三者的重试策略冲突。

核心设计：
- 维护全局 task_id -> retry_state 映射
- 所有重试请求必须经过 RetryCoordinator.check_can_retry()
- 返回是否允许重试、建议延迟、建议策略（immediate/exponential/abandon）
- 与 CircuitBreaker 和 DLQ 联动：
    - 如果 CircuitBreaker 对应 Agent 处于 open 状态，拒绝重试
    - 如果 DLQ 中已达到 max_retries，建议 abandon
    - Ledger 的 replan 评估仅在 abandon 时触发
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# [V9.6] 按错误类型自适应退避配置
ADAPTIVE_BACKOFF_PROFILES: dict[str, dict[str, float]] = {
    "timeout": {"base_delay": 0.5, "max_delay": 5.0, "multiplier": 1.5},
    "network": {"base_delay": 1.0, "max_delay": 30.0, "multiplier": 2.0},
    "oom": {"base_delay": 5.0, "max_delay": 120.0, "multiplier": 2.0},
    "circuit_breaker": {"base_delay": 10.0, "max_delay": 60.0, "multiplier": 1.0},
    "unknown": {"base_delay": 1.0, "max_delay": 60.0, "multiplier": 2.0},
}


def _classify_error(error: str) -> str:
    """[V9.6] 根据错误消息分类错误类型"""
    lower_err = error.lower()
    if any(k in lower_err for k in ["timeout", "timed out", "asyncio.timeout"]):
        return "timeout"
    if any(k in lower_err for k in ["oom", "out of memory", "cuda", "memory"]):
        return "oom"
    if any(k in lower_err for k in ["circuit breaker", "circuit_breaker"]):
        return "circuit_breaker"
    if any(k in lower_err for k in ["connection", "network", "dns", "refused"]):
        return "network"
    return "unknown"


class RetryStrategy(str, Enum):
    """重试策略"""
    IMMEDIATE = "immediate"        # 立即重试
    EXPONENTIAL = "exponential"    # 指数退避重试
    ABANDON = "abandon"            # 放弃重试（转 DLQ 或 Ledger replan）


@dataclass
class RetryDecision:
    """重试决策结果"""
    allowed: bool
    strategy: RetryStrategy
    delay_seconds: float = 0.0
    reason: str = ""
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class RetryState:
    """单个任务的重试状态"""

    task_id: str
    retry_count: int = 0
    max_retries: int = 3
    first_failure_time: float = field(default_factory=time.time)
    last_retry_time: float = 0.0
    last_error: str = ""
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    # 基础退避时间（秒）
    base_delay: float = 1.0
    # 最大退避时间（秒）
    max_delay: float = 60.0
    # 退避乘数
    backoff_multiplier: float = 2.0
    # [V9.6] 错误类型历史
    error_history: list[str] = field(default_factory=list)
    # [V9.6] EMA 学习的乘数
    learned_multiplier: float = 2.0
    # [P1-4-1] 最后更新时间，用于 TTL 淘汰
    last_updated: float = field(default_factory=time.time)


class RetryCoordinator:
    """重试统一协调器

    协调 CircuitBreaker / DLQ / Ledger 三者的重试策略，
    确保全局一致的重试决策。

    使用方式：
        coordinator = RetryCoordinator()
        decision = coordinator.check_can_retry(task_id, agent_id)
        if decision.allowed:
            await asyncio.sleep(decision.delay_seconds)
            # 执行重试
        else:
            # 转入 DLQ 或触发 Ledger replan
    """

    # [V9.6] 自适应退避配置：不同错误类型使用不同的基础延迟
    _ERROR_PROFILES: dict[str, dict[str, float]] = {
        "timeout": {"base_delay": 0.5, "backoff_multiplier": 2.0},
        "oom": {"base_delay": 5.0, "backoff_multiplier": 2.0},
        "network": {"base_delay": 1.0, "backoff_multiplier": 2.0},
        "unknown": {"base_delay": 1.0, "backoff_multiplier": 2.0},
    }

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        max_states: int = 10000,
        state_ttl_seconds: float = 86400.0,
    ) -> None:
        self._states: dict[str, RetryState] = {}
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_multiplier = backoff_multiplier
        # [P1-4-1] 容量与 TTL 治理
        self._max_states = max_states
        self._state_ttl_seconds = state_ttl_seconds
        self._total_expired: int = 0
        """累计过期清理的状态数"""
        self._total_evicted: int = 0
        """累计容量淘汰的状态数"""
        self._logger = logger.bind(service="retry_coordinator")

    def check_can_retry(
        self,
        task_id: str,
        agent_id: str = "",
        circuit_breaker: Any | None = None,
        dlq_retry_count: int | None = None,
        dlq_max_retries: int = 3,
    ) -> RetryDecision:
        """检查是否允许重试

        统一协调三方的重试判断：
        1. 本地 retry_state 计数器
        2. CircuitBreaker 状态（如提供）
        3. DLQ 重试计数（如提供）

        Args:
            task_id: 任务 ID
            agent_id: 目标 Agent ID（用于 CircuitBreaker 检查）
            circuit_breaker: 可选的 CircuitBreaker 实例
            dlq_retry_count: DLQ 中已记录的重试次数
            dlq_max_retries: DLQ 最大重试次数

        Returns:
            RetryDecision: 重试决策
        """
        state = self._get_or_create_state(task_id)

        # 1. 检查 CircuitBreaker 状态
        if circuit_breaker is not None:
            cb_state = circuit_breaker.get_state()
            if cb_state.value == "open":
                self._logger.info(
                    "retry_rejected_circuit_breaker_open",
                    task_id=task_id,
                    agent_id=agent_id,
                )
                return RetryDecision(
                    allowed=False,
                    strategy=RetryStrategy.ABANDON,
                    reason=f"CircuitBreaker for '{agent_id}' is open",
                    retry_count=state.retry_count,
                    max_retries=state.max_retries,
                )

        # 2. 检查本地重试计数
        if state.retry_count >= state.max_retries:
            self._logger.info(
                "retry_rejected_max_retries",
                task_id=task_id,
                retry_count=state.retry_count,
                max_retries=state.max_retries,
            )
            return RetryDecision(
                allowed=False,
                strategy=RetryStrategy.ABANDON,
                reason=f"Max retries ({state.max_retries}) exceeded",
                retry_count=state.retry_count,
                max_retries=state.max_retries,
            )

        # 3. 检查 DLQ 重试计数（如果提供）
        if dlq_retry_count is not None and dlq_retry_count >= dlq_max_retries:
            self._logger.info(
                "retry_rejected_dlq_max_retries",
                task_id=task_id,
                dlq_retry_count=dlq_retry_count,
                dlq_max_retries=dlq_max_retries,
            )
            return RetryDecision(
                allowed=False,
                strategy=RetryStrategy.ABANDON,
                reason=f"DLQ max retries ({dlq_max_retries}) exceeded",
                retry_count=max(state.retry_count, dlq_retry_count),
                max_retries=state.max_retries,
            )

        # 4. 决定重试策略
        next_count = state.retry_count + 1

        # [V9.6] 自适应退避：根据错误类型选择配置
        error_type = _classify_error(state.last_error)
        profile = ADAPTIVE_BACKOFF_PROFILES.get(error_type, ADAPTIVE_BACKOFF_PROFILES["unknown"])

        if next_count == 1:
            # 第一次重试：立即执行
            strategy = RetryStrategy.IMMEDIATE
            delay = 0.0
        else:
            # 后续重试：指数退避
            strategy = RetryStrategy.EXPONENTIAL
            # 使用 EMA 学习后的乘数，混合配置乘数
            effective_multiplier = (profile["multiplier"] + state.learned_multiplier) / 2
            delay = min(
                profile["base_delay"] * (effective_multiplier ** (next_count - 1)),
                profile["max_delay"],
                self._max_delay,  # [V9.6] 实例级 max_delay 作为最终上限
            )

        return RetryDecision(
            allowed=True,
            strategy=strategy,
            delay_seconds=delay,
            reason=f"Retry #{next_count} with {strategy.value} strategy",
            retry_count=state.retry_count,
            max_retries=state.max_retries,
        )

    def record_retry(
        self,
        task_id: str,
        error: str = "",
    ) -> None:
        """记录一次重试

        Args:
            task_id: 任务 ID
            error: 失败原因
        """
        state = self._get_or_create_state(task_id)
        state.retry_count += 1
        state.last_retry_time = time.time()
        state.last_error = error
        # [V9.6] 记录错误类型
        error_type = _classify_error(error)
        state.error_history.append(error_type)
        # [V9.7] EMA 学习：连续失败后增加 learned_multiplier
        if state.retry_count >= 2:
            alpha = 0.3
            state.learned_multiplier = min(
                4.0,
                state.learned_multiplier * (1 + alpha * 0.3)
            )

        self._logger.info(
            "retry_recorded",
            task_id=task_id,
            retry_count=state.retry_count,
            max_retries=state.max_retries,
            error=error,
        )

    def record_success(self, task_id: str) -> None:
        """记录任务成功（清除重试状态）

        [V9.7] EMA 学习：成功后适当减小 learned_multiplier，
        因为当前退避可能过于保守。
        """
        state = self._states.get(task_id)
        if state is not None and state.retry_count > 0:
            # EMA 衰减：成功后减小乘数（alpha=0.3）
            alpha = 0.3
            state.learned_multiplier = max(
                1.1,
                state.learned_multiplier * (1 - alpha * 0.5)
            )
        self._states.pop(task_id, None)

    def get_state(self, task_id: str) -> RetryState | None:
        """获取任务的重试状态"""
        return self._states.get(task_id)

    def reset(self, task_id: str) -> None:
        """重置任务的重试状态"""
        self._states.pop(task_id, None)

    def reset_all(self) -> None:
        """重置所有重试状态"""
        self._states.clear()

    @classmethod
    def classify_error(cls, error: str) -> str:
        """[V9.6] 自适应错误分类：根据错误内容判断错误类型"""
        error_lower = error.lower()
        if "timeout" in error_lower or "timed out" in error_lower:
            return "timeout"
        if "oom" in error_lower or "out of memory" in error_lower or "memory" in error_lower and "exhausted" in error_lower:
            return "oom"
        if "network" in error_lower or "connection" in error_lower or "refused" in error_lower or "dns" in error_lower:
            return "network"
        return "unknown"

    @classmethod
    def adaptive_delay(cls, error_type: str, retry_count: int) -> float:
        """[V9.6] 自适应延迟计算：根据错误类型选择退避参数"""
        profile = cls._ERROR_PROFILES.get(error_type, cls._ERROR_PROFILES["unknown"])
        base = profile["base_delay"]
        mult = profile["backoff_multiplier"]
        return min(base * (mult ** retry_count), 60.0)

    def stats(self) -> dict[str, Any]:
        """获取协调器统计"""
        active_states = {
            tid: {
                "retry_count": s.retry_count,
                "max_retries": s.max_retries,
                "strategy": s.strategy.value,
                "last_error": s.last_error,
            }
            for tid, s in self._states.items()
        }
        return {
            "active_tasks": len(self._states),
            "max_states": self._max_states,
            "state_ttl_seconds": self._state_ttl_seconds,
            "total_expired": self._total_expired,
            "total_evicted": self._total_evicted,
            "max_retries": self._max_retries,
            "base_delay": self._base_delay,
            "max_delay": self._max_delay,
            "backoff_multiplier": self._backoff_multiplier,
            "tasks": active_states,
        }

    def cleanup_expired(self) -> int:
        """主动清理所有过期的重试状态（内存泄漏防护）。

        与惰性清理（每次 _get_or_create_state 时触发）不同，
        此方法可以被外部定时任务调用，确保即使长时间没有新任务，
        过期状态也能被及时回收。

        Returns:
            清理掉的过期状态数量
        """
        now = time.time()
        expired = [
            tid for tid, s in self._states.items()
            if now - s.last_updated > self._state_ttl_seconds
        ]
        for tid in expired:
            del self._states[tid]

        if expired:
            self._total_expired += len(expired)
            self._logger.info(
                "retry_coordinator_cleanup_expired",
                expired_count=len(expired),
                remaining=len(self._states),
            )

        return len(expired)

    def _get_or_create_state(self, task_id: str) -> RetryState:
        """获取或创建任务重试状态

        [P1-4-1] 增加容量上限与 TTL 过期清理，防止内存泄漏。
        """
        now = time.time()

        # 清理 TTL 过期的条目
        expired = [
            tid for tid, s in self._states.items()
            if now - s.last_updated > self._state_ttl_seconds
        ]
        for tid in expired:
            del self._states[tid]
        if expired:
            self._total_expired += len(expired)
            self._logger.debug(
                "retry_state_expired_cleanup",
                expired_count=len(expired),
                remaining=len(self._states),
            )

        # 容量淘汰：如果超过上限，淘汰最旧的条目（按 last_updated）
        if len(self._states) >= self._max_states:
            oldest_tid = min(self._states.items(), key=lambda x: x[1].last_updated)[0]
            del self._states[oldest_tid]
            self._total_evicted += 1
            self._logger.warning(
                "retry_state_capacity_eviction",
                evicted_task_id=oldest_tid,
                max_states=self._max_states,
            )

        if task_id not in self._states:
            self._states[task_id] = RetryState(
                task_id=task_id,
                max_retries=self._max_retries,
                base_delay=self._base_delay,
                max_delay=self._max_delay,
                backoff_multiplier=self._backoff_multiplier,
            )
        self._states[task_id].last_updated = now
        return self._states[task_id]
