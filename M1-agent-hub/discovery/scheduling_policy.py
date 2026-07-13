"""
云汐内核 V10.0 — 端云调度策略

根据设备状态（电量、网络）和任务复杂度，做出端云调度决策。

支持三种策略模式：
- LOCAL_FIRST：优先本地执行，仅在资源不足时回退到云端
- AUTO：综合负载评分自动决定
- CLOUD_FIRST：优先云端执行，在离线时缓存任务
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from shared_models import SchedulingDecision

logger = structlog.get_logger(__name__)


class SchedulingPolicy:
    """端云调度策略引擎

    根据当前设备状态（电量、网络可用性）与任务复杂度，
    基于所选策略模式输出调度决策。

    阈值可通过构造参数或属性配置。
    """

    def __init__(
        self,
        battery_threshold: float = 20.0,
        network_threshold: float = 100.0,
        default_strategy: SchedulingDecision = SchedulingDecision.AUTO,
    ) -> None:
        """
        Args:
            battery_threshold:   电量低于此值（%）时视为低电量
            network_threshold:   网络延迟高于此值（ms）时视为网络差
            default_strategy:     默认策略模式
        """
        self._battery_threshold: float = battery_threshold
        self._network_threshold: float = network_threshold
        self._strategy: SchedulingDecision = default_strategy
        self._decision: SchedulingDecision = SchedulingDecision.AUTO
        self._offline_tasks: list[dict[str, Any]] = []
        self._logger = logger.bind(component="scheduling_policy")

    @property
    def battery_threshold(self) -> float:
        """电量阈值"""
        return self._battery_threshold

    @battery_threshold.setter
    def battery_threshold(self, value: float) -> None:
        self._battery_threshold = max(0.0, min(100.0, value))

    @property
    def network_threshold(self) -> float:
        """网络延迟阈值"""
        return self._network_threshold

    @network_threshold.setter
    def network_threshold(self, value: float) -> None:
        self._network_threshold = max(0.0, value)

    @property
    def strategy(self) -> SchedulingDecision:
        """当前策略模式"""
        return self._strategy

    @strategy.setter
    def strategy(self, value: SchedulingDecision) -> None:
        self._strategy = value

    @property
    def last_decision(self) -> SchedulingDecision:
        """最近一次调度决策"""
        return self._decision

    @property
    def offline_tasks(self) -> list[dict[str, Any]]:
        """缓存的离线任务列表"""
        return list(self._offline_tasks)

    def decide(
        self,
        battery_pct: float,
        network_available: bool,
        task_complexity: float = 0.5,
    ) -> SchedulingDecision:
        """根据设备状态和任务复杂度做出调度决策

        Args:
            battery_pct:       当前电量百分比 (0.0-100.0)
            network_available: 网络是否可用
            task_complexity:   任务复杂度 (0.0-1.0)，1.0 为最复杂

        Returns:
            SchedulingDecision 调度决策枚举
        """
        if self._strategy == SchedulingDecision.LOCAL_FIRST:
            self._decision = self._decide_local_first(
                battery_pct=battery_pct,
                network_available=network_available,
                task_complexity=task_complexity,
            )
        elif self._strategy == SchedulingDecision.CLOUD_FIRST:
            self._decision = self._decide_cloud_first(
                battery_pct=battery_pct,
                network_available=network_available,
                task_complexity=task_complexity,
            )
        else:
            # AUTO 模式
            self._decision = self._decide_auto(
                battery_pct=battery_pct,
                network_available=network_available,
                task_complexity=task_complexity,
            )

        self._logger.info(
            "scheduling_decision",
            decision=self._decision.value,
            strategy=self._strategy.value,
            battery_pct=battery_pct,
            network_available=network_available,
            task_complexity=task_complexity,
        )

        return self._decision

    # ── LOCAL_FIRST 策略 ──────────────────────────────

    def _decide_local_first(
        self,
        battery_pct: float,
        network_available: bool,
        task_complexity: float,
    ) -> SchedulingDecision:
        """LOCAL_FIRST：优先本地执行

        条件满足时本地执行：
        - 电量 > 阈值
        - 网络可用（用于可能的云端回退）

        否则回退到云端。
        """
        if battery_pct > self._battery_threshold:
            # 电量充足，优先本地
            if network_available:
                return SchedulingDecision.LOCAL_FIRST
            else:
                # 电量充足但无网络，仍可本地执行
                # 但复杂度高的任务可能需要云端辅助
                if task_complexity > 0.8:
                    return SchedulingDecision.CLOUD_FIRST
                return SchedulingDecision.LOCAL_FIRST
        else:
            # 电量低，回退到云端（节省端侧资源）
            if network_available:
                return SchedulingDecision.CLOUD_FIRST
            else:
                # 电量低且无网络：尝试本地，但缓存任务
                return SchedulingDecision.LOCAL_FIRST

    # ── AUTO 策略 ─────────────────────────────────────

    def _decide_auto(
        self,
        battery_pct: float,
        network_available: bool,
        task_complexity: float,
    ) -> SchedulingDecision:
        """AUTO：综合评分决定

        根据电量、网络、任务复杂度综合判断。
        """
        # 低电量且网络可用 → 云端
        if battery_pct < self._battery_threshold and network_available:
            return SchedulingDecision.CLOUD_FIRST

        # 无网络 → 必须本地
        if not network_available:
            return SchedulingDecision.LOCAL_FIRST

        # 高复杂度 + 电量一般 → 云端
        if task_complexity > 0.7 and battery_pct < 50.0:
            return SchedulingDecision.CLOUD_FIRST

        # 其他情况 → 本地优先
        return SchedulingDecision.LOCAL_FIRST

    # ── CLOUD_FIRST 策略 ──────────────────────────────

    def _decide_cloud_first(
        self,
        battery_pct: float,
        network_available: bool,
        task_complexity: float,
    ) -> SchedulingDecision:
        """CLOUD_FIRST：优先云端执行

        在无网络时缓存离线任务，待网络恢复后重试。
        """
        if not network_available:
            # 缓存任务到离线队列
            offline_task = {
                "task_complexity": task_complexity,
                "battery_pct": battery_pct,
                "cached_at": time.time(),
            }
            self._offline_tasks.append(offline_task)
            self._logger.info(
                "task_cached_offline",
                offline_queue_size=len(self._offline_tasks),
            )
            return SchedulingDecision.LOCAL_FIRST

        # 网络可用，优先云端
        return SchedulingDecision.CLOUD_FIRST

    # ── 离线任务管理 ──────────────────────────────────

    def drain_offline_tasks(self) -> list[dict[str, Any]]:
        """取出所有缓存的离线任务

        在网络恢复后调用，将缓存的离线任务返回供重新调度。

        Returns:
            离线任务列表（调用后清空缓存）
        """
        tasks = list(self._offline_tasks)
        self._offline_tasks.clear()
        self._logger.info(
            "offline_tasks_drained",
            count=len(tasks),
        )
        return tasks

    def config_snapshot(self) -> dict[str, Any]:
        """返回策略配置快照"""
        return {
            "strategy": self._strategy.value,
            "battery_threshold": self._battery_threshold,
            "network_threshold": self._network_threshold,
            "last_decision": self._decision.value,
            "offline_tasks_count": len(self._offline_tasks),
        }
