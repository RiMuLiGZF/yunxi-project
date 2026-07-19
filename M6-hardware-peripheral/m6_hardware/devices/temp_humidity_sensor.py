"""
P2 半真实化改造：温湿度传感器模拟器

设备特性：
- 温度（随时间小幅波动，模拟昼夜变化）
- 湿度（随时间小幅波动）
- 传感器校准状态
- 电池电量
- 延迟特性：读取操作 50-200ms
"""

from __future__ import annotations

import random
import time
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class TempHumiditySensorSimulator(BaseDeviceSimulator):
    """温湿度传感器模拟器（半真实化）

    状态机设计：
    - 温度：15-35°C 范围内自然波动（±5% 随机漫步）
    - 湿度：30-80%RH 范围内自然波动
    - 校准状态：calibrated / needs_calibration / calibrating
    - 电池电量：随使用时间缓慢下降
    - 数据质量：受校准状态和电量影响
    """

    capability = DeviceCapability(
        sensors=["temperature", "humidity", "heat_index", "battery_voltage", "data_quality"],
        actions=["calibrate", "reset_calibration", "force_reading"],
        description="温湿度传感器：环境温度 + 相对湿度 + 体感温度",
    )

    def __init__(self, device: Device, config=None):
        super().__init__(device, config=config)

        # 传感器状态变量
        self._temperature: float = 24.0       # 当前温度 °C
        self._humidity: float = 55.0          # 当前湿度 %RH
        self._calibration_status: str = "calibrated"  # calibrated / needs_calibration / calibrating
        self._last_calibration_time: float = time.time()
        self._reading_count: int = 0          # 累计读数次数
        self._data_quality: int = 100         # 数据质量评分 0-100
        self._battery_voltage: float = 3.3    # 电池电压 V

        # 传感器参数
        self._temp_min = 10.0
        self._temp_max = 40.0
        self._humidity_min = 20.0
        self._humidity_max = 90.0
        self._calibration_interval = 86400 * 30  # 30 天需要重新校准

    # ------------------------------------------------------------------
    # 状态序列化/反序列化（用于持久化）
    # ------------------------------------------------------------------

    def get_state_vars(self) -> Dict[str, Any]:
        """获取内部状态变量（用于持久化）"""
        return {
            "temperature": self._temperature,
            "humidity": self._humidity,
            "calibration_status": self._calibration_status,
            "last_calibration_time": self._last_calibration_time,
            "reading_count": self._reading_count,
            "data_quality": self._data_quality,
            "battery_voltage": self._battery_voltage,
        }

    def restore_state_vars(self, state: Dict[str, Any]) -> None:
        """从持久化状态恢复"""
        self._temperature = state.get("temperature", self._temperature)
        self._humidity = state.get("humidity", self._humidity)
        self._calibration_status = state.get("calibration_status", self._calibration_status)
        self._last_calibration_time = state.get("last_calibration_time", self._last_calibration_time)
        self._reading_count = state.get("reading_count", self._reading_count)
        self._data_quality = state.get("data_quality", self._data_quality)
        self._battery_voltage = state.get("battery_voltage", self._battery_voltage)

    # ------------------------------------------------------------------
    # 传感器数据生成
    # ------------------------------------------------------------------

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成温湿度传感器数据"""
        # 温度随机漫步（自然波动）
        self._temperature = self._random_walk(
            self._temperature, self._temp_min, self._temp_max, 0.15
        )

        # 湿度随机漫步（自然波动）
        self._humidity = self._random_walk(
            self._humidity, self._humidity_min, self._humidity_max, 0.3
        )

        # 体感温度（热指数）简化计算
        heat_index = self._calculate_heat_index(self._temperature, self._humidity)

        # 计算数据质量
        self._update_data_quality()

        # 电池电压（随电量下降）
        if self.device.battery is not None:
            self._battery_voltage = 3.0 + (self.device.battery / 100.0) * 0.6  # 3.0V - 3.6V

        # 读数计数
        self._reading_count += 1

        # 设置读数
        quality = self._data_quality
        self._set_reading("temperature", round(self._temperature, 2), "°C", quality=quality)
        self._set_reading("humidity", round(self._humidity, 1), "%RH", quality=quality)
        self._set_reading("heat_index", round(heat_index, 1), "°C", quality=quality)
        self._set_reading("battery_voltage", round(self._battery_voltage, 2), "V")
        self._set_reading("data_quality", self._data_quality, "score")

    def _calculate_heat_index(self, temp: float, humidity: float) -> float:
        """简化的体感温度（热指数）计算

        使用简化版 Rothfusz 回归公式。
        """
        if temp < 27:
            return temp  # 低温下体感温度≈实际温度

        # 简化计算
        hi = (
            -8.784695
            + 1.61139411 * temp
            + 2.338549 * humidity
            - 0.14611605 * temp * humidity
            - 1.2308094e-2 * temp ** 2
            - 1.6424828e-2 * humidity ** 2
            + 2.211732e-3 * temp ** 2 * humidity
            + 7.2546e-4 * temp * humidity ** 2
            - 3.582e-6 * temp ** 2 * humidity ** 2
        )
        return hi

    def _update_data_quality(self) -> None:
        """更新数据质量评分"""
        quality = 100

        # 校准状态影响
        if self._calibration_status == "needs_calibration":
            quality -= 20
        elif self._calibration_status == "calibrating":
            quality -= 50

        # 低电量影响
        if self.device.battery is not None:
            if self.device.battery < 10:
                quality -= 30
            elif self.device.battery < 20:
                quality -= 15

        # 长时间未校准
        time_since_calibration = time.time() - self._last_calibration_time
        if time_since_calibration > self._calibration_interval:
            quality -= 10
            if self._calibration_status == "calibrated":
                self._calibration_status = "needs_calibration"

        self._data_quality = max(0, min(100, quality))

    def _update_device_state(self, elapsed: float) -> None:
        """更新传感器状态"""
        # 电量消耗（传感器功耗较低）
        if self.device.battery is not None:
            drain_rate = 0.2  # 每小时 0.2%
            self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 信号强度波动
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 50, 100, 0.8
        ))

        # 检查是否需要校准
        time_since_calibration = time.time() - self._last_calibration_time
        if time_since_calibration > self._calibration_interval:
            if self._calibration_status == "calibrated":
                self._calibration_status = "needs_calibration"

    # ------------------------------------------------------------------
    # 设备动作
    # ------------------------------------------------------------------

    def _action_calibrate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行传感器校准"""
        if self._calibration_status == "calibrating":
            return {
                "success": False,
                "message": "校准正在进行中，请稍候",
                "error_code": "CALIBRATION_IN_PROGRESS",
            }

        self._calibration_status = "calibrating"

        # 模拟校准过程（实际应异步执行，此处同步简化）
        self._last_calibration_time = time.time()
        self._calibration_status = "calibrated"

        # 校准后重置数据质量
        self._data_quality = 100

        return {
            "success": True,
            "message": "传感器校准完成",
            "calibration_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data_quality": self._data_quality,
        }

    def _action_reset_calibration(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """重置校准状态（标记为需要重新校准）"""
        self._calibration_status = "needs_calibration"
        return {
            "success": True,
            "message": "校准状态已重置，建议尽快重新校准",
        }

    def _action_force_reading(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """强制立即读取一次传感器数据"""
        self._generate_sensor_data(1.0)
        return {
            "success": True,
            "message": "已强制读取传感器数据",
            "temperature": round(self._temperature, 2),
            "humidity": round(self._humidity, 1),
            "data_quality": self._data_quality,
        }


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.TEMP_HUMIDITY,
    TempHumiditySensorSimulator,
    TempHumiditySensorSimulator.capability,
)
