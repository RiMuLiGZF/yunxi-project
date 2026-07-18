"""
事件驱动同步（Event-Driven Sync）
================================

基于事件发布订阅模式的实时数据同步。

核心能力：
- 数据变更事件发布
- 订阅者模式
- 实时数据同步
- 批量合并（减少同步次数）
"""

from __future__ import annotations

import time
import uuid
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================
# 事件类型
# ============================================================

class ChangeType(str, Enum):
    """数据变更类型"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    BULK_INSERT = "bulk_insert"
    BULK_UPDATE = "bulk_update"
    BULK_DELETE = "bulk_delete"


# ============================================================
# 数据变更事件
# ============================================================

@dataclass
class DataChangeEvent:
    """
    数据变更事件。

    Attributes:
        event_id: 事件唯一 ID
        model_name: 模型名称
        change_type: 变更类型
        record_id: 记录主键（单条变更时）
        record_ids: 记录主键列表（批量变更时）
        data: 变更数据（create/update 时有值）
        old_data: 旧数据（update/delete 时有值）
        source: 事件来源模块
        version: 数据版本号
        timestamp: 事件时间戳
        metadata: 额外元数据
    """
    model_name: str
    change_type: ChangeType
    record_id: Any = None
    record_ids: List[Any] = field(default_factory=list)
    data: Optional[Dict[str, Any]] = None
    old_data: Optional[Dict[str, Any]] = None
    source: str = ""
    version: int = 0
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "model_name": self.model_name,
            "change_type": self.change_type.value,
            "record_id": self.record_id,
            "record_ids": self.record_ids,
            "source": self.source,
            "version": self.version,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ============================================================
# 订阅者
# ============================================================

class SyncSubscriber:
    """
    同步订阅者。

    订阅数据变更事件，并处理同步逻辑。
    """

    def __init__(self, name: str):
        self._name = name
        self._event_count = 0
        self._last_event_time: Optional[float] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def event_count(self) -> int:
        return self._event_count

    def on_event(self, event: DataChangeEvent) -> None:
        """
        处理数据变更事件。

        子类应重写此方法实现具体的同步逻辑。
        """
        self._event_count += 1
        self._last_event_time = event.timestamp
        logger.debug(f"Subscriber {self._name} received event: {event.event_id}")

    def on_batch(self, events: List[DataChangeEvent]) -> None:
        """
        处理批量事件。

        默认实现是逐个调用 on_event，子类可以优化为批量处理。
        """
        for event in events:
            self.on_event(event)


# ============================================================
# 回调式订阅者
# ============================================================

class CallbackSubscriber(SyncSubscriber):
    """基于回调函数的订阅者"""

    def __init__(self, name: str, callback: Callable[[DataChangeEvent], None]):
        super().__init__(name)
        self._callback = callback

    def on_event(self, event: DataChangeEvent) -> None:
        super().on_event(event)
        try:
            self._callback(event)
        except Exception as e:
            logger.error(f"Subscriber {self._name} callback error: {e}")


# ============================================================
# 事件同步管理器
# ============================================================

class EventSyncManager:
    """
    事件驱动同步管理器。

    提供数据变更事件的发布和订阅能力，
    支持实时同步和批量合并。

    使用方式：
        manager = EventSyncManager()

        # 订阅
        subscriber = CallbackSubscriber("test", handler)
        manager.subscribe("user", subscriber)

        # 发布
        manager.publish(DataChangeEvent(
            model_name="user",
            change_type=ChangeType.CREATE,
            data={"id": 1, "name": "test"},
        ))
    """

    def __init__(self, batch_flush_interval: float = 1.0, max_batch_size: int = 100):
        """
        初始化事件同步管理器。

        Args:
            batch_flush_interval: 批量刷新间隔（秒）
            max_batch_size: 最大批量大小
        """
        self._subscribers: Dict[str, List[SyncSubscriber]] = {}
        self._all_subscribers: List[SyncSubscriber] = []
        self._event_log: List[DataChangeEvent] = []
        self._lock = threading.RLock()

        # 批量合并
        self._batch_flush_interval = batch_flush_interval
        self._max_batch_size = max_batch_size
        self._pending_batches: Dict[str, List[DataChangeEvent]] = {}
        self._batch_timers: Dict[str, Any] = {}
        self._total_published = 0
        self._total_delivered = 0

    # ---- 订阅管理 ----

    def subscribe(
        self,
        model_pattern: str,
        subscriber: SyncSubscriber,
    ) -> None:
        """
        订阅数据变更事件。

        Args:
            model_pattern: 模型名模式（支持 "*" 通配所有）
            subscriber: 订阅者
        """
        with self._lock:
            if model_pattern == "*":
                if subscriber not in self._all_subscribers:
                    self._all_subscribers.append(subscriber)
            else:
                if model_pattern not in self._subscribers:
                    self._subscribers[model_pattern] = []
                if subscriber not in self._subscribers[model_pattern]:
                    self._subscribers[model_pattern].append(subscriber)

    def unsubscribe(
        self,
        model_pattern: str,
        subscriber: SyncSubscriber,
    ) -> bool:
        """取消订阅"""
        with self._lock:
            if model_pattern == "*":
                if subscriber in self._all_subscribers:
                    self._all_subscribers.remove(subscriber)
                    return True
            elif model_pattern in self._subscribers:
                if subscriber in self._subscribers[model_pattern]:
                    self._subscribers[model_pattern].remove(subscriber)
                    return True
            return False

    def get_subscribers(self, model_name: str) -> List[SyncSubscriber]:
        """获取指定模型的所有订阅者"""
        with self._lock:
            result = list(self._all_subscribers)
            if model_name in self._subscribers:
                result.extend(self._subscribers[model_name])
            return result

    # ---- 事件发布 ----

    def publish(self, event: DataChangeEvent) -> int:
        """
        发布数据变更事件。

        Args:
            event: 数据变更事件

        Returns:
            通知的订阅者数量
        """
        with self._lock:
            self._event_log.append(event)
            self._total_published += 1

            # 保留最近 10000 条
            if len(self._event_log) > 10000:
                self._event_log = self._event_log[-10000:]

            subscribers = self.get_subscribers(event.model_name)
            delivered = 0

            for subscriber in subscribers:
                try:
                    subscriber.on_event(event)
                    delivered += 1
                except Exception as e:
                    logger.error(f"Failed to deliver event to {subscriber.name}: {e}")

            self._total_delivered += delivered
            return delivered

    def publish_many(self, events: List[DataChangeEvent]) -> int:
        """批量发布事件"""
        total = 0
        for event in events:
            total += self.publish(event)
        return total

    # ---- 批量合并 ----

    def publish_batched(self, event: DataChangeEvent) -> None:
        """
        发布批量事件（延迟合并后推送）。

        将事件加入待处理队列，达到批量大小或时间间隔后统一推送。
        """
        with self._lock:
            model = event.model_name
            if model not in self._pending_batches:
                self._pending_batches[model] = []

            self._pending_batches[model].append(event)

            # 达到批量大小，立即刷新
            if len(self._pending_batches[model]) >= self._max_batch_size:
                self._flush_batch(model)

    def flush_all(self) -> None:
        """刷新所有待处理的批量事件"""
        with self._lock:
            for model in list(self._pending_batches.keys()):
                self._flush_batch(model)

    def _flush_batch(self, model_name: str) -> None:
        """刷新指定模型的批量事件"""
        if model_name not in self._pending_batches:
            return

        events = self._pending_batches[model_name]
        if not events:
            return

        self._pending_batches[model_name] = []

        # 记录事件日志
        self._event_log.extend(events)
        self._total_published += len(events)

        # 通知订阅者
        subscribers = self.get_subscribers(model_name)
        for subscriber in subscribers:
            try:
                subscriber.on_batch(events)
                self._total_delivered += len(events)
            except Exception as e:
                logger.error(f"Batch delivery failed to {subscriber.name}: {e}")

    # ---- 查询 ----

    def get_event_log(
        self,
        model_name: Optional[str] = None,
        change_type: Optional[ChangeType] = None,
        limit: int = 100,
    ) -> List[DataChangeEvent]:
        """获取事件日志"""
        with self._lock:
            events = list(self._event_log)

            if model_name:
                events = [e for e in events if e.model_name == model_name]
            if change_type:
                events = [e for e in events if e.change_type == change_type]

            return events[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_published": self._total_published,
                "total_delivered": self._total_delivered,
                "subscriber_count": sum(
                    len(subs) for subs in self._subscribers.values()
                ) + len(self._all_subscribers),
                "model_count": len(self._subscribers),
                "event_log_size": len(self._event_log),
                "pending_batches": {
                    k: len(v) for k, v in self._pending_batches.items()
                },
            }

    def clear(self) -> None:
        """清空所有状态"""
        with self._lock:
            self._subscribers.clear()
            self._all_subscribers.clear()
            self._event_log.clear()
            self._pending_batches.clear()
            self._total_published = 0
            self._total_delivered = 0
