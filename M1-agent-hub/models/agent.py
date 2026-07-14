"""
M1 Agent 集群 - Agent 相关模型

Agent 注册、信息查询、状态管理、身份模型、分身池、人格偏好等相关的 Pydantic 模型。
包含从 shared_models 迁移的 Agent 核心模型。
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from models.base import M1BaseModel
from models.enums import AgentRole, CloneType, SecurityClassification


class AgentStatusResponse(M1BaseModel):
    """Agent 状态响应。

    用于 HTTP API 返回 Agent 注册状态与健康信息。
    """

    agent_id: str
    registered: bool
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    health: dict[str, Any] = Field(default_factory=dict)


class AgentInfo(M1BaseModel):
    """Agent 信息模型。

    用于 Agent 注册中心对外暴露的 Agent 结构化信息。
    提供完整的 Agent 元数据，包括角色、能力、状态、安全等级等。
    """

    agent_id: str
    name: str = ""
    version: str = ""
    role: str = "executor"  # supervisor / executor / reviewer / external
    capabilities: list[str] = Field(default_factory=list)
    status: str = "active"  # active / inactive / error
    registered: bool = False
    health_status: str = "unknown"  # up / down / degraded / unknown
    security_clearance: int = 1  # SecurityClassification 的值
    last_health_check: float | None = None
    created_at: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRegisterRequest(M1BaseModel):
    """Agent 注册请求。

    用于 Agent 向注册中心发起注册的请求模型。

    字段边界校验：
    - agent_id: 1~64 字符
    - name: 最长 128 字符
    - version: 最长 64 字符
    - role: 最长 32 字符
    """

    agent_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    version: str = Field(default="1.0.0", max_length=64)
    role: str = Field(default="executor", max_length=32)
    capabilities: list[str] = Field(default_factory=list)
    security_clearance: int = Field(default=1, ge=0, le=3)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentUnregisterRequest(M1BaseModel):
    """Agent 注销请求。

    字段边界校验：
    - agent_id: 1~64 字符
    """

    agent_id: str = Field(..., min_length=1, max_length=64)
    reason: str = ""


class AgentListResponse(M1BaseModel):
    """Agent 列表响应。

    用于批量查询 Agent 列表时的响应模型。
    """

    total: int = 0
    agents: list[AgentInfo] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════
# Agent 核心模型（从 shared_models 迁移）
# ══════════════════════════════════════════════════════════


class SubAgentIdentity(BaseModel):
    """子Agent身份模型"""
    agent_id: str = ""
    name: str = ""
    role: AgentRole = AgentRole.EXECUTOR
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    security_clearance: SecurityClassification = SecurityClassification.INTERNAL


class CloneIdentity(BaseModel):
    """临时分身身份"""
    clone_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_agent_id: str = ""
    clone_type: CloneType = CloneType.SCOUT
    task_id: str = ""
    capabilities: list[str] = Field(default_factory=list)
    security_clearance: SecurityClassification = SecurityClassification.PUBLIC  # 分身默认最低权限
    created_at: float = Field(default_factory=lambda: __import__("time").time())
    ttl: int = 300  # 秒，分身最大存活时间
    minimized_context: dict[str, Any] = Field(default_factory=dict)  # 最小信息下发


class PersonalityPreference(BaseModel):
    """云汐人格用户偏好配置

    存储在 M5 潮汐记忆系统（L2 海湾层），标记为 CONFIDENTIAL 级。
    """
    user_id: str = ""
    tone_temperature: str = "default"   # colder / default / warmer
    formality_level: str = "medium"     # casual / medium / formal
    verbosity: str = "balanced"         # concise / balanced / detailed
    humor_level: str = "medium"         # low / medium / high
    nickname: str | None = None         # 用户自定义称呼
    updated_at: float = Field(default_factory=lambda: __import__("time").time())
    version: int = 1


class AgentInfoDict(TypedDict):
    """Agent 信息 TypedDict

    用于 Agent 注册中心对外暴露的 Agent 结构化信息。
    """
    agent_id: str
    name: str
    version: str
    role: str                      # supervisor / executor / reviewer / external
    capabilities: list[str]
    status: str                    # active / inactive / error
    registered: bool
    health_status: str             # up / down / degraded / unknown
    security_clearance: int        # SecurityClassification 的值
    last_health_check: float | None
