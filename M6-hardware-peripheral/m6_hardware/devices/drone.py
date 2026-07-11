"""
M6 硬件外设 - 改装无人机模拟器
传感器：GPS、高度、速度、电池电压
状态：idle/flying/charging/returning
"""

import random
import time
import math
from datetime import datetime
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class DroneSimulator(BaseDeviceSimulator):
    """改装无人机模拟器

    状态:
        - idle: 待机（在地面）
        - flying: 飞行中
        - charging: 充电中
        - returning: 返航中
    """

    capability = DeviceCapability(
        sensors=['altitude', 'battery', 'gps', 'camera'],
        actions=['takeoff', 'land', 'goto', 'return_home'],
        description="无人机：空中拍摄 + 巡检",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 飞行状态
        self._flight_state = "idle"  # idle/flying/returning

        # 位置（模拟坐标，原点为起飞点）
        self._latitude = 31.2304     # 纬度（以上海为基准）
        self._longitude = 121.4737   # 经度
        self._altitude = 0.0         # 高度 m

        # 速度
        self._speed = 0.0            # 速度 m/s
        self._heading = 0.0          # 航向角 0-360°

        # 电池电压
        self._voltage = 11.1         # 3S 锂电池标称电压

        # 相机状态
        self._camera_recording = False
        self._camera_mode = "photo"  # photo/video

        # 载荷
        self._payload_weight = 0.0   # 载荷重量 g

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成无人机传感器数据"""
        if self._flight_state == "idle":
            # 待机状态，数据基本不变
            self._altitude = self._smooth_value(self._altitude, 0.0, 0.2)
            self._speed = self._smooth_value(self._speed, 0.0, 0.2)
        else:
            # 飞行中
            # 高度变化
            if self._flight_state == "flying":
                target_alt = random.uniform(20, 80)
            else:  # returning 返航下降
                target_alt = max(0, self._altitude - 5 * elapsed)
            self._altitude = self._smooth_value(self._altitude, target_alt, 0.1)
            self._altitude = max(0, self._altitude)

            # 速度变化
            if self._altitude > 5:
                target_speed = random.uniform(3, 12) if self._flight_state == "flying" else random.uniform(2, 6)
            else:
                target_speed = 0.0
            self._speed = self._smooth_value(self._speed, target_speed, 0.15)

            # 位置移动
            if self._speed > 0.5:
                # 航向微调
                self._heading = self._random_walk(self._heading, 0, 360, 2.0)
                # 经纬度变化（粗略模拟）
                dx = self._speed * elapsed * math.sin(math.radians(self._heading))
                dy = self._speed * elapsed * math.cos(math.radians(self._heading))
                # 约 111km 每度纬度，经度随纬度变化
                self._latitude += dy / 111000
                self._longitude += dx / (111000 * math.cos(math.radians(self._latitude)))

            # 返航到家检测
            if self._flight_state == "returning" and self._altitude < 1 and self._speed < 0.5:
                self._flight_state = "idle"

        # 电池电压（与电量百分比关联）
        if self.device.battery is not None:
            # 3S 锂电: 满电 12.6V，空电 ~9.0V
            self._voltage = 9.0 + (self.device.battery / 100.0) * 3.6
        else:
            self._voltage = 12.0

        # GPS 信号强度（飞行时更好）
        gps_quality = 90 if self._flight_state != "idle" else 70
        self.device.signal_strength = int(self._random_walk(
            float(gps_quality), gps_quality - 10, 100, 1.5
        ))

        # 保存读数
        self._set_reading("latitude", round(self._latitude, 6), "°")
        self._set_reading("longitude", round(self._longitude, 6), "°")
        self._set_reading("altitude", round(self._altitude, 1), "m")
        self._set_reading("speed", round(self._speed, 2), "m/s")
        self._set_reading("heading", round(self._heading, 1), "°")
        self._set_reading("voltage", round(self._voltage, 2), "V")
        self._set_reading("flight_state", self._flight_state, "")
        self._set_reading("camera_recording", self._camera_recording, "")

    def _update_device_state(self, elapsed: float) -> None:
        """更新无人机状态"""
        # 飞行状态影响设备状态
        if self._flight_state == "idle":
            # 待机时可能充电
            if self.device.battery is not None and self.device.battery < 90:
                if random.random() < elapsed / 300:  # 每5分钟可能开始充电
                    self.status = DeviceStatus.CHARGING
            elif self.device.battery is not None and self.device.battery >= 99:
                if self.status == DeviceStatus.CHARGING:
                    self.status = DeviceStatus.ONLINE
        elif self._flight_state in ("flying", "returning"):
            if self.status != DeviceStatus.ONLINE:
                self.status = DeviceStatus.ONLINE

        # 电量消耗
        if self._flight_state == "flying":
            drain_rate = 30.0 + self._payload_weight / 100  # 飞行每小时 30%+
        elif self._flight_state == "returning":
            drain_rate = 25.0
        elif self._flight_state == "idle" and self.status != DeviceStatus.CHARGING:
            drain_rate = 2.0  # 待机每小时 2%
        else:
            drain_rate = 0.0

        if self.status != DeviceStatus.CHARGING:
            self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 低电量自动返航
        if (self._flight_state == "flying"
                and self.device.battery is not None
                and self.device.battery < 25):
            self._flight_state = "returning"
            self._add_alert("low_battery_return", "电量不足，正在自动返航")

    def _action_takeoff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """起飞"""
        altitude = params.get("altitude", 30)
        if self._flight_state != "idle":
            return {"success": False, "message": "无人机不在待机状态，无法起飞"}
        if self.device.battery is not None and self.device.battery < 20:
            return {"success": False, "message": "电量不足，无法起飞"}

        self._flight_state = "flying"
        self.status = DeviceStatus.ONLINE
        return {
            "success": True,
            "message": f"无人机已起飞，目标高度 {altitude}m",
            "flight_id": f"flight_{int(time.time())}",
        }

    def _action_return_home(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """返航"""
        if self._flight_state == "idle":
            return {"success": False, "message": "无人机已在地面"}
        self._flight_state = "returning"
        return {"success": True, "message": "无人机正在返航"}

    def _action_take_photo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """拍照"""
        if self._flight_state == "idle" and self.status == DeviceStatus.OFFLINE:
            return {"success": False, "message": "设备离线"}
        self._camera_mode = "photo"
        return {
            "success": True,
            "message": "照片已拍摄",
            "photo_id": f"photo_{int(time.time())}",
            "resolution": "48MP",
        }

    def _action_start_video(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开始录像"""
        self._camera_recording = True
        self._camera_mode = "video"
        return {"success": True, "message": "录像已开始", "video_id": f"video_{int(time.time())}"}

    def _action_stop_video(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """停止录像"""
        self._camera_recording = False
        return {"success": True, "message": "录像已停止"}

    def _action_deliver(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """物品投递"""
        item = params.get("item", "物品")
        weight = params.get("weight", 100)
        self._payload_weight = float(weight)
        return {
            "success": True,
            "message": f"已装载 {item}（{weight}g），准备起飞投递",
            "delivery_id": f"deliver_{int(time.time())}",
        }


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.DRONE,
    DroneSimulator,
)
