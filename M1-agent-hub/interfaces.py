"""
云汐内核 - 多 Agent 集群调度系统
核心接口与数据模型定义

定义 IAgentPlugin 抽象基类、AgentTask、AgentResult、BusMessage 等
所有核心数据模型与接口。
"""

from __future__ import annotations

import asyncio
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field


# ── 自定义异常类 ──────────────────────────────────────────────


class AgentClusterError(Exception):
    """Agent 集群基础异常"""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class DispatchError(AgentClusterError):
    """任务分发异常"""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class BusError(AgentClusterError):
    """消息总线异常"""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class RegistryError(AgentClusterError):
    """Agent 注册中心异常"""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


# ── 数据模型 ──────────────────────────────────────────────────


class AgentTask(BaseModel):
    """Agent 任务数据模型"""

    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = ""
    source: str = ""
    target: str = ""
    intent: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    ttl: int = 300
    created_at: float = Field(default_factory=time.time)
    deadline: float | None = None
    requires_confirmation: bool = False
    collaborators: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    security_classification: str = "INTERNAL"  # [v2.0-LINKAGE] x-security-classification


class AgentResult(BaseModel):
    """Agent 执行结果"""

    task_id: str = ""
    trace_id: str = ""
    agent_id: str = ""
    status: Literal["success", "failure", "partial", "timeout", "handoff"] = "success"
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    metrics: dict[str, Any] = Field(default_factory=dict)
    agents_deployed: list[str] = Field(default_factory=list)  # [v2.0-LINKAGE]
    budget_consumed: float = 0.0  # [v2.0-LINKAGE]


class BusMessage(BaseModel):
    """消息总线消息"""

    msg_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = Field(default_factory=time.time)
    topic: str = ""
    sender: str = ""
    recipient: str | None = None
    msg_type: Literal[
        "user.input",
        "agent.task_complete",
        "agent.handoff",
        "system.config_change",
        "skill.result",
        "scene.result",
    ] = "user.input"
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    ttl: int = 300
    trace_id: str = ""
    security_classification: str = "INTERNAL"  # [v2.0-LINKAGE] x-security-classification


class ClassifyResult(BaseModel):
    """意图分类结果"""

    target_agent: str = "master_scheduler"
    intent: str = "general.fallback"
    confidence: float = 0.0
    requires_confirmation: bool = False


@dataclass
class CancelToken:
    """[V9.8] 任务取消令牌

    通过 asyncio.Event 实现协作式取消。
    Agent 在 handle_task 中应定期检查 token.is_cancelled()。
    """
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    reason: str = ""

    def cancel(self, reason: str = "") -> None:
        self.reason = reason or "cancelled"
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait_cancelled(self, timeout: float | None = None) -> bool:
        """等待取消信号，或超时返回False"""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout or 0.001)
            return True
        except asyncio.TimeoutError:
            return False


# ── 抽象基类 ──────────────────────────────────────────────────


class IAgentPlugin(ABC):
    """Agent 插件抽象基类

    所有 Agent 必须实现此接口。
    """

    agent_id: str = ""
    version: str = "1.0.0"
    capabilities: list[str] = []

    @abstractmethod
    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理一个任务"""
        ...

    async def on_mount(self, registry: Optional["AgentRegistry"] = None) -> None:
        """Agent 被注册到注册中心时调用"""
        pass

    async def on_unmount(self) -> None:
        """Agent 从注册中心注销时调用"""
        pass

    async def health(self) -> dict[str, Any]:
        """返回健康状态"""
        return {"agent_id": self.agent_id, "status": "healthy", "version": self.version}


# ── 外部模块接口（预留，不实现底层）────────────────────────────

class MemoryInterface(ABC):
    """潮汐记忆系统接口（模块四）

    模块一仅通过此接口与潮汐记忆交互，严禁直接操作记忆存储。
    """

    @abstractmethod
    async def query(
        self,
        agent_id: str,
        query: str,
        visibility: str,
        role: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """RBAC过滤后的记忆查询"""
        ...

    @abstractmethod
    async def write(
        self,
        agent_id: str,
        content: str,
        visibility: str,
        metadata: dict[str, Any],
    ) -> bool:
        """写入记忆，模块四负责沉降与归档"""
        ...

    @abstractmethod
    async def permission_check(
        self, agent_id: str, action: str, memory_id: str
    ) -> bool:
        """权限预检"""
        ...


class SkillsInterface(ABC):
    """Skills技能集群接口（模块二）

    模块一通过此接口调用工具与技能，模块二负责具体实现与沙箱隔离。
    """

    @abstractmethod
    async def invoke_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用指定技能工具"""
        ...

    @abstractmethod
    async def list_available_tools(self, agent_capabilities: list[str]) -> list[dict[str, Any]]:
        """根据Agent能力返回可用工具列表"""
        ...

    @abstractmethod
    async def check_tool_permission(
        self, agent_id: str, tool_name: str
    ) -> bool:
        """校验Agent是否有权限调用指定工具"""
        ...


# ── 类型别名 ──────────────────────────────────────────────────

class InferenceInterface(ABC):
    """推理执行接口（模块三）

    模块一通过此接口委托模型推理执行给模块三，
    M1仅负责本地/云端路由决策，M3负责实际模型调用。

    [V10.0-R03] 新增接口，用于剥离LLM推理执行至模块3。
    """

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """非流式对话推理"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式对话推理"""
        ...

    @abstractmethod
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """文本嵌入"""
        ...


class HardwareStatus(BaseModel):
    """[V10.0-R06] 硬件状态（模块6传入）

    描述手表/戒指/无人机等端侧硬件的在线状态与健康信息。
    """

    device_id: str = ""
    device_type: str = ""  # watch | ring | drone | desktop
    online: bool = True
    battery_pct: float = 100.0
    rssi: float = -50.0  # 信号强度(dBm)
    last_seen: float = Field(default_factory=time.time)
    capabilities: list[str] = Field(default_factory=list)


BusHandler = Callable[[BusMessage], Awaitable[None]]
"""消息总线处理函数签名"""