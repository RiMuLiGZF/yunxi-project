from __future__ import annotations

"""A2A Bus - Agent-to-Agent 消息总线.

基于现有 EventBus 扩展，实现 Agent 之间的点对点、广播、任务委派通信，
支持 AgentCard 发现、Task 状态同步、消息路由。
"""

import asyncio
import time
from typing import Any, Awaitable, Callable

import structlog

from skill_cluster.a2a_protocol import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)
from skill_cluster.agent.runtime import AgentRegistry
from skill_cluster.infrastructure.event_bus import EventBus

logger = structlog.get_logger()

MessageHandler = Callable[[A2AMessage], Awaitable[None]]
TaskHandler = Callable[[A2ATask], Awaitable[None]]


class A2ABus:
    """A2A 消息总线.

    管理 AgentCard 注册发现、消息路由、任务生命周期。
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus()
        self._agent_registry = agent_registry or AgentRegistry()
        self._cards: dict[str, A2AAgentCard] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._msg_handlers: dict[str, list[MessageHandler]] = {}
        self._task_handlers: dict[str, list[TaskHandler]] = {}
        self._lock = asyncio.Lock()

    # ---- AgentCard 管理 ----

    def register_card(self, card: A2AAgentCard) -> None:
        """注册 Agent 能力卡片."""
        card.updated_at = time.time()
        self._cards[card.agent_id] = card
        logger.info("a2a_card_registered", agent_id=card.agent_id, name=card.name)

    def unregister_card(self, agent_id: str) -> None:
        """注销 Agent 卡片."""
        self._cards.pop(agent_id, None)

    def get_card(self, agent_id: str) -> A2AAgentCard | None:
        """获取 Agent 卡片."""
        return self._cards.get(agent_id)

    def list_cards(self) -> list[A2AAgentCard]:
        """列出所有 Agent 卡片."""
        return list(self._cards.values())

    def discover_by_skill(self, skill_id: str) -> list[A2AAgentCard]:
        """按 Skill ID 发现可处理该技能的 Agent."""
        return [
            card for card in self._cards.values() if skill_id in card.skills
        ]

    # ---- 消息发送 ----

    async def send_message(
        self,
        source_agent_id: str,
        target_agent_id: str,
        parts: list[A2APart],
        metadata: dict[str, Any] | None = None,
    ) -> A2AMessage:
        """发送点对点消息.

        Args:
            source_agent_id: 发送方 Agent ID.
            target_agent_id: 接收方 Agent ID.
            parts: 消息内容单元.
            metadata: 扩展元数据.

        Returns:
            发送的消息实例.
        """
        msg = A2AMessage(
            role="agent",
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            parts=parts,
            metadata=metadata or {},
        )

        # 本地路由：如果目标 Agent 在当前进程注册了处理器
        handlers = self._msg_handlers.get(target_agent_id, [])
        if handlers:
            await asyncio.gather(
                *[self._safe_msg_handler(h, msg) for h in handlers],
                return_exceptions=True,
            )
        else:
            # 退化为 EventBus 事件
            await self._event_bus.publish(
                type("Event", (), {
                    "event_type": f"a2a.msg.{target_agent_id}",
                    "payload": msg.model_dump(),
                    "source_skill_id": None,
                    "trace_id": msg.message_id,
                    "timestamp": time.time(),
                    "to_dict": lambda self: {
                        "event_type": self.event_type,
                        "payload": self.payload,
                        "trace_id": self.trace_id,
                    },
                })()
            )

        logger.info(
            "a2a_message_sent",
            msg_id=msg.message_id,
            from_agent=source_agent_id,
            to_agent=target_agent_id,
        )
        return msg

    async def broadcast(
        self,
        source_agent_id: str,
        parts: list[A2APart],
        metadata: dict[str, Any] | None = None,
    ) -> list[A2AMessage]:
        """广播消息给所有已知 Agent.

        Returns:
            发送的消息列表.
        """
        messages: list[A2AMessage] = []
        for card in self._cards.values():
            if card.agent_id == source_agent_id:
                continue
            msg = await self.send_message(
                source_agent_id, card.agent_id, parts, metadata
            )
            messages.append(msg)
        return messages

    # ---- 消息订阅 ----

    def on_message(
        self, agent_id: str, handler: MessageHandler
    ) -> None:
        """订阅指定 Agent 的消息."""
        self._msg_handlers.setdefault(agent_id, []).append(handler)

    def off_message(
        self, agent_id: str, handler: MessageHandler
    ) -> None:
        """取消订阅."""
        handlers = self._msg_handlers.get(agent_id, [])
        if handler in handlers:
            handlers.remove(handler)

    # ---- Task 管理 ----

    async def create_task(
        self,
        creator_agent_id: str,
        handler_agent_id: str | None = None,
        initial_message: A2AMessage | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> A2ATask:
        """创建协作任务.

        Args:
            creator_agent_id: 创建者 Agent ID.
            handler_agent_id: 指定处理者 Agent ID（None 表示待分配）.
            initial_message: 初始消息.
            metadata: 扩展元数据.

        Returns:
            创建的任务实例.
        """
        task = A2ATask(
            creator_agent_id=creator_agent_id,
            handler_agent_id=handler_agent_id,
            metadata=metadata or {},
        )
        if initial_message:
            task.add_message(initial_message)
        self._tasks[task.task_id] = task

        # 通知处理者
        if handler_agent_id:
            task.transition("submitted", f"Assigned to {handler_agent_id}")
            await self._notify_task_handlers(task)
        else:
            task.transition("submitted", "Awaiting handler assignment")

        logger.info(
            "a2a_task_created",
            task_id=task.task_id,
            creator=creator_agent_id,
            handler=handler_agent_id,
        )
        return task

    async def assign_task(
        self, task_id: str, handler_agent_id: str
    ) -> A2ATask | None:
        """为任务分配处理者."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.handler_agent_id = handler_agent_id
        task.transition("working", f"Assigned to {handler_agent_id}")
        await self._notify_task_handlers(task)
        return task

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        reason: str = "",
        artifact: A2AArtifact | None = None,
    ) -> A2ATask | None:
        """更新任务状态."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.transition(status, reason)
        if artifact:
            task.add_artifact(artifact)
        await self._notify_task_handlers(task)
        return task

    def get_task(self, task_id: str) -> A2ATask | None:
        """获取任务."""
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        agent_id: str | None = None,
        status: str | None = None,
    ) -> list[A2ATask]:
        """列出任务."""
        results = list(self._tasks.values())
        if agent_id:
            results = [
                t
                for t in results
                if t.creator_agent_id == agent_id
                or t.handler_agent_id == agent_id
            ]
        if status:
            results = [t for t in results if t.status == status]
        return results

    # ---- Task 订阅 ----

    def on_task(self, agent_id: str, handler: TaskHandler) -> None:
        """订阅指定 Agent 的任务事件."""
        self._task_handlers.setdefault(agent_id, []).append(handler)

    def off_task(self, agent_id: str, handler: TaskHandler) -> None:
        """取消订阅."""
        handlers = self._task_handlers.get(agent_id, [])
        if handler in handlers:
            handlers.remove(handler)

    # ---- 内部方法 ----

    async def _notify_task_handlers(self, task: A2ATask) -> None:
        """通知任务相关的处理器."""
        agents = [task.creator_agent_id, task.handler_agent_id]
        for agent_id in agents:
            if agent_id is None:
                continue
            handlers = self._task_handlers.get(agent_id, [])
            for handler in handlers:
                try:
                    await handler(task)
                except Exception as e:
                    logger.error(
                        "a2a_task_handler_error",
                        task_id=task.task_id,
                        agent_id=agent_id,
                        error=str(e),
                    )

    async def _safe_msg_handler(
        self, handler: MessageHandler, msg: A2AMessage
    ) -> None:
        try:
            await handler(msg)
        except Exception as e:
            logger.error(
                "a2a_msg_handler_error",
                msg_id=msg.message_id,
                error=str(e),
            )

    # ---- 统计 ----

    def get_stats(self) -> dict[str, Any]:
        """获取总线统计信息."""
        return {
            "registered_agents": len(self._cards),
            "active_tasks": len(self._tasks),
            "task_status_breakdown": {
                status: len([t for t in self._tasks.values() if t.status == status])
                for status in [
                    "submitted",
                    "working",
                    "input-required",
                    "completed",
                    "failed",
                    "canceled",
                ]
            },
        }
