"""M2 技能集群 - Pydantic 模型统一导出.

所有 Pydantic 模型按领域分类存放在各子模块中，本模块统一导出，
方便外部以 ``from skill_cluster.models import Xxx`` 的方式使用。

领域分类：
    - base: 基类 (M2BaseModel)
    - common: 通用 API 模型 (响应、请求、统计等)
    - skill: 技能核心模型 (清单、调用请求/结果等)
    - pipeline: 流水线模型
    - security: 安全模型 (沙箱、权限)
    - resilience: 弹性模型 (预留)
    - observability: 可观测性模型 (预留)
    - extension: 扩展模型 (钩子、图谱、函数模式、Token预算)
"""

from __future__ import annotations

# ---- 基类 ----
from skill_cluster.models.base import M2BaseModel

# ---- 技能核心模型 ----
from skill_cluster.models.skill import (
    SkillManifest,
    SkillQuery,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillConfig,
)

# ---- 通用 API 模型 ----
from skill_cluster.models.common import (
    ApiResponse,
    BatchInvokeRequest,
    RecommendTestRequest,
    SkillToggleRequest,
    SkillItem,
    SkillDetail,
    RecommendResultItem,
    AccuracyStats,
    InvokeStats,
    SystemStats,
)

# 注意：common 中也有一个 SkillInvokeRequest（API 层入参模型），
# 为避免与 skill 中的核心模型命名冲突，此处以别名方式提供，
# 同时保留原名作为 API 层的向后兼容别名。
from skill_cluster.models.common import (
    SkillInvokeRequest as ApiSkillInvokeRequest,
)

# ---- 流水线模型 ----
from skill_cluster.models.pipeline import (
    PipelineStep,
    PipelineDefinition,
    PipelineContext,
)

# ---- 安全模型 ----
from skill_cluster.models.security import (
    SandboxConfig,
    PermissionRule,
    PermissionMatrix,
)

# ---- 扩展模型 ----
from skill_cluster.models.extension import (
    HookRegistration,
    GraphEdge,
    ComposableChain,
    FunctionParameter,
    FunctionSchema,
    ActionSignature,
    BudgetEntry,
    BudgetAlert,
)

__all__ = [
    # 基类
    "M2BaseModel",
    # 技能核心
    "SkillManifest",
    "SkillQuery",
    "SkillInvokeRequest",
    "SkillInvokeResult",
    "SkillConfig",
    # 通用 API
    "ApiResponse",
    "ApiSkillInvokeRequest",
    "BatchInvokeRequest",
    "RecommendTestRequest",
    "SkillToggleRequest",
    "SkillItem",
    "SkillDetail",
    "RecommendResultItem",
    "AccuracyStats",
    "InvokeStats",
    "SystemStats",
    # 流水线
    "PipelineStep",
    "PipelineDefinition",
    "PipelineContext",
    # 安全
    "SandboxConfig",
    "PermissionRule",
    "PermissionMatrix",
    # 扩展
    "HookRegistration",
    "GraphEdge",
    "ComposableChain",
    "FunctionParameter",
    "FunctionSchema",
    "ActionSignature",
    "BudgetEntry",
    "BudgetAlert",
]
