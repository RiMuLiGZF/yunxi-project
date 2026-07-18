"""端云协同通信协议测试.

覆盖：
- 同步协议 (Sync Protocol)
- 任务分发协议 (Task Distribution)
- 心跳协议 (Heartbeat)
- 握手协议 (Handshake)
- 消息序列化/反序列化
- 校验和验证
"""

from __future__ import annotations

import json
import time

import pytest

from edge_cloud_kernel.services.protocol import (
    HandshakeRequest,
    HandshakeResponse,
    HeartbeatMessage,
    MessageHeader,
    MessageType,
    ProtocolMessage,
    ProtocolVersion,
    SyncPhase,
    SyncProtocol,
    TaskDistributionMessage,
    validate_message,
)


# ============================================================
# 枚举值测试
# ============================================================

class TestEnums:
    """枚举值测试."""

    def test_protocol_version_values(self):
        """测试协议版本枚举值."""
        assert ProtocolVersion.V1_0_0 == "1.0.0"

    def test_message_type_values(self):
        """测试消息类型枚举值."""
        assert MessageType.HANDSHAKE == "handshake"
        assert MessageType.HEARTBEAT == "heartbeat"
        assert MessageType.SYNC_PUSH == "sync_push"
        assert MessageType.SYNC_PULL == "sync_pull"
        assert MessageType.SYNC_ACK == "sync_ack"
        assert MessageType.SYNC_CONFLICT == "sync_conflict"
        assert MessageType.TASK_SUBMIT == "task_submit"
        assert MessageType.TASK_ASSIGN == "task_assign"
        assert MessageType.TASK_RESULT == "task_result"
        assert MessageType.TASK_ACK == "task_ack"
        assert MessageType.DEVICE_REGISTER == "device_register"
        assert MessageType.DEVICE_STATUS == "device_status"
        assert MessageType.ERROR == "error"

    def test_sync_phase_values(self):
        """测试同步阶段枚举值."""
        assert SyncPhase.HANDSHAKE == "handshake"
        assert SyncPhase.DELTA_EXCHANGE == "delta_exchange"
        assert SyncPhase.CONFLICT_RESOLUTION == "conflict_resolution"
        assert SyncPhase.COMMIT == "commit"
        assert SyncPhase.COMPLETED == "completed"


# ============================================================
# 消息头测试
# ============================================================

class TestMessageHeader:
    """消息头测试."""

    def test_create_header(self):
        """测试创建消息头."""
        header = MessageHeader(
            message_id="msg-001",
            message_type=MessageType.HANDSHAKE,
            protocol_version=ProtocolVersion.V1_0_0,
            device_id="dev-001",
            session_id="sess-001",
        )
        assert header.message_id == "msg-001"
        assert header.message_type == MessageType.HANDSHAKE
        assert header.protocol_version == ProtocolVersion.V1_0_0
        assert header.device_id == "dev-001"
        assert header.session_id == "sess-001"

    def test_header_to_dict(self):
        """测试消息头转字典."""
        header = MessageHeader(
            message_id="msg-002",
            message_type=MessageType.HEARTBEAT,
        )
        d = header.to_dict()
        assert isinstance(d, dict)
        assert d["message_id"] == "msg-002"
        assert d["message_type"] == "heartbeat"

    def test_header_from_dict(self):
        """测试从字典创建消息头."""
        data = {
            "message_id": "msg-003",
            "message_type": "sync_push",
            "protocol_version": "1.0.0",
            "device_id": "dev-003",
            "session_id": "sess-003",
            "timestamp": time.time(),
        }
        header = MessageHeader.from_dict(data)
        assert header.message_id == "msg-003"
        assert header.message_type == MessageType.SYNC_PUSH
        assert header.device_id == "dev-003"


# ============================================================
# 协议消息测试
# ============================================================

