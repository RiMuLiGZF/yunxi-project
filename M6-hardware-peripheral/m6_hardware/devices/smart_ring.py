"""
M6 硬件外设 - 智能戒指模拟器
传感器：心率、体温、睡眠阶段、压力指数
"""

import random
import time
from datetime import datetime
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class SmartRingSimulator(BaseDeviceSimulator):
    """智能戒指模拟器

    特点：体积小、续航长（7-10天）、传感器精度高
    """

    capability = DeviceCapability(
        sensors=["heart_rate", "temperature", "sleep_stage", "stress_index", "hrv"],
        actions=["meditation", "sleep_tracking"],
        description="智能戒指：全天候健康监测 + 压力管理",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 初始化传感器值
        self._heart_rate = 68.0          # 心率 bpm（戒指测量更稳定）
        self._temperature = 36.5         # 体温 ℃
        self._sleep_stage = "awake"      # 睡眠阶段: awake/light/deep/rem
        self._stress_index = 35.0        # 压力指数 0-100
        self._hrv = 55.0                 # 心率变异性 ms

        self._is_sleeping = False
        self._last_sleep_check = time.time()

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成戒指传感器数据"""
        hour = datetime.now().hour
        is_night = hour >= 23 or hour <= 6

        # 心率（戒指测量更精准，波动小）
        if is_night and self._is_sleeping:
            target_hr = random.uniform(52, 62)
        else:
            target_hr = random.uniform(62, 78)
        self._heart_rate = self._smooth_value(self._heart_rate, target_hr, 0.08)
        self._heart_rate = self._random_walk(self._heart_rate, 50, 90, 0.8)

        # 体温（夜间略低，白天略高）
        base_temp = 36.2 if is_night else 36.6
        target_temp = base_temp + random.uniform(-0.3, 0.4)
        self._temperature = self._smooth_value(self._temperature, target_temp, 0.05)
        self._temperature = self._random_walk(self._temperature, 35.8, 37.2, 0.05)

        # 睡眠阶段
        if is_night and self._is_sleeping:
            # 睡眠周期约 90 分钟，随机切换阶段
            if random.random() < elapsed / 300:  # 每5分钟可能变化
                stages = ["light", "deep", "rem", "light"]
                self._sleep_stage = random.choice(stages)
        else:
            self._sleep_stage = "awake"

        # 压力指数
        if self._sleep_stage in ("deep", "rem"):
            target_stress = random.uniform(15, 30)
        elif self._sleep_stage == "light":
            target_stress = random.uniform(25, 40)
        else:
            # 清醒状态，压力受工作影响
            work_hours = 9 <= hour <= 18
            target_stress = random.uniform(35, 65) if work_hours else random.uniform(25, 45)
        self._stress_index = self._smooth_value(self._stress_index, target_stress, 0.05)
        self._stress_index = self._random_walk(self._stress_index, 10, 80, 1.0)

        # 心率变异性（与压力负相关）
        target_hrv = 80 - self._stress_index * 0.5
        self._hrv = self._smooth_value(self._hrv, target_hrv, 0.08)
        self._hrv = self._random_walk(self._hrv, 20, 80, 1.5)

        # 信号强度（戒指一般稳定）
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 80, 100, 0.5
        ))

        # 保存读数
        self._set_reading("heart_rate", round(self._heart_rate, 1), "bpm")
        self._set_reading("temperature", round(self._temperature, 2), "℃")
        self._set_reading("sleep_stage", self._sleep_stage, "")
        self._set_reading("stress_index", round(self._stress_index, 1), "")
        self._set_reading("hrv", round(self._hrv, 1), "ms")

    def _update_device_state(self, elapsed: float) -> None:
        """更新戒指状态"""
        # 检测睡眠状态
        now = time.time()
        if now - self._last_sleep_check > 60:  # 每分钟检查一次
            hour = datetime.now().hour
            if hour >= 23 or hour <= 5:
                self._is_sleeping = random.random() < 0.7
            else:
                self._is_sleeping = False
            self._last_sleep_check = now

        # 电量消耗：戒指续航长，每天消耗 5-10%
        # 即每小时约 0.2-0.4%
        drain_rate = 0.3
        self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 极低电量警告
        if self.device.battery is not None and self.device.battery < 10:
            if self.device.status == DeviceStatus.ONLINE:
                self.status = DeviceStatus.WARNING

    def _action_meditation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开始冥想引导"""
        duration = params.get("duration", 5)
        self._stress_index = max(10, self._stress_index - 10)
        return {"success": True, "message": f"冥想模式已启动，时长{duration}分钟", "session_id": f"med_{int(time.time())}"}

    def _action_sleep_tracking(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开始/停止睡眠追踪"""
        enable = params.get("enable", True)
        self._is_sleeping = enable
        return {"success": True, "message": f"睡眠追踪已{'开启' if enable else '关闭'}"}


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.RING,
    SmartRingSimulator,
    SmartRingSimulator.capability,
)
