from __future__ import annotations

"""A2A Protocol - Agent-to-Agent 协作协议.

参考 Google A2A 协议核心概念，实现 AgentCard、Task、Message、Artifact
等数据模型，支持多 Agent 之间的标准化消息传递与任务协作。
"""

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class A2APart(BaseModel):
    """消息内容单元."""

    type: Literal["text", "file", "data"] = Field(..., description="内容类型")
    content: Any = Field(..., description="内容数据")
    mime_type: str | None = Field(default=None, description="MIME 类型")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class A2AMessage(BaseModel):
    """Agent 间通信消息."""

    message_id: str = Field(
        default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}",
        description="消息唯一标识",
    )
    role: Literal["user", "agent"] = Field(..., description="发送者角色")
    source_agent_id: str = Field(..., description="发送 Agent ID")
    target_agent_id: str = Field(..., description="目标 Agent ID")
    parts: list[A2APart] = Field(default_factory=list, description="内容单元列表")
    timestamp: float = Field(default_factory=time.time, description="发送时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class A2AArtifact(BaseModel):
    """任务输出产物."""

    artifact_id: str = Field(
        default_factory=lambda: f"art_{uuid.uuid4().hex[:12]}",
        description="产物唯一标识",
    )
    name: str = Field(..., description="产物名称")
    parts: list[A2APart] = Field(default_factory=list, description="内容单元")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    timestamp: float = Field(default_factory=time.time, description="生成时间")


class A2ATask(BaseModel):
    """协作任务.

    任务状态机:
        submitted -> working -> [input-required] -> completed/failed/canceled
    """

    task_id: str = Field(
        default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}",
        description="任务唯一标识",
    )
    session_id: str = Field(
        default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}",
        description="会话标识",
    )
    status: Literal[
        "submitted", "working", "input-required", "completed", "failed", "canceled"
    ] = Field(default="submitted", description="任务状态")
    creator_agent_id: str = Field(..., description="创建者 Agent ID")
    handler_agent_id: str | None = Field(
        default=None, description="处理者 Agent ID"
    )
    messages: list[A2AMessage] = Field(
        default_factory=list, description="消息历史"
    )
    artifacts: list[A2AArtifact] = Field(
        default_factory=list, description="输出产物"
    )
    history: list[dict[str, Any]] = Field(
        default_factory=list, description="状态变更历史"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    created_at: float = Field(default_factory=time.time, description="创建时间")
    updated_at: float = Field(default_factory=time.time, description="更新时间")

    def add_message(self, message: A2AMessage) -> None:
        """添加消息并更新时间."""
        self.messages.append(message)
        self.updated_at = time.time()

    def add_artifact(self, artifact: A2AArtifact) -> None:
        """添加产物并标记完成."""
        self.artifacts.append(artifact)
        self.status = "completed"
        self.updated_at = time.time()
        self._log_history("artifact_added", artifact.artifact_id)

    def transition(self, new_status: str, reason: str = "") -> None:
        """状态迁移."""
        old_status = self.status
        self.status = new_status
        self.updated_at = time.time()
        self._log_history(
            "status_changed",
            {"from": old_status, "to": new_status, "reason": reason},
        )

    def _log_history(self, event: str, detail: Any) -> None:
        self.history.append(
            {
                "event": event,
                "detail": detail,
                "timestamp": time.time(),
            }
        )


class A2AAgentCard(BaseModel):
    """Agent 能力卡片.

    描述 Agent 的标识、能力、端点和认证方式，
    供其他 Agent 发现和调用。
    """

    agent_id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="Agent 名称")
    description: str = Field(default="", description="能力描述")
    version: str = Field(default="1.0.0", description="版本")
    skills: list[str] = Field(
        default_factory=list, description="支持的 Skill ID 列表"
    )
    endpoints: list[str] = Field(
        default_factory=list, description="可用端点地址"
    )
    auth_scheme: Literal["none", "api_key", "oauth2"] = Field(
        default="none", description="认证方式"
    )
    capabilities: list[str] = Field(
        default_factory=list, description="协议能力列表"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    updated_at: float = Field(default_factory=time.time, description="更新时间")