class TestProtocolMessage:
    """协议消息测试."""

    def test_create_message(self):
        """测试创建协议消息."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-001",
                message_type=MessageType.HANDSHAKE,
            ),
            body={"data": "test"},
        )
        assert msg.header.message_id == "msg-001"
        assert msg.body == {"data": "test"}

    def test_message_to_json(self):
        """测试消息序列化为 JSON."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-json",
                message_type=MessageType.HEARTBEAT,
            ),
            body={"status": "ok"},
        )
        json_str = msg.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["header"]["message_id"] == "msg-json"

    def test_message_from_json(self):
        """测试从 JSON 反序列化消息."""
        data = {
            "header": {
                "message_id": "msg-from-json",
                "message_type": "sync_pull",
                "protocol_version": "1.0.0",
                "timestamp": time.time(),
            },
            "body": {"cursor": "abc123"},
        }
        json_str = json.dumps(data)
        msg = ProtocolMessage.from_json(json_str)
        assert msg.header.message_id == "msg-from-json"
        assert msg.body["cursor"] == "abc123"

    def test_message_from_dict(self):
        """测试从字典创建消息."""
        data = {
            "header": {
                "message_id": "msg-dict",
                "message_type": "task_submit",
                "protocol_version": "1.0.0",
                "timestamp": time.time(),
            },
            "body": {"task": {"id": "t1"}},
        }
        msg = ProtocolMessage.from_dict(data)
        assert msg.header.message_type == MessageType.TASK_SUBMIT
        assert msg.body["task"]["id"] == "t1"

    def test_compute_checksum(self):
        """测试计算校验和."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-checksum",
                message_type=MessageType.SYNC_ACK,
            ),
            body={"ack": True},
        )
        checksum = msg.compute_checksum()
        assert isinstance(checksum, str)
        assert len(checksum) > 0

    def test_verify_checksum(self):
        """测试校验和验证."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-verify",
                message_type=MessageType.SYNC_PUSH,
            ),
            body={"data": [1, 2, 3]},
        )
        # 计算并设置校验和
        checksum = msg.compute_checksum()
        msg.header.checksum = checksum
        assert msg.verify_checksum() is True

    def test_verify_checksum_tampered(self):
        """测试篡改后校验和验证失败."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-tamper",
                message_type=MessageType.SYNC_PUSH,
            ),
            body={"data": "original"},
        )
        checksum = msg.compute_checksum()
        msg.header.checksum = checksum
        # 篡改数据
        msg.body = {"data": "tampered"}
        assert msg.verify_checksum() is False

    def test_is_expired_false(self):
        """测试消息未过期."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-expire",
                message_type=MessageType.HEARTBEAT,
                ttl=3600,
            ),
            body={},
        )
        assert msg.is_expired() is False

    def test_is_expired_true(self):
        """测试消息已过期."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-expired",
                message_type=MessageType.HEARTBEAT,
                timestamp=time.time() - 10,
                ttl=1,
            ),
            body={},
        )
        assert msg.is_expired() is True


# ============================================================
# 握手协议测试
# ============================================================

class TestHandshakeProtocol:
    """握手协议测试."""

    def test_handshake_request_creation(self):
        """测试创建握手请求."""
        req = HandshakeRequest(
            device_id="dev-hs-1",
            device_type="phone",
            client_version="1.0.0",
            capabilities=["sync", "edge_compute"],
        )
        assert req.device_id == "dev-hs-1"
        assert req.device_type == "phone"
        assert req.client_version == "1.0.0"
        assert len(req.capabilities) == 2

    def test_handshake_request_to_message(self):
        """测试握手请求转消息."""
        req = HandshakeRequest(
            device_id="dev-hs-2",
            device_type="tablet",
            client_version="2.0.0",
        )
        msg = req.to_message(session_id="sess-hs")
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.HANDSHAKE
        assert msg.header.session_id == "sess-hs"

    def test_handshake_response_creation(self):
        """测试创建握手响应."""
        resp = HandshakeResponse(
            success=True,
            session_id="sess-resp",
            server_version="1.0.0",
        )
        assert resp.success is True
        assert resp.session_id == "sess-resp"
        assert resp.server_version == "1.0.0"

    def test_handshake_response_to_message(self):
        """测试握手响应转消息."""
        resp = HandshakeResponse(
            success=True,
            session_id="sess-msg",
            server_version="1.0.0",
        )
        msg = resp.to_message(device_id="dev-resp")
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.HANDSHAKE
        assert msg.header.device_id == "dev-resp"


# ============================================================
# 心跳协议测试
# ============================================================

class TestHeartbeatProtocol:
    """心跳协议测试."""

    def test_heartbeat_creation(self):
        """测试创建心跳消息."""
        hb = HeartbeatMessage(
            device_id="dev-hb-1",
            cpu_usage=30.5,
            memory_usage=55.0,
            battery_level=85.0,
            network_latency_ms=25.0,
        )
        assert hb.device_id == "dev-hb-1"
        assert hb.cpu_usage == 30.5
        assert hb.memory_usage == 55.0
        assert hb.battery_level == 85.0

    def test_heartbeat_to_message(self):
        """测试心跳消息转 ProtocolMessage."""
        hb = HeartbeatMessage(
            device_id="dev-hb-2",
        )
        msg = hb.to_message()
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.HEARTBEAT

    def test_heartbeat_from_message(self):
        """测试从 ProtocolMessage 解析心跳."""
        hb = HeartbeatMessage(
            device_id="dev-hb-3",
            cpu_usage=42.0,
            battery_level=78.0,
        )
        msg = hb.to_message()
        parsed = HeartbeatMessage.from_message(msg)
        assert parsed.device_id == "dev-hb-3"
        assert parsed.cpu_usage == 42.0
        assert parsed.battery_level == 78.0


# ============================================================
# 同步协议测试
# ============================================================

class TestSyncProtocol:
    """同步协议测试."""

    def test_create_sync_protocol(self):
        """测试创建同步协议实例."""
        protocol = SyncProtocol()
        assert protocol is not None

    def test_create_session(self):
        """测试创建同步会话."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-sync-1",
            sync_scopes=["conversation", "settings"],
        )
        assert session_id is not None
        assert isinstance(session_id, str)
        # 获取会话状态验证
        status = protocol.get_session_status(session_id)
        assert status is not None
        assert status["device_id"] == "dev-sync-1"
        assert "scopes" in status

    def test_handshake(self):
        """测试握手流程."""
        protocol = SyncProtocol()
        request = HandshakeRequest(
            device_id="dev-hs-proto",
            client_version="1.0.0",
            capabilities=["sync"],
        )
        result = protocol.handshake(request)
        assert result is not None
        assert isinstance(result, HandshakeResponse)
        assert result.success is True
        assert result.session_id != ""

    def test_push_changes(self):
        """测试推送变更."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-push",
            sync_scopes=["conversation"],
        )
        changes = [
            {"item_id": "1", "op": "create", "data": {"text": "hello"}},
            {"item_id": "2", "op": "update", "data": {"text": "world"}},
        ]
        result = protocol.push_changes(
            session_id=session_id,
            changes=changes,
            version_vector={"conversation": 5},
        )
        assert result is not None
        assert "accepted" in result
        assert "rejected" in result
        assert "conflicts" in result

    def test_pull_changes(self):
        """测试拉取变更."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-pull",
            sync_scopes=["conversation"],
        )
        result = protocol.pull_changes(
            session_id=session_id,
            since_cursor={"conversation": 0},
        )
        assert result is not None
        assert "changes" in result
        assert "cursor" in result

    def test_resolve_conflicts(self):
        """测试解决冲突."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-conflict",
            sync_scopes=["conversation"],
        )
        conflict_ids = ["c1", "c2"]
        result = protocol.resolve_conflicts(
            session_id=session_id,
            conflict_ids=conflict_ids,
            resolution="local_win",
        )
        assert result is not None
        assert "resolved" in result
        assert "failed" in result

    def test_complete_session(self):
        """测试完成会话."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-complete",
            sync_scopes=["conversation"],
        )
        result = protocol.complete_session(session_id)
        assert result is True

    def test_get_session_status(self):
        """测试获取会话状态."""
        protocol = SyncProtocol()
        session_id = protocol.create_session(
            device_id="dev-status",
            sync_scopes=["conversation"],
        )
        status = protocol.get_session_status(session_id)
        assert status is not None
        assert "phase" in status
        assert status["device_id"] == "dev-status"

    def test_get_session_status_nonexistent(self):
        """测试获取不存在会话的状态."""
        protocol = SyncProtocol()
        status = protocol.get_session_status("nonexistent")
        assert status is None

    def test_cleanup_expired_sessions(self):
        """测试清理过期会话."""
        protocol = SyncProtocol()
        # 创建会话（TTL 很短，手动修改 last_active）
        session_id = protocol.create_session(
            device_id="dev-expired",
            sync_scopes=["conversation"],
        )
        # 手动设置为过期
        protocol._sessions[session_id]["last_active"] = time.time() - 7200
        count = protocol.cleanup_expired_sessions(ttl=3600)
        assert isinstance(count, int)
        assert count >= 1


