"""
云汐 M9 数据水晶 - 管道包

P3 优化：数据采集管道 + 连接器生态
统一导出所有管道相关组件
"""

from .base import (
    DataPipeline,
    PipelineStage,
    PipelineResult,
    StageResult,
    PipelineStatus,
    StageRegistry,
)

from .stages import (
    FilterStage,
    TransformStage,
    CleanStage,
    EnrichStage,
    AggregateStage,
    ValidateStage,
)

from .manager import (
    PipelineManager,
    PipelineDefinition,
    PipelineRunRecord,
    get_pipeline_manager,
)

__all__ = [
    # 基类
    "DataPipeline",
    "PipelineStage",
    "PipelineResult",
    "StageResult",
    "PipelineStatus",
    "StageRegistry",
    # 阶段
    "FilterStage",
    "TransformStage",
    "CleanStage",
    "EnrichStage",
    "AggregateStage",
    "ValidateStage",
    # 管理器
    "PipelineManager",
    "PipelineDefinition",
    "PipelineRunRecord",
    "get_pipeline_manager",
]
