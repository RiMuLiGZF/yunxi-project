"""
M6 硬件外设 - 数据模型
"""

from .device import Device, DeviceStatus, DeviceType
from .sensor_data import SensorData, SensorReading
from .errors import ErrorCode, M6Exception

__all__ = [
    "Device",
    "DeviceStatus",
    "DeviceType",
    "SensorData",
    "SensorReading",
    "ErrorCode",
    "M6Exception",
]