# ============================================================
# 任务分发协议测试
# ============================================================

class TestTaskDistribution:
    """任务分发协议测试."""

    def test_create_task_message(self):
        """测试创建任务分发消息."""
        task = TaskDistributionMessage(
            task_id="task-001",
            task_type="compute",
            payload={"input": [1, 2, 3]},
            priority=8,
        )
        assert task.task_id == "task-001"
        assert task.task_type == "compute"
        assert task.priority == 8

    def test_task_to_submit_message(self):
        """测试任务提交消息."""
        task = TaskDistributionMessage(
            task_id="task-submit",
            task_type="inference",
            payload={"model": "gpt"},
        )
        msg = task.to_submit_message(device_id="dev-submit")
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.TASK_SUBMIT

    def test_task_to_assign_message(self):
        """测试任务分配消息."""
        task = TaskDistributionMessage(
            task_id="task-assign",
            task_type="compute",
            payload={},
        )
        msg = task.to_assign_message(session_id="sess-assign")
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.TASK_ASSIGN

    def test_task_to_result_message(self):
        """测试任务结果消息."""
        task = TaskDistributionMessage(
            task_id="task-result",
            task_type="compute",
            payload={},
        )
        task.result = {"output": 42}
        task.status = "completed"
        msg = task.to_result_message(
            device_id="dev-result",
            session_id="sess-result",
        )
        assert isinstance(msg, ProtocolMessage)
        assert msg.header.message_type == MessageType.TASK_RESULT

    def test_task_from_message(self):
        """测试从消息解析任务."""
        task = TaskDistributionMessage(
            task_id="task-parse",
            task_type="compute",
            payload={"x": 10},
        )
        msg = task.to_submit_message()
        parsed = TaskDistributionMessage.from_message(msg)
        assert parsed.task_id == "task-parse"
        assert parsed.task_type == "compute"


