"""
云汐内核 V4 - 事件溯源存储系统

灵感来源：Event Sourcing + CQRS 架构模式

将所有 Agent 集群的关键操作建模为不可变事件，
支持完整的历史回放、审计追踪和状态重建。

事件类型：
- user.input_received
- intent.classified
- agent.task_dispatched
- agent.task_completed
- agent.task_failed
- guardrail.triggered
- memory.consolidated
- reflection.generated
- feedback.received
- system.config_changed
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger(__name__)


class EventType(str, Enum):
    """标准事件类型"""

    USER_INPUT_RECEIVED = "user.input_received"
    INTENT_CLASSIFIED = "intent.classified"
    AGENT_TASK_DISPATCHED = "agent.task_dispatched"
    AGENT_TASK_COMPLETED = "agent.task_completed"
    AGENT_TASK_FAILED = "agent.task_failed"
    AGENT_HANDOFF = "agent.handoff"
    GUARDRAIL_TRIGGERED = "guardrail.triggered"
    GUARDRAIL_PASSED = "guardrail.passed"
    MEMORY_WRITTEN = "memory.written"
    MEMORY_CONSOLIDATED = "memory.consolidated"
    REFLECTION_GENERATED = "reflection.generated"
    FEEDBACK_RECEIVED = "feedback.received"
    ROUTE_ADAPTED = "route.adapted"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    SYSTEM_CONFIG_CHANGED = "system.config_changed"
    STREAM_CHUNK_EMITTED = "stream.chunk_emitted"
    STREAM_COMPLETED = "stream.completed"


@dataclass
class DomainEvent:
    """领域事件

    不可变、可序列化、带时间戳的事件记录。
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    event_type: EventType = EventType.USER_INPUT_RECEIVED
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)
    version: int = 1  # 事件模式版本
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "version": self.version,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """从字典反序列化"""
        return cls(
            event_id=data.get("event_id", ""),
            event_type=EventType(data.get("event_type", "user.input_received")),
            trace_id=data.get("trace_id", ""),
            timestamp=data.get("timestamp", 0.0),
            version=data.get("version", 1),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )


EventHandler = Callable[[DomainEvent], Awaitable[None]]
"""事件处理函数签名"""


class EventStore:
    """事件存储

    内存中的事件溯源存储，支持追加、查询、回放和订阅。
    生产环境应接入持久化后端（如 SQLite、PostgreSQL）。
    """

    MAX_EVENTS: int = 50000

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []
        self._trace_index: dict[str, list[str]] = {}  # trace_id -> [event_id, ...]
        self._type_index: dict[str, list[str]] = {}  # event_type -> [event_id, ...]
        self._subscribers: dict[str, list[EventHandler]] = {}  # event_type -> [handler, ...]
        self._logger = logger.bind(service="event_store")

    # ── 写入接口 ────────────────────────────────────────

    async def append(self, event: DomainEvent) -> DomainEvent:
        """追加事件（不可变）"""
        self._events.append(event)

        # 更新索引
        self._trace_index.setdefault(event.trace_id, []).append(event.event_id)
        type_key = event.event_type.value
        self._type_index.setdefault(type_key, []).append(event.event_id)

        # 容量控制
        if len(self._events) > self.MAX_EVENTS:
            self._evict_oldest()

        self._logger.debug(
            "event_appended",
            event_id=event.event_id,
            event_type=type_key,
            trace_id=event.trace_id,
        )

        # 触发订阅者
        await self._notify_subscribers(event)

        return event

    async def append_many(self, events: list[DomainEvent]) -> list[DomainEvent]:
        """批量追加事件"""
        for event in events:
            await self.append(event)
        return events

    def _evict_oldest(self) -> None:
        """淘汰最旧的事件（仅保留最近 80%）"""
        cutoff = int(self.MAX_EVENTS * 0.2)
        removed = self._events[:cutoff]
        self._events = self._events[cutoff:]

        # 重建索引
        self._trace_index.clear()
        self._type_index.clear()
        for event in self._events:
            self._trace_index.setdefault(event.trace_id, []).append(event.event_id)
            self._type_index.setdefault(event.event_type.value, []).append(event.event_id)

        self._logger.info(
            "events_evicted",
            removed_count=len(removed),
            remaining_count=len(self._events),
        )

    # ── 查询接口 ────────────────────────────────────────

    def get_all(self, limit: int | None = None) -> list[DomainEvent]:
        """获取所有事件"""
        events = self._events
        if limit:
            events = events[-limit:]
        return list(events)

    def get_by_trace(self, trace_id: str) -> list[DomainEvent]:
        """按 trace_id 查询事件序列"""
        event_ids = self._trace_index.get(trace_id, [])
        event_map = {e.event_id: e for e in self._events}
        return [event_map[eid] for eid in event_ids if eid in event_map]

    def get_by_type(self, event_type: EventType, limit: int | None = None) -> list[DomainEvent]:
        """按事件类型查询"""
        event_ids = self._type_index.get(event_type.value, [])
        event_map = {e.event_id: e for e in self._events}
        events = [event_map[eid] for eid in event_ids if eid in event_map]
        if limit:
            events = events[-limit:]
        return events

    def get_by_time_range(
        self, start: float, end: float, limit: int | None = None
    ) -> list[DomainEvent]:
        """按时间范围查询"""
        events = [e for e in self._events if start <= e.timestamp <= end]
        if limit:
            events = events[-limit:]
        return events

    # ── 回放 ────────────────────────────────────────────

    async def replay(
        self,
        trace_id: str | None = None,
        event_types: list[EventType] | None = None,
        handler: EventHandler | None = None,
    ) -> list[DomainEvent]:
        """回放事件

        Args:
            trace_id: 指定 trace_id 回放，None 则回放全部
            event_types: 只回放指定类型的事件
            handler: 可选的处理函数，对每个事件调用

        Returns:
            回放的事件列表
        """
        if trace_id:
            events = self.get_by_trace(trace_id)
        else:
            events = list(self._events)

        if event_types:
            type_set = {et.value for et in event_types}
            events = [e for e in events if e.event_type.value in type_set]

        if handler:
            for event in events:
                await handler(event)

        self._logger.info(
            "events_replayed",
            trace_id=trace_id,
            count=len(events),
            types=[et.value for et in event_types] if event_types else None,
        )

        return events

    # ── 订阅 ────────────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """订阅特定类型的事件"""
        self._subscribers.setdefault(event_type.value, []).append(handler)
        self._logger.info("event_subscribed", event_type=event_type.value)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """取消订阅"""
        handlers = self._subscribers.get(event_type.value, [])
        if handler in handlers:
            handlers.remove(handler)

    async def _notify_subscribers(self, event: DomainEvent) -> None:
        """通知订阅者"""
        handlers = self._subscribers.get(event.event_type.value, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                self._logger.error(
                    "event_handler_error",
                    event_id=event.event_id,
                    handler=handler.__name__,
                    error=str(exc),
                )

    # ── 统计 ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """获取事件存储统计"""
        return {
            "total_events": len(self._events),
            "trace_count": len(self._trace_index),
            "type_distribution": {
                et: len(ids) for et, ids in self._type_index.items()
            },
            "time_range": {
                "oldest": self._events[0].timestamp if self._events else None,
                "newest": self._events[-1].timestamp if self._events else None,
            },
        }

    def clear(self) -> None:
        """清空所有事件（主要用于测试）"""
        self._events.clear()
        self._trace_index.clear()
        self._type_index.clear()
        self._subscribers.clear()
