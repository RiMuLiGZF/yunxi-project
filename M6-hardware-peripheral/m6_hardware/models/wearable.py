"""
可穿戴设备数据模型
================

定义可穿戴设备相关的 Pydantic 模型：
- WearableDevice: 可穿戴设备
- WearableHealthData: 健康数据
- WearableNotification: 通知推送
- WearableSettings: 设备配置

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 枚举类型
# ============================================================================

class WearableDeviceType(str, Enum):
    """可穿戴设备类型"""
    WATCH = "watch"           # 智能手表
    RING = "ring"             # 智能戒指
    BAND = "band"             # 智能手环
    GLASSES = "glasses"       # AR 眼镜


class WearableDeviceStatus(str, Enum):
    """设备状态"""
    ONLINE = "online"         # 在线
    OFFLINE = "offline"       # 离线
    CHARGING = "charging"     # 充电中
    WARNING = "warning"       # 告警状态


class HealthDataType(str, Enum):
    """健康数据类型"""
    HEART_RATE = "heart_rate"     # 心率
    SPO2 = "spo2"                 # 血氧
    STEPS = "steps"               # 步数
    SLEEP = "sleep"               # 睡眠
    TEMPERATURE = "temperature"   # 体温
    CALORIES = "calories"         # 卡路里


class DataQuality(str, Enum):
    """数据质量"""
    GOOD = "good"       # 良好
    POOR = "poor"       # 质量差


class DataSource(str, Enum):
    """数据来源"""
    DEVICE = "device"       # 设备采集
    MANUAL = "manual"       # 手动录入
    SYNCED = "synced"       # 同步而来


class NotificationStatus(str, Enum):
    """通知状态"""
    PENDING = "pending"       # 待发送
    SENT = "sent"             # 已发送
    DELIVERED = "delivered"   # 已送达
    FAILED = "failed"         # 发送失败
    READ = "read"             # 已读


class NotificationSource(str, Enum):
    """通知来源"""
    SYSTEM = "system"     # 系统通知
    APP = "app"           # 应用推送
    API = "api"           # API 调用


# ============================================================================
# 可穿戴设备
# ============================================================================

class WearableDeviceBase(BaseModel):
    """可穿戴设备基础模型"""
    device_id: str = Field(..., description="设备唯一标识")
    user_id: str = Field("default", description="所属用户ID")
    name: str = Field("", description="设备名称")
    device_type: WearableDeviceType = Field(WearableDeviceType.WATCH, description="设备类型")
    brand: str = Field("", description="品牌")
    model: str = Field("", description="型号")
    mac_address: str = Field("", description="MAC地址")
    status: WearableDeviceStatus = Field(WearableDeviceStatus.OFFLINE, description="设备状态")
    battery_level: Optional[float] = Field(None, ge=0, le=100, description="电量百分比")
    firmware_version: str = Field("", description="固件版本")
    last_sync_at: Optional[datetime] = Field(None, description="最后同步时间")
    paired_at: Optional[datetime] = Field(None, description="配对时间")


class WearableDevice(WearableDeviceBase):
    """可穿戴设备完整模型"""
    id: int = Field(0, description="数据库自增ID")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，枚举转 value，datetime 转 isoformat"""
        data = self.model_dump()
        # 枚举字段转字符串 value
        for field_name in ["device_type", "status"]:
            val = getattr(self, field_name)
            if isinstance(val, Enum):
                data[field_name] = val.value
        # datetime 字段转 ISO 字符串
        for field_name in ["last_sync_at", "paired_at", "created_at", "updated_at"]:
            val = data.get(field_name)
            if isinstance(val, datetime):
                data[field_name] = val.isoformat()
        return data


class WearableDeviceCreate(BaseModel):
    """创建设备请求"""
    device_id: str
    user_id: str = "default"
    name: str = ""
    device_type: WearableDeviceType = WearableDeviceType.WATCH
    brand: str = ""
    model: str = ""
    mac_address: str = ""
    status: WearableDeviceStatus = WearableDeviceStatus.OFFLINE
    battery_level: Optional[float] = None
    firmware_version: str = ""


