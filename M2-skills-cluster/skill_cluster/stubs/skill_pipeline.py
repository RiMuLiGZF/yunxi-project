from __future__ import annotations

"""【DEPRECATED】技能流水线引擎已迁移.

本模块已迁移至 :mod:`skill_cluster.core.pipeline.engine`，
请使用 ``from skill_cluster.core.pipeline import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.skill_pipeline 已迁移至 skill_cluster.core.pipeline，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.pipeline import (
    PipelineContext,
    PipelineDefinition,
    PipelineEngine,
    PipelineStep,
)

__all__ = [
    "PipelineEngine",
    "PipelineDefinition",
    "PipelineStep",
    "PipelineContext",
]
