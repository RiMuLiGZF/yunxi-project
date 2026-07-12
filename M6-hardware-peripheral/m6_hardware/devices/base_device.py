"""
M6 硬件外设 - 设备模拟器基类
所有设备模拟器继承此类，提供通用的模拟逻辑
"""

import random
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod

from ..models.device import Device, DeviceStatus, DeviceType
from ..models.sensor_data import SensorData, SensorReading
from .device_factory import DeviceCapability


class BaseDeviceSimulator(ABC):
    """设备模拟器基类

    提供设备状态管理、电量消耗、传感器数据生成等通用能力。
    子类需要实现 _generate_sensor_data 和 _update_device_state 方法。

    P2-10: 增加能力声明机制和设备健康度评分。
    """

    # 子类可覆盖的能力声明
    capability: DeviceCapability = DeviceCapability(description="基础设备")

    def __init__(self, device: Device):
        """初始化设备模拟器

        Args:
            device: 设备基础信息模型
        """
        self.device = device
        self._last_tick_time = time.time()
        self._sensor_data = SensorData(device_id=device.device_id)
        self._alerts: List[Dict[str, Any]] = []

    @property
    def device_id(self) -> str:
        """设备ID"""
        return self.device.device_id

    @property
    def device_type(self) -> DeviceType:
        """设备类型"""
        return self.device.device_type

    @property
    def status(self) -> DeviceStatus:
        """设备当前状态"""
        return self.device.status

    @status.setter
    def status(self, value: DeviceStatus):
        """设置设备状态"""
        if self.device.status != value:
            self.device.status = value
            self._on_status_change(value)

    def tick(self) -> SensorData:
        """执行一次模拟步进，生成新的传感器数据

        Returns:
            最新的传感器数据
        """
        now = time.time()
        elapsed = now - self._last_tick_time
        self._last_tick_time = now

        # 更新设备在线时间
        if self.device.status != DeviceStatus.OFFLINE:
            self.device.last_seen = datetime.now()

        # 消耗电量
        self._consume_battery(elapsed)

        # 更新设备状态
        self._update_device_state(elapsed)

        # 生成传感器数据
        self._generate_sensor_data(elapsed)

        # 检查告警
        self._check_alerts()

        return self._sensor_data

    def get_current_sensor_data(self) -> SensorData:
        """获取当前传感器数据"""
        return self._sensor_data

    def get_device_info(self) -> Device:
        """获取设备信息"""
        return self.device

    def to_dict(self) -> Dict[str, Any]:
        """转换为完整的设备字典（包含最新传感器数据）"""
        return {
            **self.device.to_dict(),
            "sensors": self._sensor_data.to_dict()["readings"],
        }

    def execute_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行设备动作

        Args:
            action: 动作名称
            params: 动作参数

        Returns:
            执行结果
        """
        params = params or {}
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return {"success": False, "message": f"不支持的动作: {action}"}
        try:
            return handler(params)
        except Exception as e:
            return {"success": False, "message": f"动作执行失败: {str(e)}"}

    def push_notification(self, title: str, content: str, **kwargs) -> Dict[str, Any]:
        """向设备推送通知

        Args:
            title: 通知标题
            content: 通知内容

        Returns:
            推送结果
        """
        # 模拟通知推送
        return {
            "success": True,
            "message": "通知已推送",
            "notification_id": f"notif_{int(time.time())}",
        }

    # ------------------------------------------------------------------
    # 需要子类实现的方法
    # ------------------------------------------------------------------

    @abstractmethod
    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成传感器数据（子类实现）

        Args:
            elapsed: 距上次调用经过的秒数
        """
        pass

    @abstractmethod
    def _update_device_state(self, elapsed: float) -> None:
        """更新设备状态（子类实现）

        Args:
            elapsed: 距上次调用经过的秒数
        """
        pass

    # ------------------------------------------------------------------
    # 通用工具方法
    # ------------------------------------------------------------------

    def _consume_battery(self, elapsed: float, rate_per_hour: float = 5.0) -> None:
        """消耗电量

        Args:
            elapsed: 经过的秒数
            rate_per_hour: 每小时消耗百分比（默认 5%/小时）
        """
        if self.device.battery is None:
            return  # 有线供电，不消耗

        if self.device.status == DeviceStatus.CHARGING:
            # 充电中，电量增加
            charge_rate = 20.0  # 每小时充 20%
            self.device.battery = min(
                100.0,
                self.device.battery + (charge_rate * elapsed / 3600)
            )
            if self.device.battery >= 100.0:
                self.device.battery = 100.0
            return

        if self.device.status == DeviceStatus.OFFLINE:
            return  # 离线不消耗

        # 正常消耗
        self.device.battery = max(
            0.0,
            self.device.battery - (rate_per_hour * elapsed / 3600)
        )

    def _check_alerts(self) -> None:
        """检查告警条件"""
        # 低电量告警
        if (self.device.battery is not None
                and self.device.battery < 20
                and self.device.status != DeviceStatus.CHARGING):
            self._add_alert("low_battery", f"电量低: {self.device.battery:.1f}%")

        # 离线告警
        if self.device.status == DeviceStatus.OFFLINE:
            self._add_alert("offline", "设备离线")

    def _add_alert(self, alert_type: str, message: str) -> None:
        """添加告警（避免重复）"""
        # 检查最近是否已有相同类型告警
        recent = [a for a in self._alerts[-5:] if a["type"] == alert_type]
        if recent:
            return
        self._alerts.append({
            "type": alert_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "device_id": self.device.device_id,
        })

    def get_alerts(self, clear: bool = False) -> List[Dict[str, Any]]:
        """获取告警列表

        Args:
            clear: 是否清除已读告警
        """
        alerts = list(self._alerts)
        if clear:
            self._alerts.clear()
        return alerts

    def get_health_score(self) -> int:
        """P2-10: 计算设备健康度评分 (0-100)

        综合考虑：电量、信号强度、状态、告警数量
        分数越高表示设备越健康。

        Returns:
            健康度评分 0-100
        """
        score = 100

        # 电量扣分 (最多扣 40 分)
        if self.device.battery is not None:
            if self.device.battery < 10:
                score -= 40
            elif self.device.battery < 20:
                score -= 25
            elif self.device.battery < 50:
                score -= 10

        # 信号强度扣分 (最多扣 20 分)
        if self.device.signal_strength < 50:
            score -= 20
        elif self.device.signal_strength < 70:
            score -= 10
        elif self.device.signal_strength < 85:
            score -= 5

        # 状态扣分
        if self.device.status == DeviceStatus.OFFLINE:
            score -= 50
        elif self.device.status == DeviceStatus.ERROR:
            score -= 40
        elif self.device.status == DeviceStatus.WARNING:
            score -= 15
        elif self.device.status == DeviceStatus.CHARGING:
            score -= 0  # 充电中不扣分

        # 告警扣分 (每个扣 5 分，最多 20 分)
        alert_penalty = min(len(self._alerts) * 5, 20)
        score -= alert_penalty

        return max(0, min(100, score))

    def get_capability(self) -> DeviceCapability:
        """获取设备能力声明"""
        return self.capability

    def supports_sensor(self, sensor_type: str) -> bool:
        """检查设备是否支持指定传感器"""
        return self.capability.has_sensor(sensor_type)

    def supports_action(self, action: str) -> bool:
        """检查设备是否支持指定动作"""
        return self.capability.has_action(action)

    def _on_status_change(self, new_status: DeviceStatus) -> None:
        """状态变更回调（可被子类重写）"""
        pass

    def _smooth_value(self, current: float, target: float, factor: float = 0.3) -> float:
        """平滑过渡数值，避免突变

        Args:
            current: 当前值
            target: 目标值
            factor: 平滑因子 (0-1)，越大变化越快

        Returns:
            平滑后的值
        """
        return current + (target - current) * factor

    def _random_walk(self, current: float, min_val: float, max_val: float, step: float) -> float:
        """随机游走生成自然波动的数据

        Args:
            current: 当前值
            min_val: 最小值
            max_val: 最大值
            step: 最大步长

        Returns:
            新的值
        """
        delta = random.uniform(-step, step)
        new_val = current + delta
        # 边界回弹
        if new_val < min_val:
            new_val = min_val + (min_val - new_val) * 0.5
        if new_val > max_val:
            new_val = max_val - (new_val - max_val) * 0.5
        return max(min_val, min(max_val, new_val))

    def _set_reading(self, sensor_type: str, value: Any, unit: str = "", quality: int = 100) -> None:
        """设置传感器读数"""
        self._sensor_data.readings[sensor_type] = SensorReading(
            sensor_type=sensor_type,
            value=value,
            unit=unit,
            quality=quality,
        )