class WearableDeviceUpdate(BaseModel):
    """更新设备请求"""
    name: Optional[str] = None
    device_type: Optional[WearableDeviceType] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    mac_address: Optional[str] = None
    status: Optional[WearableDeviceStatus] = None
    battery_level: Optional[float] = None
    firmware_version: Optional[str] = None
    last_sync_at: Optional[datetime] = None


# ============================================================================
# 健康数据
# ============================================================================

class WearableHealthDataBase(BaseModel):
    """健康数据基础模型"""
    device_id: str = Field(..., description="设备标识")
    user_id: str = Field("default", description="用户标识")
    data_type: HealthDataType = Field(..., description="数据类型")
    value: float = Field(0.0, description="数值")
    unit: str = Field("", description="单位")
    recorded_at: datetime = Field(default_factory=datetime.now, description="采集时间")
    source: DataSource = Field(DataSource.DEVICE, description="数据来源")
    quality: DataQuality = Field(DataQuality.GOOD, description="数据质量")


class WearableHealthData(WearableHealthDataBase):
    """健康数据完整模型"""
    id: int = Field(0, description="数据库自增ID")
    created_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        for field_name in ["data_type", "source", "quality"]:
            val = getattr(self, field_name)
            if isinstance(val, Enum):
                data[field_name] = val.value
        for field_name in ["recorded_at", "created_at"]:
            val = data.get(field_name)
            if isinstance(val, datetime):
                data[field_name] = val.isoformat()
        return data


class WearableHealthDataCreate(BaseModel):
    """上报健康数据请求"""
    device_id: str
    user_id: str = "default"
    data_type: HealthDataType
    value: float
    unit: str = ""
    recorded_at: Optional[datetime] = None
    source: DataSource = DataSource.DEVICE
    quality: DataQuality = DataQuality.GOOD


class HealthDataQuery(BaseModel):
    """健康数据查询参数"""
    device_id: Optional[str] = None
    user_id: Optional[str] = None
    data_type: Optional[HealthDataType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 1000
    offset: int = 0


# ============================================================================
# 通知推送
# ============================================================================

class WearableNotificationBase(BaseModel):
    """通知基础模型"""
    notification_id: str = Field(..., description="通知唯一ID")
    device_id: str = Field(..., description="目标设备")
    user_id: str = Field("default", description="用户标识")
    title: str = Field("", description="通知标题")
    content: str = Field("", description="通知内容")
    type: str = Field("system", description="通知类型")
    status: NotificationStatus = Field(NotificationStatus.PENDING, description="通知状态")
    source: NotificationSource = Field(NotificationSource.SYSTEM, description="来源")
    delivered_at: Optional[datetime] = Field(None, description="送达时间")


class WearableNotification(WearableNotificationBase):
    """通知完整模型"""
    id: int = Field(0, description="数据库自增ID")
    created_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        for field_name in ["status", "source"]:
            val = getattr(self, field_name)
            if isinstance(val, Enum):
                data[field_name] = val.value
        for field_name in ["delivered_at", "created_at"]:
            val = data.get(field_name)
            if isinstance(val, datetime):
                data[field_name] = val.isoformat()
        return data


class WearableNotificationCreate(BaseModel):
    """发送通知请求"""
    device_id: str
    user_id: str = "default"
    title: str
    content: str = ""
    type: str = "system"
    source: NotificationSource = NotificationSource.API


# ============================================================================
# 设备配置
# ============================================================================

class WearableSettings(BaseModel):
    """设备配置模型"""
    id: int = Field(0, description="数据库自增ID")
    device_id: str = Field(..., description="设备标识")
    user_id: str = Field("default", description="用户标识")
    settings_json: Dict[str, Any] = Field(default_factory=dict, description="配置JSON")
    updated_at: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if isinstance(data["updated_at"], datetime):
            data["updated_at"] = data["updated_at"].isoformat()
        return data


class WearableSettingsUpdate(BaseModel):
    """更新设备配置请求"""
    settings_json: Dict[str, Any]
