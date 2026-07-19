from __future__ import annotations

"""【DEPRECATED】流水线状态存储已迁移.

本模块已迁移至 :mod:`skill_cluster.core.pipeline.store`，
请使用 ``from skill_cluster.core.pipeline import PipelineStateStore`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.pipeline_store 已迁移至 skill_cluster.core.pipeline.store，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.pipeline.store import (
    PipelineRunRecord,
    PipelineStateStore,
)

__all__ = ["PipelineStateStore", "PipelineRunRecord"]
