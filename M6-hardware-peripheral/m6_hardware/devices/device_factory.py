"""
P2-10: 设备工厂 - 统一设备创建与注册机制

提供设备类型到模拟器类的映射，支持动态注册新设备类型。
每个设备声明自己的能力（传感器、动作），便于上层发现和调用。
"""

from __future__ import annotations

from typing import Dict, Type, List, Optional, Any, TYPE_CHECKING
from ..models.device import Device, DeviceType

if TYPE_CHECKING:
    from .base_device import BaseDeviceSimulator


class DeviceCapability:
    """设备能力声明

    描述一个设备支持的传感器类型和可执行动作。
    用于上层发现设备能力，避免硬编码。
    """

    def __init__(
        self,
        sensors: Optional[List[str]] = None,
        actions: Optional[List[str]] = None,
        description: str = "",
    ):
        self.sensors = sensors or []
        self.actions = actions or []
        self.description = description

    def has_sensor(self, sensor_type: str) -> bool:
        """检查是否支持指定传感器"""
        return sensor_type in self.sensors

    def has_action(self, action: str) -> bool:
        """检查是否支持指定动作"""
        return action in self.actions

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "sensors": list(self.sensors),
            "actions": list(self.actions),
            "description": self.description,
        }


class DeviceFactory:
    """设备工厂 - 注册和创建设备模拟器

    使用注册表模式，每种设备类型注册自己的模拟器类和能力声明。
    新增设备类型只需调用 register() 即可，无需修改工厂代码。
    """

    _registry: Dict[DeviceType, Type[BaseDeviceSimulator]] = {}  # type: ignore
    _capabilities: Dict[DeviceType, DeviceCapability] = {}

    @classmethod
    def register(
        cls,
        device_type: DeviceType,
        simulator_cls: Type[BaseDeviceSimulator],  # type: ignore
        capability: Optional[DeviceCapability] = None,
    ):
        """注册设备类型

        Args:
            device_type: 设备类型枚举
            simulator_cls: 模拟器类
            capability: 设备能力声明
        """
        cls._registry[device_type] = simulator_cls
        if capability:
            cls._capabilities[device_type] = capability

    @classmethod
    def create(cls, device: Device) -> BaseDeviceSimulator:  # type: ignore
        """根据设备模型创建模拟器实例

        Args:
            device: 设备基础信息模型

        Returns:
            设备模拟器实例

        Raises:
            ValueError: 不支持的设备类型
        """
        simulator_cls = cls._registry.get(device.device_type)
        if simulator_cls is None:
            raise ValueError(f"不支持的设备类型: {device.device_type}")
        return simulator_cls(device)

    @classmethod
    def get_capability(cls, device_type: DeviceType) -> Optional[DeviceCapability]:
        """获取设备类型的能力声明"""
        return cls._capabilities.get(device_type)

    @classmethod
    def supported_types(cls) -> List[DeviceType]:
        """获取所有支持的设备类型"""
        return list(cls._registry.keys())

    @classmethod
    def is_supported(cls, device_type: DeviceType) -> bool:
        """检查设备类型是否受支持"""
        return device_type in cls._registry


def get_device_factory() -> type[DeviceFactory]:
    """获取设备工厂（向后兼容）"""
    return DeviceFactory
