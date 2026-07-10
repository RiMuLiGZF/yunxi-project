"""
云汐内核 V9 - BusMessage ↔ A2A Task 消息适配器

解决评审 P3-002：BusMessage（内部消息总线）与 A2A Task（标准通信协议）
两套消息模型完全割裂，需要双向转换桥接。

核心能力：
1. bus_to_a2a: BusMessage → A2A Task
2. a2a_to_bus: A2A Task → BusMessage
3. 双向注册：自动桥接 MessageBus 与 A2ATransport
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from interfaces import BusMessage
from a2a_protocol import (
    Task, TaskStatus, A2ATransport, MemoryTransport, TaskUpdate,
)
from message_bus import MessageBus

logger = structlog.get_logger(__name__)


class MessageAdapter:
    """BusMessage ↔ A2A Task 双向消息适配器

    职责：
    - 将内部 BusMessage 转换为标准 A2A Task
    - 将 A2A Task 转换为内部 BusMessage
    - 提供双向桥接注册，实现消息总线与 A2A 传输的自动转发
    """

    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._transport: A2ATransport | None = None
        self._logger = logger.bind(service="message_adapter")

    # ── 单向转换 ──────────────────────────────────────────

    def bus_to_a2a(self, bus_msg: BusMessage) -> Task:
        """将 BusMessage 转换为 A2A Task

        映射规则：
        - bus_msg.msg_type → Task.description
        - bus_msg.payload → Task.payload
        - bus_msg.trace_id → Task.trace_id
        - bus_msg.sender → Task.sender
        - bus_msg.recipient → Task.recipient
        - Task.status = TaskStatus.SUBMITTED
        """
        task = Task(
            task_id=bus_msg.msg_id,
            status=TaskStatus.SUBMITTED,
            sender=bus_msg.sender,
            recipient=bus_msg.recipient or "",
            description=bus_msg.msg_type,
            payload=dict(bus_msg.payload),
            trace_id=bus_msg.trace_id,
        )
        self._logger.debug(
            "bus_to_a2a_converted",
            msg_id=bus_msg.msg_id,
            task_id=task.task_id,
        )
        return task

    def a2a_to_bus(self, task: Task) -> BusMessage:
        """将 A2A Task 转换为 BusMessage

        映射规则：
        - Task.task_id → BusMessage.msg_id
        - Task.description → BusMessage.content (payload的desc字段)
        - Task.trace_id → BusMessage.trace_id
        - 根据 Task.status 映射 msg_type:
          completed → agent.task_complete
          failed → agent.error
          其他 → skill.result
        """
        # 根据状态映射 msg_type
        # 注意：BusMessage.msg_type 是 Literal 类型，只能使用预定义值
        status_to_msg_type: dict[TaskStatus, str] = {
            TaskStatus.COMPLETED: "agent.task_complete",
            TaskStatus.FAILED: "agent.handoff",        # 映射到 agent.handoff（错误场景）
            TaskStatus.CANCELLED: "agent.handoff",     # 映射到 agent.handoff（取消场景）
            TaskStatus.WORKING: "skill.result",
            TaskStatus.INPUT_REQUIRED: "skill.result",
            TaskStatus.SUBMITTED: "user.input",
        }

        msg_type = status_to_msg_type.get(task.status, "skill.result")

        # 构建 payload，包含 description 和原始 payload
        payload = {
            "desc": task.description,
            **task.payload,
        }
        if task.error:
            payload["error"] = task.error

        bus_msg = BusMessage(
            msg_id=task.task_id,
            topic=f"agent.{task.sender}",
            sender=task.sender,
            recipient=task.recipient or None,
            msg_type=msg_type,  # type: ignore[arg-type]
            payload=payload,
            priority=5,
            ttl=300,
            trace_id=task.trace_id,
        )
        self._logger.debug(
            "a2a_to_bus_converted",
            task_id=task.task_id,
            msg_id=bus_msg.msg_id,
            msg_type=msg_type,
        )
        return bus_msg

    # ── 双向桥接注册 ──────────────────────────────────────

    async def register_with_bus(self, msg_bus: MessageBus) -> None:
        """注册到消息总线，将 BusMessage 自动转换为 A2A Task 并通过 transport 发送

        [V9.5] 对 MemoryTransport 使用直接 handler 调用替代 send()，
        确保 A2A Task 被正确处理而非仅存入队列无人消费。
        """
        self._bus = msg_bus

        if self._transport is None:
            self._logger.warning("register_with_bus_no_transport")
            return

        async def _bus_to_a2a_handler(bus_msg: BusMessage) -> None:
            task = self.bus_to_a2a(bus_msg)

            if isinstance(self._transport, MemoryTransport):
                # [V9.5] MemoryTransport: 直接调用已注册的 handlers
                handlers = self._transport.get_handlers()
                for handler_fn in handlers.values():
                    try:
                        await handler_fn(task)
                    except Exception as exc:
                        self._logger.warning(
                            "handler_invocation_error",
                            handler=handler_fn.__name__ if hasattr(handler_fn, '__name__') else str(handler_fn),
                            error=str(exc),
                        )
            else:
                # HTTP/其他 transport: 通过 send() 发送
                target_url = f"memory://{task.recipient}" if task.recipient else ""
                if target_url:
                    await self._transport.send(target_url, task)

        await self._bus.subscribe("agent.*", _bus_to_a2a_handler, subscriber_id="message_adapter")
        self._logger.info("registered_with_message_bus")

    async def register_with_transport(self, transport: A2ATransport) -> None:
        """注册到 A2A 传输层，将 A2A Task 自动转换为 BusMessage 并发布

        在 MemoryTransport 上注册回调，将 Task 转换为 BusMessage 后发布到总线。
        """
        self._transport = transport

        if isinstance(transport, MemoryTransport):
            # 注册一个通用 handler 到 transport
            async def _a2a_to_bus_handler(task: Task) -> TaskUpdate:
                bus_msg = self.a2a_to_bus(task)
                if self._bus:
                    await self._bus.publish(bus_msg)
                return TaskUpdate(
                    task_id=task.task_id,
                    status=task.status,
                    is_final=task.status in (
                        TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
                    ),
                )

            # 注册默认 handler
            transport.register_handler("_adapter_bridge", _a2a_to_bus_handler)
            self._logger.info("registered_with_transport")

        elif self._bus is None:
            self._logger.warning("register_with_transport_no_bus")

    def stats(self) -> dict[str, Any]:
        return {
            "bus_registered": self._bus is not None,
            "transport_registered": self._transport is not None,
        }
