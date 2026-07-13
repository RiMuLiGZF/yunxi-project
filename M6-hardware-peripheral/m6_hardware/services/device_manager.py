"""
M6 硬件外设 - 设备管理器
单例模式，管理所有设备的注册、查询、配对等操作
"""

import random
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from ..models.device import Device, DeviceStatus, DeviceType
from ..devices import (
    BaseDeviceSimulator,
    SmartWatchSimulator,
    SmartRingSimulator,
    DesktopScreenSimulator,
    ARGlassesSimulator,
    DroneSimulator,
    LaptopSimulator,
)


class DeviceManager:
    """设备管理器

    管理所有已注册的设备模拟器，提供设备列表、详情、配对、扫描等功能。

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_device_manager() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self):
        self._devices: Dict[str, BaseDeviceSimulator] = {}
        self._init_default_devices()

    def _init_default_devices(self):
        """初始化默认的 6 种设备"""
        # 智能手表
        watch = Device(
            device_id="dev-watch-001",
            name="云汐智能手表",
            device_type=DeviceType.WATCH,
            status=DeviceStatus.ONLINE,
            battery=78.0,
            signal_strength=85,
            firmware_version="2.3.1",
            capabilities=[
                "heart_rate_monitor", "step_counter", "sleep_tracking",
                "notification", "sedentary_reminder", "find_device",
            ],
            position={"x": 50, "y": 30},
            paired=True,
        )
        self._devices[watch.device_id] = SmartWatchSimulator(watch)

        # 智能戒指
        ring = Device(
            device_id="dev-ring-001",
            name="云汐智能戒指",
            device_type=DeviceType.RING,
            status=DeviceStatus.ONLINE,
            battery=92.0,
            signal_strength=90,
            firmware_version="1.5.2",
            capabilities=[
                "heart_rate_monitor", "temperature_sensor",
                "sleep_tracking", "stress_monitor", "hrv_analysis",
            ],
            position={"x": 20, "y": 50},
            paired=True,
        )
        self._devices[ring.device_id] = SmartRingSimulator(ring)

        # 桌面终端
        desktop = Device(
            device_id="dev-desktop-001",
            name="云汐桌面终端",
            device_type=DeviceType.DESKTOP,
            status=DeviceStatus.ONLINE,
            battery=None,  # 有线供电
            signal_strength=100,
            firmware_version="3.1.0",
            capabilities=[
                "ambient_light", "temperature_sensor", "humidity_sensor",
                "air_quality", "schedule_display", "video_call",
            ],
            position={"x": 80, "y": 30},
            paired=True,
        )
        self._devices[desktop.device_id] = DesktopScreenSimulator(desktop)

        # AR眼镜
        ar = Device(
            device_id="dev-ar-001",
            name="云汐AR眼镜",
            device_type=DeviceType.AR,
            status=DeviceStatus.WARNING,
            battery=35.0,
            signal_strength=75,
            firmware_version="1.2.0",
            capabilities=[
                "head_tracking", "eye_tracking", "depth_sensing",
                "ar_navigation", "translation", "info_overlay",
            ],
            position={"x": 50, "y": 60},
            paired=True,
        )
        self._devices[ar.device_id] = ARGlassesSimulator(ar)

        # 改装无人机
        drone = Device(
            device_id="dev-drone-001",
            name="云汐改装无人机",
            device_type=DeviceType.DRONE,
            status=DeviceStatus.OFFLINE,
            battery=65.0,
            signal_strength=70,
            firmware_version="4.0.1",
            capabilities=[
                "gps", "altitude_sensor", "aerial_photography",
                "environmental_monitoring", "delivery", "return_to_home",
            ],
            position={"x": 20, "y": 20},
            paired=False,
        )
        self._devices[drone.device_id] = DroneSimulator(drone)

        # 笔记本电脑
        laptop = Device(
            device_id="dev-laptop-001",
            name="云汐笔记本电脑",
            device_type=DeviceType.LAPTOP,
            status=DeviceStatus.ONLINE,
            battery=65.0,
            signal_strength=95,
            firmware_version="1.8.3",
            capabilities=[
                "cpu_monitor", "memory_monitor", "disk_monitor",
                "network_monitor", "work_efficiency", "focus_mode",
            ],
            position={"x": 80, "y": 70},
            paired=True,
        )
        self._devices[laptop.device_id] = LaptopSimulator(laptop)

    def list_devices(
        self,
        status: Optional[DeviceStatus] = None,
        device_type: Optional[DeviceType] = None,
    ) -> List[Dict[str, Any]]:
        """获取设备列表

        Args:
            status: 按状态过滤
            device_type: 按类型过滤

        Returns:
            设备信息列表
        """
        result = []
        for dev in self._devices.values():
            if status and dev.status != status:
                continue
            if device_type and dev.device_type != device_type:
                continue
            result.append(dev.to_dict())
        return result

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取单个设备详情

        Args:
            device_id: 设备ID

        Returns:
            设备信息（包含最新传感器数据），不存在返回 None
        """
        dev = self._devices.get(device_id)
        if not dev:
            return None
        return dev.to_dict()

    def get_simulator(self, device_id: str) -> Optional[BaseDeviceSimulator]:
        """获取设备模拟器实例

        Args:
            device_id: 设备ID

        Returns:
            设备模拟器实例
        """
        return self._devices.get(device_id)

    def pair_device(self, device_id: str) -> Dict[str, Any]:
        """配对设备

        Args:
            device_id: 设备ID

        Returns:
            配对结果
        """
        dev = self._devices.get(device_id)
        if not dev:
            return {"success": False, "message": f"设备不存在: {device_id}"}

        if dev.device.paired:
            return {"success": False, "message": "设备已配对"}

        dev.device.paired = True
        if dev.status == DeviceStatus.OFFLINE:
            dev.device.status = DeviceStatus.ONLINE
        return {
            "success": True,
            "message": "设备配对成功",
            "device_id": device_id,
        }

    def unpair_device(self, device_id: str) -> Dict[str, Any]:
        """取消配对

        Args:
            device_id: 设备ID

        Returns:
            取消配对结果
        """
        dev = self._devices.get(device_id)
        if not dev:
            return {"success": False, "message": f"设备不存在: {device_id}"}

        if not dev.device.paired:
            return {"success": False, "message": "设备未配对"}

        dev.device.paired = False
        return {
            "success": True,
            "message": "设备已取消配对",
            "device_id": device_id,
        }

    def update_device_config(self, device_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新设备配置

        Args:
            device_id: 设备ID
            config: 配置更新字典

        Returns:
            更新结果
        """
        dev = self._devices.get(device_id)
        if not dev:
            return {"success": False, "message": f"设备不存在: {device_id}"}

        dev.device.config.update(config)

        # 位置更新
        if "position" in config:
            dev.device.position.update(config["position"])

        # 名称更新
        if "name" in config:
            dev.device.name = config["name"]

        return {
            "success": True,
            "message": "配置已更新",
            "device_id": device_id,
            "updated_keys": list(config.keys()),
        }

    def scan_devices(self) -> List[Dict[str, Any]]:
        """扫描附近设备（模拟发现新设备）

        Returns:
            发现的设备列表（可能包含未配对的新设备）
        """
        # 模拟扫描过程
        found = []

        # 已有的未配对设备
        for dev in self._devices.values():
            if not dev.device.paired:
                found.append({
                    "device_id": dev.device_id,
                    "name": dev.device.name,
                    "device_type": dev.device_type.value,
                    "rssi": random.randint(-80, -40),
                    "paired": False,
                })

        # 模拟发现 1-2 个新设备
        num_new = random.randint(0, 2)
        device_types = list(DeviceType)
        for i in range(num_new):
            dtype = random.choice(device_types)
            found.append({
                "device_id": f"dev-new-{uuid.uuid4().hex[:8]}",
                "name": f"新设备-{dtype.value}-{random.randint(100, 999)}",
                "device_type": dtype.value,
                "rssi": random.randint(-90, -50),
                "paired": False,
                "is_new": True,
            })

        return found

    def get_stats(self) -> Dict[str, Any]:
        """获取设备统计

        Returns:
            统计数据
        """
        total = len(self._devices)
        online = sum(1 for d in self._devices.values() if d.status == DeviceStatus.ONLINE)
        offline = sum(1 for d in self._devices.values() if d.status == DeviceStatus.OFFLINE)
        warning = sum(1 for d in self._devices.values() if d.status == DeviceStatus.WARNING)
        charging = sum(1 for d in self._devices.values() if d.status == DeviceStatus.CHARGING)
        paired = sum(1 for d in self._devices.values() if d.device.paired)

        # 按类型统计
        by_type = {}
        for dtype in DeviceType:
            count = sum(1 for d in self._devices.values() if d.device_type == dtype)
            if count > 0:
                by_type[dtype.value] = count

        return {
            "total": total,
            "online": online,
            "offline": offline,
            "warning": warning,
            "charging": charging,
            "paired": paired,
            "by_type": by_type,
        }

    def tick_all(self):
        """驱动所有设备执行一次模拟步进"""
        for dev in self._devices.values():
            dev.tick()


_instance: DeviceManager | None = None


def get_device_manager() -> DeviceManager:
    """获取设备管理器单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_device_manager)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = DeviceManager()
    return _instance
