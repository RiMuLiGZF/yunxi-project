"""手表交互表模块.

包含设备、健康数据、通知等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)

from .base import Base


class WatchDeviceDB(Base):
    """手表交互 - 设备表."""

    __tablename__ = "watch_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String(100), default="智能手表")
    device_type = Column(String(20), default="watch", index=True)  # watch/ring/band
    brand = Column(String(50), default="Yunxi")
    model = Column(String(50), default="")
    firmware_version = Column(String(50), default="v1.0.0")
    status = Column(String(20), default="offline", index=True)  # online/offline
    battery = Column(Integer, default=100)
    paired = Column(Boolean, default=False)
    paired_at = Column(DateTime, nullable=True)
    last_sync = Column(DateTime, nullable=True)
    mac_address = Column(String(32), default="")
    features = Column(JSON, default=list)  # ["heart_rate", "steps", "sleep", ...]
    settings = Column(JSON, default=dict)  # 手表端配置
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_watch_dev_user", "user_id"),
        Index("idx_watch_dev_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type,
            "brand": self.brand,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "status": self.status,
            "battery": self.battery,
            "paired": self.paired,
            "paired_at": self.paired_at.isoformat() if self.paired_at else None,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "mac_address": self.mac_address,
            "features": self.features or [],
            "settings": self.settings or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WatchHealthDataDB(Base):
    """手表交互 - 健康数据表."""

    __tablename__ = "watch_health_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    data_type = Column(String(30), nullable=False, index=True)  # heart_rate/steps/spo2/sleep/calories
    value = Column(Float, default=0.0)
    unit = Column(String(20), default="")
    extra = Column(JSON, default=dict)  # 额外字段（如睡眠分期、步数目标等）
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_watch_health_dev", "device_id", "data_type", "recorded_at"),
        Index("idx_watch_health_user", "user_id", "data_type", "recorded_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "device_id": self.device_id,
            "data_type": self.data_type,
            "value": self.value,
            "unit": self.unit,
            "extra": self.extra or {},
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "timestamp": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class WatchNotificationDB(Base):
    """手表交互 - 通知表."""

    __tablename__ = "watch_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(String(64), nullable=False, unique=True, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    title = Column(String(100), default="")
    content = Column(Text, default="")
    notification_type = Column(String(20), default="info", index=True)  # info/warning/reminder/error
    status = Column(String(20), default="pending", index=True)  # pending/delivered/read/failed
    action_type = Column(String(50), default="")
    action_data = Column(JSON, default=dict)
    source = Column(String(30), default="api")
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_watch_notif_dev", "device_id", "created_at"),
        Index("idx_watch_notif_user", "user_id", "created_at"),
        Index("idx_watch_notif_status", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "notification_id": self.notification_id,
            "device_id": self.device_id,
            "title": self.title,
            "content": self.content,
            "notification_type": self.notification_type,
            "status": self.status,
            "action_type": self.action_type,
            "action_data": self.action_data or {},
            "source": self.source,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
