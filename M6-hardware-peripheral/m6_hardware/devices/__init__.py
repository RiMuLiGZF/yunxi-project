"""
M6 硬件外设 - 设备模拟器包
包含 6 种硬件设备的模拟逻辑
"""

from .base_device import BaseDeviceSimulator
from .smart_watch import SmartWatchSimulator
from .smart_ring import SmartRingSimulator
from .desktop_screen import DesktopScreenSimulator
from .ar_glasses import ARGlassesSimulator
from .drone import DroneSimulator
from .laptop import LaptopSimulator

__all__ = [
    "BaseDeviceSimulator",
    "SmartWatchSimulator",
    "SmartRingSimulator",
    "DesktopScreenSimulator",
    "ARGlassesSimulator",
    "DroneSimulator",
    "LaptopSimulator",
]

# P2-10: 设备工厂统一入口
from .device_factory import DeviceFactory, DeviceCapability, get_device_factory
