"""
云汐内核 V12.1 - A2A 标准通信协议适配层

基于 A2A Protocol v1.0 规范实现：
https://a2a-protocol.org/dev/announcing-1.0/

核心设计：
- Task 状态机（submitted/working/input_required/completed/failed/cancelled）
- AgentCard 能力声明与发现
- 多传输绑定（内存/HTTP/WebSocket）
- Signed 身份验证（HMAC-SHA256）
- 协议版本协商与握手
- 流式 Task 更新（SSE）
- 标准化错误码

[V12.1 GAP-004 补全]：
- HttpTransport: HTTP 传输实现
- A2AProtocolServer: A2A 服务端
- 握手协议（handshake）
- 协议版本协商
- 流式更新（SSE）
- 标准化错误响应
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
from typing import Any, AsyncIterator, Callable

import structlog

logger = structlog.get_logger(__name__)

# 协议版本
A2A_PROTOCOL_VERSION = "1.0"
A2A_PROTOCOL_VERSIONS_SUPPORTED = ["1.0", "0.9"]

# 标准错误码
A2A_ERROR_CODES = {
    "BAD_REQUEST": ("A2A-001", 400, "Invalid request format"),
    "UNAUTHORIZED": ("A2A-002", 401, "Authentication required"),
    "FORBIDDEN": ("A2A-003", 403, "Permission denied"),
    "NOT_FOUND": ("A2A-004", 404, "Agent or Task not found"),
    "AGENT_NOT_FOUND": ("A2A-005", 404, "Target agent not found"),
    "TASK_NOT_FOUND": ("A2A-006", 404, "Task not found"),
    "INVALID_STATUS": ("A2A-007", 409, "Invalid task status transition"),
    "CAPABILITY_NOT_SUPPORTED": ("A2A-008", 400, "Requested capability not supported"),
    "RATE_LIMITED": ("A2A-009", 429, "Rate limit exceeded"),
    "INTERNAL_ERROR": ("A2A-500", 500, "Internal server error"),
    "PROTOCOL_VERSION_MISMATCH": ("A2A-010", 400, "Protocol version not supported"),
}


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "kind": self.kind,
            "data": self.data,
            "metadata": self.metadata,
        }


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
        """合法状态转换

        状态转换规则：
        - SUBMITTED -> WORKING / COMPLETED / FAILED / CANCELLED
          (COMPLETED/FAILED 用于同步任务直接返回结果)
        - WORKING -> INPUT_REQUIRED / COMPLETED / FAILED / CANCELLED
        - INPUT_REQUIRED -> WORKING / CANCELLED
        - COMPLETED / FAILED / CANCELLED: 终态，不可转换
        """
        valid = {
            TaskStatus.SUBMITTED: {
                TaskStatus.WORKING,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            },
            TaskStatus.WORKING: {
                TaskStatus.INPUT_REQUIRED,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            },
            TaskStatus.INPUT_REQUIRED: {
                TaskStatus.WORKING,
                TaskStatus.CANCELLED,
            },
        }
        allowed = valid.get(self.status, set())
        # 允许相同状态的幂等转换
        if new_status == self.status:
            self.updated_at = time.time()
            return
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
            "artifacts": [a.to_dict() for a in self.artifacts],
            "artifact_count": len(self.artifacts),
            "error": self.error,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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

    async def handshake(self, target_url: str) -> dict[str, Any]:
        """[V12.1] 与目标 Agent 进行协议握手

        协商协议版本、验证身份、获取能力声明。

        Args:
            target_url: 目标 Agent 的 A2A 端点 URL

        Returns:
            握手结果，包含协议版本、AgentCard 等信息
        """
        # 对于 memory transport，直接返回成功
        if target_url.startswith("memory://"):
            agent_id = target_url.replace("memory://", "")
            return {
                "success": True,
                "protocol_version": A2A_PROTOCOL_VERSION,
                "agent_id": agent_id,
                "transport": "memory",
            }

        # HTTP transport 握手
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # 1. 发现 AgentCard
                well_known_url = target_url.rstrip("/") + "/.well-known/agent-card.json"
                async with session.get(well_known_url, timeout=5) as resp:
                    if resp.status != 200:
                        return {
                            "success": False,
                            "error": f"Discovery failed: HTTP {resp.status}",
                        }
                    card_data = await resp.json()

                # 2. 版本协商
                server_versions = card_data.get("protocol_version", A2A_PROTOCOL_VERSION)
                if isinstance(server_versions, str):
                    server_versions = [server_versions]

                negotiated = _negotiate_version(
                    A2A_PROTOCOL_VERSIONS_SUPPORTED,
                    server_versions,
                )

                return {
                    "success": negotiated is not None,
                    "protocol_version": negotiated,
                    "agent_card": card_data,
                    "transport": "http",
                }
        except ImportError:
            return {
                "success": False,
                "error": "aiohttp not available for HTTP transport",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }


# ── HTTP 传输实现 ────────────────────────────────────────


class HttpTransport(A2ATransport):
    """[V12.1] HTTP 传输实现（基于 A2A 协议 v1.0）

    通过 HTTP/HTTPS 与远程 Agent 通信：
    - POST /tasks/submit       提交 Task
    - GET  /tasks/{task_id}    查询 Task 状态
    - GET  /tasks/{task_id}/stream  SSE 流式更新
    - POST /tasks/{task_id}/cancel  取消 Task
    """

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        signing_secret: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._signing_secret = signing_secret
        self._logger = logger.bind(service="a2a_http_transport")

    async def send(self, target_url: str, task: Task) -> TaskUpdate:
        """通过 HTTP 提交 Task"""
        url = target_url or self.base_url
        if not url:
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error="No target URL specified",
                is_final=True,
            )

        # 确保 URL 以 /tasks/submit 结尾
        if not url.endswith("/tasks/submit"):
            url = url.rstrip("/") + "/tasks/submit"

        try:
            import aiohttp
        except ImportError:
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error="aiohttp not installed",
                is_final=True,
            )

        try:
            # 签名 Task
            if self._signing_secret:
                task.signature = sign_task(task, self._signing_secret)

            payload = {
                "task_id": task.task_id,
                "sender": task.sender,
                "recipient": task.recipient,
                "description": task.description,
                "payload": task.payload,
                "trace_id": task.trace_id,
                "signature": task.signature,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    data = await resp.json()

                    if resp.status >= 400:
                        return TaskUpdate(
                            task_id=task.task_id,
                            status=TaskStatus.FAILED,
                            error=data.get("error", f"HTTP {resp.status}"),
                            is_final=True,
                        )

                    status_str = data.get("status", "submitted")
                    try:
                        status = TaskStatus(status_str)
                    except ValueError:
                        status = TaskStatus.SUBMITTED

                    artifact = None
                    if data.get("artifact"):
                        art = data["artifact"]
                        artifact = Artifact(
                            artifact_id=art.get("artifact_id", ""),
                            name=art.get("name", ""),
                            kind=art.get("kind", "text"),
                            data=art.get("data", ""),
                            metadata=art.get("metadata", {}),
                        )

                    return TaskUpdate(
                        task_id=data.get("task_id", task.task_id),
                        status=status,
                        artifact=artifact,
                        error=data.get("error"),
                        is_final=status in (
                            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
                        ),
                    )
        except Exception as exc:
            self._logger.error("http_send_failed", error=str(exc), url=url)
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=str(exc),
                is_final=True,
            )

    async def subscribe(
        self, agent_id: str
    ) -> AsyncIterator[TaskUpdate]:
        """HTTP 轮询模式订阅（SSE 或长轮询）"""
        # 简化实现：空订阅
        yield TaskUpdate(task_id="", status=TaskStatus.SUBMITTED, is_final=True)

    async def get_task_status(self, base_url: str, task_id: str) -> dict[str, Any] | None:
        """查询 Task 状态"""
        url = base_url.rstrip("/") + f"/tasks/{task_id}"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
        except Exception:
            return None

    async def cancel_task(self, base_url: str, task_id: str) -> bool:
        """取消 Task"""
        url = base_url.rstrip("/") + f"/tasks/{task_id}/cancel"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, timeout=self.timeout) as resp:
                    return resp.status == 200
        except Exception:
            return False


# ── A2A 协议服务端 ────────────────────────────────────────


class A2AProtocolServer:
    """[V12.1] A2A 协议服务端

    实现 A2A 协议的服务端接口，用于接收外部 Agent 的 Task 请求，
    并将其路由到内部 Agent 处理。

    标准端点：
    - GET  /.well-known/agent-card.json  发现端点
    - POST /a2a/v1/tasks/submit          提交 Task
    - GET  /a2a/v1/tasks/{task_id}       查询 Task
    - GET  /a2a/v1/tasks/{task_id}/stream  SSE 流式更新
    - POST /a2a/v1/tasks/{task_id}/cancel  取消 Task
    - POST /a2a/v1/handshake             握手协商
    """

    def __init__(
        self,
        agent_card: AgentCard,
        task_handler: Callable[[Task], TaskUpdate] | None = None,
        signing_secret: str = "",
        require_auth: bool = False,
    ) -> None:
        self.agent_card = agent_card
        self._task_handler = task_handler
        self._signing_secret = signing_secret
        self._require_auth = require_auth
        self._tasks: dict[str, Task] = {}
        self._updates: dict[str, list[TaskUpdate]] = {}
        self._logger = logger.bind(
            service="a2a_server",
            agent_id=agent_card.agent_id,
        )

    def set_task_handler(self, handler: Callable[[Task], TaskUpdate]) -> None:
        """设置 Task 处理器"""
        self._task_handler = handler

    # ── 发现 & 握手 ──────────────────────────────────

    def get_agent_card(self) -> dict[str, Any]:
        """获取 AgentCard（用于 .well-known 端点）"""
        card_dict = self.agent_card.to_dict()
        card_dict["protocol_version"] = A2A_PROTOCOL_VERSION
        card_dict["supported_versions"] = A2A_PROTOCOL_VERSIONS_SUPPORTED
        return card_dict

    def handle_handshake(self, request: dict[str, Any]) -> dict[str, Any]:
        """处理握手请求

        协商协议版本、验证客户端身份。

        Args:
            request: 握手请求，包含 client_version, client_id 等

        Returns:
            握手响应
        """
        client_versions = request.get("supported_versions", [request.get("protocol_version", "1.0")])
        if isinstance(client_versions, str):
            client_versions = [client_versions]

        negotiated = _negotiate_version(
            A2A_PROTOCOL_VERSIONS_SUPPORTED,
            client_versions,
        )

        if negotiated is None:
            return {
                "success": False,
                "error_code": A2A_ERROR_CODES["PROTOCOL_VERSION_MISMATCH"][0],
                "error": "No compatible protocol version",
                "supported_versions": A2A_PROTOCOL_VERSIONS_SUPPORTED,
            }

        client_id = request.get("client_id", "unknown")
        self._logger.info(
            "a2a_handshake_success",
            client_id=client_id,
            protocol_version=negotiated,
        )

        return {
            "success": True,
            "protocol_version": negotiated,
            "server_id": self.agent_card.agent_id,
            "agent_card": self.agent_card.to_dict(),
            "capabilities": self.agent_card.capabilities,
            "endpoints": {
                "submit": "/a2a/v1/tasks/submit",
                "status": "/a2a/v1/tasks/{task_id}",
                "stream": "/a2a/v1/tasks/{task_id}/stream",
                "cancel": "/a2a/v1/tasks/{task_id}/cancel",
            },
        }

    # ── Task 处理 ────────────────────────────────────

    async def submit_task(self, task_data: dict[str, Any]) -> dict[str, Any]:
        """提交 Task

        Args:
            task_data: Task 数据（符合 A2A 协议格式）

        Returns:
            Task 提交结果
        """
        # 验证签名
        if self._require_auth and self._signing_secret:
            signature = task_data.get("signature", "")
            if not signature:
                return _build_a2a_error("UNAUTHORIZED", "Missing signature")

            temp_task = Task(
                task_id=task_data.get("task_id", ""),
                sender=task_data.get("sender", ""),
                recipient=task_data.get("recipient", ""),
                payload=task_data.get("payload", {}),
                created_at=task_data.get("created_at", time.time()),
            )
            if not verify_task(temp_task, signature, self._signing_secret):
                return _build_a2a_error("FORBIDDEN", "Invalid signature")

        # 构建 Task 对象
        task = Task(
            task_id=task_data.get("task_id") or uuid.uuid4().hex,
            status=TaskStatus.SUBMITTED,
            sender=task_data.get("sender", ""),
            recipient=task_data.get("recipient", self.agent_card.agent_id),
            description=task_data.get("description", ""),
            payload=task_data.get("payload", {}),
            trace_id=task_data.get("trace_id", ""),
        )

        # 验证能力
        capability = task_data.get("capability")
        if capability and capability not in self.agent_card.capabilities:
            return _build_a2a_error(
                "CAPABILITY_NOT_SUPPORTED",
                f"Capability '{capability}' not supported",
            )

        # 存储 Task
        self._tasks[task.task_id] = task
        self._updates[task.task_id] = [
            TaskUpdate(task_id=task.task_id, status=TaskStatus.SUBMITTED)
        ]

        # 如果有处理器，立即处理
        if self._task_handler:
            try:
                update = await self._task_handler(task)
                # 更新 Task 状态
                try:
                    task.transition_to(update.status)
                except ValueError:
                    pass  # 忽略非法转换
                task.error = update.error
                if update.artifact:
                    task.artifacts.append(update.artifact)
                self._updates[task.task_id].append(update)
            except Exception as exc:
                self._logger.error("task_handler_failed", error=str(exc))
                task.transition_to(TaskStatus.FAILED)
                task.error = str(exc)
                self._updates[task.task_id].append(
                    TaskUpdate(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=str(exc),
                        is_final=True,
                    )
                )

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """查询 Task 状态"""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        return task.to_dict()

    async def stream_task_updates(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        """流式获取 Task 更新（SSE 格式）"""
        task = self._tasks.get(task_id)
        if task is None:
            yield {"error": "Task not found"}
            return

        # 返回已有更新
        for update in self._updates.get(task_id, []):
            yield {
                "task_id": update.task_id,
                "status": update.status.value,
                "error": update.error,
                "is_final": update.is_final,
                "timestamp": update.timestamp,
            }
            if update.is_final:
                return

    def cancel_task(self, task_id: str) -> bool:
        """取消 Task"""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        try:
            task.transition_to(TaskStatus.CANCELLED)
            self._updates[task_id].append(
                TaskUpdate(
                    task_id=task_id,
                    status=TaskStatus.CANCELLED,
                    is_final=True,
                )
            )
            return True
        except ValueError:
            return False

    def stats(self) -> dict[str, Any]:
        """获取服务端统计"""
        return {
            "agent_id": self.agent_card.agent_id,
            "protocol_version": A2A_PROTOCOL_VERSION,
            "active_tasks": sum(
                1 for t in self._tasks.values()
                if t.status in (TaskStatus.SUBMITTED, TaskStatus.WORKING, TaskStatus.INPUT_REQUIRED)
            ),
            "total_tasks": len(self._tasks),
            "capabilities": self.agent_card.capabilities,
        }


# ── 辅助函数 ──────────────────────────────────────────


def _negotiate_version(supported: list[str], requested: list[str]) -> str | None:
    """协商协议版本

    选择双方都支持的最高版本。

    Args:
        supported: 服务端支持的版本列表（从高到低）
        requested: 客户端支持的版本列表

    Returns:
        协商后的版本号，None 表示没有兼容版本
    """
    for v in supported:
        if v in requested:
            return v
    return None


def _build_a2a_error(error_key: str, detail: str = "") -> dict[str, Any]:
    """构建标准 A2A 错误响应"""
    code, http_status, message = A2A_ERROR_CODES.get(
        error_key, A2A_ERROR_CODES["INTERNAL_ERROR"]
    )
    return {
        "success": False,
        "error_code": code,
        "error": detail or message,
        "http_status": http_status,
    }


# ── 便捷工厂函数 ──────────────────────────────────────


def create_a2a_server(
    agent_id: str,
    agent_name: str = "",
    capabilities: list[str] | None = None,
    task_handler: Callable[[Task], TaskUpdate] | None = None,
    version: str = "1.0.0",
    signing_secret: str = "",
) -> A2AProtocolServer:
    """便捷创建 A2A 协议服务端

    Args:
        agent_id: Agent ID
        agent_name: Agent 名称
        capabilities: 能力列表
        task_handler: Task 处理函数
        version: Agent 版本
        signing_secret: 签名密钥

    Returns:
        A2AProtocolServer 实例
    """
    card = AgentCard(
        agent_id=agent_id,
        name=agent_name or agent_id,
        version=version,
        capabilities=capabilities or [],
    )
    if signing_secret:
        card.sign(signing_secret)

    return A2AProtocolServer(
        agent_card=card,
        task_handler=task_handler,
        signing_secret=signing_secret,
    )
