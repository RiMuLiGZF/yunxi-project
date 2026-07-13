"""
测试：P3-002 BusMessage ↔ A2A Task 消息适配器
"""

import sys
import pytest

sys.path.insert(0, "/workspace/agent_cluster")

from interfaces import BusMessage
from a2a_protocol import (
    Task, TaskStatus, MemoryTransport, TaskUpdate,
)
from message_adapter import MessageAdapter


class TestBusToA2A:
    """BusMessage → A2A Task 转换"""

    def test_basic_conversion(self):
        adapter = MessageAdapter()
        bus_msg = BusMessage(
            topic="agent.task",
            sender="agent_a",
            recipient="agent_b",
            msg_type="user.input",
            payload={"key": "value", "data": 42},
            trace_id="trace_001",
        )
        task = adapter.bus_to_a2a(bus_msg)

        assert task.task_id == bus_msg.msg_id
        assert task.status == TaskStatus.SUBMITTED
        assert task.sender == "agent_a"
        assert task.recipient == "agent_b"
        assert task.description == "user.input"
        assert task.payload == {"key": "value", "data": 42}
        assert task.trace_id == "trace_001"

    def test_task_complete_msg_type(self):
        adapter = MessageAdapter()
        bus_msg = BusMessage(
            topic="agent.result",
            sender="agent_a",
            msg_type="agent.task_complete",
            payload={"result": "done"},
        )
        task = adapter.bus_to_a2a(bus_msg)
        assert task.description == "agent.task_complete"

    def test_null_recipient(self):
        adapter = MessageAdapter()
        bus_msg = BusMessage(
            topic="agent.broadcast",
            sender="agent_a",
            recipient=None,
            msg_type="user.input",
        )
        task = adapter.bus_to_a2a(bus_msg)
        assert task.recipient == ""


class TestA2AToBus:
    """A2A Task → BusMessage 转换"""

    def test_completed_task(self):
        adapter = MessageAdapter()
        task = Task(
            task_id="task_001",
            status=TaskStatus.COMPLETED,
            sender="agent_a",
            recipient="agent_b",
            description="complete task",
            trace_id="trace_001",
            payload={"result": "ok"},
        )
        bus_msg = adapter.a2a_to_bus(task)

        assert bus_msg.msg_id == "task_001"
        assert bus_msg.msg_type == "agent.task_complete"
        assert bus_msg.sender == "agent_a"
        assert bus_msg.recipient == "agent_b"
        assert bus_msg.trace_id == "trace_001"
        assert bus_msg.payload["desc"] == "complete task"
        assert bus_msg.payload["result"] == "ok"

    def test_failed_task(self):
        adapter = MessageAdapter()
        task = Task(
            task_id="task_002",
            status=TaskStatus.FAILED,
            sender="agent_a",
            recipient="agent_b",
            error="timeout exceeded",
            trace_id="trace_002",
        )
        bus_msg = adapter.a2a_to_bus(task)

        # agent.error 不在 BusMessage.msg_type Literal 中，映射到 agent.handoff
        assert bus_msg.msg_type == "agent.handoff"
        assert bus_msg.payload["error"] == "timeout exceeded"

    def test_working_task(self):
        adapter = MessageAdapter()
        task = Task(
            task_id="task_003",
            status=TaskStatus.WORKING,
            sender="agent_a",
        )
        bus_msg = adapter.a2a_to_bus(task)
        assert bus_msg.msg_type == "skill.result"

    def test_submitted_task(self):
        adapter = MessageAdapter()
        task = Task(
            task_id="task_004",
            status=TaskStatus.SUBMITTED,
            sender="user",
        )
        bus_msg = adapter.a2a_to_bus(task)
        assert bus_msg.msg_type == "user.input"

    def test_null_recipient_in_task(self):
        adapter = MessageAdapter()
        task = Task(
            task_id="task_005",
            status=TaskStatus.COMPLETED,
            sender="agent_a",
            recipient="",
        )
        bus_msg = adapter.a2a_to_bus(task)
        assert bus_msg.recipient is None


class TestRoundTrip:
    """双向转换往返一致性"""

    def test_bus_a2a_bus_roundtrip(self):
        adapter = MessageAdapter()
        original = BusMessage(
            msg_id="msg_001",
            topic="agent.task",
            sender="agent_a",
            recipient="agent_b",
            msg_type="user.input",
            payload={"key": "value"},
            trace_id="trace_001",
        )

        task = adapter.bus_to_a2a(original)
        # Task 状态是 SUBMITTED，转换回来 msg_type = user.input
        back = adapter.a2a_to_bus(task)

        assert back.msg_id == "msg_001"
        assert back.sender == "agent_a"
        assert back.recipient == "agent_b"
        assert back.msg_type == "user.input"
        assert back.trace_id == "trace_001"


class TestRegisterWithTransport:
    """Transport 注册"""

    @pytest.mark.asyncio
    async def test_register_with_memory_transport(self):
        adapter = MessageAdapter()
        transport = MemoryTransport()
        await adapter.register_with_transport(transport)

        stats = adapter.stats()
        assert stats["transport_registered"] is True
        # handler 应已注册
        assert "_adapter_bridge" in transport._handlers


class TestStats:
    def test_initial_stats(self):
        adapter = MessageAdapter()
        stats = adapter.stats()
        assert stats["bus_registered"] is False
        assert stats["transport_registered"] is False
