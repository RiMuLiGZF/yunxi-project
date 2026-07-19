"""
P2 半真实化改造：智能台灯模拟器

设备特性：
- 开关状态
- 亮度调节 (0-100%)
- 色温模式（暖白/冷白/自然光）
- 使用时长累计
- 灯泡寿命衰减
- 延迟特性：写入操作 200-500ms
"""

from __future__ import annotations

import random
import time
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class SmartLampSimulator(BaseDeviceSimulator):
    """智能台灯模拟器（半真实化）

    状态机设计：
    - 开关状态：on/off
    - 亮度：0-100%
    - 色温：warm(暖白) / cool(冷白) / natural(自然光)
    - 使用时长：累计小时数
    - 灯泡寿命：随使用时长衰减
    """

    capability = DeviceCapability(
        sensors=["brightness", "color_temperature", "power_consumption", "usage_hours", "bulb_health"],
        actions=["turn_on", "turn_off", "toggle", "set_brightness", "set_color_temp", "reset_usage"],
        description="智能台灯：亮度调节 + 色温切换 + 使用统计",
    )

    def __init__(self, device: Device, config=None):
        super().__init__(device, config=config)

        # 台灯状态变量
        self._is_on: bool = device.status == DeviceStatus.ONLINE  # 默认为在线时开灯
        self._brightness: float = 80.0      # 亮度 0-100%
        self._color_temp: str = "natural"    # 色温：warm / cool / natural
        self._usage_hours: float = 0.0       # 累计使用时长（小时）
        self._bulb_health: float = 100.0     # 灯泡健康度 0-100%
        self._power: float = 0.0             # 当前功率（W）
        self._last_on_time: float = time.time() if self._is_on else 0.0

        # 灯泡参数
        self._max_power = 12.0  # 最大功耗 12W
        self._bulb_lifespan_hours = 25000  # 灯泡标称寿命 25000 小时

    # ------------------------------------------------------------------
    # 状态序列化/反序列化（用于持久化）
    # ------------------------------------------------------------------

    def get_state_vars(self) -> Dict[str, Any]:
        """获取内部状态变量（用于持久化）"""
        return {
            "is_on": self._is_on,
            "brightness": self._brightness,
            "color_temp": self._color_temp,
            "usage_hours": self._usage_hours,
            "bulb_health": self._bulb_health,
            "power": self._power,
            "last_on_time": self._last_on_time,
        }

    def restore_state_vars(self, state: Dict[str, Any]) -> None:
        """从持久化状态恢复"""
        self._is_on = state.get("is_on", self._is_on)
        self._brightness = state.get("brightness", self._brightness)
        self._color_temp = state.get("color_temp", self._color_temp)
        self._usage_hours = state.get("usage_hours", self._usage_hours)
        self._bulb_health = state.get("bulb_health", self._bulb_health)
        self._power = state.get("power", self._power)
        self._last_on_time = state.get("last_on_time", self._last_on_time)

    # ------------------------------------------------------------------
    # 传感器数据生成
    # ------------------------------------------------------------------

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成台灯传感器数据"""
        # 功率：关灯时为 0，开灯时与亮度成正比 + 灯泡健康度影响
        if not self._is_on:
            self._power = 0.0
        else:
            base_power = self._max_power * (self._brightness / 100.0)
            # 灯泡老化会略微增加功耗
            aging_factor = 1.0 + (100.0 - self._bulb_health) / 200.0
            self._power = base_power * aging_factor
            # 添加微小波动
            self._power = self._random_walk(self._power, 0, self._max_power * 1.2, 0.05)

        # 设置读数
        self._set_reading("brightness", round(self._brightness, 1), "%")
        self._set_reading("color_temperature", self._color_temp, "mode")
        self._set_reading("power_consumption", round(self._power, 2), "W")
        self._set_reading("usage_hours", round(self._usage_hours, 2), "h")
        self._set_reading("bulb_health", round(self._bulb_health, 1), "%")

    def _update_device_state(self, elapsed: float) -> None:
        """更新台灯状态"""
        # 累计使用时长（开灯时才计时）
        if self._is_on:
            self._usage_hours += elapsed / 3600.0

            # 灯泡寿命衰减
            # 25000 小时寿命，每小时衰减 100/25000 = 0.004%
            decay_rate = 100.0 / self._bulb_lifespan_hours
            self._bulb_health = max(0.0, self._bulb_health - decay_rate * elapsed / 3600.0)

            # 高亮度加速衰减
            if self._brightness > 80:
                extra_decay = decay_rate * 0.5 * elapsed / 3600.0
                self._bulb_health = max(0.0, self._bulb_health - extra_decay)

        # 电量消耗（如果是电池供电的台灯，大多数是有线的）
        # 此处不消耗电池（智能台灯通常为有线供电）
        # 但如果设备模型有 battery，则按低速率消耗
        if self.device.battery is not None:
            drain_rate = 0.5 if self._is_on else 0.05
            self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 信号强度波动
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 60, 100, 0.5
        ))

        # 灯泡寿命低于 20% 时警告
        if self._bulb_health < 20 and self.device.status == DeviceStatus.ONLINE:
            self.device.status = DeviceStatus.WARNING

    # ------------------------------------------------------------------
    # 设备动作
    # ------------------------------------------------------------------

    def _action_turn_on(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开灯"""
        if self._is_on:
            return {
                "success": True,
                "message": "台灯已经是开启状态",
                "brightness": self._brightness,
                "color_temp": self._color_temp,
            }
        self._is_on = True
        self._last_on_time = time.time()
        if self.device.status == DeviceStatus.OFFLINE:
            self.device.status = DeviceStatus.ONLINE
        return {
            "success": True,
            "message": "台灯已开启",
            "brightness": self._brightness,
            "color_temp": self._color_temp,
            "power": round(self._power, 2),
        }

    def _action_turn_off(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """关灯"""
        if not self._is_on:
            return {
                "success": True,
                "message": "台灯已经是关闭状态",
            }
        self._is_on = False
        return {
            "success": True,
            "message": "台灯已关闭",
            "usage_hours": round(self._usage_hours, 2),
        }

    def _action_toggle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """切换开关"""
        if self._is_on:
            return self._action_turn_off(params)
        else:
            return self._action_turn_on(params)

    def _action_set_brightness(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置亮度"""
        brightness = params.get("brightness")
        if brightness is None:
            return {
                "success": False,
                "message": "缺少 brightness 参数",
                "error_code": "INVALID_PARAMS",
            }
        try:
            brightness = float(brightness)
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "brightness 必须是数字",
                "error_code": "INVALID_PARAMS",
            }

        brightness = max(0.0, min(100.0, brightness))
        old_brightness = self._brightness
        self._brightness = brightness

        # 亮度为 0 时自动关灯
        if brightness == 0:
            self._is_on = False
        elif old_brightness == 0 and brightness > 0:
            self._is_on = True
            self._last_on_time = time.time()

        return {
            "success": True,
            "message": f"亮度已设置为 {brightness:.0f}%",
            "brightness": self._brightness,
            "is_on": self._is_on,
        }

    def _action_set_color_temp(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置色温"""
        mode = params.get("mode", params.get("color_temp", ""))
        valid_modes = ["warm", "cool", "natural"]
        if mode not in valid_modes:
            return {
                "success": False,
                "message": f"无效的色温模式，可选值: {valid_modes}",
                "error_code": "INVALID_PARAMS",
            }
        old_mode = self._color_temp
        self._color_temp = mode
        return {
            "success": True,
            "message": f"色温已切换为 {mode}",
            "color_temp": mode,
            "previous": old_mode,
        }

    def _action_reset_usage(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """重置使用时长统计"""
        old_usage = self._usage_hours
        self._usage_hours = 0.0
        return {
            "success": True,
            "message": "使用时长已重置",
            "previous_usage_hours": round(old_usage, 2),
        }


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.SMART_LAMP,
    SmartLampSimulator,
    SmartLampSimulator.capability,
)
