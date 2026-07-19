"""
M6 硬件外设 - 设备管理器
单例模式，管理所有设备的注册、查询、配对等操作

P2 半真实化改造：
- 新增智能家居设备（智能台灯、温湿度传感器、智能插座、窗帘电机）
- 集成状态持久化（StatePersistence）
- 支持设备注册/发现/移除接口
"""

import logging
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..config import get_config
from ..models.device import Device, DeviceStatus, DeviceType
from ..devices import (
    BaseDeviceSimulator,
    SmartWatchSimulator,
    SmartRingSimulator,
    DesktopScreenSimulator,
    ARGlassesSimulator,
    DroneSimulator,
    LaptopSimulator,
    # P2 半真实化：智能家居设备
    SmartLampSimulator,
    TempHumiditySensorSimulator,
    SmartPlugSimulator,
    CurtainMotorSimulator,
)
from .state_persistence import StatePersistence

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备管理器

    管理所有已注册的设备模拟器，提供设备列表、详情、配对、扫描等功能。

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_device_manager() 作为向后兼容层保留（标记 deprecated）。
    """

    def __init__(self, config=None, state_persistence: Optional[StatePersistence] = None):
        self._config = config if config is not None else get_config()
        self._devices: Dict[str, BaseDeviceSimulator] = {}

        # P2 半真实化：状态持久化
        if state_persistence is not None:
            self._state_persistence = state_persistence
        else:
            state_file = str(Path(self._config.database_path).parent / "device_states.json")
            self._state_persistence = StatePersistence(state_file)

        self._init_default_devices()
        # P2: 启动时加载持久化状态
        self._load_persisted_states()

    def _create_simulator(self, device: Device) -> Optional[BaseDeviceSimulator]:
        """根据设备类型创建对应的模拟器实例"""
        mapping = {
            DeviceType.WATCH: SmartWatchSimulator,
            DeviceType.RING: SmartRingSimulator,
            DeviceType.DESKTOP: DesktopScreenSimulator,
            DeviceType.AR: ARGlassesSimulator,
            DeviceType.DRONE: DroneSimulator,
            DeviceType.LAPTOP: LaptopSimulator,
            # P2 半真实化：智能家居设备
            DeviceType.SMART_LAMP: SmartLampSimulator,
            DeviceType.TEMP_HUMIDITY: TempHumiditySensorSimulator,
            DeviceType.SMART_PLUG: SmartPlugSimulator,
            DeviceType.CURTAIN_MOTOR: CurtainMotorSimulator,
        }
        sim_class = mapping.get(device.device_type)
        if sim_class is None:
            logger.warning("未知的设备类型: %s", device.device_type)
            return None
        return sim_class(device, config=self._config)

    def _init_default_devices(self):
        """初始化默认设备

        P1-3 改造：优先从配置的 default_devices_path 加载 YAML 设备列表，
        未配置或加载失败时回退到内置的 6 种默认设备。
        """
        if self._config.default_devices_path:
            try:
                import yaml
                path = self._config.default_devices_path
                with open(path, "r", encoding="utf-8") as f:
                    devices_config = yaml.safe_load(f)
                if isinstance(devices_config, list):
                    for item in devices_config:
                        device = Device(**item)
                        simulator = self._create_simulator(device)
                        if simulator:
                            self._devices[device.device_id] = simulator
                    if self._devices:
                        logger.info("已从 %s 加载 %d 个默认设备", path, len(self._devices))
                        return
                    else:
                        logger.warning("YAML 文件未解析出有效设备: %s", path)
                else:
                    logger.warning("YAML 文件格式错误，应为设备列表: %s", path)
            except ImportError:
                logger.warning("未安装 PyYAML，无法从 %s 加载设备，使用内置默认设备", self._config.default_devices_path)
            except Exception as e:
                logger.warning("从 %s 加载默认设备失败: %s，回退到内置默认设备", self._config.default_devices_path, e)

        # 内置默认的 6 种设备
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

        # P2 半真实化改造：智能家居设备
        # 智能台灯
        lamp = Device(
            device_id="dev-lamp-001",
            name="云汐智能台灯",
            device_type=DeviceType.SMART_LAMP,
            status=DeviceStatus.ONLINE,
            battery=None,  # 有线供电
            signal_strength=95,
            firmware_version="2.0.0",
            capabilities=[
                "brightness_control", "color_temperature", "timer",
                "scene_mode", "voice_control",
            ],
            position={"x": 30, "y": 20},
            paired=True,
        )
        self._devices[lamp.device_id] = SmartLampSimulator(lamp, config=self._config)

        # 温湿度传感器
        temp_sensor = Device(
            device_id="dev-temp-001",
            name="云汐温湿度传感器",
            device_type=DeviceType.TEMP_HUMIDITY,
            status=DeviceStatus.ONLINE,
            battery=88.0,
            signal_strength=80,
            firmware_version="1.2.0",
            capabilities=[
                "temperature", "humidity", "heat_index",
                "low_battery_alarm", "data_export",
            ],
            position={"x": 60, "y": 40},
            paired=True,
        )
        self._devices[temp_sensor.device_id] = TempHumiditySensorSimulator(temp_sensor, config=self._config)

        # 智能插座
        plug = Device(
            device_id="dev-plug-001",
            name="云汐智能插座",
            device_type=DeviceType.SMART_PLUG,
            status=DeviceStatus.ONLINE,
            battery=None,  # 有线供电
            signal_strength=92,
            firmware_version="1.5.0",
            capabilities=[
                "power_meter", "overload_protection", "timer",
                "energy_statistics", "child_lock",
            ],
            position={"x": 70, "y": 50},
            paired=True,
        )
        self._devices[plug.device_id] = SmartPlugSimulator(plug, config=self._config)

        # 窗帘电机
        curtain = Device(
            device_id="dev-curtain-001",
            name="云汐窗帘电机",
            device_type=DeviceType.CURTAIN_MOTOR,
            status=DeviceStatus.ONLINE,
            battery=None,  # 有线供电
            signal_strength=75,
            firmware_version="1.8.0",
            capabilities=[
                "position_control", "timing_control", "hand_pull_start",
                "overheat_protection", "limit_calibration",
            ],
            position={"x": 40, "y": 60},
            paired=True,
        )
        self._devices[curtain.device_id] = CurtainMotorSimulator(curtain, config=self._config)

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

    # ------------------------------------------------------------------
    # P2 半真实化：状态持久化
    # ------------------------------------------------------------------

    def _load_persisted_states(self) -> None:
        """从持久化存储加载设备状态"""
        persisted = self._state_persistence.load()
        for device_id, state in persisted.items():
            sim = self._devices.get(device_id)
            if sim is not None:
                # 恢复设备内部状态变量
                state_vars = state.get("state_vars", {})
                if state_vars and hasattr(sim, "restore_state_vars"):
                    try:
                        sim.restore_state_vars(state_vars)
                        logger.debug("已恢复设备 %s 的持久化状态", device_id)
                    except Exception as e:
                        logger.warning("恢复设备 %s 状态失败: %s", device_id, e)

    def save_all_states(self) -> None:
        """保存所有设备状态到持久化存储"""
        states = {}
        for device_id, sim in self._devices.items():
            state = {
                "battery": sim.device.battery,
                "status": sim.device.status.value,
                "signal_strength": sim.device.signal_strength,
            }
            if hasattr(sim, "get_state_vars"):
                state["state_vars"] = sim.get_state_vars()
            states[device_id] = state
        self._state_persistence.save_all(states)

    def save_device_state(self, device_id: str) -> None:
        """保存单个设备状态"""
        sim = self._devices.get(device_id)
        if sim is None:
            return
        state = {
            "battery": sim.device.battery,
            "status": sim.device.status.value,
            "signal_strength": sim.device.signal_strength,
        }
        if hasattr(sim, "get_state_vars"):
            state["state_vars"] = sim.get_state_vars()
        self._state_persistence.save_device_state(device_id, state)

    @property
    def state_persistence(self) -> StatePersistence:
        """获取状态持久化管理器"""
        return self._state_persistence

    # ------------------------------------------------------------------
    # P2 半真实化：设备注册/发现/移除
    # ------------------------------------------------------------------

    def register_device(self, device_data: Dict[str, Any]) -> Dict[str, Any]:
        """注册新设备

        Args:
            device_data: 设备数据字典，需包含 device_id、name、device_type

        Returns:
            注册结果
        """
        device_id = device_data.get("device_id")
        if not device_id:
            device_id = f"dev-{uuid.uuid4().hex[:12]}"

        if device_id in self._devices:
            return {
                "success": False,
                "message": f"设备已存在: {device_id}",
                "error_code": "DEVICE_ALREADY_EXISTS",
            }

        device_type_str = device_data.get("device_type")
        try:
            device_type = DeviceType(device_type_str)
        except ValueError:
            return {
                "success": False,
                "message": f"不支持的设备类型: {device_type_str}",
                "error_code": "UNSUPPORTED_DEVICE_TYPE",
            }

        # 创建设备模型
        device = Device(
            device_id=device_id,
            name=device_data.get("name", f"新设备-{device_type_str}"),
            device_type=device_type,
            status=DeviceStatus(device_data.get("status", "online")),
            battery=device_data.get("battery", 100.0),
            signal_strength=device_data.get("signal_strength", 85),
            firmware_version=device_data.get("firmware_version", "1.0.0"),
            capabilities=device_data.get("capabilities", []),
            position=device_data.get("position", {"x": 50, "y": 50}),
            paired=device_data.get("paired", True),
        )

        # 创建模拟器
        simulator = self._create_simulator(device)
        if simulator is None:
            return {
                "success": False,
                "message": f"无法创建设备模拟器: {device_type}",
                "error_code": "SIMULATOR_CREATION_FAILED",
            }

        self._devices[device_id] = simulator
        logger.info("新设备已注册: %s (%s)", device_id, device_type.value)

        # 保存状态
        self.save_device_state(device_id)

        return {
            "success": True,
            "message": "设备注册成功",
            "device_id": device_id,
            "device_type": device_type.value,
            "name": device.name,
        }

    def discover_devices(self) -> List[Dict[str, Any]]:
        """发现网络中的设备（模拟扫描）

        模拟扫描过程，返回可发现的设备列表（包含已有的和随机生成的新设备）。
        """
        discovered = []

        # 已注册但未配对的设备
        for sim in self._devices.values():
            if not sim.device.paired:
                discovered.append({
                    "device_id": sim.device_id,
                    "name": sim.device.name,
                    "device_type": sim.device_type.value,
                    "rssi": random.randint(-70, -40),
                    "paired": False,
                    "status": sim.device.status.value,
                })

        # 模拟发现 2-4 个新设备
        num_new = random.randint(2, 4)
        smart_home_types = [
            DeviceType.SMART_LAMP,
            DeviceType.TEMP_HUMIDITY,
            DeviceType.SMART_PLUG,
            DeviceType.CURTAIN_MOTOR,
        ]
        type_names = {
            DeviceType.SMART_LAMP: "智能台灯",
            DeviceType.TEMP_HUMIDITY: "温湿度传感器",
            DeviceType.SMART_PLUG: "智能插座",
            DeviceType.CURTAIN_MOTOR: "窗帘电机",
        }

        for i in range(num_new):
            dtype = random.choice(smart_home_types)
            discovered.append({
                "device_id": f"dev-discover-{uuid.uuid4().hex[:8]}",
                "name": f"{type_names[dtype]}-{random.randint(100, 999)}",
                "device_type": dtype.value,
                "rssi": random.randint(-85, -45),
                "paired": False,
                "is_new": True,
                "manufacturer": "云汐智能",
                "model": f"{dtype.value}-pro",
            })

        return discovered

    def remove_device(self, device_id: str) -> Dict[str, Any]:
        """移除设备

        Args:
            device_id: 设备ID

        Returns:
            移除结果
        """
        if device_id not in self._devices:
            return {
                "success": False,
                "message": f"设备不存在: {device_id}",
                "error_code": "DEVICE_NOT_FOUND",
            }

        sim = self._devices.pop(device_id)
        device_type = sim.device_type.value
        device_name = sim.device.name

        # 删除持久化状态
        self._state_persistence.remove_device_state(device_id)

        logger.info("设备已移除: %s (%s)", device_id, device_type)

        return {
            "success": True,
            "message": "设备已移除",
            "device_id": device_id,
            "device_type": device_type,
            "name": device_name,
        }


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
