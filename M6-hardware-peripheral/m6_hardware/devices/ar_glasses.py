"""
M6 硬件外设 - AR眼镜模拟器
传感器：头动追踪、眼动追踪、环境深度
"""

import random
import time
from datetime import datetime
from typing import Dict, Any, Tuple

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class ARGlassesSimulator(BaseDeviceSimulator):
    """AR眼镜模拟器

    特点：使用时耗电快、支持AR导航/翻译/信息叠加
    """

    capability = DeviceCapability(
        sensors=['display', 'camera', 'imu'],
        actions=['display_content', 'take_photo', 'navigation'],
        description="AR眼镜：增强现实显示 + 空间计算",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 初始化传感器值
        self._head_pitch = 0.0         # 头部俯仰角 -90~90°
        self._head_yaw = 0.0           # 头部偏航角 -180~180°
        self._gaze_x = 0.5             # 视线X坐标 0-1
        self._gaze_y = 0.5             # 视线Y坐标 0-1
        self._depth_near = 1.5         # 最近深度 m
        self._depth_far = 10.0         # 最远深度 m
        self._brightness = 80.0        # 显示亮度 %

        self._is_worn = True           # 是否佩戴
        self._usage_mode = "idle"      # 使用模式: idle/navigation/translation/info

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成AR眼镜传感器数据"""
        if not self._is_worn:
            # 未佩戴时传感器数据不更新
            return

        # 头部追踪（轻微移动）
        self._head_pitch = self._random_walk(self._head_pitch, -30, 30, 1.0)
        self._head_yaw = self._random_walk(self._head_yaw, -60, 60, 1.5)

        # 眼动追踪
        self._gaze_x = self._random_walk(self._gaze_x, 0.1, 0.9, 0.02)
        self._gaze_y = self._random_walk(self._gaze_y, 0.1, 0.9, 0.02)

        # 环境深度
        if self._usage_mode == "navigation":
            # 导航模式，深度变化大
            self._depth_near = self._random_walk(self._depth_near, 0.5, 3.0, 0.2)
            self._depth_far = self._random_walk(self._depth_far, 5.0, 20.0, 1.0)
        else:
            self._depth_near = self._random_walk(self._depth_near, 1.0, 2.5, 0.1)
            self._depth_far = self._random_walk(self._depth_far, 5.0, 15.0, 0.5)

        # 环境光自适应亮度
        ambient_factor = random.uniform(0.8, 1.2)
        self._brightness = self._smooth_value(
            self._brightness,
            60 * ambient_factor if self._usage_mode == "idle" else 85 * ambient_factor,
            0.1
        )

        # 信号强度
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 60, 95, 2.0
        ))

        # 保存读数
        self._set_reading("head_pitch", round(self._head_pitch, 1), "°")
        self._set_reading("head_yaw", round(self._head_yaw, 1), "°")
        self._set_reading("gaze_x", round(self._gaze_x, 3), "")
        self._set_reading("gaze_y", round(self._gaze_y, 3), "")
        self._set_reading("depth_near", round(self._depth_near, 2), "m")
        self._set_reading("depth_far", round(self._depth_far, 2), "m")
        self._set_reading("brightness", round(self._brightness, 1), "%")

    def _update_device_state(self, elapsed: float) -> None:
        """更新AR眼镜状态"""
        # 佩戴状态变化
        if random.random() < elapsed / 600:  # 每10分钟可能摘下
            self._is_worn = not self._is_worn

        if not self._is_worn:
            # 未佩戴时进入待机
            if self.device.status == DeviceStatus.ONLINE:
                self.status = DeviceStatus.OFFLINE
            return

        # 使用模式切换
        if random.random() < elapsed / 180:  # 每3分钟可能切换
            modes = ["idle", "navigation", "translation", "info", "idle", "idle"]
            self._usage_mode = random.choice(modes)

        # 电量消耗：使用时耗电快
        if self._usage_mode == "idle":
            drain_rate = 8.0  # 待机每小时 8%
        elif self._usage_mode == "navigation":
            drain_rate = 20.0  # 导航最耗电
        else:
            drain_rate = 15.0  # 其他使用模式每小时 15%

        self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 低电量警告
        if self.device.battery is not None and self.device.battery < 20:
            if self.device.status == DeviceStatus.ONLINE:
                self.status = DeviceStatus.WARNING

    def _action_start_navigation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """启动AR导航"""
        destination = params.get("destination", "未知目的地")
        self._usage_mode = "navigation"
        return {
            "success": True,
            "message": f"AR导航已启动，目的地: {destination}",
            "nav_id": f"nav_{int(time.time())}",
        }

    def _action_translate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """启动实时翻译"""
        target_lang = params.get("target_lang", "en")
        self._usage_mode = "translation"
        return {
            "success": True,
            "message": f"实时翻译已启动，目标语言: {target_lang}",
            "translate_id": f"trans_{int(time.time())}",
        }

    def _action_display_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """在AR眼镜上显示信息"""
        content = params.get("content", "")
        position = params.get("position", "center")
        self._usage_mode = "info"
        return {
            "success": True,
            "message": "信息已叠加显示",
            "info_id": f"info_{int(time.time())}",
            "content": content[:50] + "..." if len(content) > 50 else content,
            "position": position,
        }

    def _action_power_off(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """关机"""
        self._is_worn = False
        self.status = DeviceStatus.OFFLINE
        return {"success": True, "message": "AR眼镜已关机"}


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.AR,
    ARGlassesSimulator,
)
