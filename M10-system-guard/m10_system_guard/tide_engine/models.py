"""
潮汐引擎数据模型
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TidePhase(str, Enum):
    """潮汐阶段

    类比真实潮汐的四个阶段：
    - FLOOD（涨潮）：资源充裕，提升并发
    - SLACK（平潮）：资源平稳，标准运行
    - EBB（退潮）：资源紧张，收缩并发
    - LOW（枯潮）：资源枯竭，最低运行
    """
    FLOOD = "flood"      # 涨潮 - 高水位，资源充裕
    SLACK = "slack"      # 平潮 - 中水位，平稳运行
    EBB = "ebb"          # 退潮 - 低水位，资源收缩
    LOW = "low"          # 枯潮 - 极低水位，最小运行


class TideTrend(str, Enum):
    """潮汐趋势"""
    RISING = "rising"    # 上涨中
    FALLING = "falling"  # 下降中
    STABLE = "stable"    # 平稳


class MissionPriority(str, Enum):
    """任务优先级"""
    CRITICAL = "critical"  # 关键 - 枯潮也必须运行
    HIGH = "high"          # 高 - 退潮可运行
    NORMAL = "normal"      # 普通 - 平潮可运行
    LOW = "low"            # 低 - 仅涨潮运行
    BATCH = "batch"        # 批量 - 涨潮时批量执行


@dataclass
class TideStrategy:
    """潮汐策略配置

    定义各潮汐阶段的资源阈值和行为参数。
    """
    strategy_id: str = "default"
    name: str = "默认潮汐策略"
    description: str = "基于 GPU 显存使用率的潮汐调度策略"

    # 资源水位指标：gpu_memory / gpu_util / combined
    primary_metric: str = "gpu_memory"

    # 各阶段阈值（基于主指标的百分比 0-100）
    # 涨潮：水位 < flood_threshold，资源充裕
    flood_threshold: float = 30.0
    # 平潮：flood < 水位 < ebb，正常运行
    ebb_threshold: float = 70.0
    # 枯潮：水位 > low_threshold，资源严重不足
    low_threshold: float = 90.0

    # 各阶段并发系数（相对于基线并发数）
    flood_concurrency_multiplier: float = 2.0   # 涨潮 2 倍并发
    slack_concurrency_multiplier: float = 1.0   # 平潮 1 倍
    ebb_concurrency_multiplier: float = 0.5     # 退潮 0.5 倍
    low_concurrency_multiplier: float = 0.2     # 枯潮 0.2 倍

    # 各阶段允许的最低任务优先级
    flood_min_priority: MissionPriority = MissionPriority.BATCH
    slack_min_priority: MissionPriority = MissionPriority.NORMAL
    ebb_min_priority: MissionPriority = MissionPriority.HIGH
    low_min_priority: MissionPriority = MissionPriority.CRITICAL

    # GPU 显存超售比例（涨潮时允许适度超售）
    flood_gpu_oversell_ratio: float = 1.2
    slack_gpu_oversell_ratio: float = 1.0
    ebb_gpu_oversell_ratio: float = 0.8
    low_gpu_oversell_ratio: float = 0.5

    # 预测配置
    prediction_enabled: bool = True
    prediction_window_minutes: int = 30  # 预测未来 30 分钟
    prediction_samples: int = 60  # 使用 60 个历史样本

    # 滞回控制（防止频繁切换阶段）
    hysteresis_percent: float = 5.0  # 5% 滞回区间

    # 阶段最小持续时间（秒）
    min_phase_duration_sec: int = 120  # 至少持续 2 分钟

    def get_phase_for_level(self, level: float, current_phase: TidePhase = TidePhase.SLACK) -> TidePhase:
        """根据资源水位计算潮汐阶段（带滞回）

        Args:
            level: 资源使用率 (0-100)，越高越紧张
            current_phase: 当前阶段（用于滞回）

        Returns:
            潮汐阶段
        """
        h = self.hysteresis_percent

        # 根据当前阶段调整阈值（滞回）
        if current_phase == TidePhase.FLOOD:
            # 涨潮时，需要超过 ebb 阈值 + 滞回才切换
            if level > self.ebb_threshold + h:
                return TidePhase.EBB
            elif level > self.flood_threshold + h:
                return TidePhase.SLACK
            else:
                return TidePhase.FLOOD
        elif current_phase == TidePhase.EBB:
            # 退潮时，需要低于 flood - 滞回才升级
            if level < self.flood_threshold - h:
                return TidePhase.FLOOD
            elif level < self.ebb_threshold - h:
                return TidePhase.SLACK
            elif level > self.low_threshold + h:
                return TidePhase.LOW
            else:
                return TidePhase.EBB
        elif current_phase == TidePhase.LOW:
            # 枯潮时，需要明显改善才升级
            if level < self.ebb_threshold - h:
                return TidePhase.SLACK
            elif level < self.flood_threshold - h:
                return TidePhase.FLOOD
            else:
                return TidePhase.LOW
        else:  # SLACK
            if level < self.flood_threshold - h:
                return TidePhase.FLOOD
            elif level > self.ebb_threshold + h:
                return TidePhase.EBB
            else:
                return TidePhase.SLACK

    def get_concurrency_multiplier(self, phase: TidePhase) -> float:
        """获取阶段对应的并发系数"""
        return {
            TidePhase.FLOOD: self.flood_concurrency_multiplier,
            TidePhase.SLACK: self.slack_concurrency_multiplier,
            TidePhase.EBB: self.ebb_concurrency_multiplier,
            TidePhase.LOW: self.low_concurrency_multiplier,
        }.get(phase, 1.0)

    def get_min_priority(self, phase: TidePhase) -> MissionPriority:
        """获取阶段允许的最低优先级"""
        return {
            TidePhase.FLOOD: self.flood_min_priority,
            TidePhase.SLACK: self.slack_min_priority,
            TidePhase.EBB: self.ebb_min_priority,
            TidePhase.LOW: self.low_min_priority,
        }.get(phase, MissionPriority.NORMAL)

    def get_oversell_ratio(self, phase: TidePhase) -> float:
        """获取阶段的显存超售比例"""
        return {
            TidePhase.FLOOD: self.flood_gpu_oversell_ratio,
            TidePhase.SLACK: self.slack_gpu_oversell_ratio,
            TidePhase.EBB: self.ebb_gpu_oversell_ratio,
            TidePhase.LOW: self.low_gpu_oversell_ratio,
        }.get(phase, 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "primary_metric": self.primary_metric,
            "flood_threshold": self.flood_threshold,
            "ebb_threshold": self.ebb_threshold,
            "low_threshold": self.low_threshold,
            "flood_concurrency_multiplier": self.flood_concurrency_multiplier,
            "slack_concurrency_multiplier": self.slack_concurrency_multiplier,
            "ebb_concurrency_multiplier": self.ebb_concurrency_multiplier,
            "low_concurrency_multiplier": self.low_concurrency_multiplier,
            "prediction_enabled": self.prediction_enabled,
            "prediction_window_minutes": self.prediction_window_minutes,
            "hysteresis_percent": self.hysteresis_percent,
            "min_phase_duration_sec": self.min_phase_duration_sec,
        }


@dataclass
class TideSnapshot:
    """潮汐快照 - 某一时刻的潮汐状态"""
    timestamp: float = field(default_factory=time.time)
    phase: TidePhase = TidePhase.SLACK
    trend: TideTrend = TideTrend.STABLE
    resource_level: float = 50.0  # 综合资源水位 (0-100)
    gpu_memory_level: float = 0.0
    gpu_util_level: float = 0.0
    cpu_level: float = 0.0
    memory_level: float = 0.0
    concurrency_multiplier: float = 1.0
    min_priority: MissionPriority = MissionPriority.NORMAL
    predicted_phase_5min: Optional[TidePhase] = None
    predicted_phase_15min: Optional[TidePhase] = None
    predicted_phase_30min: Optional[TidePhase] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "phase": self.phase.value,
            "trend": self.trend.value,
            "resource_level": round(self.resource_level, 1),
            "gpu_memory_level": round(self.gpu_memory_level, 1),
            "gpu_util_level": round(self.gpu_util_level, 1),
            "cpu_level": round(self.cpu_level, 1),
            "memory_level": round(self.memory_level, 1),
            "concurrency_multiplier": self.concurrency_multiplier,
            "min_priority": self.min_priority.value,
            "predicted_phase_5min": self.predicted_phase_5min.value if self.predicted_phase_5min else None,
            "predicted_phase_15min": self.predicted_phase_15min.value if self.predicted_phase_15min else None,
            "predicted_phase_30min": self.predicted_phase_30min.value if self.predicted_phase_30min else None,
        }


@dataclass
class TidePrediction:
    """潮汐预测结果"""
    generated_at: float = field(default_factory=time.time)
    horizon_minutes: int = 30
    points: List[Tuple[float, float]] = field(default_factory=list)  # (timestamp, predicted_level)
    predicted_phases: Dict[int, TidePhase] = field(default_factory=dict)  # {minutes: phase}
    confidence: float = 0.0  # 预测置信度 0-1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "horizon_minutes": self.horizon_minutes,
            "confidence": round(self.confidence, 3),
            "predicted_phases": {k: v.value for k, v in self.predicted_phases.items()},
            "sample_points": len(self.points),
            "next_phase_change_minutes": self._next_phase_change_minutes(),
        }

    def _next_phase_change_minutes(self) -> Optional[int]:
        """计算下一次阶段变化的时间（分钟）"""
        if not self.predicted_phases:
            return None
        # 找到第一个与当前不同的阶段
        # 简化实现：返回第一个变化点
        minutes_list = sorted(self.predicted_phases.keys())
        if len(minutes_list) < 2:
            return None
        first_phase = self.predicted_phases[minutes_list[0]]
        for m in minutes_list[1:]:
            if self.predicted_phases[m] != first_phase:
                return m
        return None


@dataclass
class GPUMission:
    """GPU 计算任务（潮汐调度的任务单元）

    与 SandboxTask 类似，但专为 GPU 计算设计，包含显存需求、GPU 亲和性等。
    """
    mission_id: str = field(default_factory=lambda: f"tide_{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    priority: MissionPriority = MissionPriority.NORMAL
    status: str = "pending"  # pending / running / completed / failed / cancelled / queued

    # 资源需求
    estimated_gpu_memory_mb: float = 1024.0
    estimated_duration_sec: float = 60.0
    gpu_affinity: List[int] = field(default_factory=list)  # 优先使用的 GPU ID
    preferred_gpu_id: Optional[int] = None

    # 调度信息
    assigned_gpu_id: int = -1
    assigned_source_id: str = ""
    submit_time: float = field(default_factory=time.time)
    start_time: float = 0.0
    end_time: float = 0.0
    queue_position: int = 0

    # 业务信息
    mission_type: str = "general"  # inference / training / embedding / vector_search / render
    caller_module: str = ""
    callback_url: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    # 潮汐属性
    tide_phase_at_submit: Optional[TidePhase] = None
    tide_phase_at_start: Optional[TidePhase] = None
    tide_preemptible: bool = False  # 是否可被潮汐调度抢占

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status,
            "estimated_gpu_memory_mb": self.estimated_gpu_memory_mb,
            "estimated_duration_sec": self.estimated_duration_sec,
            "preferred_gpu_id": self.preferred_gpu_id,
            "assigned_gpu_id": self.assigned_gpu_id,
            "submit_time": self.submit_time,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "queue_position": self.queue_position,
            "mission_type": self.mission_type,
            "caller_module": self.caller_module,
            "tide_phase_at_submit": self.tide_phase_at_submit.value if self.tide_phase_at_submit else None,
            "tide_phase_at_start": self.tide_phase_at_start.value if self.tide_phase_at_start else None,
            "tide_preemptible": self.tide_preemptible,
            "progress": self.result.get("progress", 0) if self.status == "running" else 0,
        }


@dataclass
class TideStats:
    """潮汐引擎统计信息"""
    total_missions_submitted: int = 0
    total_missions_completed: int = 0
    total_missions_failed: int = 0
    total_missions_preempted: int = 0  # 被潮汐调度抢占的任务数

    current_pending: int = 0
    current_running: int = 0
    current_queued: int = 0

    phase_time_distribution: Dict[str, float] = field(default_factory=dict)  # 各阶段累计时间（秒）
    phase_transition_count: int = 0  # 阶段切换次数

    avg_wait_time_sec: float = 0.0
    peak_concurrency: int = 0
    gpu_utilization_avg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_missions_submitted": self.total_missions_submitted,
            "total_missions_completed": self.total_missions_completed,
            "total_missions_failed": self.total_missions_failed,
            "total_missions_preempted": self.total_missions_preempted,
            "current_pending": self.current_pending,
            "current_running": self.current_running,
            "current_queued": self.current_queued,
            "phase_time_distribution": self.phase_time_distribution,
            "phase_transition_count": self.phase_transition_count,
            "avg_wait_time_sec": round(self.avg_wait_time_sec, 1),
            "peak_concurrency": self.peak_concurrency,
            "gpu_utilization_avg": round(self.gpu_utilization_avg, 1),
        }
