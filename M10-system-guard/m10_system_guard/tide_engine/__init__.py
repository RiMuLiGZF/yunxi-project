"""
M10 潮汐引擎 (Tide Engine)

基于 GPU/系统资源潮汐式变化的智能调度系统。
- 涨潮（FLOOD）：资源充裕，提升并发，放行重型任务
- 平潮（SLACK）：资源平稳，标准并发
- 退潮（EBB）：资源紧张，降低并发，仅放行轻量任务
- 枯潮（LOW）：资源严重不足，最小并发，暂停重型任务
"""

from .tide_engine import TideEngine, get_tide_engine
from .models import (
    TidePhase,
    TideTrend,
    TideSnapshot,
    TideStrategy,
    TidePrediction,
    GPUMission,
    MissionPriority,
    TideStats,
)
from .tide_state import TideStateMachine
from .tide_scheduler import TideScheduler
from .gpu_orchestrator import GPUOrchestrator

__all__ = [
    "TideEngine",
    "get_tide_engine",
    "TidePhase",
    "TideTrend",
    "TideSnapshot",
    "TideStrategy",
    "TidePrediction",
    "GPUMission",
    "MissionPriority",
    "TideStats",
    "TideStateMachine",
    "TideScheduler",
    "GPUOrchestrator",
]
