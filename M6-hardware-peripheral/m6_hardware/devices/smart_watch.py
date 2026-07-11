"""
M6 硬件外设 - 智能手表模拟器
传感器：心率、步数、卡路里、睡眠、血氧
"""

import random
import time
from datetime import datetime
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class SmartWatchSimulator(BaseDeviceSimulator):
    """智能手表模拟器"""

    capability = DeviceCapability(
        sensors=["heart_rate", "steps", "calories", "sleep_score", "blood_oxygen"],
        actions=["start_exercise", "stop_exercise", "find_device"],
        description="智能手表：运动追踪 + 健康监测",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 初始化传感器基线值
        self._heart_rate = 72.0       # 心率 bpm
        self._steps = 0               # 步数
        self._calories = 0.0          # 卡路里 kcal
        self._sleep_score = 85.0      # 睡眠分数
        self._blood_oxygen = 97.0     # 血氧 %
        self._steps_per_minute = 30   # 每分钟步数基准

        # 运动状态: rest / walking / running / sleeping
        self._activity_state = "rest"
        self._state_change_time = time.time()

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成手表传感器数据"""
        hours_passed = elapsed / 3600.0

        # 根据活动状态调整心率基线
        if self._activity_state == "sleeping":
            target_hr = random.uniform(55, 65)
        elif self._activity_state == "rest":
            target_hr = random.uniform(65, 80)
        elif self._activity_state == "walking":
            target_hr = random.uniform(90, 110)
        else:  # running
            target_hr = random.uniform(130, 160)

        # 心率平滑变化
        self._heart_rate = self._smooth_value(self._heart_rate, target_hr, 0.1)
        # 添加微小波动
        self._heart_rate = self._random_walk(self._heart_rate, 50, 170, 1.5)

        # 步数增加（根据活动状态）
        if self._activity_state in ("walking", "running"):
            step_rate = self._steps_per_minute if self._activity_state == "walking" else 160
            self._steps += int(step_rate * elapsed / 60 * random.uniform(0.8, 1.2))

        # 卡路里消耗
        # 基础代谢 + 活动消耗
        bmr_per_sec = 1.2 / 3600  # 基础代谢约 1.2 kcal/分钟
        activity_factor = {
            "sleeping": 0.9,
            "rest": 1.0,
            "walking": 2.5,
            "running": 6.0,
        }.get(self._activity_state, 1.0)
        self._calories += bmr_per_sec * activity_factor * elapsed

        # 血氧（睡眠时略低，运动时正常）
        if self._activity_state == "sleeping":
            target_spo2 = random.uniform(94, 96)
        elif self._activity_state == "running":
            target_spo2 = random.uniform(95, 98)
        else:
            target_spo2 = random.uniform(96, 99)
        self._blood_oxygen = self._smooth_value(self._blood_oxygen, target_spo2, 0.05)
        self._blood_oxygen = self._random_walk(self._blood_oxygen, 92, 100, 0.3)

        # 睡眠分数（只在睡眠状态下更新）
        if self._activity_state == "sleeping":
            self._sleep_score = self._random_walk(self._sleep_score, 70, 95, 0.5)

        # 信号强度波动
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 70, 100, 1.0
        ))

        # 保存读数
        self._set_reading("heart_rate", round(self._heart_rate, 1), "bpm")
        self._set_reading("steps", self._steps, "步")
        self._set_reading("calories", round(self._calories, 1), "kcal")
        self._set_reading("sleep_score", round(self._sleep_score, 1), "分")
        self._set_reading("blood_oxygen", round(self._blood_oxygen, 1), "%")

    def _update_device_state(self, elapsed: float) -> None:
        """更新手表状态"""
        # 每 2-5 分钟随机切换活动状态
        state_duration = time.time() - self._state_change_time
        if state_duration > random.uniform(120, 300):
            states = ["rest", "walking", "rest", "rest"]
            # 晚上有概率睡眠
            hour = datetime.now().hour
            if hour >= 22 or hour <= 6:
                states.append("sleeping")
            self._activity_state = random.choice(states)
            self._state_change_time = time.time()

        # 电量消耗：正常使用每小时 3-5%
        drain_rate = 3.0
        if self._activity_state == "running":
            drain_rate = 5.0  # GPS + 心率监测更耗电
        self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 低电量时状态变化
        if self.device.battery is not None and self.device.battery < 15:
            if self.device.status == DeviceStatus.ONLINE:
                self.status = DeviceStatus.WARNING

    def _action_start_exercise(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开始运动"""
        exercise_type = params.get("type", "running")
        self._activity_state = "running" if exercise_type == "run" else "walking"
        self._state_change_time = time.time()
        return {"success": True, "message": f"已开始{exercise_type}运动", "exercise_id": f"ex_{int(time.time())}"}

    def _action_stop_exercise(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """停止运动"""
        self._activity_state = "rest"
        return {"success": True, "message": "运动已停止", "summary": {"steps": self._steps, "calories": round(self._calories, 1)}}

    def _action_find_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """查找设备（响铃+震动）"""
        return {"success": True, "message": "手表正在响铃并震动"}


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.WATCH,
    SmartWatchSimulator,
    SmartWatchSimulator.capability,
)
