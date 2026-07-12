"""
潮汐状态机

持续监测系统资源水位，判定当前潮汐阶段。
带滞回控制，防止频繁切换。
"""

from __future__ import annotations

import time
import threading
from collections import deque
from typing import Optional

import structlog

from .models import TidePhase, TideTrend, TideSnapshot, TideStrategy

logger = structlog.get_logger(__name__)


class TideStateMachine:
    """潮汐状态机

    持续监测资源水位，输出当前潮汐阶段和趋势。
    """

    def __init__(self, strategy: Optional[TideStrategy] = None):
        self._strategy = strategy or TideStrategy()
        self._current_phase: TidePhase = TidePhase.SLACK
        self._current_trend: TideTrend = TideTrend.STABLE
        self._current_level: float = 50.0
        self._last_phase_change_time: float = time.time()

        # 历史水位（用于趋势计算）
        self._level_history: deque = deque(maxlen=60)  # 60 个样本
        self._snapshot_history: deque = deque(maxlen=120)  # 2 分钟快照

        self._lock = threading.Lock()

    def update_strategy(self, strategy: TideStrategy):
        """更新策略"""
        with self._lock:
            self._strategy = strategy

    def update(
        self,
        gpu_memory_percent: float = 0.0,
        gpu_util_percent: float = 0.0,
        cpu_percent: float = 0.0,
        memory_percent: float = 0.0,
    ) -> TideSnapshot:
        """更新资源水位，计算潮汐状态

        Args:
            gpu_memory_percent: GPU 显存使用率 (0-100)
            gpu_util_percent: GPU 计算使用率 (0-100)
            cpu_percent: CPU 使用率 (0-100)
            memory_percent: 内存使用率 (0-100)

        Returns:
            潮汐快照
        """
        with self._lock:
            # 计算综合资源水位
            level = self._compute_resource_level(
                gpu_memory_percent, gpu_util_percent, cpu_percent, memory_percent
            )

            # 记录历史
            self._level_history.append((time.time(), level))

            # 计算趋势
            trend = self._compute_trend()

            # 计算新相位（带滞回和最小持续时间）
            now = time.time()
            elapsed = now - self._last_phase_change_time

            if elapsed >= self._strategy.min_phase_duration_sec:
                new_phase = self._strategy.get_phase_for_level(level, self._current_phase)
                if new_phase != self._current_phase:
                    logger.info(
                        f"潮汐阶段切换: {self._current_phase.value} -> {new_phase.value} "
                        f"(水位={level:.1f}%)"
                    )
                    self._current_phase = new_phase
                    self._last_phase_change_time = now

            # 更新趋势
            self._current_trend = trend
            self._current_level = level

            # 生成快照
            snapshot = TideSnapshot(
                phase=self._current_phase,
                trend=self._current_trend,
                resource_level=level,
                gpu_memory_level=gpu_memory_percent,
                gpu_util_level=gpu_util_percent,
                cpu_level=cpu_percent,
                memory_level=memory_percent,
                concurrency_multiplier=self._strategy.get_concurrency_multiplier(self._current_phase),
                min_priority=self._strategy.get_min_priority(self._current_phase),
            )

            self._snapshot_history.append(snapshot)
            return snapshot

    def _compute_resource_level(
        self,
        gpu_memory: float,
        gpu_util: float,
        cpu: float,
        memory: float,
    ) -> float:
        """计算综合资源水位

        根据策略的主指标加权计算。
        水位越高表示资源越紧张。
        """
        metric = self._strategy.primary_metric

        if metric == "gpu_memory":
            # GPU 显存为主，GPU 利用率为辅
            level = gpu_memory * 0.7 + gpu_util * 0.3
        elif metric == "gpu_util":
            level = gpu_util * 0.7 + gpu_memory * 0.3
        elif metric == "combined":
            # 综合 GPU + CPU + 内存
            level = max(
                gpu_memory * 0.4 + gpu_util * 0.2,
                cpu * 0.2 + memory * 0.2,
            )
        else:
            level = gpu_memory

        return max(0.0, min(100.0, level))

    def _compute_trend(self) -> TideTrend:
        """计算潮汐趋势（基于最近的水位变化）"""
        if len(self._level_history) < 5:
            return TideTrend.STABLE

        # 比较最近 5 个点和前 5 个点的平均值
        recent = [l for _, l in list(self._level_history)[-5:]]
        earlier = [l for _, l in list(self._level_history)[-10:-5]] if len(self._level_history) >= 10 else recent

        recent_avg = sum(recent) / len(recent)
        earlier_avg = sum(earlier) / len(earlier) if earlier else recent_avg

        diff = recent_avg - earlier_avg
        threshold = 2.0  # 2% 变化阈值

        if diff > threshold:
            return TideTrend.RISING
        elif diff < -threshold:
            return TideTrend.FALLING
        else:
            return TideTrend.STABLE

    @property
    def current_phase(self) -> TidePhase:
        return self._current_phase

    @property
    def current_trend(self) -> TideTrend:
        return self._current_trend

    @property
    def current_level(self) -> float:
        return self._current_level

    @property
    def strategy(self) -> TideStrategy:
        return self._strategy

    def get_snapshot_history(self, limit: int = 30) -> list:
        """获取历史快照"""
        return list(self._snapshot_history)[-limit:]

    def get_level_history(self, limit: int = 30) -> list:
        """获取水位历史"""
        return list(self._level_history)[-limit:]
