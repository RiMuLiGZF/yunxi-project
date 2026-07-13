from __future__ import annotations

"""Event Bus 事件驱动总线.

实现 Skill 之间的发布/订阅通信，解耦技能调用链，支持异步事件流处理。
"""

import asyncio
import fnmatch
import time
import uuid
from collections import deque
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger()

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class SkillEvent:
    """Skill 事件."""

    def __init__(
        self,
        event_type: str,
        payload: dict[str, Any],
        source_skill_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        self.event_id = f"evt_{uuid.uuid4().hex[:12]}"
        self.event_type = event_type
        self.payload = payload
        self.source_skill_id = source_skill_id
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:16]}"
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "source_skill_id": self.source_skill_id,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }


class EventBus:
    """事件总线.

    支持通配符订阅（如 'skill.*.completed'）、异步发布、事件持久化。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._history: deque[SkillEvent] = deque(maxlen=1000)
        self._max_history = 1000
        self._lock = asyncio.Lock()

    async def subscribe(
        self, event_pattern: str, handler: EventHandler
    ) -> None:
        """订阅事件.

        Args:
            event_pattern: 事件类型或通配符模式，如 'skill.doc_proc.completed' 或 'skill.*.completed'.
            handler: 异步事件处理器.
        """
        async with self._lock:
            self._handlers.setdefault(event_pattern, []).append(handler)
        logger.info("event_subscribed", pattern=event_pattern)

    async def unsubscribe(
        self, event_pattern: str, handler: EventHandler
    ) -> None:
        """取消订阅."""
        async with self._lock:
            handlers = self._handlers.get(event_pattern, [])
            if handler in handlers:
                handlers.remove(handler)

    async def publish(self, event: SkillEvent) -> None:
        """发布事件.

        Args:
            event: 事件实例.
        """
        self._history.append(event)

        # 匹配并分发
        matched_handlers: list[EventHandler] = []
        async with self._lock:
            for pattern, handlers in self._handlers.items():
                if fnmatch.fnmatch(event.event_type, pattern):
                    matched_handlers.extend(handlers)

        if not matched_handlers:
            logger.debug("event_no_handlers", event_type=event.event_type)
            return

        logger.info(
            "event_published",
            event_type=event.event_type,
            event_id=event.event_id,
            handlers=len(matched_handlers),
            trace_id=event.trace_id,
        )

        # 并发执行所有处理器
        tasks = [self._safe_handle(h, event) for h in matched_handlers]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_handle(
        self, handler: EventHandler, event: SkillEvent
    ) -> None:
        try:
            await handler(event.to_dict())
        except Exception as e:
            logger.error(
                "event_handler_error",
                event_type=event.event_type,
                handler=handler.__name__,
                error=str(e),
                trace_id=event.trace_id,
            )

    def get_history(
        self,
        event_type: str | None = None,
        source_skill_id: str | None = None,
        limit: int = 100,
    ) -> list[SkillEvent]:
        """查询事件历史."""
        results = list(reversed(self._history))
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if source_skill_id:
            results = [e for e in results if e.source_skill_id == source_skill_id]
        return results[:limit]

    def clear_history(self) -> None:
        """清空事件历史."""
        self._history.clear()
