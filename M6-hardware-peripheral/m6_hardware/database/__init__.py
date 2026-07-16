"""
M6 硬件外设 - 数据库层

P1-5 改造：将 SQLite 连接管理与 SQL 操作抽离为独立数据层，
上层 service 只关注业务事务编排，不再直接拼接 SQL。
"""

from .connection import DatabaseConnection, get_db
from .repositories import DeviceStatusRepository, SensorDataRepository
from .wearable_repository import (
    WearableDeviceRepository,
    WearableHealthRepository,
    WearableNotificationRepository,
    WearableSettingsRepository,
)

__all__ = [
    "DatabaseConnection",
    "get_db",
    "DeviceStatusRepository",
    "SensorDataRepository",
    "WearableDeviceRepository",
    "WearableHealthRepository",
    "WearableNotificationRepository",
    "WearableSettingsRepository",
]
