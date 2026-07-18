"""
云汐系统模块间通信 SDK - 全局事件总线
========================================

发布/订阅模式的事件总线，支持：
- 同步发布与异步发布
- 事件类型通配符（* 单级，# 多级）
- 事件历史记录与溯源
- 事件重放
- 内存实现（默认）+ Redis 实现（可选）

使用方式：
    from shared.module_sdk.event_bus import EventBus, get_event_bus

    bus = get_event_bus()

    # 订阅
    def handler(event):
        print(f"Received: {event.event_type}")

    sub_id = bus.subscribe("user.created", handler)

    # 发布
    bus.publish("user.created", {"user_id": "123"}, source="m1")
"""

from __future__ import annotations

import asyncio
import time
import uuid
import threading
import logging
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from .models import Event

logger = logging.getLogger(__name__)


# ============================================================
# 内存事件总线
# ============================================================

class InMemoryEventBus:
    """
    内存实现的事件总线。

    所有事件和订阅都存储在进程内存中。
    适用于单体部署或测试环境。
    线程安全。
    """

    def __init__(self, max_history: int = 10000):
        """
        初始化内存事件总线。

        Args:
            max_history: 最大历史事件记录数
        """
        self._subscribers: Dict[str, Dict[str, Callable]] = {}
        # pattern -> subscription_id -> handler
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=max_history)
        self._max_history = max_history
        self._sub_counter = 0

    # ------------------------------------------------------------------
    #  发布
    # ------------------------------------------------------------------

    def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        同步发布事件。

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
            metadata: 附加元数据

        Returns:
            是否成功发布
        """
        event = Event(
            event_type=event_type,
            data=data,
            source=source,
            metadata=metadata or {},
        )
        return self._publish_event(event)

    async def publish_async(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        异步发布事件（在线程池中执行处理器）。

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源
            metadata: 附加元数据

        Returns:
            是否成功发布
        """
        event = Event(
            event_type=event_type,
            data=data,
            source=source,
            metadata=metadata or {},
        )
        # 先记录历史
        with self._lock:
            self._history.append(event)

        # 异步执行处理器
        handlers = self._get_matching_handlers(event.event_type)
        if not handlers:
            return True

        loop = asyncio.get_event_loop()
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    loop.create_task(handler(event))
                else:
                    loop.run_in_executor(None, handler, event)
            except Exception as e:
                logger.error("Async event handler error: %s", e)

        return True

    def _publish_event(self, event: Event) -> bool:
        """发布事件（内部方法）"""
        # 记录历史
        with self._lock:
            self._history.append(event)
            handlers = self._get_matching_handlers(event.event_type)

        if not handlers:
            return True

        # 同步调用所有匹配的处理器
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    # 如果处理器是协程，尝试运行
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(result)
                        else:
                            asyncio.run(result)
                    except Exception:
                        pass
            except Exception as e:
                logger.error("Event handler error for %s: %s", event.event_type, e)

        return True

    def _get_matching_handlers(self, event_type: str) -> List[Callable]:
        """获取匹配事件类型的所有处理器"""
        handlers: List[Callable] = []
        for pattern, subs in self._subscribers.items():
            if _match_pattern(event_type, pattern):
                handlers.extend(subs.values())
        return handlers

    # ------------------------------------------------------------------
    #  订阅
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Any],
    ) -> str:
        """
        订阅事件。

        Args:
            event_type: 事件类型或模式（支持 * 和 # 通配符）
            handler: 事件处理器函数

        Returns:
            订阅 ID，用于取消订阅
        """
        subscription_id = f"sub_{self._next_id()}"
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = {}
            self._subscribers[event_type][subscription_id] = handler

        logger.debug("Subscribed: %s -> %s", event_type, subscription_id)
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅。

        Args:
            subscription_id: 订阅 ID

        Returns:
            是否成功取消
        """
        with self._lock:
            for pattern, subs in self._subscribers.items():
                if subscription_id in subs:
                    del subs[subscription_id]
                    if not subs:
                        del self._subscribers[pattern]
                    logger.debug("Unsubscribed: %s", subscription_id)
                    return True
        return False

    def get_subscription_count(self, event_type: Optional[str] = None) -> int:
        """获取订阅数量"""
        with self._lock:
            if event_type:
                return len(self._subscribers.get(event_type, {}))
            total = 0
            for subs in self._subscribers.values():
                total += len(subs)
            return total

    # ------------------------------------------------------------------
    #  历史与重放
    # ------------------------------------------------------------------

    def get_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
        since: Optional[float] = None,
    ) -> List[Event]:
        """
        获取事件历史。

        Args:
            event_type: 按事件类型过滤（支持通配符），None 表示全部
            limit: 返回最大数量
            since: 只返回此时间戳之后的事件

        Returns:
            事件列表（从新到旧）
        """
        with self._lock:
            events = list(self._history)

        # 反转（从新到旧）
        events.reverse()

        result = []
        for event in events:
            if since and event.timestamp < since:
                continue
            if event_type and not _match_pattern(event.event_type, event_type):
                # 也反过来匹配：event_type 可能是模式
                if not _match_pattern(event.event_type, event_type):
                    if not _match_pattern(event_type, event.event_type):
                        continue
            result.append(event)
            if len(result) >= limit:
                break

        return result

    def replay(
        self,
        event_type: str,
        since: Optional[float] = None,
        handler: Optional[Callable[[Event], Any]] = None,
    ) -> int:
        """
        事件重放。

        将历史事件重新分发给指定处理器或当前所有订阅者。

        Args:
            event_type: 要重放的事件类型（支持通配符）
            since: 只重放此时间戳之后的事件
            handler: 自定义处理器，None 时使用当前订阅者

        Returns:
            重放的事件数量
        """
        events = self.get_history(event_type=event_type, since=since, limit=10000)
        # 反转回从旧到新
        events.reverse()

        count = 0
        for event in events:
            if handler:
                try:
                    handler(event)
                    count += 1
                except Exception as e:
                    logger.error("Replay handler error: %s", e)
            else:
                # 分发给当前订阅者
                self._publish_event(event)
                count += 1

        return count

    # ------------------------------------------------------------------
    #  内部工具
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._sub_counter += 1
        return f"{int(time.time()*1000)}_{self._sub_counter}"

    def clear(self) -> None:
        """清空所有订阅和历史（测试用）"""
        with self._lock:
            self._subscribers.clear()
            self._history.clear()


# ============================================================
# 事件总线统一接口
# ============================================================

class EventBus:
    """
    全局事件总线。

    根据配置选择后端实现（默认内存实现）。
    提供统一的发布、订阅、取消订阅、历史查询、事件重放接口。
    """

    def __init__(self, backend: str = "memory", **kwargs: Any):
        """
        初始化事件总线。

        Args:
            backend: 后端类型 ("memory" 或 "redis")
            **kwargs: 传递给后端实现的参数
        """
        self.backend = backend

        if backend == "memory":
            self._impl = InMemoryEventBus(
                max_history=kwargs.get("max_history", 10000),
            )
        elif backend == "redis":
            # Redis 实现（可选，延迟导入）
            raise NotImplementedError(
                "Redis event bus backend not implemented yet. "
                "Use 'memory' backend for now."
            )
        else:
            raise ValueError(f"Unsupported event bus backend: {backend}")

    def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = None,
    ) -> bool:
        """
        发布事件。

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源模块

        Returns:
            是否成功
        """
        return self._impl.publish(event_type, data, source=source or "")

    async def publish_async(
        self,
        event_type: str,
        data: Dict[str, Any],
        source: str = None,
    ) -> bool:
        """
        异步发布事件。

        Args:
            event_type: 事件类型
            data: 事件数据
            source: 事件来源模块

        Returns:
            是否成功
        """
        return await self._impl.publish_async(event_type, data, source=source or "")

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Any],
    ) -> str:
        """
        订阅事件。

        Args:
            event_type: 事件类型或模式（支持 * 和 # 通配符）
            handler: 事件处理器函数

        Returns:
            订阅 ID
        """
        return self._impl.subscribe(event_type, handler)

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅。

        Args:
            subscription_id: 订阅 ID

        Returns:
            是否成功
        """
        return self._impl.unsubscribe(subscription_id)

    def get_history(
        self,
        event_type: str = None,
        limit: int = 100,
        since: float = None,
    ) -> List[Event]:
        """获取事件历史"""
        return self._impl.get_history(event_type=event_type, limit=limit, since=since)

    def replay(
        self,
        event_type: str,
        since: float = None,
        handler: Callable[[Event], Any] = None,
    ) -> int:
        """事件重放"""
        return self._impl.replay(event_type, since=since, handler=handler)

    def get_subscription_count(self, event_type: str = None) -> int:
        """获取订阅数量"""
        return self._impl.get_subscription_count(event_type=event_type)

    def clear(self) -> None:
        """清空（测试用）"""
        self._impl.clear()


