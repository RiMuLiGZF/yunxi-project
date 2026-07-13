"""
云汐内核 V4 - 熔断器系统

灵感来源：Netflix Hystrix / Resilience4j Circuit Breaker Pattern

保护 Agent 集群免受级联故障影响。
当某个 Agent 在滑动窗口内的错误率或慢调用比例达到阈值时，熔断器打开，
后续请求快速失败，给故障 Agent 恢复时间。

状态机：
CLOSED    -> 正常通行，记录失败率
OPEN      -> 快速失败，拒绝请求
HALF_OPEN -> 允许试探请求，验证是否恢复
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────
#  枚举与配置
# ─────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    """熔断器状态"""

    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断
    HALF_OPEN = "half_open" # 半开（试探）


@dataclass
class CircuitBreakerConfig:
    """熔断器配置

    新版配置基于滑动窗口统计错误率与慢调用比例。
    旧版 ``failure_threshold`` 字段保留以兼容旧代码，
    其值会映射为最小调用次数与错误率阈值的等效关系。
    """

    # ── 滑动窗口 ────────────────────────────────────
    sliding_window_size: float = 60.0
    """滑动窗口大小（秒），默认 60 秒"""

    minimum_call_count: int = 10
    """触发熔断所需的最小调用次数（样本数不足时不熔断）"""

    failure_rate_threshold: float = 0.5
    """错误率阈值 (0-1)，超过则熔断，默认 50%"""

    # ── 慢调用 ──────────────────────────────────────
    slow_call_duration_threshold: float = 5.0
    """慢调用阈值（秒），超过此时间的调用被视为慢调用"""

    slow_call_rate_threshold: float = 0.8
    """慢调用比例阈值 (0-1)，超过则熔断，默认 80%"""

    enable_slow_call: bool = True
    """是否启用慢调用熔断"""

    # ── 恢复与半开 ──────────────────────────────────
    recovery_timeout: float = 30.0
    """熔断后等待恢复时间（秒）"""

    half_open_max_calls: int = 3
    """半开状态允许的最大试探次数"""

    success_threshold: int = 2
    """半开状态连续成功次数，达到则恢复 CLOSED"""

    # ── 排除规则 ────────────────────────────────────
    exclusion_statuses: set[str] = field(default_factory=lambda: {"not_found"})
    """不计入失败的错误状态"""

    # ── 兼容旧版字段 ────────────────────────────────
    failure_threshold: int = 5
    """旧版连续失败次数（兼容字段）。
    当未显式设置 minimum_call_count / failure_rate_threshold 时，
    以此值作为最小调用次数下限参考。"""

    def __post_init__(self) -> None:
        """字段初始化后校验与兼容映射"""
        if not (0 < self.sliding_window_size <= 3600):
            raise ValueError("sliding_window_size 必须在 (0, 3600] 秒之间")
        if self.minimum_call_count < 1:
            raise ValueError("minimum_call_count 必须 >= 1")
        if not (0 < self.failure_rate_threshold <= 1):
            raise ValueError("failure_rate_threshold 必须在 (0, 1] 之间")
        if self.slow_call_duration_threshold <= 0:
            raise ValueError("slow_call_duration_threshold 必须 > 0")
        if not (0 < self.slow_call_rate_threshold <= 1):
            raise ValueError("slow_call_rate_threshold 必须在 (0, 1] 之间")
        # 兼容旧字段：若 failure_threshold 大于 minimum_call_count，
        # 则以 failure_threshold 作为最小调用次数下限
        if self.failure_threshold > self.minimum_call_count:
            self.minimum_call_count = self.failure_threshold


# ─────────────────────────────────────────────────────────
#  滑动窗口统计
# ─────────────────────────────────────────────────────────

@dataclass
class _Bucket:
    """单个时间片桶"""

    timestamp: float
    """桶起始时间戳（秒）"""

    total_calls: int = 0
    """总调用数"""

    failure_calls: int = 0
    """失败调用数"""

    slow_calls: int = 0
    """慢调用数"""

    total_response_time: float = 0.0
    """总响应时间（秒），用于计算平均响应时间"""


class SlidingWindowMetrics:
    """基于时间片（bucket）的滑动窗口指标统计

    窗口以 1 秒为粒度划分为若干桶，新的调用结果落入当前桶，
    过期的桶在每次查询时自动淘汰。

    Args:
        window_size: 滑动窗口大小（秒）
        bucket_interval: 每个桶的时间跨度（秒），默认 1 秒
    """

    def __init__(self, window_size: float, bucket_interval: float = 1.0) -> None:
        self._window_size = window_size
        self._bucket_interval = bucket_interval
        self._buckets: deque[_Bucket] = deque()
        self._lock = asyncio.Lock()

    # ── 内部工具 ─────────────────────────────────────

    def _current_bucket_key(self, now: float) -> float:
        """计算当前时间对应的桶起始时间戳"""
        return (now // self._bucket_interval) * self._bucket_interval

    def _evict_expired(self, now: float) -> None:
        """淘汰过期桶（必须在持有锁或单线程上下文中调用）"""
        cutoff = now - self._window_size
        while self._buckets and self._buckets[0].timestamp < cutoff:
            self._buckets.popleft()

    def _get_or_create_bucket(self, now: float) -> _Bucket:
        """获取或创建当前时间对应的桶"""
        key = self._current_bucket_key(now)
        if self._buckets and self._buckets[-1].timestamp == key:
            return self._buckets[-1]
        bucket = _Bucket(timestamp=key)
        self._buckets.append(bucket)
        return bucket

    # ── 记录调用 ─────────────────────────────────────

    async def record(self, success: bool, response_time: float, is_slow: bool) -> None:
        """记录一次调用结果

        Args:
            success: 是否成功（False 视为失败）
            response_time: 调用耗时（秒）
            is_slow: 是否为慢调用
        """
        now = time.time()
        async with self._lock:
            self._evict_expired(now)
            bucket = self._get_or_create_bucket(now)
            bucket.total_calls += 1
            if not success:
                bucket.failure_calls += 1
            if is_slow:
                bucket.slow_calls += 1
            bucket.total_response_time += response_time

    def record_sync(self, success: bool, response_time: float, is_slow: bool) -> None:
        """同步版本的 record（用于非协程上下文，调用方自行保证并发安全）

        .. note::
            此方法不获取锁，仅在确定单线程访问时使用。
        """
        now = time.time()
        self._evict_expired(now)
        bucket = self._get_or_create_bucket(now)
        bucket.total_calls += 1
        if not success:
            bucket.failure_calls += 1
        if is_slow:
            bucket.slow_calls += 1
        bucket.total_response_time += response_time

    # ── 聚合查询 ─────────────────────────────────────

    async def get_snapshot(self) -> dict[str, Any]:
        """获取当前窗口的统计快照

        Returns:
            包含 total_calls / failure_calls / slow_calls /
            failure_rate / slow_call_rate / avg_response_time_ms /
            window_start_time 的字典
        """
        now = time.time()
        async with self._lock:
            self._evict_expired(now)
            return self._compute_snapshot(now)

    def get_snapshot_sync(self) -> dict[str, Any]:
        """同步版本的 get_snapshot"""
        now = time.time()
        self._evict_expired(now)
        return self._compute_snapshot(now)

    def _compute_snapshot(self, now: float) -> dict[str, Any]:
        """根据当前桶数据计算统计快照"""
        total = 0
        failures = 0
        slow = 0
        total_rt = 0.0
        window_start = now - self._window_size

        for bucket in self._buckets:
            total += bucket.total_calls
            failures += bucket.failure_calls
            slow += bucket.slow_calls
            total_rt += bucket.total_response_time

        failure_rate = failures / total if total > 0 else 0.0
        slow_rate = slow / total if total > 0 else 0.0
        avg_rt_ms = (total_rt / total * 1000.0) if total > 0 else 0.0

        return {
            "total_calls": total,
            "failure_calls": failures,
            "slow_calls": slow,
            "failure_rate": failure_rate,
            "slow_call_rate": slow_rate,
            "avg_response_time_ms": avg_rt_ms,
            "window_start_time": window_start,
        }

    async def reset(self) -> None:
        """清空所有统计数据"""
        async with self._lock:
            self._buckets.clear()

    def reset_sync(self) -> None:
        """同步版本的 reset"""
        self._buckets.clear()


# ─────────────────────────────────────────────────────────
#  异常
# ─────────────────────────────────────────────────────────

class CircuitBreakerError(Exception):
    """熔断器拦截异常"""

    def __init__(self, agent_id: str, state: CircuitState, message: str = "") -> None:
        self.agent_id = agent_id
        self.state = state
        super().__init__(message or f"Circuit breaker is {state.value} for agent '{agent_id}'")


# ─────────────────────────────────────────────────────────
#  熔断器主体
# ─────────────────────────────────────────────────────────

class CircuitBreaker:
    """熔断器

    为单个 Agent 提供故障保护。

    核心特性：
    - 基于滑动窗口的错误率统计
    - 慢调用比例熔断（可选）
    - 状态变更事件回调 / 消息总线发布
    - 异步安全（asyncio.Lock）

    Args:
        agent_id: 熔断器标识（通常为 Agent ID）
        config: 熔断器配置
        on_state_change: 状态变更回调函数
            签名: (name: str, old_state: CircuitState, new_state: CircuitState, reason: str) -> None
        message_bus: 消息总线对象，需支持 publish(event_name, payload) 方法
    """

    def __init__(
        self,
        agent_id: str,
        config: CircuitBreakerConfig | None = None,
        on_state_change: Callable[[str, CircuitState, CircuitState, str], None] | None = None,
        message_bus: Any = None,
    ) -> None:
        self.agent_id = agent_id
        self.config = config or CircuitBreakerConfig()
        self._on_state_change_cb = on_state_change
        self._message_bus = message_bus

        self.state = CircuitState.CLOSED

        # 滑动窗口统计
        self._metrics = SlidingWindowMetrics(
            window_size=self.config.sliding_window_size,
            bucket_interval=1.0,
        )

        # 半开状态计数
        self._half_open_calls: int = 0
        self._half_open_successes: int = 0

        # 最后一次失败时间（用于 OPEN -> HALF_OPEN 转换）
        self._last_failure_time: float | None = None

        # 异步锁
        self._lock = asyncio.Lock()

        self._logger = logger.bind(service="circuit_breaker", agent_id=agent_id)

    # ── 核心执行接口 ──────────────────────────────────

    async def call(self, func: Callable[[], Awaitable[Any]], context: dict[str, Any] | None = None) -> Any:
        """在熔断器保护下执行函数

        Args:
            func: 被保护的异步函数
            context: 可选上下文

        Returns:
            func 的返回值

        Raises:
            CircuitBreakerError: 熔断器处于 OPEN 状态或半开试探已达上限
        """
        async with self._lock:
            self._transition_state()

            if self.state == CircuitState.OPEN:
                raise CircuitBreakerError(self.agent_id, self.state)

            if self.state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerError(
                        self.agent_id, self.state, "Half-open max calls exceeded"
                    )
                self._half_open_calls += 1

        # 实际执行（不在锁内，避免阻塞其他调用）
        start_time = time.time()
        try:
            result = await func()
            response_time = time.time() - start_time
            await self._on_success(response_time)
            return result
        except Exception as exc:
            response_time = time.time() - start_time
            await self._on_failure(exc, response_time)
            raise

    # ── 状态转换 ──────────────────────────────────────

    def _transition_state(self) -> None:
        """根据时间自动转换状态（调用方必须持有锁）"""
        if self.state == CircuitState.OPEN:
            if self._last_failure_time is None:
                return
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN, "recovery_timeout")
                self._half_open_calls = 0
                self._half_open_successes = 0

    def _transition_to(self, new_state: CircuitState, reason: str) -> None:
        """执行状态转换并发布事件（调用方必须持有锁）"""
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        self._logger.info(
            "circuit_breaker_state_changed",
            old_state=old_state.value,
            new_state=new_state.value,
            reason=reason,
        )
        # 回调
        if self._on_state_change_cb is not None:
            try:
                self._on_state_change_cb(self.agent_id, old_state, new_state, reason)
            except Exception:
                self._logger.exception("state_change_callback_error")
        # 消息总线
        if self._message_bus is not None:
            try:
                event_payload = {
                    "name": self.agent_id,
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "reason": reason,
                    "timestamp": time.time(),
                }
                self._message_bus.publish("circuit_breaker.state_changed", event_payload)
            except Exception:
                self._logger.exception("message_bus_publish_error")

    # ── 成功 / 失败回调 ───────────────────────────────

    async def _on_success(self, response_time: float) -> None:
        """成功回调

        Args:
            response_time: 调用耗时（秒）
        """
        is_slow = self._is_slow_call(response_time)
        await self._metrics.record(success=True, response_time=response_time, is_slow=is_slow)

        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED, "half_open_success_threshold")

    async def _on_failure(self, exc: Exception, response_time: float) -> None:
        """失败回调

        Args:
            exc: 异常对象
            response_time: 调用耗时（秒）
        """
        # 排除不计入的错误
        if self._is_excluded(exc):
            return

        is_slow = self._is_slow_call(response_time)
        await self._metrics.record(success=False, response_time=response_time, is_slow=is_slow)

        async with self._lock:
            self._last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # 半开状态失败，直接重新熔断
                self._transition_to(CircuitState.OPEN, "half_open_failure")
            elif self.state == CircuitState.CLOSED:
                if self._should_open_circuit():
                    reason = self._get_open_reason()
                    self._transition_to(CircuitState.OPEN, reason)

    # ── 熔断判断 ──────────────────────────────────────

    def _should_open_circuit(self) -> bool:
        """判断是否应该打开熔断器（调用方必须持有锁）"""
        snapshot = self._metrics.get_snapshot_sync()
        total = snapshot["total_calls"]
        if total < self.config.minimum_call_count:
            return False
        # 错误率阈值
        if snapshot["failure_rate"] >= self.config.failure_rate_threshold:
            return True
        # 慢调用比例阈值
        if self.config.enable_slow_call and snapshot["slow_call_rate"] >= self.config.slow_call_rate_threshold:
            return True
        return False

    def _get_open_reason(self) -> str:
        """获取触发熔断的原因描述（调用方必须持有锁）"""
        snapshot = self._metrics.get_snapshot_sync()
        reasons = []
        if snapshot["failure_rate"] >= self.config.failure_rate_threshold:
            reasons.append(
                f"failure_rate={snapshot['failure_rate']:.2%} >= {self.config.failure_rate_threshold:.2%}"
            )
        if (
            self.config.enable_slow_call
            and snapshot["slow_call_rate"] >= self.config.slow_call_rate_threshold
        ):
            reasons.append(
                f"slow_call_rate={snapshot['slow_call_rate']:.2%} >= {self.config.slow_call_rate_threshold:.2%}"
            )
        return "; ".join(reasons) if reasons else "threshold_exceeded"

    # ── 辅助方法 ──────────────────────────────────────

    def _is_slow_call(self, response_time: float) -> bool:
        """判断是否为慢调用"""
        if not self.config.enable_slow_call:
            return False
        return response_time >= self.config.slow_call_duration_threshold

    def _is_excluded(self, exc: Exception) -> bool:
        """判断异常是否应被排除（不计入失败）"""
        error_str = str(exc).lower()
        for excluded in self.config.exclusion_statuses:
            if excluded.lower() in error_str:
                return True
        return False

    # ── 状态查询 ──────────────────────────────────────

    def get_state(self) -> CircuitState:
        """获取当前状态

        .. note::
            此方法为同步调用，在获取状态前会尝试基于时间进行状态转换。
            并发场景下状态可能随时变化，仅作参考。
        """
        # 同步方式尝试转换（单线程简单操作，无需锁）
        if self.state == CircuitState.OPEN and self._last_failure_time is not None:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout:
                # 通过锁安全地转换
                # 注意：在同步方法中无法获取 asyncio.Lock，这里做尽力而为的判断
                # 实际转换以 call() 中的为准
                pass
        return self.state

    async def get_stats(self) -> dict[str, Any]:
        """获取统计信息

        Returns:
            包含熔断器状态、配置、滑动窗口指标等完整信息的字典
        """
        async with self._lock:
            self._transition_state()
            snapshot = await self._metrics.get_snapshot()

        return {
            "agent_id": self.agent_id,
            "state": self.state.value,
            # 窗口指标
            "total_calls": snapshot["total_calls"],
            "failure_rate": snapshot["failure_rate"],
            "slow_call_rate": snapshot["slow_call_rate"],
            "avg_response_time_ms": snapshot["avg_response_time_ms"],
            "window_start_time": snapshot["window_start_time"],
            # 详细计数
            "failure_calls": snapshot["failure_calls"],
            "slow_calls": snapshot["slow_calls"],
            # 半开状态
            "half_open_calls": self._half_open_calls,
            "half_open_successes": self._half_open_successes,
            "last_failure_time": self._last_failure_time,
            # 配置
            "config": {
                "sliding_window_size": self.config.sliding_window_size,
                "minimum_call_count": self.config.minimum_call_count,
                "failure_rate_threshold": self.config.failure_rate_threshold,
                "slow_call_duration_threshold": self.config.slow_call_duration_threshold,
                "slow_call_rate_threshold": self.config.slow_call_rate_threshold,
                "enable_slow_call": self.config.enable_slow_call,
                "recovery_timeout": self.config.recovery_timeout,
                "half_open_max_calls": self.config.half_open_max_calls,
                "success_threshold": self.config.success_threshold,
                "failure_threshold": self.config.failure_threshold,
            },
        }

    async def reset(self) -> None:
        """手动重置熔断器（异步版本）"""
        async with self._lock:
            await self._metrics.reset()
            self._transition_to(CircuitState.CLOSED, "manual_reset")
            self._half_open_calls = 0
            self._half_open_successes = 0
            self._last_failure_time = None


# ─────────────────────────────────────────────────────────
#  注册中心
# ─────────────────────────────────────────────────────────

class CircuitBreakerRegistry:
    """熔断器注册中心

    为所有 Agent 统一管理熔断器实例。

    Args:
        default_config: 默认熔断器配置
        on_state_change: 全局状态变更回调
        message_bus: 全局消息总线
    """

    def __init__(
        self,
        default_config: CircuitBreakerConfig | None = None,
        on_state_change: Callable[[str, CircuitState, CircuitState, str], None] | None = None,
        message_bus: Any = None,
    ) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = default_config or CircuitBreakerConfig()
        self._on_state_change = on_state_change
        self._message_bus = message_bus
        self._lock = asyncio.Lock()
        self._logger = logger.bind(service="circuit_breaker_registry")

    async def get(self, agent_id: str) -> CircuitBreaker:
        """获取或创建熔断器

        Args:
            agent_id: 熔断器标识

        Returns:
            CircuitBreaker 实例
        """
        async with self._lock:
            if agent_id not in self._breakers:
                self._breakers[agent_id] = CircuitBreaker(
                    agent_id,
                    self._default_config,
                    on_state_change=self._on_state_change,
                    message_bus=self._message_bus,
                )
                self._logger.info("circuit_breaker_created", agent_id=agent_id)
            return self._breakers[agent_id]

    def get_sync(self, agent_id: str) -> CircuitBreaker:
        """同步版本的 get（调用方自行保证并发安全）"""
        if agent_id not in self._breakers:
            self._breakers[agent_id] = CircuitBreaker(
                agent_id,
                self._default_config,
                on_state_change=self._on_state_change,
                message_bus=self._message_bus,
            )
            self._logger.info("circuit_breaker_created", agent_id=agent_id)
        return self._breakers[agent_id]

    async def remove(self, agent_id: str) -> None:
        """移除熔断器"""
        async with self._lock:
            self._breakers.pop(agent_id, None)

    async def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有熔断器统计"""
        result: dict[str, dict[str, Any]] = {}
        # 先在锁内复制引用
        async with self._lock:
            items = list(self._breakers.items())
        for agent_id, breaker in items:
            result[agent_id] = await breaker.get_stats()
        return result

    async def reset_all(self) -> None:
        """重置所有熔断器"""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.reset()
