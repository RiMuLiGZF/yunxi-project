"""端云协同通信协议.

定义端云之间的标准通信协议，包括：
1. 同步协议 (Sync Protocol)
2. 任务分发协议 (Task Distribution Protocol)
3. 心跳协议 (Heartbeat Protocol)
4. 握手协议 (Handshake Protocol)

所有协议消息均使用 JSON 格式，遵循统一的消息头结构。
向后兼容：不修改现有协议实现，作为标准协议层提供。
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "1.0.0"
DEFAULT_HEARTBEAT_INTERVAL = 30  # 秒
DEFAULT_SESSION_TIMEOUT = 3600  # 秒
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class ProtocolVersion(str, Enum):
    """协议版本枚举.

    Attributes:
        V1_0_0: 协议版本 1.0.0.
    """

    V1_0_0 = "1.0.0"


class MessageType(str, Enum):
    """消息类型枚举.

    Attributes:
        HANDSHAKE: 握手消息.
        HEARTBEAT: 心跳消息.
        SYNC_PUSH: 同步推送.
        SYNC_PULL: 同步拉取.
        SYNC_ACK: 同步确认.
        SYNC_CONFLICT: 同步冲突.
        TASK_SUBMIT: 任务提交.
        TASK_ASSIGN: 任务分配.
        TASK_RESULT: 任务结果.
        TASK_ACK: 任务确认.
        DEVICE_REGISTER: 设备注册.
        DEVICE_STATUS: 设备状态.
        ERROR: 错误消息.
    """

    HANDSHAKE = "handshake"
    HEARTBEAT = "heartbeat"
    SYNC_PUSH = "sync_push"
    SYNC_PULL = "sync_pull"
    SYNC_ACK = "sync_ack"
    SYNC_CONFLICT = "sync_conflict"
    TASK_SUBMIT = "task_submit"
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_ACK = "task_ack"
    DEVICE_REGISTER = "device_register"
    DEVICE_STATUS = "device_status"
    ERROR = "error"


class SyncPhase(str, Enum):
    """同步阶段枚举.

    Attributes:
        HANDSHAKE: 握手阶段.
        DELTA_EXCHANGE: 增量交换阶段.
        CONFLICT_RESOLUTION: 冲突解决阶段.
        COMMIT: 提交阶段.
        COMPLETED: 完成.
    """

    HANDSHAKE = "handshake"
    DELTA_EXCHANGE = "delta_exchange"
    CONFLICT_RESOLUTION = "conflict_resolution"
    COMMIT = "commit"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# 消息头
# ---------------------------------------------------------------------------


@dataclass
class MessageHeader:
    """统一消息头.

    Attributes:
        message_id: 消息唯一标识.
        message_type: 消息类型.
        protocol_version: 协议版本.
        device_id: 发送方设备 ID.
        session_id: 会话 ID.
        timestamp: 发送时间戳.
        sequence: 消息序列号（同一会话内递增）.
        checksum: 消息体校验和.
        priority: 消息优先级（0-10）.
        ttl: 消息存活时间（秒）.
    """

    message_id: str
    message_type: MessageType
    protocol_version: str = PROTOCOL_VERSION
    device_id: str = ""
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0
    checksum: str = ""
    priority: int = 5
    ttl: int = 300

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "protocol_version": self.protocol_version,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "checksum": self.checksum,
            "priority": self.priority,
            "ttl": self.ttl,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageHeader":
        """从字典反序列化."""
        return cls(
            message_id=data["message_id"],
            message_type=MessageType(data["message_type"]),
            protocol_version=data.get("protocol_version", PROTOCOL_VERSION),
            device_id=data.get("device_id", ""),
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp", time.time()),
            sequence=data.get("sequence", 0),
            checksum=data.get("checksum", ""),
            priority=data.get("priority", 5),
            ttl=data.get("ttl", 300),
        )


@dataclass
class ProtocolMessage:
    """协议消息.

    统一的端云消息格式，包含消息头和消息体。

    Attributes:
        header: 消息头.
        body: 消息体.
    """

    header: MessageHeader
    body: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典."""
        return {
            "header": self.header.to_dict(),
            "body": self.body,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "ProtocolMessage":
        """从 JSON 字符串反序列化."""
        data = json.loads(json_str)
        header = MessageHeader.from_dict(data["header"])
        return cls(header=header, body=data.get("body", {}))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProtocolMessage":
        """从字典反序列化."""
        header = MessageHeader.from_dict(data["header"])
        return cls(header=header, body=data.get("body", {}))

    def compute_checksum(self) -> str:
        """计算消息体校验和."""
        body_str = json.dumps(self.body, sort_keys=True, default=str)
        return hashlib.sha256(body_str.encode("utf-8")).hexdigest()

    def verify_checksum(self) -> bool:
        """校验消息校验和."""
        if not self.header.checksum:
            return True
        computed = self.compute_checksum()
        return computed == self.header.checksum

    def is_expired(self) -> bool:
        """检查消息是否已过期."""
        return (time.time() - self.header.timestamp) > self.header.ttl


# ---------------------------------------------------------------------------
# 4.1 握手协议
# ---------------------------------------------------------------------------


@dataclass
class HandshakeRequest:
    """握手请求.

    Attributes:
        device_id: 设备 ID.
        device_type: 设备类型.
        device_name: 设备名称.
        client_version: 客户端版本.
        supported_protocols: 支持的协议版本列表.
        capabilities: 设备能力列表.
        sync_scopes: 请求的同步范围.
        metadata: 附加元数据.
    """

    device_id: str
    device_type: str = "unknown"
    device_name: str = ""
    client_version: str = ""
    supported_protocols: list[str] = field(default_factory=lambda: [PROTOCOL_VERSION])
    capabilities: list[str] = field(default_factory=list)
    sync_scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_message(self, session_id: str = "") -> ProtocolMessage:
        """转换为协议消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.HANDSHAKE,
            device_id=self.device_id,
            session_id=session_id,
            priority=10,
        )
        body = {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "device_name": self.device_name,
            "client_version": self.client_version,
            "supported_protocols": self.supported_protocols,
            "capabilities": self.capabilities,
            "sync_scopes": self.sync_scopes,
            "metadata": self.metadata,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg


@dataclass
class HandshakeResponse:
    """握手响应.

    Attributes:
        success: 是否成功.
        session_id: 会话 ID.
        server_version: 服务端版本.
        negotiated_protocol: 协商后的协议版本.
        heartbeat_interval: 心跳间隔（秒）.
        assigned_capabilities: 分配的能力列表.
        sync_cursor: 同步游标（初始版本向量）.
        error: 错误信息（失败时）.
    """

    success: bool
    session_id: str = ""
    server_version: str = ""
    negotiated_protocol: str = PROTOCOL_VERSION
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL
    assigned_capabilities: list[str] = field(default_factory=list)
    sync_cursor: dict[str, int] = field(default_factory=dict)
    error: str = ""

    def to_message(self, device_id: str = "") -> ProtocolMessage:
        """转换为协议消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.HANDSHAKE,
            device_id=device_id,
            session_id=self.session_id,
            priority=10,
        )
        body = {
            "success": self.success,
            "session_id": self.session_id,
            "server_version": self.server_version,
            "negotiated_protocol": self.negotiated_protocol,
            "heartbeat_interval": self.heartbeat_interval,
            "assigned_capabilities": self.assigned_capabilities,
            "sync_cursor": self.sync_cursor,
            "error": self.error,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg


# ---------------------------------------------------------------------------
# 4.2 心跳协议
# ---------------------------------------------------------------------------


@dataclass
class HeartbeatMessage:
    """心跳消息.

    Attributes:
        device_id: 设备 ID.
        session_id: 会话 ID.
        status: 设备状态（online/busy/idle/error）.
        cpu_usage: CPU 使用率.
        memory_usage: 内存使用率.
        battery_level: 电池电量.
        network_latency_ms: 网络延迟.
        active_tasks: 活跃任务数.
        metrics: 附加性能指标.
    """

    device_id: str
    session_id: str = ""
    status: str = "online"
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    battery_level: float = -1.0
    network_latency_ms: float = 0.0
    active_tasks: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> ProtocolMessage:
        """转换为协议消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.HEARTBEAT,
            device_id=self.device_id,
            session_id=self.session_id,
            priority=8,
            ttl=DEFAULT_HEARTBEAT_INTERVAL * 3,
        )
        body = {
            "device_id": self.device_id,
            "status": self.status,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "battery_level": self.battery_level,
            "network_latency_ms": self.network_latency_ms,
            "active_tasks": self.active_tasks,
            "metrics": self.metrics,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg

    @classmethod
    def from_message(cls, msg: ProtocolMessage) -> "HeartbeatMessage":
        """从协议消息解析."""
        body = msg.body
        return cls(
            device_id=body.get("device_id", msg.header.device_id),
            session_id=msg.header.session_id,
            status=body.get("status", "online"),
            cpu_usage=body.get("cpu_usage", 0.0),
            memory_usage=body.get("memory_usage", 0.0),
            battery_level=body.get("battery_level", -1.0),
            network_latency_ms=body.get("network_latency_ms", 0.0),
            active_tasks=body.get("active_tasks", 0),
            metrics=body.get("metrics", {}),
        )


# ---------------------------------------------------------------------------
# 4.3 同步协议
# ---------------------------------------------------------------------------


@dataclass
class SyncProtocol:
    """同步协议处理器.

    实现端云同步协议的状态机，管理同步会话的生命周期：
    握手 -> 增量交换 -> 冲突解决 -> 提交 -> 完成

    Attributes:
        _sessions: 同步会话字典 {session_id: session_state}.
        _sync_cursors: 同步游标 {session_id: {scope: version}}.
        _conflict_registry: 冲突注册表 {session_id: [conflict, ...]}.
    """

    def __init__(self) -> None:
        """初始化同步协议处理器."""
        self._sessions: dict[str, dict[str, Any]] = {}
        self._sync_cursors: dict[str, dict[str, int]] = {}
        self._conflict_registry: dict[str, list[dict[str, Any]]] = {}
        logger.info("sync_protocol.init")

    def create_session(
        self,
        device_id: str,
        sync_scopes: list[str] | None = None,
    ) -> str:
        """创建同步会话.

        Args:
            device_id: 设备 ID.
            sync_scopes: 同步范围列表.

        Returns:
            会话 ID.
        """
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = {
            "device_id": device_id,
            "phase": SyncPhase.HANDSHAKE,
            "scopes": sync_scopes or [],
            "created_at": time.time(),
            "last_active": time.time(),
            "sequence": 0,
        }
        self._sync_cursors[session_id] = {}
        self._conflict_registry[session_id] = []

        logger.info(
            "sync_protocol.session_created",
            session_id=session_id,
            device_id=device_id,
            scopes=sync_scopes,
        )
        return session_id

    def handshake(
        self,
        request: HandshakeRequest,
    ) -> HandshakeResponse:
        """处理握手请求.

        Args:
            request: 握手请求.

        Returns:
            握手响应.
        """
        session_id = self.create_session(
            device_id=request.device_id,
            sync_scopes=request.sync_scopes,
        )

        # 协商协议版本
        negotiated = PROTOCOL_VERSION
        for version in request.supported_protocols:
            if version == PROTOCOL_VERSION:
                negotiated = version
                break

        # 更新会话状态
        if session_id in self._sessions:
            self._sessions[session_id]["phase"] = SyncPhase.DELTA_EXCHANGE
            self._sessions[session_id]["last_active"] = time.time()

        # 初始化同步游标
        self._sync_cursors[session_id] = {
            scope: 0 for scope in request.sync_scopes
        }

        response = HandshakeResponse(
            success=True,
            session_id=session_id,
            server_version="2.1.0",
            negotiated_protocol=negotiated,
            heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL,
            assigned_capabilities=request.capabilities,
            sync_cursor=dict(self._sync_cursors.get(session_id, {})),
        )

        logger.info(
            "sync_protocol.handshake_success",
            session_id=session_id,
            device_id=request.device_id,
            protocol=negotiated,
        )
        return response

    def push_changes(
        self,
        session_id: str,
        changes: list[dict[str, Any]],
        version_vector: dict[str, int],
    ) -> dict[str, Any]:
        """处理推送变更请求.

        Args:
            session_id: 会话 ID.
            changes: 变更列表.
            version_vector: 客户端版本向量.

        Returns:
            推送结果 {accepted, rejected, conflicts}.
        """
        if session_id not in self._sessions:
            return {
                "accepted": [],
                "rejected": [c.get("item_id", "") for c in changes],
                "conflicts": [],
                "error": "Session not found",
            }

        session = self._sessions[session_id]
        session["last_active"] = time.time()
        session["sequence"] += 1

        # 更新游标
        cursor = self._sync_cursors.get(session_id, {})
        for scope, version in version_vector.items():
            cursor[scope] = max(cursor.get(scope, 0), version)
        self._sync_cursors[session_id] = cursor

        # 模拟处理（实际应委托给 SyncEngine）
        accepted: list[str] = []
        rejected: list[str] = []
        conflicts: list[dict[str, Any]] = []

        for change in changes:
            item_id = change.get("item_id", "")
            # 简单策略：全部接受
            accepted.append(item_id)

        logger.debug(
            "sync_protocol.push_processed",
            session_id=session_id,
            total=len(changes),
            accepted=len(accepted),
            conflicts=len(conflicts),
        )

        return {
            "accepted": accepted,
            "rejected": rejected,
            "conflicts": conflicts,
            "new_cursor": dict(cursor),
        }

    def pull_changes(
        self,
        session_id: str,
        since_cursor: dict[str, int],
    ) -> dict[str, Any]:
        """处理拉取变更请求.

        Args:
            session_id: 会话 ID.
            since_cursor: 客户端游标.

        Returns:
            拉取结果 {changes, cursor}.
        """
        if session_id not in self._sessions:
            return {"changes": [], "cursor": {}, "error": "Session not found"}

        session = self._sessions[session_id]
        session["last_active"] = time.time()
        session["sequence"] += 1

        # 更新游标
        cursor = self._sync_cursors.get(session_id, {})

        logger.debug(
            "sync_protocol.pull_processed",
            session_id=session_id,
            scopes=session.get("scopes", []),
        )

        return {
            "changes": [],
            "cursor": dict(cursor),
            "server_version": "2.1.0",
        }

    def resolve_conflicts(
        self,
        session_id: str,
        conflict_ids: list[str],
        resolution: str,
    ) -> dict[str, Any]:
        """处理冲突解决请求.

        Args:
            session_id: 会话 ID.
            conflict_ids: 冲突 ID 列表.
            resolution: 解决策略.

        Returns:
            解决结果 {resolved, failed}.
        """
        if session_id not in self._sessions:
            return {"resolved": [], "failed": conflict_ids, "error": "Session not found"}

        session = self._sessions[session_id]
        session["last_active"] = time.time()

        # 模拟：全部成功解决
        resolved = conflict_ids
        failed: list[str] = []

        # 更新阶段
        if session["phase"] == SyncPhase.CONFLICT_RESOLUTION and not failed:
            session["phase"] = SyncPhase.COMMIT

        logger.info(
            "sync_protocol.conflicts_resolved",
            session_id=session_id,
            total=len(conflict_ids),
            resolved=len(resolved),
            resolution=resolution,
        )

        return {"resolved": resolved, "failed": failed}

    def complete_session(self, session_id: str) -> bool:
        """完成同步会话.

        Args:
            session_id: 会话 ID.

        Returns:
            是否成功.
        """
        if session_id not in self._sessions:
            return False

        self._sessions[session_id]["phase"] = SyncPhase.COMPLETED
        self._sessions[session_id]["last_active"] = time.time()

        logger.info("sync_protocol.session_completed", session_id=session_id)
        return True

    def get_session_status(self, session_id: str) -> dict[str, Any] | None:
        """获取会话状态.

        Args:
            session_id: 会话 ID.

        Returns:
            会话状态字典，不存在返回 None.
        """
        session = self._sessions.get(session_id)
        if not session:
            return None

        return {
            "session_id": session_id,
            "device_id": session["device_id"],
            "phase": session["phase"].value,
            "scopes": session["scopes"],
            "created_at": session["created_at"],
            "last_active": session["last_active"],
            "sequence": session["sequence"],
            "cursor": dict(self._sync_cursors.get(session_id, {})),
            "conflict_count": len(self._conflict_registry.get(session_id, [])),
        }

    def cleanup_expired_sessions(self, ttl: int = DEFAULT_SESSION_TIMEOUT) -> int:
        """清理过期会话.

        Args:
            ttl: 会话超时时间（秒）.

        Returns:
            清理的会话数.
        """
        now = time.time()
        expired = [
            sid for sid, sess in self._sessions.items()
            if now - sess["last_active"] > ttl
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
            self._sync_cursors.pop(sid, None)
            self._conflict_registry.pop(sid, None)

        if expired:
            logger.info("sync_protocol.expired_sessions_cleaned", count=len(expired))
        return len(expired)


# ---------------------------------------------------------------------------
# 4.4 任务分发协议
# ---------------------------------------------------------------------------


@dataclass
class TaskDistributionMessage:
    """任务分发消息.

    Attributes:
        task_id: 任务 ID.
        task_type: 任务类型.
        priority: 优先级（0-10）.
        payload: 任务数据.
        estimated_complexity: 预估复杂度.
        estimated_duration_ms: 预估耗时（毫秒）.
        target_device_id: 目标设备 ID（云端下发时使用）.
        result: 任务结果（设备上报时使用）.
        status: 任务状态.
    """

    task_id: str
    task_type: str = "general"
    priority: int = 5
    payload: dict[str, Any] = field(default_factory=dict)
    estimated_complexity: float = 50.0
    estimated_duration_ms: float = 0.0
    target_device_id: str = ""
    result: Any = None
    status: str = "pending"

    def to_submit_message(self, device_id: str = "") -> ProtocolMessage:
        """转换为任务提交消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TASK_SUBMIT,
            device_id=device_id,
            priority=self.priority,
        )
        body = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "priority": self.priority,
            "payload": self.payload,
            "estimated_complexity": self.estimated_complexity,
            "estimated_duration_ms": self.estimated_duration_ms,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg

    def to_assign_message(self, session_id: str = "") -> ProtocolMessage:
        """转换为任务分配消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TASK_ASSIGN,
            device_id=self.target_device_id,
            session_id=session_id,
            priority=self.priority,
        )
        body = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "priority": self.priority,
            "payload": self.payload,
            "estimated_complexity": self.estimated_complexity,
            "estimated_duration_ms": self.estimated_duration_ms,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg

    def to_result_message(self, device_id: str = "", session_id: str = "") -> ProtocolMessage:
        """转换为任务结果消息."""
        header = MessageHeader(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TASK_RESULT,
            device_id=device_id,
            session_id=session_id,
            priority=self.priority,
        )
        body = {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
        }
        msg = ProtocolMessage(header=header, body=body)
        msg.header.checksum = msg.compute_checksum()
        return msg

    @classmethod
    def from_message(cls, msg: ProtocolMessage) -> "TaskDistributionMessage":
        """从协议消息解析."""
        body = msg.body
        return cls(
            task_id=body.get("task_id", ""),
            task_type=body.get("task_type", "general"),
            priority=body.get("priority", 5),
            payload=body.get("payload", {}),
            estimated_complexity=body.get("estimated_complexity", 50.0),
            estimated_duration_ms=body.get("estimated_duration_ms", 0.0),
            target_device_id=msg.header.device_id,
            result=body.get("result"),
            status=body.get("status", "pending"),
        )


# ---------------------------------------------------------------------------
# 协议验证工具
# ---------------------------------------------------------------------------


def validate_message(msg: ProtocolMessage) -> tuple[bool, str]:
    """验证协议消息的合法性.

    Args:
        msg: 协议消息.

    Returns:
        (is_valid, error_message) 元组.
    """
    # 检查消息 ID
    if not msg.header.message_id:
        return False, "Missing message_id"

    # 检查消息类型
    try:
        MessageType(msg.header.message_type.value)
    except ValueError:
        return False, f"Invalid message_type: {msg.header.message_type}"

    # 检查过期
    if msg.is_expired():
        return False, "Message expired"

    # 校验和验证
    if msg.header.checksum and not msg.verify_checksum():
        return False, "Checksum mismatch"

    # 检查消息大小
    try:
        msg_size = len(msg.to_json())
        if msg_size > MAX_MESSAGE_SIZE:
            return False, f"Message too large: {msg_size} > {MAX_MESSAGE_SIZE}"
    except Exception:
        pass

    return True, ""
