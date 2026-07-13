"""
A2A通信总线子Agent — BusAgent

职责：
- 封装现有 MessageBus，增加优先级路由和 DLQ 管理
- handle_task 处理消息路由 / 发布 / 订阅请求
- 支持 A2A（Agent-to-Agent）消息格式转换

依赖：
- message_bus.MessageBus：底层消息总线
- dead_letter_queue.DeadLetterQueue：死信队列
- interfaces.IAgentPlugin / AgentTask / AgentResult：插件接口
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

import structlog

from interfaces import (
    AgentTask,
    AgentResult,
    BusHandler,
    BusMessage,
    IAgentPlugin,
)
from message_bus import MessageBus
from dead_letter_queue import DeadLetterQueue

logger = structlog.get_logger(__name__)


class BusAgent(IAgentPlugin):
    """A2A 通信总线子Agent

    在底层 MessageBus 基础上，提供面向 Agent 的消息路由、
    优先级发布、主题订阅及 DLQ 管理能力。
    同时支持将 AgentTask 转换为 BusMessage 进行 A2A 通信。
    """

    agent_id: str = "agent.bus"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "bus.route",
        "bus.publish",
        "bus.subscribe",
        "bus.unsubscribe",
        "bus.queue_stats",
        "bus.dlq_stats",
    ]

    def __init__(self) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        # 延迟初始化：在 on_mount 中获取单例
        self._bus: MessageBus | None = None
        self._dlq: DeadLetterQueue | None = None
        # 本地订阅缓存：subscription_id -> (topic, subscriber_id)
        self._local_subscriptions: dict[str, tuple[str, str]] = {}

    # ── 生命周期 ──────────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """挂载时获取 MessageBus 单例"""
        self._bus = await MessageBus.get_instance()
        self._dlq = self._bus._dlq
        self._logger.info("bus_agent_mounted", bus_instance=True)

    async def on_unmount(self) -> None:
        """卸载时取消所有本地订阅"""
        for sub_id in list(self._local_subscriptions.keys()):
            await self.unsubscribe_topic_by_id(sub_id)
        self._local_subscriptions.clear()
        self._logger.info("bus_agent_unmounted")

    async def health(self) -> dict[str, Any]:
        """健康检查：包含队列与DLQ状态"""
        base = await super().health()
        base["queue_stats"] = self.get_queue_stats()
        base["dlq_stats"] = self.get_dlq_stats()
        base["subscriptions_count"] = len(self._local_subscriptions)
        return base

    # ── 核心任务处理 ─────────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理消息路由/发布/订阅请求

        支持的 intent：
        - bus.route       ：路由消息到目标Agent
        - bus.publish      ：发布事件到topic
        - bus.subscribe    ：订阅topic
        - bus.unsubscribe  ：取消订阅
        - bus.queue_stats  ：查询队列统计
        - bus.dlq_stats    ：查询死信队列统计
        """
        start_time = time.time()
        self._logger.info(
            "bus_agent_handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=task.intent,
        )

        try:
            # 优先级路由
            result = await self.route_message(task)
            latency = (time.time() - start_time) * 1000
            result.latency_ms = latency
            result.task_id = task.task_id
            result.trace_id = task.trace_id
            result.agent_id = self.agent_id
            return result
        except Exception as exc:
            self._logger.error(
                "bus_agent_task_failed",
                error=str(exc),
                exc_info=True,
                task_id=task.task_id,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"BusAgent任务处理失败: {exc}",
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def route_message(self, task: AgentTask) -> AgentResult:
        """根据 task.intent 路由到对应handler

        将 AgentTask 格式转换为 BusMessage 进行 A2A 通信，
        并将底层 BusMessage 投递结果转换回 AgentResult。
        """
        intent = task.intent
        payload = task.payload

        if intent == "bus.route":
            return await self._handle_route(task, payload)
        elif intent == "bus.publish":
            return await self._handle_publish(task, payload)
        elif intent == "bus.subscribe":
            return await self._handle_subscribe(task, payload)
        elif intent == "bus.unsubscribe":
            return await self._handle_unsubscribe(task, payload)
        elif intent == "bus.queue_stats":
            return self._handle_queue_stats(task)
        elif intent == "bus.dlq_stats":
            return self._handle_dlq_stats(task)
        else:
            return AgentResult(
                status="failure",
                error=f"不支持的intent: {intent}",
            )

    # ── A2A消息格式转换 ─────────────────────────────────

    def _task_to_bus_message(
        self,
        task: AgentTask,
        topic: str = "",
        msg_type: str = "agent.handoff",
    ) -> BusMessage:
        """将 AgentTask 转换为 BusMessage（A2A格式）

        保留原始 task 的 trace_id、priority、ttl 等元信息。
        [v2.0-LINKAGE] 所有A2A消息必须携带 x-security-classification。
        M5（潮汐记忆）相关消息默认标记为绝密（TOP_SECRET）。
        """
        # [v2.0-LINKAGE] 自动判定涉密等级：M5消息默认绝密
        security_classification = task.security_classification
        target = task.target or ""
        if security_classification == "INTERNAL" and ("memory" in target or "m5" in target or target.startswith("agent.m5")):
            security_classification = "TOP_SECRET"

        bus_msg = BusMessage(
            topic=topic or f"agent.{target}",
            sender=task.source or self.agent_id,
            recipient=target or None,
            msg_type=msg_type,  # type: ignore[arg-type]
            payload={
                "task_id": task.task_id,
                "intent": task.intent,
                "data": task.payload,
                "_a2a": True,  # 标记为A2A消息
            },
            priority=task.priority,
            ttl=task.ttl,
            trace_id=task.trace_id,
            security_classification=security_classification,
        )
        return bus_msg

    def _bus_message_to_task(self, msg: BusMessage) -> AgentTask:
        """将 BusMessage 转换回 AgentTask（A2A格式反向转换）"""
        payload = msg.payload
        return AgentTask(
            task_id=payload.get("task_id", msg.msg_id),
            trace_id=msg.trace_id,
            source=msg.sender,
            target=msg.recipient or "",
            intent=payload.get("intent", ""),
            payload=payload.get("data", {}),
            priority=msg.priority,
            ttl=msg.ttl,
            security_classification=msg.security_classification,
        )

    # ── Handler实现 ──────────────────────────────────────

    async def _handle_route(self, task: AgentTask, payload: dict[str, Any]) -> AgentResult:
        """处理路由请求：将 AgentTask 作为 BusMessage 投递到目标Agent"""
        if not self._bus:
            return AgentResult(status="failure", error="MessageBus未初始化")

        target = payload.get("target", task.target)
        topic = payload.get("topic", f"agent.{target}")
        msg = self._task_to_bus_message(task, topic=topic, msg_type="agent.handoff")
        await self._bus.publish(msg)

        return AgentResult(
            status="success",
            output={
                "action": "route",
                "msg_id": msg.msg_id,
                "topic": topic,
                "target": target,
                "priority": msg.priority,
            },
        )

    async def _handle_publish(self, task: AgentTask, payload: dict[str, Any]) -> AgentResult:
        """处理发布请求"""
        topic: str = payload.get("topic", "")
        event_payload: dict[str, Any] = payload.get("payload", {})
        priority: int = payload.get("priority", task.priority)

        if not topic:
            return AgentResult(status="failure", error="缺少topic参数")

        msg_id = await self.publish_event(topic, event_payload, priority)
        return AgentResult(
            status="success",
            output={
                "action": "publish",
                "msg_id": msg_id,
                "topic": topic,
                "priority": priority,
            },
        )

    async def _handle_subscribe(self, task: AgentTask, payload: dict[str, Any]) -> AgentResult:
        """处理订阅请求"""
        topic: str = payload.get("topic", "")
        subscriber_id: str = payload.get("subscriber_id", task.source)

        if not topic:
            return AgentResult(status="failure", error="缺少topic参数")

        # 使用内部空handler占位；实际消费方通过外部注册
        async def _placeholder_handler(msg: BusMessage) -> None:
            self._logger.debug(
                "placeholder_handler_triggered",
                msg_id=msg.msg_id,
                topic=msg.topic,
            )

        sub_id = await self.subscribe_topic(topic, _placeholder_handler, subscriber_id)
        return AgentResult(
            status="success",
            output={
                "action": "subscribe",
                "subscription_id": sub_id,
                "topic": topic,
                "subscriber_id": subscriber_id,
            },
        )

    async def _handle_unsubscribe(self, task: AgentTask, payload: dict[str, Any]) -> AgentResult:
        """处理取消订阅请求"""
        subscription_id: str = payload.get("subscription_id", "")
        if not subscription_id:
            return AgentResult(status="failure", error="缺少subscription_id参数")

        await self.unsubscribe_topic_by_id(subscription_id)
        return AgentResult(
            status="success",
            output={
                "action": "unsubscribe",
                "subscription_id": subscription_id,
            },
        )

    def _handle_queue_stats(self, task: AgentTask) -> AgentResult:
        """处理队列统计请求"""
        stats = self.get_queue_stats()
        return AgentResult(
            status="success",
            output=stats,
        )

    def _handle_dlq_stats(self, task: AgentTask) -> AgentResult:
        """处理DLQ统计请求"""
        stats = self.get_dlq_stats()
        return AgentResult(
            status="success",
            output=stats,
        )

    # ── 公开API ──────────────────────────────────────────

    async def publish_event(
        self,
        topic: str,
        payload: dict[str, Any],
        priority: int = 5,
    ) -> str:
        """发布事件到总线

        Args:
            topic: 主题名称
            payload: 事件数据
            priority: 优先级（越小越高）

        Returns:
            消息ID
        """
        if not self._bus:
            raise RuntimeError("MessageBus未初始化，请先调用on_mount")

        msg = BusMessage(
            topic=topic,
            sender=self.agent_id,
            msg_type="system.config_change",  # type: ignore[arg-type]
            payload=payload,
            priority=priority,
        )
        await self._bus.publish(msg)

        self._logger.info(
            "event_published",
            msg_id=msg.msg_id,
            topic=topic,
            priority=priority,
        )
        return msg.msg_id

    async def subscribe_topic(
        self,
        topic: str,
        handler: Callable[[BusMessage], Awaitable[None]],
        subscriber_id: str = "anonymous",
    ) -> str:
        """订阅主题

        Args:
            topic: 主题模式（支持通配符）
            handler: 消息处理回调
            subscriber_id: 订阅者标识

        Returns:
            subscription_id
        """
        if not self._bus:
            raise RuntimeError("MessageBus未初始化，请先调用on_mount")

        sub_id = await self._bus.subscribe(topic, handler, subscriber_id)
        self._local_subscriptions[sub_id] = (topic, subscriber_id)

        self._logger.info(
            "topic_subscribed",
            subscription_id=sub_id,
            topic=topic,
            subscriber_id=subscriber_id,
        )
        return sub_id

    async def unsubscribe_topic_by_id(self, subscription_id: str) -> bool:
        """通过 subscription_id 取消订阅"""
        if not self._bus:
            return False

        await self._bus.unsubscribe(subscription_id)
        self._local_subscriptions.pop(subscription_id, None)

        self._logger.info(
            "topic_unsubscribed",
            subscription_id=subscription_id,
        )
        return True

    def get_queue_stats(self) -> dict[str, Any]:
        """获取队列统计信息

        Returns:
            包含队列大小、订阅数等信息的字典
        """
        stats: dict[str, Any] = {
            "queue_size": self._bus.queue_size() if self._bus else 0,
            "max_queue_size": MessageBus.MAX_QUEUE_SIZE,
            "local_subscriptions": len(self._local_subscriptions),
            "subscription_details": [
                {
                    "subscription_id": sid,
                    "topic": topic,
                    "subscriber_id": sub_id,
                }
                for sid, (topic, sub_id) in self._local_subscriptions.items()
            ],
        }
        return stats

    def get_dlq_stats(self) -> dict[str, Any]:
        """获取死信队列统计

        Returns:
            DLQ条目总数、原因分布、可重试数等
        """
        if self._dlq:
            return self._dlq.stats()
        return {"total_entries": 0, "error": "DLQ未初始化"}
