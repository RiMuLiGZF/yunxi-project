"""
M6 硬件外设 - 传感器数据模型
定义各类传感器数据的结构
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class SensorReading(BaseModel):
    """单个传感器读数"""

    sensor_type: str = Field(..., description="传感器类型，如 heart_rate, temperature 等")
    value: Any = Field(..., description="传感器读数")
    unit: str = Field(default="", description="单位")
    timestamp: datetime = Field(default_factory=datetime.now, description="采集时间")
    quality: int = Field(default=100, ge=0, le=100, description="数据质量分数")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = self.model_dump()
        data["timestamp"] = self.timestamp.isoformat()
        return data


class SensorData(BaseModel):
    """设备传感器数据集"""

    device_id: str = Field(..., description="设备ID")
    readings: Dict[str, SensorReading] = Field(default_factory=dict, description="各传感器读数")
    collected_at: datetime = Field(default_factory=datetime.now, description="采集时间")

    def get_reading(self, sensor_type: str) -> Optional[SensorReading]:
        """获取指定传感器的读数"""
        return self.readings.get(sensor_type)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "device_id": self.device_id,
            "collected_at": self.collected_at.isoformat(),
            "readings": {k: v.to_dict() for k, v in self.readings.items()},
        }
