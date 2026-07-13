"""
M1 Agent 集群 - 消息总线模型

消息总线发布、消息结构等相关的 Pydantic 模型。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from models.base import M1BaseModel


class BusPublishRequest(M1BaseModel):
    """消息总线发布请求。

    HTTP API 层的消息发布请求模型，用于参数校验。

    字段边界校验：
    - topic: 1~128 字符
    - sender: 最长 64 字符
    - msg_type: 最长 64 字符
    - priority: 1~10 整数
    - ttl: 0~3600 秒
    """

    topic: str = Field(..., min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    sender: str = Field(default="api_client", max_length=64)
    recipient: str | None = Field(default=None, max_length=64)
    msg_type: str = Field(default="user.input", max_length=64)
    priority: int = Field(default=5, ge=1, le=10)
    ttl: int = Field(default=300, ge=0, le=3600)
    trace_id: str = Field(default="", max_length=64)


class BusMessageModel(M1BaseModel):
    """消息总线消息模型。

    消息总线内部使用的完整消息结构模型。
    与 interfaces.BusMessage 字段对齐，提供 Pydantic 校验能力。

    字段边界校验：
    - msg_id: 最长 64 字符
    - topic: 1~256 字符
    - sender: 最长 128 字符
    - priority: 1~10 整数
    - ttl: 0~86400 秒
    """

    msg_id: str = Field(default="", max_length=64)
    timestamp: float = 0.0
    topic: str = Field(..., min_length=1, max_length=256)
    sender: str = Field(default="", max_length=128)
    recipient: str | None = Field(default=None, max_length=128)
    msg_type: Literal[
        "user.input",
        "agent.task_complete",
        "agent.handoff",
        "system.config_change",
        "skill.result",
        "scene.result",
    ] = "user.input"
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    ttl: int = Field(default=300, ge=0, le=86400)
    trace_id: str = Field(default="", max_length=64)
    security_classification: str = "INTERNAL"


class BusSubscribeRequest(M1BaseModel):
    """消息总线订阅请求。

    字段边界校验：
    - topic_pattern: 1~256 字符
    - subscriber_id: 最长 128 字符
    """

    topic_pattern: str = Field(..., min_length=1, max_length=256)
    subscriber_id: str = Field(default="", max_length=128)
