"""
P2 半真实化改造：智能插座模拟器

设备特性：
- 开关状态
- 实时功率消耗
- 累计用电量（kWh）
- 过载保护状态
- 电压/电流读数
- 延迟特性：写入操作 200-500ms
"""

from __future__ import annotations

import random
import time
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class SmartPlugSimulator(BaseDeviceSimulator):
    """智能插座模拟器（半真实化）

    状态机设计：
    - 开关状态：on/off
    - 实时功率：0 - 额定功率（取决于负载模拟）
    - 累计用电量：kWh
    - 电压：220V ± 5% 波动
    - 电流：根据功率/电压计算
    - 过载保护：功率超过阈值时自动断电
    """

    capability = DeviceCapability(
        sensors=[
            "power", "voltage", "current", "energy_total",
            "overload_protection", "power_factor",
        ],
        actions=[
            "turn_on", "turn_off", "toggle",
            "reset_energy", "set_overload_threshold",
        ],
        description="智能插座：功率计量 + 过载保护 + 用电统计",
    )

    def __init__(self, device: Device, config=None):
        super().__init__(device, config=config)

        # 插座状态变量
        self._is_on: bool = device.status == DeviceStatus.ONLINE
        self._power: float = 0.0              # 实时功率 W
        self._voltage: float = 220.0          # 电压 V
        self._current: float = 0.0            # 电流 A
        self._energy_total: float = 0.0       # 累计用电量 kWh
        self._power_factor: float = 0.95      # 功率因数
        self._overload_protected: bool = False  # 过载保护触发状态
        self._overload_threshold: float = 2500.0  # 过载阈值 W（2.5kW）
        self._rated_power: float = 500.0      # 模拟负载额定功率 W
        self._last_on_time: float = 0.0
        self._switch_count: int = 0           # 开关次数计数

        # 模拟负载参数（模拟不同电器的功耗曲线）
        self._load_type: str = "stable"       # stable / fluctuating / spike
        self._load_base_power: float = 500.0  # 基础负载功率

    # ------------------------------------------------------------------
    # 状态序列化/反序列化（用于持久化）
    # ------------------------------------------------------------------

    def get_state_vars(self) -> Dict[str, Any]:
        """获取内部状态变量（用于持久化）"""
        return {
            "is_on": self._is_on,
            "power": self._power,
            "voltage": self._voltage,
            "current": self._current,
            "energy_total": self._energy_total,
            "power_factor": self._power_factor,
            "overload_protected": self._overload_protected,
            "overload_threshold": self._overload_threshold,
            "rated_power": self._rated_power,
            "last_on_time": self._last_on_time,
            "switch_count": self._switch_count,
            "load_type": self._load_type,
            "load_base_power": self._load_base_power,
        }

    def restore_state_vars(self, state: Dict[str, Any]) -> None:
        """从持久化状态恢复"""
        self._is_on = state.get("is_on", self._is_on)
        self._power = state.get("power", self._power)
        self._voltage = state.get("voltage", self._voltage)
        self._current = state.get("current", self._current)
        self._energy_total = state.get("energy_total", self._energy_total)
        self._power_factor = state.get("power_factor", self._power_factor)
        self._overload_protected = state.get("overload_protected", self._overload_protected)
        self._overload_threshold = state.get("overload_threshold", self._overload_threshold)
        self._rated_power = state.get("rated_power", self._rated_power)
        self._last_on_time = state.get("last_on_time", self._last_on_time)
        self._switch_count = state.get("switch_count", self._switch_count)
        self._load_type = state.get("load_type", self._load_type)
        self._load_base_power = state.get("load_base_power", self._load_base_power)

    # ------------------------------------------------------------------
    # 传感器数据生成
    # ------------------------------------------------------------------

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成智能插座传感器数据"""
        # 电压波动（220V ± 5%）
        self._voltage = self._random_walk(self._voltage, 209.0, 231.0, 0.5)

        if not self._is_on or self._overload_protected:
            # 关断状态：功率为 0，电流为 0
            self._power = 0.0
            self._current = 0.0
        else:
            # 模拟不同负载类型的功耗
            self._simulate_load(elapsed)

            # 根据功率和电压计算电流（考虑功率因数）
            if self._voltage > 0:
                self._current = self._power / (self._voltage * self._power_factor)

            # 累计用电量（kWh = W * h / 1000）
            self._energy_total += (self._power * elapsed / 3600.0) / 1000.0

            # 检查过载保护
            self._check_overload()

        # 设置读数
        quality = 100
        if self._overload_protected:
            quality = 0  # 过载保护触发，数据无效

        self._set_reading("power", round(self._power, 2), "W", quality=quality)
        self._set_reading("voltage", round(self._voltage, 1), "V")
        self._set_reading("current", round(self._current, 3), "A")
        self._set_reading("energy_total", round(self._energy_total, 4), "kWh")
        self._set_reading("overload_protection", self._overload_protected, "status")
        self._set_reading("power_factor", round(self._power_factor, 3), "")

    def _simulate_load(self, elapsed: float) -> None:
        """模拟负载功率变化"""
        if self._load_type == "stable":
            # 稳定负载：小幅波动
            self._power = self._random_walk(
                self._load_base_power,
                self._load_base_power * 0.95,
                self._load_base_power * 1.05,
                self._load_base_power * 0.01,
            )
        elif self._load_type == "fluctuating":
            # 波动负载：较大幅度变化
            self._power = self._random_walk(
                self._load_base_power if self._power == 0 else self._power,
                self._load_base_power * 0.5,
                self._load_base_power * 1.5,
                self._load_base_power * 0.05,
            )
        elif self._load_type == "spike":
            # 尖峰负载：偶尔出现功率尖峰
            base = self._load_base_power
            self._power = self._random_walk(base, base * 0.9, base * 1.1, base * 0.02)
            if random.random() < 0.05:  # 5% 概率出现尖峰
                self._power = base * random.uniform(1.5, 2.5)

    def _check_overload(self) -> None:
        """检查过载保护"""
        if self._power > self._overload_threshold:
            # 功率超过阈值，触发过载保护
            self._overload_protected = True
            self._is_on = False
            self._power = 0.0
            self._current = 0.0
            self._add_alert("overload", f"过载保护触发: {self._power:.1f}W > {self._overload_threshold}W")

    def _update_device_state(self, elapsed: float) -> None:
        """更新插座状态"""
        # 智能插座通常为有线供电，不消耗电池
        if self.device.battery is not None:
            drain_rate = 0.1
            self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 信号强度波动
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 70, 100, 0.5
        ))

        # 过载保护时状态设为警告
        if self._overload_protected and self.device.status != DeviceStatus.WARNING:
            self.device.status = DeviceStatus.WARNING

    # ------------------------------------------------------------------
    # 设备动作
    # ------------------------------------------------------------------

    def _action_turn_on(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开启插座"""
        if self._overload_protected:
            return {
                "success": False,
                "message": "过载保护已触发，请先解除保护后再开启",
                "error_code": "OVERLOAD_PROTECTED",
            }
        if self._is_on:
            return {
                "success": True,
                "message": "插座已经是开启状态",
                "power": round(self._power, 2),
            }
        self._is_on = True
        self._last_on_time = time.time()
        self._switch_count += 1
        if self.device.status == DeviceStatus.OFFLINE:
            self.device.status = DeviceStatus.ONLINE
        return {
            "success": True,
            "message": "插座已开启",
            "power": round(self._power, 2),
            "voltage": round(self._voltage, 1),
        }

    def _action_turn_off(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """关闭插座"""
        if not self._is_on and not self._overload_protected:
            return {
                "success": True,
                "message": "插座已经是关闭状态",
            }
        was_on = self._is_on
        self._is_on = False
        self._overload_protected = False  # 关闭时重置过载保护
        self._switch_count += 1
        return {
            "success": True,
            "message": "插座已关闭",
            "energy_used": round(self._energy_total, 4),
            "was_overload_protected": not was_on and self._overload_protected,
        }

    def _action_toggle(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """切换开关"""
        if self._is_on:
            return self._action_turn_off(params)
        else:
            return self._action_turn_on(params)

    def _action_reset_energy(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """重置用电量统计"""
        old_energy = self._energy_total
        self._energy_total = 0.0
        return {
            "success": True,
            "message": "用电量统计已重置",
            "previous_energy": round(old_energy, 4),
        }

    def _action_set_overload_threshold(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置过载保护阈值"""
        threshold = params.get("threshold", params.get("power_threshold"))
        if threshold is None:
            return {
                "success": False,
                "message": "缺少 threshold 参数",
                "error_code": "INVALID_PARAMS",
            }
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "threshold 必须是数字",
                "error_code": "INVALID_PARAMS",
            }

        if threshold < 100 or threshold > 3500:
            return {
                "success": False,
                "message": "阈值范围应在 100-3500W 之间",
                "error_code": "INVALID_PARAMS",
            }

        old_threshold = self._overload_threshold
        self._overload_threshold = threshold

        return {
            "success": True,
            "message": f"过载保护阈值已设置为 {threshold}W",
            "threshold": threshold,
            "previous_threshold": old_threshold,
        }


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.SMART_PLUG,
    SmartPlugSimulator,
    SmartPlugSimulator.capability,
)