# ============================================================
# 全局单例
# ============================================================

_event_bus: Optional[EventBus] = None
_event_bus_lock = threading.Lock()


def get_event_bus(backend: str = "memory", **kwargs: Any) -> EventBus:
    """
    获取全局事件总线单例。

    Args:
        backend: 后端类型
        **kwargs: 后端参数

    Returns:
        EventBus 实例
    """
    global _event_bus
    if _event_bus is None:
        with _event_bus_lock:
            if _event_bus is None:
                _event_bus = EventBus(backend=backend, **kwargs)
    return _event_bus


def reset_event_bus() -> None:
    """重置事件总线（测试用）"""
    global _event_bus
    with _event_bus_lock:
        _event_bus = None


# ============================================================
# 工具函数
# ============================================================

def _match_pattern(event_type: str, pattern: str) -> bool:
    """
    事件类型模式匹配（与 models.py 中的 _match_event_pattern 相同逻辑）。

    规则：
    - 完全相等则匹配
    - "*" 匹配单级任意值
    - "#" 匹配 0 或多级任意值（只能在末尾）
    """
    if pattern == "#":
        return True
    if pattern == event_type:
        return True

    event_parts = event_type.split(".")
    pattern_parts = pattern.split(".")

    ei = 0
    pi = 0
    while ei < len(event_parts) and pi < len(pattern_parts):
        pp = pattern_parts[pi]
        if pp == "#":
            return True
        if pp == "*":
            ei += 1
            pi += 1
            continue
        if pp == event_parts[ei]:
            ei += 1
            pi += 1
            continue
        return False

    if pi == len(pattern_parts) and ei == len(event_parts):
        return True
    if pi == len(pattern_parts) - 1 and pattern_parts[pi] == "#":
        return True
    return False


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "EventBus",
    "InMemoryEventBus",
    "get_event_bus",
    "reset_event_bus",
]
