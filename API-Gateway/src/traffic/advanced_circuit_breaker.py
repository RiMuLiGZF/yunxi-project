"""
云汐 API 网关 - 增强版熔断器

在现有熔断器基础上增加：
1. 慢请求熔断（响应时间超过阈值也算失败）
2. 失败率自适应阈值
3. 熔断恢复的渐进式恢复策略
4. 半开状态探测
"""
import time
import asyncio
import logging
from enum import Enum
from typing import Dict, Optional, Callable, Awaitable, Any
from collections import defaultdict, deque
from dataclasses import dataclass, field


logger = logging.getLogger("yunxi-gateway.advanced_circuit_breaker")


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class SlowRequestConfig:
    """慢请求配置

    Attributes:
        enabled: 是否启用慢请求熔断
        threshold_ms: 慢请求阈值（毫秒）
        failure_weight: 慢请求的失败权重（0-1，0.5 表示慢请求算半个失败）
    """
    enabled: bool = False
    threshold_ms: float = 5000.0  # 5秒
    failure_weight: float = 0.5


@dataclass
class AdaptiveThresholdConfig:
    """自适应阈值配置

    Attributes:
        enabled: 是否启用自适应阈值
        min_threshold: 最小失败次数阈值
        max_threshold: 最大失败次数阈值
        window_size: 统计窗口大小（请求数）
        target_failure_rate: 目标失败率（0-1）
    """
    enabled: bool = False
    min_threshold: int = 3
    max_threshold: int = 20
    window_size: int = 100
    target_failure_rate: float = 0.1  # 10%


@dataclass
class ProgressiveRecoveryConfig:
    """渐进式恢复配置

    Attributes:
        enabled: 是否启用渐进式恢复
        steps: 恢复步数
        step_percentages: 每步允许的流量百分比
        step_interval: 每步的时间间隔（秒）
    """
    enabled: bool = False
    steps: int = 5
    step_percentages: list = field(default_factory=lambda: [10, 25, 50, 75, 100])
    step_interval: int = 30  # 秒


