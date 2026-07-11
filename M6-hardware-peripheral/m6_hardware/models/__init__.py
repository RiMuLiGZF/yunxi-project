"""
M6 硬件外设 - 数据模型
"""

from .device import Device, DeviceStatus, DeviceType
from .sensor_data import SensorData, SensorReading

__all__ = [
    "Device",
    "DeviceStatus",
    "DeviceType",
    "SensorData",
    "SensorReading",
]
