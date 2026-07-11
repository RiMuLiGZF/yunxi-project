"""
M6 硬件外设 - 桌面终端/桌面屏模拟器
传感器：环境光、温湿度、空气质量
"""

import random
import time
from datetime import datetime
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class DesktopScreenSimulator(BaseDeviceSimulator):
    """桌面终端模拟器

    特点：有线供电、常驻在线、环境监测、日程显示
    """

    capability = DeviceCapability(
        sensors=['display_brightness', 'ambient_light'],
        actions=['adjust_brightness', 'power_on', 'power_off'],
        description="桌面终端：大屏显示 + 交互中心",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 桌面终端是有线供电
        self.device.battery = None

        # 初始化传感器值
        self._ambient_light = 300.0       # 环境光 lux
        self._temperature = 24.0          # 温度 ℃
        self._humidity = 50.0             # 湿度 %
        self._air_quality = 45.0          # 空气质量指数（越低越好）
        self._co2 = 600.0                 # 二氧化碳浓度 ppm
        self._pm25 = 15.0                 # PM2.5 μg/m³

        self._screen_on = True

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成桌面终端传感器数据"""
        hour = datetime.now().hour

        # 环境光（随时间变化，模拟日夜）
        if 6 <= hour < 8:
            # 日出
            target_light = random.uniform(100, 500)
        elif 8 <= hour < 18:
            # 白天
            target_light = random.uniform(400, 800)
        elif 18 <= hour < 20:
            # 日落
            target_light = random.uniform(100, 400)
        else:
            # 夜晚
            target_light = random.uniform(20, 100)

        self._ambient_light = self._smooth_value(self._ambient_light, target_light, 0.05)
        self._ambient_light = self._random_walk(self._ambient_light, 10, 1000, 10.0)

        # 温度（白天略高，晚上略低）
        base_temp = 24.5 if 8 <= hour < 20 else 23.0
        target_temp = base_temp + random.uniform(-1.0, 1.0)
        self._temperature = self._smooth_value(self._temperature, target_temp, 0.03)
        self._temperature = self._random_walk(self._temperature, 22.0, 26.0, 0.1)

        # 湿度
        target_humidity = random.uniform(42, 58)
        self._humidity = self._smooth_value(self._humidity, target_humidity, 0.03)
        self._humidity = self._random_walk(self._humidity, 40.0, 60.0, 0.5)

        # 空气质量（工作时间略差，晚上好）
        work_hours = 9 <= hour <= 18
        base_aqi = 60 if work_hours else 35
        target_aqi = base_aqi + random.uniform(-10, 15)
        self._air_quality = self._smooth_value(self._air_quality, target_aqi, 0.05)
        self._air_quality = self._random_walk(self._air_quality, 20, 100, 2.0)

        # CO2 浓度（工作时间人多则高）
        base_co2 = 800 if work_hours else 500
        target_co2 = base_co2 + random.uniform(-100, 150)
        self._co2 = self._smooth_value(self._co2, target_co2, 0.05)
        self._co2 = self._random_walk(self._co2, 400, 1200, 20.0)

        # PM2.5
        target_pm25 = random.uniform(10, 35)
        self._pm25 = self._smooth_value(self._pm25, target_pm25, 0.05)
        self._pm25 = self._random_walk(self._pm25, 5, 50, 1.0)

        # 信号强度（有线设备，信号稳定）
        self.device.signal_strength = 100

        # 保存读数
        self._set_reading("ambient_light", round(self._ambient_light, 1), "lux")
        self._set_reading("temperature", round(self._temperature, 1), "℃")
        self._set_reading("humidity", round(self._humidity, 1), "%")
        self._set_reading("air_quality", round(self._air_quality, 0), "AQI")
        self._set_reading("co2", round(self._co2, 0), "ppm")
        self._set_reading("pm25", round(self._pm25, 1), "μg/m³")

    def _update_device_state(self, elapsed: float) -> None:
        """更新桌面终端状态"""
        # 桌面终端始终在线（有线供电）
        if self.device.status == DeviceStatus.OFFLINE:
            self.status = DeviceStatus.ONLINE

        # 屏幕开关状态（晚上可能息屏）
        hour = datetime.now().hour
        if 23 <= hour or hour <= 6:
            self._screen_on = random.random() < 0.3  # 深夜可能息屏
        else:
            self._screen_on = True

    def _check_alerts(self) -> None:
        """检查告警（空气质量差、CO2过高等）"""
        super()._check_alerts()

        # 空气质量差告警
        if self._air_quality > 80:
            self._add_alert("poor_air_quality", f"空气质量较差: AQI {self._air_quality:.0f}")

        # CO2 过高告警
        if self._co2 > 1000:
            self._add_alert("high_co2", f"CO₂浓度偏高: {self._co2:.0f}ppm，建议通风")

    def _action_display_schedule(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """显示日程"""
        schedule = params.get("schedule", {})
        return {"success": True, "message": "日程已显示在桌面屏", "schedule": schedule}

    def _action_video_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """发起视频通话"""
        contact = params.get("contact", "未知联系人")
        return {"success": True, "message": f"正在呼叫 {contact}...", "call_id": f"call_{int(time.time())}"}

    def _action_toggle_screen(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开关屏幕"""
        self._screen_on = not self._screen_on
        return {"success": True, "message": f"屏幕已{'开启' if self._screen_on else '关闭'}"}


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.DESKTOP,
    DesktopScreenSimulator,
)
