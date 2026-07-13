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

# ── 任务相关模型 ──────────────────────────────────────
from models.task import (
    ChatRequest,
    ChatStreamRequest,
    CloneReleaseRequest,
    CloneRequest,
    SubmitTaskRequest,
    SubmitTaskResponse,
    TaskInfo,
    TaskStatusResponse,
)

# ── Agent 相关模型 ───────────────────────────────────
from models.agent import (
    AgentInfo,
    AgentListResponse,
    AgentRegisterRequest,
    AgentStatusResponse,
    AgentUnregisterRequest,
)

# ── 联邦调度模型 ──────────────────────────────────────
from models.federation import (
    FedBudgetRequest,
    FedCompareRequest,
    FedDecideRequest,
    FedInvokeRequest,
    FedPrivacyScanRequest,
    FedRegisterRequest,
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
    # 任务相关模型
    "SubmitTaskRequest",
    "SubmitTaskResponse",
    "TaskStatusResponse",
    "TaskInfo",
    "CloneRequest",
    "CloneReleaseRequest",
    "ChatRequest",
    "ChatStreamRequest",
    # Agent 相关模型
    "AgentStatusResponse",
    "AgentInfo",
    "AgentRegisterRequest",
    "AgentUnregisterRequest",
    "AgentListResponse",
    # 联邦调度模型
    "FedRegisterRequest",
    "FedInvokeRequest",
    "FedDecideRequest",
    "FedCompareRequest",
    "FedPrivacyScanRequest",
    "FedBudgetRequest",
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
