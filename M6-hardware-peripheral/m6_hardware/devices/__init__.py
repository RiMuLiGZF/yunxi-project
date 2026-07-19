"""
M6 硬件外设 - 设备模拟器包
包含可穿戴设备 + 智能家居设备的模拟逻辑

P2 半真实化改造：新增 5 种智能家居设备（智能台灯、温湿度传感器、智能插座、窗帘电机、空气质量传感器）
"""

from .base_device import BaseDeviceSimulator
from .smart_watch import SmartWatchSimulator
from .smart_ring import SmartRingSimulator
from .desktop_screen import DesktopScreenSimulator
from .ar_glasses import ARGlassesSimulator
from .drone import DroneSimulator
from .laptop import LaptopSimulator

# P2 半真实化改造：智能家居设备
from .smart_lamp import SmartLampSimulator
from .temp_humidity_sensor import TempHumiditySensorSimulator
from .smart_plug import SmartPlugSimulator
from .curtain_motor import CurtainMotorSimulator

__all__ = [
    "BaseDeviceSimulator",
    "SmartWatchSimulator",
    "SmartRingSimulator",
    "DesktopScreenSimulator",
    "ARGlassesSimulator",
    "DroneSimulator",
    "LaptopSimulator",
    # 智能家居设备
    "SmartLampSimulator",
    "TempHumiditySensorSimulator",
    "SmartPlugSimulator",
    "CurtainMotorSimulator",
]

# P2-10: 设备工厂统一入口
from .device_factory import DeviceFactory, DeviceCapability, get_device_factory
