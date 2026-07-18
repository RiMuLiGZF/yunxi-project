"""
数据同步引擎模块（Sync Engine）
==========================

提供模块间数据同步能力。
"""

from .sync_engine import (
    SyncEngine,
    SyncEndpoint,
    SyncRecord,
    SyncProgress,
    SyncConflict,
    SyncMode,
    SyncStatus,
    SyncDirection,
    ConflictResolution,
)
from .event_sync import (
    EventSyncManager,
    DataChangeEvent,
    SyncSubscriber,
)

__all__ = [
    # 同步引擎
    "SyncEngine",
    "SyncEndpoint",
    "SyncRecord",
    "SyncProgress",
    "SyncConflict",
    "SyncMode",
    "SyncStatus",
    "SyncDirection",
    "ConflictResolution",
    # 事件驱动同步
    "EventSyncManager",
    "DataChangeEvent",
    "SyncSubscriber",
]
