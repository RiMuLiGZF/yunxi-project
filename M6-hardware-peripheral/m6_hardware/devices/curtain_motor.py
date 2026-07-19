"""
P2 半真实化改造：窗帘电机模拟器

设备特性：
- 开合度 (0-100%)
- 运行方向（停止/正转/反转）
- 限位状态（上限位/下限位/中间）
- 电机温度
- 延迟特性：500-2000ms 延迟（取决于行程距离）
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Dict, Any, Optional

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class CurtainMotorSimulator(BaseDeviceSimulator):
    """窗帘电机模拟器（半真实化 - 慢速设备代表）

    状态机设计：
    - 开合度：0-100%（0 = 完全打开，100 = 完全关闭）
    - 运行状态：stopped / opening / closing
    - 限位状态：top_limit / bottom_limit / middle
    - 电机温度：随运行时间上升
    - 运行速度：可调节（影响延迟时间）
    """

    capability = DeviceCapability(
        sensors=[
            "position", "motor_temperature", "running_state",
            "limit_status", "runtime_total",
        ],
        actions=[
            "open", "close", "stop", "set_position",
            "set_speed", "calibrate_limits",
        ],
        description="窗帘电机：开合控制 + 位置记忆 + 电机温度监测",
    )

    # 速度档位（mm/s，对应开合百分比速度）
    SPEED_LEVELS = {
        "low": 1.0,       # 低速：1% 每秒
        "medium": 2.0,    # 中速：2% 每秒
        "high": 3.0,      # 高速：3% 每秒
    }

    def __init__(self, device: Device, config=None):
        super().__init__(device, config=config)

        # 电机状态变量
        self._position: float = 50.0          # 当前开合度 0-100%
        self._target_position: float = 50.0   # 目标位置
        self._running_state: str = "stopped"  # stopped / opening / closing
        self._limit_status: str = "middle"    # top_limit / bottom_limit / middle
        self._motor_temp: float = 25.0        # 电机温度 °C
        self._speed_level: str = "medium"     # 速度档位
        self._runtime_total: float = 0.0      # 累计运行时间（小时）
        self._last_run_time: float = 0.0
        self._is_moving: bool = False         # 是否正在移动中
        self._move_start_position: float = 0.0
        self._move_start_time: float = 0.0
        self._top_limit_calibrated: bool = True  # 上限位已校准
        self._bottom_limit_calibrated: bool = True  # 下限位已校准

        # 电机参数
        self._max_motor_temp = 80.0  # 电机最高温度
        self._overheat_temp = 70.0   # 过热保护温度
        self._temp_rise_rate = 2.0   # 每秒温升速率
        self._temp_cool_rate = 0.5   # 每秒降温速率

    # ------------------------------------------------------------------
    # 状态序列化/反序列化（用于持久化）
    # ------------------------------------------------------------------

    def get_state_vars(self) -> Dict[str, Any]:
        """获取内部状态变量（用于持久化）"""
        return {
            "position": self._position,
            "target_position": self._target_position,
            "running_state": self._running_state,
            "limit_status": self._limit_status,
            "motor_temp": self._motor_temp,
            "speed_level": self._speed_level,
            "runtime_total": self._runtime_total,
            "last_run_time": self._last_run_time,
            "is_moving": self._is_moving,
            "move_start_position": self._move_start_position,
            "move_start_time": self._move_start_time,
            "top_limit_calibrated": self._top_limit_calibrated,
            "bottom_limit_calibrated": self._bottom_limit_calibrated,
        }

    def restore_state_vars(self, state: Dict[str, Any]) -> None:
        """从持久化状态恢复"""
        self._position = state.get("position", self._position)
        self._target_position = state.get("target_position", self._target_position)
        self._running_state = state.get("running_state", self._running_state)
        self._limit_status = state.get("limit_status", self._limit_status)
        self._motor_temp = state.get("motor_temp", self._motor_temp)
        self._speed_level = state.get("speed_level", self._speed_level)
        self._runtime_total = state.get("runtime_total", self._runtime_total)
        self._last_run_time = state.get("last_run_time", self._last_run_time)
        self._is_moving = state.get("is_moving", False)
        self._move_start_position = state.get("move_start_position", 0.0)
        self._move_start_time = state.get("move_start_time", 0.0)
        self._top_limit_calibrated = state.get("top_limit_calibrated", True)
        self._bottom_limit_calibrated = state.get("bottom_limit_calibrated", True)

    # ------------------------------------------------------------------
    # 行程距离计算（用于延迟模拟）
    # ------------------------------------------------------------------

    def get_travel_time(self, target_position: float) -> float:
        """计算到达目标位置需要的时间（秒）

        用于慢速设备延迟模拟。
        """
        distance = abs(target_position - self._position)
        speed = self.SPEED_LEVELS.get(self._speed_level, 2.0)
        if speed <= 0:
            return 2.0  # 保底
        return distance / speed

    # ------------------------------------------------------------------
    # 传感器数据生成
    # ------------------------------------------------------------------

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成窗帘电机传感器数据"""
        # 更新限位状态
        if self._position <= 1.0:
            self._limit_status = "top_limit"
        elif self._position >= 99.0:
            self._limit_status = "bottom_limit"
        else:
            self._limit_status = "middle"

        # 设置读数
        quality = 100
        if self._motor_temp >= self._overheat_temp:
            quality = 50  # 过热时数据质量下降

        self._set_reading("position", round(self._position, 1), "%", quality=quality)
        self._set_reading("motor_temperature", round(self._motor_temp, 1), "°C", quality=quality)
        self._set_reading("running_state", self._running_state, "state")
        self._set_reading("limit_status", self._limit_status, "status")
        self._set_reading("runtime_total", round(self._runtime_total, 2), "h")

    def _update_device_state(self, elapsed: float) -> None:
        """更新电机状态"""
        # 如果正在移动，更新位置
        if self._is_moving:
            speed = self.SPEED_LEVELS.get(self._speed_level, 2.0)
            direction = 1 if self._target_position > self._position else -1
            delta = speed * elapsed * direction

            new_position = self._position + delta
            new_position = max(0.0, min(100.0, new_position))
            self._position = new_position

            # 累计运行时间
            self._runtime_total += elapsed / 3600.0

            # 检查是否到达目标
            if (direction > 0 and self._position >= self._target_position) or \
               (direction < 0 and self._position <= self._target_position):
                self._position = self._target_position
                self._stop_moving()

        # 电机温度管理
        if self._is_moving:
            # 运行时升温
            self._motor_temp = min(
                self._max_motor_temp,
                self._motor_temp + self._temp_rise_rate * elapsed,
            )
            # 过热保护
            if self._motor_temp >= self._overheat_temp:
                self._stop_moving()
                self._add_alert("overheat", f"电机过热保护: {self._motor_temp:.1f}°C")
                if self.device.status == DeviceStatus.ONLINE:
                    self.device.status = DeviceStatus.WARNING
        else:
            # 停止时降温
            self._motor_temp = max(
                25.0,  # 室温
                self._motor_temp - self._temp_cool_rate * elapsed,
            )
            # 温度降下来后恢复状态
            if self._motor_temp < 40.0 and self.device.status == DeviceStatus.WARNING:
                # 检查是否有其他告警原因
                alerts = self.get_alerts()
                if not any(a["type"] != "overheat" for a in alerts):
                    self.device.status = DeviceStatus.ONLINE

        # 电量消耗（电机功耗较大）
        if self.device.battery is not None:
            if self._is_moving:
                drain_rate = 5.0  # 运行时每小时 5%
            else:
                drain_rate = 0.1  # 待机时每小时 0.1%
            self._consume_battery(elapsed, rate_per_hour=drain_rate)

        # 信号强度波动
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 50, 100, 0.5
        ))

    def _start_moving(self, target_position: float) -> None:
        """开始移动"""
        target_position = max(0.0, min(100.0, target_position))
        if abs(target_position - self._position) < 0.5:
            return  # 已经在目标位置附近

        # 检查过热保护
        if self._motor_temp >= self._overheat_temp:
            return

        self._target_position = target_position
        self._is_moving = True
        self._move_start_position = self._position
        self._move_start_time = time.time()

        if target_position > self._position:
            self._running_state = "closing"  # 关闭方向（开合度增加）
        else:
            self._running_state = "opening"  # 打开方向（开合度减少）

    def _stop_moving(self) -> None:
        """停止移动"""
        if self._is_moving:
            self._is_moving = False
            self._running_state = "stopped"
            self._last_run_time = time.time()

    # ------------------------------------------------------------------
    # 设备动作
    # ------------------------------------------------------------------

    def _action_open(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """打开窗帘（开合度 -> 0%）"""
        target = 0.0
        travel_time = self.get_travel_time(target)
        self._start_moving(target)
        return {
            "success": True,
            "message": "窗帘正在打开",
            "current_position": round(self._position, 1),
            "target_position": target,
            "estimated_time": round(travel_time, 1),
            "running_state": self._running_state,
        }

    def _action_close(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """关闭窗帘（开合度 -> 100%）"""
        target = 100.0
        travel_time = self.get_travel_time(target)
        self._start_moving(target)
        return {
            "success": True,
            "message": "窗帘正在关闭",
            "current_position": round(self._position, 1),
            "target_position": target,
            "estimated_time": round(travel_time, 1),
            "running_state": self._running_state,
        }

    def _action_stop(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """停止窗帘"""
        was_moving = self._is_moving
        self._stop_moving()
        return {
            "success": True,
            "message": "窗帘已停止" if was_moving else "窗帘本来就是停止的",
            "current_position": round(self._position, 1),
            "was_moving": was_moving,
        }

    def _action_set_position(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置窗帘开合位置"""
        position = params.get("position", params.get("open_percent"))
        if position is None:
            return {
                "success": False,
                "message": "缺少 position 参数",
                "error_code": "INVALID_PARAMS",
            }
        try:
            position = float(position)
        except (TypeError, ValueError):
            return {
                "success": False,
                "message": "position 必须是数字",
                "error_code": "INVALID_PARAMS",
            }

        position = max(0.0, min(100.0, position))
        travel_time = self.get_travel_time(position)
        self._start_moving(position)

        return {
            "success": True,
            "message": f"窗帘正在移动到 {position:.0f}%",
            "current_position": round(self._position, 1),
            "target_position": position,
            "estimated_time": round(travel_time, 1),
            "running_state": self._running_state,
        }

    def _action_set_speed(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """设置电机速度"""
        speed = params.get("speed", params.get("level", "medium"))
        if speed not in self.SPEED_LEVELS:
            return {
                "success": False,
                "message": f"无效的速度档位，可选值: {list(self.SPEED_LEVELS.keys())}",
                "error_code": "INVALID_PARAMS",
            }

        old_speed = self._speed_level
        self._speed_level = speed

        return {
            "success": True,
            "message": f"速度已设置为 {speed}",
            "speed": speed,
            "previous_speed": old_speed,
            "speed_percent_per_sec": self.SPEED_LEVELS[speed],
        }

    def _action_calibrate_limits(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """校准限位"""
        # 模拟校准过程
        self._top_limit_calibrated = True
        self._bottom_limit_calibrated = True
        return {
            "success": True,
            "message": "限位校准完成",
            "top_limit": 0.0,
            "bottom_limit": 100.0,
        }


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.CURTAIN_MOTOR,
    CurtainMotorSimulator,
    CurtainMotorSimulator.capability,
)
