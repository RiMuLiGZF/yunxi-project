"""M2 技能集群 - 核心流水线模块.

流水线编排引擎与状态存储。
"""

from __future__ import annotations

from skill_cluster.core.pipeline.engine import PipelineEngine
from skill_cluster.core.pipeline.store import PipelineRunRecord, PipelineStateStore

# 从 models.pipeline 导入 Pydantic 模型
from skill_cluster.models.pipeline import (
    PipelineContext,
    PipelineDefinition,
    PipelineStep,
)

__all__ = [
    "PipelineEngine",
    "PipelineDefinition",
    "PipelineStep",
    "PipelineContext",
    "PipelineStateStore",
    "PipelineRunRecord",
]
