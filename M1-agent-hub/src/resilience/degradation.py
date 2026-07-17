"""
云汐内核 - 多 Agent 集群调度系统
降级策略模块

[V11.5] 5 级渐进式降级策略体系，在系统压力过大或依赖故障时自动降级，
保证核心服务可用。级别越高，关闭的功能越多：

L0_NORMAL (0)    - 正常：所有功能全开
L1_LIGHT (1)     - 轻度降级：关闭非核心功能（反思引擎、OTLP、详细追踪、非核心指标）
L2_MODERATE (2)  - 中度降级：关闭联邦调度，仅用内部 Agent
L3_HEAVY (3)     - 重度降级：仅保留核心对话功能
L4_MINIMAL (4)   - 最小可用：仅健康检查和基础响应

使用方式：
    from src.resilience.degradation import feature_enabled, get_degradation_manager

    if feature_enabled("reflection_engine"):
        await run_reflection()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 降级级别定义 ────────────────────────────────────────


class DegradationLevel(IntEnum):
    """降级级别枚举

    级别越高表示降级越严重，关闭的功能越多。
    采用 IntEnum 以便直接比较大小。
    """

    L0_NORMAL = 0
    """正常：所有功能全开"""

    L1_LIGHT = 1
    """轻度降级：关闭非核心功能"""

    L2_MODERATE = 2
    """中度降级：关闭联邦调度，仅用内部 Agent"""

    L3_HEAVY = 3
    """重度降级：仅保留核心对话功能"""

    L4_MINIMAL = 4
    """最小可用：仅健康检查和基础响应"""


# ── 内置功能与最低可用级别映射 ──────────────────────────
#
# key: 功能名称（字符串标识）
# value: 该功能可用的最低降级级别（即当前级别 <= 此值时功能启用）
#
# 例如：reflection_engine 的最低级别是 L0_NORMAL，
# 意味着一旦进入 L1 及以上，反思引擎就会被关闭。

_BUILTIN_FEATURE_LEVELS: dict[str, DegradationLevel] = {
    # ── L1 关闭：非核心功能 ──
    "reflection_engine": DegradationLevel.L0_NORMAL,
    "otlp_export": DegradationLevel.L0_NORMAL,
    "detailed_tracing": DegradationLevel.L0_NORMAL,
    "non_core_metrics": DegradationLevel.L0_NORMAL,

    # ── L2 关闭：联邦调度与外部调用 ──
    "federation_scheduler": DegradationLevel.L1_LIGHT,
    "external_agent_call": DegradationLevel.L1_LIGHT,
    "cost_optimizer": DegradationLevel.L1_LIGHT,

    # ── L3 关闭：工作流、克隆池、插件、记忆 ──
    "workflow_engine": DegradationLevel.L2_MODERATE,
    "agent_clone_pool": DegradationLevel.L2_MODERATE,
    "plugin_system": DegradationLevel.L2_MODERATE,
    "memory_system": DegradationLevel.L2_MODERATE,

    # ── L4 保留：健康检查、存活探针、基础 /ready ──
    "health_check": DegradationLevel.L4_MINIMAL,
    "liveness_probe": DegradationLevel.L4_MINIMAL,
    "readiness_probe": DegradationLevel.L4_MINIMAL,
    "core_dialogue": DegradationLevel.L3_HEAVY,
}


# ── 自动降级阈值配置 ────────────────────────────────────


@dataclass
class AutoDegradationConfig:
    """自动降级触发阈值配置

    所有阈值均可在运行时调整。
    """

    # 内存使用率阈值（百分比）
    memory_threshold_l1: float = 80.0
    memory_threshold_l2: float = 90.0

    # 错误率阈值（百分比 0-100）
    error_rate_threshold_l1: float = 20.0
    error_rate_threshold_l2: float = 50.0

    # 错误率持续时间阈值（秒），超过该持续时间才触发
    error_rate_duration_threshold: float = 30.0

    # 平均响应时间阈值（毫秒）
    response_time_threshold_l1_ms: float = 5000.0
    response_time_threshold_l2_ms: float = 10000.0

    # 响应时间持续时间阈值（秒）
    response_time_duration_threshold: float = 30.0

    # 自动恢复冷却时间（秒），避免频繁切换
    recovery_cooldown_seconds: float = 60.0

    # 自动降级冷却时间（秒），避免抖动
    degradation_cooldown_seconds: float = 10.0


# ── 降级管理器 ──────────────────────────────────────────


class DegradationManager:
    """降级管理器

    核心管理类，负责维护当前降级级别、功能启用状态、自动降级触发逻辑
    以及降级历史记录。

    线程/协程安全：所有状态变更操作均通过 asyncio.Lock 保护。

    Attributes:
        current_level: 当前降级级别
        config: 自动降级配置
    """

    _instance: DegradationManager | None = None
    _instance_lock: asyncio.Lock | None = None

    MAX_HISTORY_SIZE: int = 100
    """降级历史最大保留条数"""

    def __init__(self) -> None:
        self._lock: asyncio.Lock = asyncio.Lock()
        self.current_level: DegradationLevel = DegradationLevel.L0_NORMAL

        # 功能注册表：feature_name -> min_level（功能可用的最低级别）
        self._feature_levels: dict[str, DegradationLevel] = dict(_BUILTIN_FEATURE_LEVELS)

        # 当前禁用的功能集合（由 current_level 推导，缓存以加速查询）
        self._disabled_features: set[str] = set()

        # 自动降级开关
        self._auto_trigger_enabled: bool = True

        # 自动降级配置
        self.config: AutoDegradationConfig = AutoDegradationConfig()

        # 降级历史：(timestamp, level, reason)
        self._level_history: list[tuple[float, DegradationLevel, str]] = []

        # 上次级别变更时间（用于冷却判断）
        self._last_level_change_time: float = 0.0

        # 指标采样历史，用于判断持续时间
        # key: metric_name, value: list of (timestamp, value)
        self._metric_history: dict[str, list[tuple[float, float]]] = {}

        # 上次检查时间
        self._last_auto_check_time: float = 0.0

        # 消息总线实例（惰性获取）
        self._bus: Any = None

        self._logger: structlog.stdlib.BoundLogger = logger.bind(
            service="degradation_manager"
        )

        # 初始化禁用功能集合
        self._recompute_disabled_features()

        # 记录初始状态到历史
        self._append_history(DegradationLevel.L0_NORMAL, "initialization")

    # ── 单例模式 ──────────────────────────────────────

    @classmethod
    def get_instance(cls) -> DegradationManager:
        """获取 DegradationManager 单例（同步版本）

        Returns:
            DegradationManager 全局单例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 级别管理 ──────────────────────────────────────

    async def set_level(
        self,
        level: DegradationLevel,
        reason: str = "",
        source: str = "manual",
    ) -> None:
        """设置降级级别

        如果新级别与当前级别相同，则忽略。
        级别变更时会：
        1. 重新计算禁用功能集合
        2. 记录历史
        3. 发布 degradation.level_changed 事件到消息总线
        4. 记录日志

        Args:
            level: 目标降级级别
            reason: 降级/恢复原因说明
            source: 触发来源（manual / auto / external）
        """
        async with self._lock:
            await self._set_level_internal(level, reason, source)

    async def _set_level_internal(
        self,
        level: DegradationLevel,
        reason: str,
        source: str,
    ) -> None:
        """内部设置级别（调用方需持有 _lock）"""
        if level == self.current_level:
            return

        old_level = self.current_level
        self.current_level = level
        self._recompute_disabled_features()
        self._last_level_change_time = time.time()

        self._append_history(level, reason)

        direction = "degraded" if level > old_level else "recovered"
        self._logger.warning(
            f"degradation_level_{direction}",
            old_level=old_level.name,
            new_level=level.name,
            reason=reason,
            source=source,
            disabled_count=len(self._disabled_features),
        )

        # 异步发布事件（不等待完成，避免阻塞）
        await self._publish_level_changed_event(old_level, level, reason, source)

    def _recompute_disabled_features(self) -> None:
        """根据当前级别重新计算禁用功能集合

        功能可用条件：current_level <= feature_min_level
        即：功能的最低可用级别 >= 当前级别时，功能启用。
        反过来，当前级别 > 功能最低级别时，功能被禁用。
        """
        self._disabled_features = {
            feature
            for feature, min_level in self._feature_levels.items()
            if self.current_level > min_level
        }

    def _append_history(self, level: DegradationLevel, reason: str) -> None:
        """追加降级历史记录（调用方需持有 _lock）"""
        self._level_history.append((time.time(), level, reason))
        # 保持历史记录不超过最大条数
        if len(self._level_history) > self.MAX_HISTORY_SIZE:
            self._level_history = self._level_history[-self.MAX_HISTORY_SIZE:]

    # ── 功能查询 ──────────────────────────────────────

    def is_feature_enabled(self, feature: str) -> bool:
        """检查功能是否启用

        未注册的功能默认视为启用（保守策略，避免误关新功能）。

        Args:
            feature: 功能名称

        Returns:
            True 表示功能启用，False 表示功能已被降级禁用
        """
        if feature not in self._feature_levels:
            return True
        return feature not in self._disabled_features

    def register_feature(
        self,
        feature: str,
        min_level: DegradationLevel,
    ) -> None:
        """注册功能及其最低可用级别

        如果功能已存在，更新其最低级别。
        注册后会重新计算当前禁用集合。

        Args:
            feature: 功能名称
            min_level: 该功能可用的最低降级级别
                     （当前级别 <= min_level 时功能启用）
        """
        self._feature_levels[feature] = min_level
        self._recompute_disabled_features()
        self._logger.debug(
            "feature_registered",
            feature=feature,
            min_level=min_level.name,
            currently_enabled=self.current_level <= min_level,
        )

    def unregister_feature(self, feature: str) -> None:
        """注销功能

        Args:
            feature: 功能名称
        """
        if feature in self._feature_levels:
            del self._feature_levels[feature]
            self._disabled_features.discard(feature)
            self._logger.debug("feature_unregistered", feature=feature)

    # ── 自动降级开关 ──────────────────────────────────

    def enable_auto_trigger(self) -> None:
        """启用自动降级触发"""
        self._auto_trigger_enabled = True
        self._logger.info("auto_trigger_enabled")

    def disable_auto_trigger(self) -> None:
        """禁用自动降级触发"""
        self._auto_trigger_enabled = False
        self._logger.info("auto_trigger_disabled")

    @property
    def auto_trigger_enabled(self) -> bool:
        """自动降级是否启用"""
        return self._auto_trigger_enabled

    # ── 自动降级检测 ──────────────────────────────────

    async def check_auto_trigger(self, metrics: dict[str, Any]) -> DegradationLevel:
        """根据系统指标判断是否需要自动降级或恢复

        支持渐进式降级和逐级恢复（带冷却时间，避免抖动）。

        metrics 字典可包含以下键：
            - memory_usage_percent: float - 内存使用率（百分比 0-100）
            - error_rate: float - 错误率（百分比 0-100）
            - avg_response_time_ms: float - 平均响应时间（毫秒）
            - dependencies_health: dict - 核心依赖健康状态
              （如 {"database": True, "message_bus": True}）

        Args:
            metrics: 系统指标字典

        Returns:
            当前降级级别（可能已变更）
        """
        if not self._auto_trigger_enabled:
            return self.current_level

        async with self._lock:
            now = time.time()
            self._last_auto_check_time = now

            # 记录指标历史（用于持续时间判断）
            self._record_metric_history(metrics, now)

            # 计算目标降级级别（取所有触发条件中的最高级别）
            target_level = self._compute_target_level(metrics, now)

            # 应用冷却时间策略
            if target_level != self.current_level:
                if target_level > self.current_level:
                    # 降级：检查降级冷却
                    if now - self._last_level_change_time < self.config.degradation_cooldown_seconds:
                        self._logger.debug(
                            "degradation_cooldown_active",
                            current_level=self.current_level.name,
                            target_level=target_level.name,
                            cooldown_remaining=(
                                self.config.degradation_cooldown_seconds
                                - (now - self._last_level_change_time)
                            ),
                        )
                        return self.current_level
                else:
                    # 恢复：检查恢复冷却
                    if now - self._last_level_change_time < self.config.recovery_cooldown_seconds:
                        self._logger.debug(
                            "recovery_cooldown_active",
                            current_level=self.current_level.name,
                            target_level=target_level.name,
                            cooldown_remaining=(
                                self.config.recovery_cooldown_seconds
                                - (now - self._last_level_change_time)
                            ),
                        )
                        return self.current_level

                # 执行级别变更（每次只变一级，避免跳变）
                if target_level > self.current_level:
                    next_level = DegradationLevel(int(self.current_level) + 1)
                else:
                    next_level = DegradationLevel(int(self.current_level) - 1)

                # 确保不超过目标级别
                if target_level > self.current_level and next_level > target_level:
                    next_level = target_level
                elif target_level < self.current_level and next_level < target_level:
                    next_level = target_level

                reason = self._build_reason(target_level, metrics)
                await self._set_level_internal(next_level, reason, source="auto")

            return self.current_level

    def _record_metric_history(self, metrics: dict[str, Any], now: float) -> None:
        """记录指标历史（用于持续时间判断）

        仅记录数值型指标。调用方需持有 _lock。
        """
        numeric_keys = ("memory_usage_percent", "error_rate", "avg_response_time_ms")
        for key in numeric_keys:
            value = metrics.get(key)
            if value is not None and isinstance(value, (int, float)):
                if key not in self._metric_history:
                    self._metric_history[key] = []
                self._metric_history[key].append((now, float(value)))

                # 清理过期数据（保留 5 分钟内的数据）
                cutoff = now - 300.0
                self._metric_history[key] = [
                    (t, v) for t, v in self._metric_history[key] if t >= cutoff
                ]

    def _compute_target_level(
        self,
        metrics: dict[str, Any],
        now: float,
    ) -> DegradationLevel:
        """计算目标降级级别（取所有触发条件中的最高级别）

        调用方需持有 _lock。
        """
        target = DegradationLevel.L0_NORMAL

        # 1. 内存使用率
        mem = metrics.get("memory_usage_percent")
        if mem is not None and isinstance(mem, (int, float)):
            if mem >= self.config.memory_threshold_l2:
                target = max(target, DegradationLevel.L2_MODERATE)
            elif mem >= self.config.memory_threshold_l1:
                target = max(target, DegradationLevel.L1_LIGHT)

        # 2. 错误率（需持续超过阈值）
        err = metrics.get("error_rate")
        if err is not None and isinstance(err, (int, float)):
            if self._is_metric_sustained(
                "error_rate",
                self.config.error_rate_threshold_l2,
                self.config.error_rate_duration_threshold,
                now,
                above=True,
            ):
                target = max(target, DegradationLevel.L2_MODERATE)
            elif self._is_metric_sustained(
                "error_rate",
                self.config.error_rate_threshold_l1,
                self.config.error_rate_duration_threshold,
                now,
                above=True,
            ):
                target = max(target, DegradationLevel.L1_LIGHT)

        # 3. 平均响应时间（需持续超过阈值）
        rt = metrics.get("avg_response_time_ms")
        if rt is not None and isinstance(rt, (int, float)):
            if self._is_metric_sustained(
                "avg_response_time_ms",
                self.config.response_time_threshold_l2_ms,
                self.config.response_time_duration_threshold,
                now,
                above=True,
            ):
                target = max(target, DegradationLevel.L2_MODERATE)
            elif self._is_metric_sustained(
                "avg_response_time_ms",
                self.config.response_time_threshold_l1_ms,
                self.config.response_time_duration_threshold,
                now,
                above=True,
            ):
                target = max(target, DegradationLevel.L1_LIGHT)

        # 4. 核心依赖不可用（DB / 总线）
        deps = metrics.get("dependencies_health")
        if deps is not None and isinstance(deps, dict):
            critical_deps = ("database", "message_bus", "db")
            unavailable_count = 0
            for dep in critical_deps:
                if dep in deps:
                    health = deps[dep]
                    if isinstance(health, bool) and not health:
                        unavailable_count += 1
                    elif isinstance(health, str) and health.lower() in ("down", "unhealthy", "false"):
                        unavailable_count += 1
            if unavailable_count > 0:
                # 核心依赖不可用直接触发 L3
                target = max(target, DegradationLevel.L3_HEAVY)

        return target

    def _is_metric_sustained(
        self,
        metric_key: str,
        threshold: float,
        duration: float,
        now: float,
        above: bool = True,
    ) -> bool:
        """检查指标是否持续超过/低于阈值

        Args:
            metric_key: 指标名称
            threshold: 阈值
            duration: 持续时间（秒）
            now: 当前时间
            above: True 表示检查是否持续高于阈值，False 表示低于

        Returns:
            True 表示满足持续条件
        """
        history = self._metric_history.get(metric_key, [])
        if not history:
            return False

        cutoff = now - duration
        # 检查从 cutoff 到 now 期间的所有采样点是否都满足条件
        recent = [(t, v) for t, v in history if t >= cutoff]

        # 如果最早的数据点还没到 cutoff 时间，说明数据不够
        if not recent or recent[0][0] > cutoff + 1.0:
            # 数据覆盖时间不足，但我们可以放宽：
            # 如果有至少 duration/2 的数据满足条件，也视为满足（保守策略）
            min_points = 3
            if len(recent) < min_points:
                return False

        if above:
            return all(v >= threshold for _, v in recent)
        else:
            return all(v <= threshold for _, v in recent)

    def _build_reason(
        self,
        target_level: DegradationLevel,
        metrics: dict[str, Any],
    ) -> str:
        """构建降级/恢复原因描述"""
        reasons: list[str] = []

        mem = metrics.get("memory_usage_percent")
        if mem is not None:
            reasons.append(f"memory={mem:.1f}%")

        err = metrics.get("error_rate")
        if err is not None:
            reasons.append(f"error_rate={err:.1f}%")

        rt = metrics.get("avg_response_time_ms")
        if rt is not None:
            reasons.append(f"avg_rt={rt:.0f}ms")

        deps = metrics.get("dependencies_health")
        if deps:
            unhealthy = [k for k, v in deps.items() if isinstance(v, bool) and not v]
            if unhealthy:
                reasons.append(f"unhealthy_deps={','.join(unhealthy)}")

        base = "auto_degraded" if target_level > self.current_level else "auto_recovered"
        detail = "; ".join(reasons) if reasons else "metrics_normalized"
        return f"{base}: {detail}"

    # ── 消息总线集成 ──────────────────────────────────

    async def _publish_level_changed_event(
        self,
        old_level: DegradationLevel,
        new_level: DegradationLevel,
        reason: str,
        source: str,
    ) -> None:
        """发布降级级别变更事件到消息总线

        使用惰性导入避免循环依赖。如果消息总线不可用，静默失败。

        Args:
            old_level: 旧级别
            new_level: 新级别
            reason: 变更原因
            source: 触发来源
        """
        try:
            bus = await self._get_bus()
            if bus is None:
                return

            # 惰性导入 BusMessage
            from src.tools.interfaces import BusMessage

            message = BusMessage(
                topic="degradation.level_changed",
                sender="degradation_manager",
                msg_type="system.config_change",
                payload={
                    "old_level": old_level.name,
                    "old_level_value": int(old_level),
                    "new_level": new_level.name,
                    "new_level_value": int(new_level),
                    "reason": reason,
                    "source": source,
                    "timestamp": time.time(),
                },
                priority=3,  # 较高优先级
                ttl=60,
            )
            await bus.publish(message)
        except Exception as exc:
            # 事件发布失败不影响降级逻辑
            self._logger.warning(
                "degradation_event_publish_failed",
                error=str(exc),
                old_level=old_level.name,
                new_level=new_level.name,
            )

    async def _get_bus(self) -> Any:
        """惰性获取消息总线实例

        Returns:
            MessageBus 实例，不可用返回 None
        """
        if self._bus is not None:
            if self._bus is False:
                return None
            return self._bus

        try:
            from src.core.message_bus import MessageBus

            self._bus = await MessageBus.get_instance()
            return self._bus
        except ImportError:
            self._bus = False  # type: ignore[assignment]
            self._logger.warning("message_bus_unavailable_for_degradation_events")
            return None
        except Exception as exc:
            self._bus = False  # type: ignore[assignment]
            self._logger.warning(
                "message_bus_init_failed",
                error=str(exc),
            )
            return None

    # ── 状态查询 ──────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取降级状态统计

        Returns:
            包含当前级别、禁用功能列表、自动降级状态等信息的字典
        """
        enabled_features = [
            f for f in self._feature_levels
            if f not in self._disabled_features
        ]
        return {
            "current_level": self.current_level.name,
            "current_level_value": int(self.current_level),
            "auto_trigger_enabled": self._auto_trigger_enabled,
            "total_features": len(self._feature_levels),
            "enabled_features": sorted(enabled_features),
            "disabled_features": sorted(self._disabled_features),
            "enabled_count": len(enabled_features),
            "disabled_count": len(self._disabled_features),
            "last_level_change_time": self._last_level_change_time,
            "last_auto_check_time": self._last_auto_check_time,
            "history_total": len(self._level_history),
            "config": {
                "memory_threshold_l1": self.config.memory_threshold_l1,
                "memory_threshold_l2": self.config.memory_threshold_l2,
                "error_rate_threshold_l1": self.config.error_rate_threshold_l1,
                "error_rate_threshold_l2": self.config.error_rate_threshold_l2,
                "response_time_threshold_l1_ms": self.config.response_time_threshold_l1_ms,
                "response_time_threshold_l2_ms": self.config.response_time_threshold_l2_ms,
                "recovery_cooldown_seconds": self.config.recovery_cooldown_seconds,
                "degradation_cooldown_seconds": self.config.degradation_cooldown_seconds,
            },
        }

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取降级历史记录（最新的在前）

        Args:
            limit: 返回记录数上限

        Returns:
            降级历史记录列表，每条包含 timestamp、level、reason
        """
        history = self._level_history[-limit:]
        return [
            {
                "timestamp": ts,
                "level": level.name,
                "level_value": int(level),
                "reason": reason,
            }
            for ts, level, reason in reversed(history)
        ]

    def get_readiness_status(self) -> str:
        """获取就绪状态（供健康检查模块使用）

        L3 及以上降级时返回 "degraded"。

        Returns:
            "up" / "degraded" / "down"
        """
        if self.current_level >= DegradationLevel.L3_HEAVY:
            return "degraded"
        return "up"


# ── 模块级便捷函数 ──────────────────────────────────────


def feature_enabled(feature_name: str) -> bool:
    """检查功能是否启用（模块级便捷函数）

    供业务代码快速检查，无需获取管理器实例。
    未注册的功能默认返回 True（保守策略）。

    Args:
        feature_name: 功能名称

    Returns:
        True 表示功能启用，False 表示已被降级禁用

    Example:
        >>> from degradation import feature_enabled
        >>> if feature_enabled("reflection_engine"):
        ...     await run_reflection()
    """
    manager = DegradationManager.get_instance()
    return manager.is_feature_enabled(feature_name)


def get_degradation_manager() -> DegradationManager:
    """获取全局降级管理器实例

    Returns:
        DegradationManager 单例
    """
    return DegradationManager.get_instance()


def get_degradation_level() -> DegradationLevel:
    """获取当前降级级别

    Returns:
        当前 DegradationLevel
    """
    return DegradationManager.get_instance().current_level
