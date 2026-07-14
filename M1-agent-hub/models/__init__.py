"""
M1 Agent 集群 - Pydantic 模型统一导出入口

所有 M1 模块的 Pydantic 模型从本包统一导出，
方便外部使用单一入口导入所有模型。

使用方式：
    from models import SubmitTaskRequest, TaskStatusResponse
    from models.task import SubmitTaskRequest  # 也可以直接从子模块导入
"""

from __future__ import annotations

# ── 基础模型 ──────────────────────────────────────────
from models.base import M1BaseModel

# ── 通用响应模型 ──────────────────────────────────────
from models.common import (
    ApiResponse,
    ErrorResponse,
    PaginatedResponse,
    PaginationParams,
    T,
)

# ── 枚举与常量（从 shared_models 迁移）──────────────────
from models.enums import (
    AgentLifeState,
    AgentPrivacyLevel,
    AgentRole,
    ArbitrationLevel,
    CloneType,
    ComparisonOutputMode,
    ConnectionType,
    ExternalAgentType,
    LicenseType,
    M4ExecutionMode,
    MODE_NAMES_ZH,
    MODE_TO_SCENE_PRIMARY,
    SchedulingDecision,
    SchedulingStrategy,
    SCENE_NAMES_ZH,
    SCENE_TO_MODE,
    SecurityClassification,
    UserPreferenceMode,
    UserScene,
)

# ── 任务相关模型 ──────────────────────────────────────
from models.task import (
    ChatRequest,
    ChatStreamRequest,
    CloneReleaseRequest,
    CloneRequest,
    DAGEdge,
    DAGNode,
    SubmitTaskRequest,
    SubmitTaskResponse,
    TaskDAG,
    TaskInfo,
    TaskInfoDict,
    TaskStatusResponse,
    TraceSpanDict,
)

# ── Agent 相关模型 ───────────────────────────────────
from models.agent import (
    AgentInfo,
    AgentInfoDict,
    AgentListResponse,
    AgentRegisterRequest,
    AgentStatusResponse,
    AgentUnregisterRequest,
    CloneIdentity,
    PersonalityPreference,
    SubAgentIdentity,
)

# ── 联邦调度模型 ──────────────────────────────────────
from models.federation import (
    AgentResultItem,
    CostModel,
    CostRecord,
    ExternalAgentProfile,
    FedBudgetRequest,
    FedCompareRequest,
    FedDecideRequest,
    FederationBudget,
    FederationDecision,
    FedInvokeRequest,
    FedPrivacyScanRequest,
    FedRegisterRequest,
    MultiAgentComparison,
    PrivacyScanResult,
)

# ── 组队与仲裁模型（从 shared_models 迁移）────────────
from models.team import (
    ArbitrationRequest,
    ArbitrationResult,
    HealthStatusDict,
    LoadScore,
    TeamComposition,
)

# ── 消息总线模型 ──────────────────────────────────────
from models.message import (
    BusMessageModel,
    BusPublishRequest,
    BusSubscribeRequest,
)

# ── 配置校验模型 ──────────────────────────────────────
from models.config import (
    AgentsConfig,
    DatabaseConfig,
    FederationConfig,
    M1Config,
    MemoryConfig,
    MessageBusConfig,
    SecurityConfig,
    ServerConfig,
)

__all__ = [
    # 基础模型
    "M1BaseModel",
    # 通用响应模型
    "ApiResponse",
    "ErrorResponse",
    "PaginatedResponse",
    "PaginationParams",
    "T",
    # 枚举与常量
    "AgentRole",
    "SecurityClassification",
    "AgentLifeState",
    "SchedulingDecision",
    "ArbitrationLevel",
    "CloneType",
    "M4ExecutionMode",
    "UserScene",
    "SchedulingStrategy",
    "ExternalAgentType",
    "AgentPrivacyLevel",
    "ConnectionType",
    "LicenseType",
    "UserPreferenceMode",
    "ComparisonOutputMode",
    "MODE_TO_SCENE_PRIMARY",
    "SCENE_TO_MODE",
    "SCENE_NAMES_ZH",
    "MODE_NAMES_ZH",
    # 任务相关模型
    "SubmitTaskRequest",
    "SubmitTaskResponse",
    "TaskStatusResponse",
    "TaskInfo",
    "CloneRequest",
    "CloneReleaseRequest",
    "ChatRequest",
    "ChatStreamRequest",
    "DAGNode",
    "DAGEdge",
    "TaskDAG",
    "TaskInfoDict",
    "TraceSpanDict",
    # Agent 相关模型
    "AgentStatusResponse",
    "AgentInfo",
    "AgentRegisterRequest",
    "AgentUnregisterRequest",
    "AgentListResponse",
    "SubAgentIdentity",
    "CloneIdentity",
    "PersonalityPreference",
    "AgentInfoDict",
    # 联邦调度模型
    "FedRegisterRequest",
    "FedInvokeRequest",
    "FedDecideRequest",
    "FedCompareRequest",
    "FedPrivacyScanRequest",
    "FedBudgetRequest",
    "CostModel",
    "ExternalAgentProfile",
    "FederationDecision",
    "AgentResultItem",
    "MultiAgentComparison",
    "CostRecord",
    "FederationBudget",
    "PrivacyScanResult",
    # 组队与仲裁模型
    "LoadScore",
    "TeamComposition",
    "ArbitrationRequest",
    "ArbitrationResult",
    "HealthStatusDict",
    # 消息总线模型
    "BusPublishRequest",
    "BusMessageModel",
    "BusSubscribeRequest",
    # 配置校验模型
    "M1Config",
    "ServerConfig",
    "DatabaseConfig",
    "MessageBusConfig",
    "FederationConfig",
    "AgentsConfig",
    "MemoryConfig",
    "SecurityConfig",
]