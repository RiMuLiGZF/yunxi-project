"""
M1 Agent 集群 - 任务相关模型

任务提交、任务状态查询、分身池等任务相关的 Pydantic 模型。
迁移自 api/server.py 中的任务模型定义。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from models.base import M1BaseModel


class SubmitTaskRequest(M1BaseModel):
    """提交任务请求。

    字段边界校验：
    - user_input: 1~10000 字符
    - task_id: 最长 64 字符，允许空字符串（服务端自动生成）
    - trace_id: 最长 64 字符
    - model: 最长 128 字符
    - priority: 1~10 整数
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    task_id: str = Field(default="", max_length=64)
    trace_id: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    budget: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    priority: int = Field(default=5, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitTaskResponse(M1BaseModel):
    """提交任务响应。"""

    status: str
    task_id: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    agents_deployed: list[str] = Field(default_factory=list)
    budget_consumed: float = 0.0


class TaskStatusResponse(M1BaseModel):
    """任务状态响应。"""

    task_id: str
    goal: str = ""
    status: str
    completion_rate: float = 0.0
    plans: list[dict[str, Any]] = Field(default_factory=list)
    agents: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = False


class TaskInfo(M1BaseModel):
    """任务信息模型。

    用于在各模块间传递任务核心信息的结构化模型，
    替代松散的 dict[str, Any] 以提升类型安全性。
    """

    task_id: str
    trace_id: str = ""
    intent: str = ""
    status: str = "pending"  # pending / running / completed / failed / timeout
    target_agent: str = ""
    priority: int = Field(default=5, ge=1, le=10)
    created_at: float = 0.0
    completed_at: float | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CloneRequest(M1BaseModel):
    """分身申请请求。

    字段边界校验：
    - parent_agent_id: 1~64 字符
    - clone_type: 枚举值（scout/planner/writer/reviewer）
    - ttl: 0~86400 秒（0 表示使用默认 TTL）
    """

    parent_agent_id: str = Field(..., min_length=1, max_length=64)
    clone_type: Literal["scout", "planner", "writer", "reviewer"] = "scout"
    task_id: str = Field(default="", max_length=64)
    capabilities: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    ttl: int = Field(default=0, ge=0, le=86400)  # 0 表示使用默认 TTL


class CloneReleaseRequest(M1BaseModel):
    """分身释放请求。

    字段边界校验：
    - clone_id: 1~64 字符
    """

    clone_id: str = Field(..., min_length=1, max_length=64)


class ChatRequest(M1BaseModel):
    """同步对话请求。

    用于 /api/v1/chat 端点，替代直接读取 request.json() 的方式。
    字段边界校验：
    - user_input: 1~10000 字符
    - trace_id: 最长 64 字符
    - model: 最长 128 字符
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    trace_id: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)


class ChatStreamRequest(M1BaseModel):
    """流式对话请求。

    用于 /api/v1/chat/stream 端点，替代直接读取 request.json() 的方式。
    字段边界校验：
    - user_input: 1~10000 字符
    - trace_id: 最长 64 字符
    - voice_polish: 是否启用人格润色（默认 True）
    """

    user_input: str = Field(..., min_length=1, max_length=10000)
    trace_id: str = Field(default="", max_length=64)
    voice_polish: bool = True