class AdvancedCircuitBreaker:
    """增强版熔断器

    增强特性：
    - 慢请求熔断
    - 自适应失败率阈值
    - 渐进式恢复
    - 半开状态探测
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_time: int = 30,
        slow_request: Optional[SlowRequestConfig] = None,
        adaptive: Optional[AdaptiveThresholdConfig] = None,
        progressive_recovery: Optional[ProgressiveRecoveryConfig] = None,
    ):
        self._default_failure_threshold = failure_threshold
        self._default_recovery_time = recovery_time
        self._slow_request_config = slow_request or SlowRequestConfig()
        self._adaptive_config = adaptive or AdaptiveThresholdConfig()
        self._progressive_config = progressive_recovery or ProgressiveRecoveryConfig()

        # 按模块的状态
        self._states: Dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self._failure_counts: Dict[str, float] = defaultdict(float)
        self._last_failure_time: Dict[str, float] = defaultdict(float)
        self._half_open_attempts: Dict[str, int] = defaultdict(int)
        self._half_open_successes: Dict[str, int] = defaultdict(int)
        self._last_state_change: Dict[str, float] = defaultdict(float)

        # 自适应阈值相关
        self._failure_windows: Dict[str, deque] = {}
        self._dynamic_thresholds: Dict[str, int] = {}

        # 渐进式恢复相关
        self._recovery_step: Dict[str, int] = {}
        self._last_step_time: Dict[str, float] = {}

        # 统计
        self._stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total_requests": 0,
            "success_count": 0,
            "failure_count": 0,
            "slow_request_count": 0,
            "rejected_count": 0,
            "state_changes": 0,
        })

        self._lock = asyncio.Lock()

    async def can_execute(self, key: str) -> bool:
        """检查是否可以执行请求"""
        async with self._lock:
            state = self._states[key]
            stats = self._stats[key]
            stats["total_requests"] += 1

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.OPEN:
                now = time.time()
                if now - self._last_failure_time[key] >= self._default_recovery_time:
                    # 切换到半开状态
                    self._states[key] = CircuitState.HALF_OPEN
                    self._half_open_attempts[key] = 0
                    self._half_open_successes[key] = 0
                    self._last_state_change[key] = now
                    stats["state_changes"] += 1

                    if self._progressive_config.enabled:
                        self._recovery_step[key] = 0
                        self._last_step_time[key] = now

                    logger.info(f"[AdvCB] {key}: OPEN -> HALF_OPEN")
                    return True

                stats["rejected_count"] += 1
                return False

            if state == CircuitState.HALF_OPEN:
                max_attempts = self._get_half_open_max_requests(key)
                if self._half_open_attempts[key] < max_attempts:
                    self._half_open_attempts[key] += 1
                    return True
                stats["rejected_count"] += 1
                return False

            return True

    def _get_half_open_max_requests(self, key: str) -> int:
        """获取半开状态最大请求数（渐进式恢复）"""
        if not self._progressive_config.enabled:
            return 3

        step = self._recovery_step.get(key, 0)
        percentages = self._progressive_config.step_percentages
        if step >= len(percentages):
            step = len(percentages) - 1

        # 基础 3 个请求，按比例增加
        return max(1, int(3 * percentages[step] / 100))

    def _check_progressive_recovery_step(self, key: str):
        """检查是否需要推进渐进式恢复步骤"""
        if not self._progressive_config.enabled:
            return

        now = time.time()
        last_step = self._last_step_time.get(key, 0)
        current_step = self._recovery_step.get(key, 0)

        if (now - last_step >= self._progressive_config.step_interval
                and current_step < self._progressive_config.steps - 1):
            self._recovery_step[key] = current_step + 1
            self._last_step_time[key] = now
            logger.info(
                f"[AdvCB] {key}: progressive recovery step "
                f"{current_step} -> {current_step + 1}"
            )

    async def record_success(self, key: str, latency_ms: float = 0):
        """记录请求成功"""
        async with self._lock:
            stats = self._stats[key]
            stats["success_count"] += 1

            # 自适应阈值：记录成功
            self._record_adaptive(key, True)

            # 慢请求检查（成功但慢也记录）
            if (self._slow_request_config.enabled
                    and latency_ms > self._slow_request_config.threshold_ms):
                stats["slow_request_count"] += 1
                # 慢请求按权重计入失败
                self._failure_counts[key] += self._slow_request_config.failure_weight

            if self._states[key] == CircuitState.HALF_OPEN:
                self._half_open_successes[key] += 1
                max_requests = self._get_half_open_max_requests(key)

                if self._progressive_config.enabled:
                    self._check_progressive_recovery_step(key)
                    # 渐进式恢复：最后一步全部成功才关闭
                    current_step = self._recovery_step.get(key, 0)
                    if (current_step >= self._progressive_config.steps - 1
                            and self._half_open_successes[key] >= max_requests):
                        self._close_circuit(key)
                else:
                    if self._half_open_successes[key] >= max_requests:
                        self._close_circuit(key)
            else:
                # 关闭状态下，成功则减少失败计数
                self._failure_counts[key] = max(0, self._failure_counts[key] - 0.1)

    def _close_circuit(self, key: str):
        """关闭熔断器"""
        self._states[key] = CircuitState.CLOSED
        self._failure_counts[key] = 0
        self._half_open_attempts[key] = 0
        self._half_open_successes[key] = 0
        self._last_state_change[key] = time.time()
        self._stats[key]["state_changes"] += 1
        self._recovery_step.pop(key, None)
        self._last_step_time.pop(key, None)
        logger.info(f"[AdvCB] {key}: HALF_OPEN -> CLOSED")

    async def record_failure(self, key: str, latency_ms: float = 0):
        """记录请求失败"""
        async with self._lock:
            stats = self._stats[key]
            stats["failure_count"] += 1

            # 自适应阈值：记录失败
            self._record_adaptive(key, False)

            self._failure_counts[key] += 1
            self._last_failure_time[key] = time.time()

            state = self._states[key]

            if state == CircuitState.HALF_OPEN:
                # 半开状态下失败，立即回到熔断状态
                self._states[key] = CircuitState.OPEN
                self._half_open_attempts[key] = 0
                self._half_open_successes[key] = 0
                self._last_state_change[key] = time.time()
                stats["state_changes"] += 1
                logger.warning(f"[AdvCB] {key}: HALF_OPEN -> OPEN (probe failed)")

            elif state == CircuitState.CLOSED:
                threshold = self._get_effective_threshold(key)
                if self._failure_counts[key] >= threshold:
                    self._states[key] = CircuitState.OPEN
                    self._half_open_attempts[key] = 0
                    self._half_open_successes[key] = 0
                    self._last_state_change[key] = time.time()
                    stats["state_changes"] += 1
                    logger.warning(
                        f"[AdvCB] {key}: CLOSED -> OPEN "
                        f"(failures={self._failure_counts[key]:.1f}, threshold={threshold})"
                    )

    def _get_effective_threshold(self, key: str) -> int:
        """获取当前有效失败阈值（考虑自适应）"""
        if not self._adaptive_config.enabled:
            return self._default_failure_threshold

        return self._dynamic_thresholds.get(key, self._default_failure_threshold)

    def _record_adaptive(self, key: str, success: bool):
        """记录自适应阈值统计"""
        if not self._adaptive_config.enabled:
            return

        if key not in self._failure_windows:
            self._failure_windows[key] = deque(maxlen=self._adaptive_config.window_size)
            self._dynamic_thresholds[key] = self._default_failure_threshold

        window = self._failure_windows[key]
        window.append(1 if not success else 0)

        # 窗口满了才计算
        if len(window) >= self._adaptive_config.window_size:
            failure_rate = sum(window) / len(window)
            config = self._adaptive_config

            # 根据失败率调整阈值
            if failure_rate > config.target_failure_rate * 1.5:
                # 失败率过高，降低阈值（更容易熔断）
                new_threshold = max(
                    config.min_threshold,
                    self._dynamic_thresholds.get(key, self._default_failure_threshold) - 1
                )
            elif failure_rate < config.target_failure_rate * 0.5:
                # 失败率很低，提高阈值（更难熔断）
                new_threshold = min(
                    config.max_threshold,
                    self._dynamic_thresholds.get(key, self._default_failure_threshold) + 1
                )
            else:
                new_threshold = self._dynamic_thresholds.get(key, self._default_failure_threshold)

            self._dynamic_thresholds[key] = new_threshold

    async def record_request(self, key: str, success: bool, latency_ms: float = 0):
        """记录请求结果（统一入口）"""
        if success:
            await self.record_success(key, latency_ms)
        else:
            await self.record_failure(key, latency_ms)

    async def reset(self, key: str) -> bool:
        """手动重置熔断器"""
        async with self._lock:
            if key in self._states:
                self._states[key] = CircuitState.CLOSED
                self._failure_counts[key] = 0
                self._half_open_attempts[key] = 0
                self._half_open_successes[key] = 0
                self._last_state_change[key] = time.time()
                self._stats[key]["state_changes"] += 1
                self._recovery_step.pop(key, None)
                self._last_step_time.pop(key, None)
                return True
            return False

    def get_state(self, key: str) -> CircuitState:
        """获取熔断器状态"""
        return self._states[key]

    def get_stats(self) -> Dict[str, Any]:
        """获取所有熔断器统计"""
        result = {}
        for key in set(list(self._states.keys())):
            state = self._states.get(key, CircuitState.CLOSED)
            stats = self._stats.get(key, {})
            now = time.time()

            result[key] = {
                "state": state.value,
                "failure_count": self._failure_counts.get(key, 0),
                "effective_threshold": self._get_effective_threshold(key),
                "recovery_time_seconds": self._default_recovery_time,
                "last_state_change": self._last_state_change.get(key, 0),
                "time_since_state_change": round(
                    now - self._last_state_change.get(key, now), 2
                ),
                "half_open_attempts": self._half_open_attempts.get(key, 0),
                "half_open_successes": self._half_open_successes.get(key, 0),
                "total_requests": stats.get("total_requests", 0),
                "success_count": stats.get("success_count", 0),
                "failure_count_total": stats.get("failure_count", 0),
                "slow_request_count": stats.get("slow_request_count", 0),
                "rejected_count": stats.get("rejected_count", 0),
                "state_changes": stats.get("state_changes", 0),
                "slow_request_enabled": self._slow_request_config.enabled,
                "adaptive_enabled": self._adaptive_config.enabled,
                "progressive_recovery_enabled": self._progressive_config.enabled,
            }

            if self._progressive_config.enabled and state == CircuitState.HALF_OPEN:
                result[key]["recovery_step"] = self._recovery_step.get(key, 0)
                result[key]["recovery_step_percent"] = (
                    self._progressive_config.step_percentages[
                        self._recovery_step.get(key, 0)
                    ]
                )

        return result

    def configure_slow_request(self, config: SlowRequestConfig):
        """配置慢请求熔断"""
        self._slow_request_config = config

    def configure_adaptive(self, config: AdaptiveThresholdConfig):
        """配置自适应阈值"""
        self._adaptive_config = config

    def configure_progressive_recovery(self, config: ProgressiveRecoveryConfig):
        """配置渐进式恢复"""
        self._progressive_config = config