# ============================================================
# 消息验证测试
# ============================================================

class TestMessageValidation:
    """消息验证工具测试."""

    def test_validate_valid_message(self):
        """测试验证有效消息."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-valid",
                message_type=MessageType.HEARTBEAT,
            ),
            body={"status": "ok"},
        )
        msg.header.checksum = msg.compute_checksum()
        is_valid, error = validate_message(msg)
        assert is_valid is True
        assert error == ""

    def test_validate_missing_message_id(self):
        """测试验证缺少 message_id 的消息."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="",
                message_type=MessageType.HEARTBEAT,
            ),
            body={},
        )
        is_valid, error = validate_message(msg)
        assert is_valid is False
        assert "message_id" in error.lower()

    def test_validate_expired_message(self):
        """测试验证过期消息."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-expired-val",
                message_type=MessageType.HEARTBEAT,
                timestamp=time.time() - 600,
                ttl=60,
            ),
            body={},
        )
        is_valid, error = validate_message(msg)
        assert is_valid is False
        assert "expired" in error.lower()

    def test_validate_checksum_mismatch(self):
        """测试验证校验和不匹配."""
        msg = ProtocolMessage(
            header=MessageHeader(
                message_id="msg-bad-checksum",
                message_type=MessageType.SYNC_PUSH,
            ),
            body={"data": "original"},
        )
        msg.header.checksum = msg.compute_checksum()
        msg.body = {"data": "tampered"}
        is_valid, error = validate_message(msg)
        assert is_valid is False
        assert "checksum" in error.lower()
