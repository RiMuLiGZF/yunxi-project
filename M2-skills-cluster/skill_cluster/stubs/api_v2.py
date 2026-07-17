from __future__ import annotations

"""【DEPRECATED】v2 API 已迁移.

本模块已迁移至 :mod:`skill_cluster.api.v2`，
请使用 ``from skill_cluster.api.v2 import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.api_v2 已迁移至 skill_cluster.api.v2，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.api.v2 import (
    create_v2_app,
)

# 从 models.common 导入的 Pydantic 模型（向后兼容）
from skill_cluster.models.common import (
    AccuracyStats,
    ApiResponse,
    BatchInvokeRequest,
    InvokeStats,
    RecommendResultItem,
    RecommendTestRequest,
    SkillDetail,
    SkillInvokeRequest,
    SkillItem,
    SkillToggleRequest,
    SystemStats,
)

__all__ = [
    "create_v2_app",
    "ApiResponse",
    "SkillInvokeRequest",
    "BatchInvokeRequest",
    "RecommendTestRequest",
    "SkillToggleRequest",
    "SkillItem",
    "SkillDetail",
    "RecommendResultItem",
    "AccuracyStats",
    "InvokeStats",
    "SystemStats",
]
