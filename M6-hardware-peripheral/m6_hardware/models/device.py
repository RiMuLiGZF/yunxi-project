"""
M6 硬件外设 - 设备数据模型
定义设备的基础属性和状态枚举
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


class DeviceStatus(str, Enum):
    """设备状态枚举"""
    ONLINE = "online"          # 在线
    OFFLINE = "offline"        # 离线
    WARNING = "warning"        # 警告（低电量、异常）
    CHARGING = "charging"      # 充电中


class DeviceType(str, Enum):
    """设备类型枚举"""
    WATCH = "watch"            # 智能手表
    RING = "ring"              # 智能戒指
    DESKTOP = "desktop"        # 桌面终端
    AR = "ar"                  # AR眼镜
    DRONE = "drone"            # 无人机
    LAPTOP = "laptop"          # 笔记本电脑


class Device(BaseModel):
    """设备基础模型"""

    device_id: str = Field(..., description="设备唯一ID")
    name: str = Field(..., description="设备名称")
    device_type: DeviceType = Field(..., description="设备类型")
    status: DeviceStatus = Field(default=DeviceStatus.ONLINE, description="设备状态")
    battery: Optional[float] = Field(default=None, ge=0, le=100, description="电量百分比，None表示有线供电")
    signal_strength: int = Field(default=85, ge=0, le=100, description="信号强度")
    firmware_version: str = Field(default="1.0.0", description="固件版本")
    last_seen: datetime = Field(default_factory=datetime.now, description="最后在线时间")
    capabilities: List[str] = Field(default_factory=list, description="支持的功能列表")
    position: Dict[str, float] = Field(default_factory=dict, description="UI展示位置坐标 {x, y}")
    paired: bool = Field(default=True, description="是否已配对")
    config: Dict[str, Any] = Field(default_factory=dict, description="设备配置")

    model_config = {
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        data = self.model_dump()
        data["device_type"] = self.device_type.value
        data["status"] = self.status.value
        data["last_seen"] = self.last_seen.isoformat()
        return data
