"""
云汐内核 V8 - A2A 标准通信协议适配层

基于 A2A Protocol v1.0 规范实现：
https://a2a-protocol.org/dev/announcing-1.0/

核心设计：
- Task 状态机（submitted/working/input_required/completed/failed）
- AgentCard 能力声明与发现
- 多传输绑定（内存/HTTP）
- Signed 身份验证（简化 HMAC）

解决评审报告 P0 问题：
- 私有 BusMessage → A2A 标准消息格式
- 内存总线 → 可扩展传输抽象
- 无身份验证 → AgentCard 签名验证
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


# ── Task 状态机 ────────────────────────────────────────────


class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Artifact:
    """多模态输出载体"""

    artifact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    kind: str = "text"  # text | image | audio | file
    data: str = ""  # base64 或 URI
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    """A2A Task 模型"""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.SUBMITTED
    sender: str = ""
    recipient: str = ""
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    trace_id: str = ""
    signature: str = ""  # [V9.6] Task 级 HMAC 签名

    def transition_to(self, new_status: TaskStatus) -> None:
        """合法状态转换"""
        valid = {
            TaskStatus.SUBMITTED: {TaskStatus.WORKING, TaskStatus.CANCELLED, TaskStatus.FAILED},
            TaskStatus.WORKING: {TaskStatus.INPUT_REQUIRED, TaskStatus.COMPLETED,
                                  TaskStatus.FAILED, TaskStatus.CANCELLED},
            TaskStatus.INPUT_REQUIRED: {TaskStatus.WORKING, TaskStatus.CANCELLED},
        }
        allowed = valid.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"非法状态转换: {self.status.value} → {new_status.value}"
            )
        self.status = new_status
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "description": self.description,
            "payload": self.payload,
            "artifact_count": len(self.artifacts),
            "error": self.error,
            "trace_id": self.trace_id,
        }


@dataclass
class TaskUpdate:
    """Task 状态更新推送"""

    task_id: str
    status: TaskStatus
    artifact: Artifact | None = None
    error: str | None = None
    is_final: bool = False
    timestamp: float = field(default_factory=time.time)


# ── AgentCard（A2A v1.0 对齐）───────────────────────────────


@dataclass
class AgentCard:
    """A2A AgentCard 能力声明"""

    agent_id: str
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    url: str = ""  # Agent 的 A2A endpoint
    capabilities: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    signature: str = ""  # HMAC 签名

    def sign(self, secret: str) -> None:
        """对 AgentCard 进行签名"""
        payload = json.dumps({
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "capabilities": sorted(self.capabilities),
        }, sort_keys=True)
        self.signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:32]

    def verify(self, secret: str) -> bool:
        """验证签名"""
        payload = json.dumps({
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "capabilities": sorted(self.capabilities),
        }, sort_keys=True)
        expected = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()[:32]
        return hmac.compare_digest(self.signature, expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "url": self.url,
            "capabilities": self.capabilities,
            "skills": self.skills,
            "signature": self.signature[:8] + "..." if self.signature else "",
        }


def sign_task(task: Task, secret: str) -> str:
    """[V9.6] 对 Task 的 payload + task_id + timestamp 做 HMAC 签名"""
    payload = json.dumps({
        "task_id": task.task_id,
        "sender": task.sender,
        "recipient": task.recipient,
        "payload": task.payload,
        "created_at": task.created_at,
    }, sort_keys=True)
    return hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_task(task: Task, signature: str, secret: str) -> bool:
    """[V9.6] 验证 Task 签名"""
    expected = sign_task(task, secret)
    return hmac.compare_digest(expected, signature)


# ── 传输抽象 ──────────────────────────────────────────────


class A2ATransport(ABC):
    """A2A 传输层抽象"""

    @abstractmethod
    async def send(self, target_url: str, task: Task) -> TaskUpdate:
        ...

    @abstractmethod
    async def subscribe(
        self, agent_id: str
    ) -> AsyncIterator[TaskUpdate]:
        ...


class MemoryTransport(A2ATransport):
    """内存传输（同进程，零序列化）"""

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}  # agent_id -> handler
        self._queues: dict[str, list[Task]] = {}  # agent_id -> task queue

    def register_handler(self, agent_id: str, handler: Any) -> None:
        self._handlers[agent_id] = handler

    def get_handlers(self) -> dict[str, Any]:
        """[V9.5] 获取所有已注册的 handler"""
        return dict(self._handlers)

    async def send(self, target_url: str, task: Task) -> TaskUpdate:
        agent_id = target_url.replace("memory://", "")
        handler = self._handlers.get(agent_id)
        if handler is None:
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=f"Agent '{agent_id}' not found",
                is_final=True,
            )
        try:
            return await handler(task)
        except Exception as exc:
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(exc),
                is_final=True,
            )

    async def subscribe(self, agent_id: str) -> AsyncIterator[TaskUpdate]:
        yield TaskUpdate(task_id="", status=TaskStatus.SUBMITTED, is_final=True)


# ── A2A 协议客户端 ────────────────────────────────────────


class A2AClient:
    """A2A 协议客户端"""

    def __init__(
        self,
        transport: A2ATransport | None = None,
        signing_secret: str = "yunxi-default-secret",
    ) -> None:
        self._transport = transport or MemoryTransport()
        self._signing_secret = signing_secret
        self._logger = logger.bind(service="a2a_client")

    async def send_task(
        self,
        target_card: AgentCard,
        task: Task,
    ) -> Task:
        """发送 Task 到目标 Agent"""
        task.recipient = target_card.agent_id
        update = await self._transport.send(
            target_card.url or f"memory://{target_card.agent_id}", task
        )
        task.transition_to(update.status)
        if update.error:
            task.error = update.error
        if update.artifact:
            task.artifacts.append(update.artifact)
        return task

    async def discover_agents(self) -> list[AgentCard]:
        """发现可用 Agent（从注册中心获取）"""
        return []

    def verify_card(self, card: AgentCard) -> bool:
        """验证 AgentCard 签名"""
        return card.verify(self._signing_secret)
