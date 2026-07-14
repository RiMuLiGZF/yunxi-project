"""
M8 管理工作台 - 手表交互模型

包含 WatchDevice, WatchHealthData, WatchNotification, WatchSetting。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class WatchDevice(Base):
    """手表设备表"""
    __tablename__ = "watch_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), unique=True, index=True, comment="设备ID")
    name = Column(String(100), comment="设备名称")
    device_type = Column(String(20), default="watch", comment="设备类型：watch/ring/glasses")
    brand = Column(String(50), default="", comment="品牌")
    model = Column(String(50), default="", comment="型号")
    firmware_version = Column(String(50), default="v1.0.0", comment="固件版本")
    status = Column(String(20), default="offline", comment="状态：online/offline/charging/warning")
    battery = Column(Integer, default=100, comment="电量百分比")
    paired = Column(Boolean, default=False, comment="是否已配对")
    paired_at = Column(DateTime, nullable=True, comment="配对时间")
    last_sync = Column(DateTime, nullable=True, comment="最后同步时间")
    mac_address = Column(String(50), default="", comment="MAC地址")
    features = Column(JSON, default=list, comment="支持的功能列表(JSON)")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
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
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WatchHealthData(Base):
    """手表健康数据表"""
    __tablename__ = "watch_health_data"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), index=True, comment="设备ID")
    data_type = Column(String(20), index=True, comment="数据类型：heart_rate/spo2/steps/sleep/temperature/calories")
    value = Column(Float, comment="数值")
    unit = Column(String(20), default="", comment="单位")
    timestamp = Column(DateTime, index=True, comment="数据采集时间")
    source = Column(String(20), default="watch", comment="数据来源")
    quality = Column(String(20), default="good", comment="数据质量：good/poor")
    extra = Column(JSON, default=dict, comment="额外数据(JSON)")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "data_type": self.data_type,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": self.source,
            "quality": self.quality,
            "extra": self.extra or {},
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WatchNotification(Base):
    """手表通知记录表"""
    __tablename__ = "watch_notifications"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(String(64), unique=True, index=True, comment="通知ID")
    device_id = Column(String(64), index=True, comment="设备ID")
    title = Column(String(255), comment="通知标题")
    content = Column(Text, comment="通知内容")
    notification_type = Column(String(20), default="info", comment="类型：info/warning/error/reminder")
    status = Column(String(20), default="sent", comment="状态：pending/sent/delivered/failed/read")
    delivered_at = Column(DateTime, nullable=True, comment="送达时间")
    read_at = Column(DateTime, nullable=True, comment="阅读时间")
    action_type = Column(String(50), default="", comment="动作类型")
    action_data = Column(JSON, default=dict, comment="动作数据(JSON)")
    source = Column(String(30), default="system", comment="来源")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "notification_id": self.notification_id,
            "device_id": self.device_id,
            "title": self.title,
            "content": self.content,
            "notification_type": self.notification_type,
            "status": self.status,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "action_type": self.action_type,
            "action_data": self.action_data or {},
            "source": self.source,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WatchSetting(Base):
    """手表设置表"""
    __tablename__ = "watch_settings"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(64), unique=True, index=True, comment="设备ID")
    settings_json = Column(JSON, default=dict, comment="设置数据(JSON)")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "settings": self.settings_json or {},
            "user_id": self.user_id,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
