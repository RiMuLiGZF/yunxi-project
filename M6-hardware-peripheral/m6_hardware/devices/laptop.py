"""
M6 硬件外设 - 笔记本电脑模拟器
传感器：CPU使用率、内存使用率、磁盘使用、网络速度
"""

import random
import time
from datetime import datetime
from typing import Dict, Any

from .base_device import BaseDeviceSimulator
from .device_factory import DeviceCapability, DeviceFactory
from ..models.device import Device, DeviceStatus, DeviceType


class LaptopSimulator(BaseDeviceSimulator):
    """笔记本电脑模拟器

    监测工作状态、效率分析
    """

    capability = DeviceCapability(
        sensors=['cpu_usage', 'memory_usage', 'battery'],
        actions=['sleep', 'shutdown', 'wake'],
        description="笔记本电脑：移动计算终端",
    )

    def __init__(self, device: Device):
        super().__init__(device)

        # 系统传感器
        self._cpu_usage = 25.0        # CPU 使用率 %
        self._memory_usage = 45.0     # 内存使用率 %
        self._disk_usage = 62.0       # 磁盘使用率 %
        self._network_up = 0.5        # 上行速度 MB/s
        self._network_down = 2.0      # 下行速度 MB/s
        self._cpu_temp = 55.0         # CPU 温度 ℃

        # 使用状态
        self._is_active = True        # 是否活跃使用
        self._active_apps = ["浏览器", "编辑器"]  # 活跃应用
        self._work_efficiency = 75.0  # 工作效率指数

    def _generate_sensor_data(self, elapsed: float) -> None:
        """生成笔记本电脑传感器数据"""
        hour = datetime.now().hour
        is_work_hours = 9 <= hour <= 19
        is_night = hour >= 23 or hour <= 6

        if not self._is_active:
            # 非活跃状态，资源占用低
            target_cpu = random.uniform(5, 15)
            target_mem = random.uniform(30, 40)
            target_net_up = random.uniform(0.01, 0.1)
            target_net_down = random.uniform(0.05, 0.5)
            target_temp = random.uniform(40, 50)
        elif is_night:
            # 深夜使用，一般较轻松
            target_cpu = random.uniform(15, 40)
            target_mem = random.uniform(35, 55)
            target_net_up = random.uniform(0.1, 1.0)
            target_net_down = random.uniform(0.5, 3.0)
            target_temp = random.uniform(50, 65)
        elif is_work_hours:
            # 工作时间，负载较高
            workload = random.random()
            if workload < 0.6:
                # 正常工作
                target_cpu = random.uniform(20, 50)
                target_mem = random.uniform(45, 65)
            elif workload < 0.85:
                # 较忙
                target_cpu = random.uniform(40, 70)
                target_mem = random.uniform(55, 75)
            else:
                # 高强度（编译、渲染等）
                target_cpu = random.uniform(60, 90)
                target_mem = random.uniform(65, 85)

            target_net_up = random.uniform(0.2, 3.0)
            target_net_down = random.uniform(1.0, 8.0)
            target_temp = random.uniform(55, 80)
        else:
            # 其他时间，中等负载
            target_cpu = random.uniform(15, 45)
            target_mem = random.uniform(35, 60)
            target_net_up = random.uniform(0.1, 2.0)
            target_net_down = random.uniform(0.5, 5.0)
            target_temp = random.uniform(48, 68)

        # 平滑变化
        self._cpu_usage = self._smooth_value(self._cpu_usage, target_cpu, 0.15)
        self._cpu_usage = self._random_walk(self._cpu_usage, 1, 99, 2.0)

        self._memory_usage = self._smooth_value(self._memory_usage, target_mem, 0.08)
        self._memory_usage = self._random_walk(self._memory_usage, 20, 90, 1.0)

        self._network_up = self._smooth_value(self._network_up, target_net_up, 0.2)
        self._network_up = self._random_walk(self._network_up, 0.01, 10, 0.1)

        self._network_down = self._smooth_value(self._network_down, target_net_down, 0.2)
        self._network_down = self._random_walk(self._network_down, 0.05, 20, 0.3)

        self._cpu_temp = self._smooth_value(self._cpu_temp, target_temp, 0.1)
        self._cpu_temp = self._random_walk(self._cpu_temp, 35, 95, 1.0)

        # 工作效率指数（根据活跃应用和负载估算）
        if self._is_active and is_work_hours:
            self._work_efficiency = self._smooth_value(
                self._work_efficiency, random.uniform(65, 90), 0.05
            )
        else:
            self._work_efficiency = self._smooth_value(
                self._work_efficiency, random.uniform(30, 60), 0.05
            )

        # 信号强度
        self.device.signal_strength = int(self._random_walk(
            float(self.device.signal_strength), 85, 100, 0.5
        ))

        # 保存读数
        self._set_reading("cpu_usage", round(self._cpu_usage, 1), "%")
        self._set_reading("memory_usage", round(self._memory_usage, 1), "%")
        self._set_reading("disk_usage", round(self._disk_usage, 1), "%")
        self._set_reading("network_up", round(self._network_up, 2), "MB/s")
        self._set_reading("network_down", round(self._network_down, 2), "MB/s")
        self._set_reading("cpu_temp", round(self._cpu_temp, 1), "℃")
        self._set_reading("work_efficiency", round(self._work_efficiency, 1), "%")

    def _update_device_state(self, elapsed: float) -> None:
        """更新笔记本状态"""
        # 活跃状态变化
        hour = datetime.now().hour
        if hour >= 1 and hour <= 7:
            # 凌晨大概率闲置
            if random.random() < elapsed / 120:
                self._is_active = not self._is_active
        else:
            if random.random() < elapsed / 600:  # 每10分钟可能切换
                self._is_active = not self._is_active

        if not self._is_active:
            if self.status == DeviceStatus.ONLINE:
                # 闲置时状态不变，但耗电减少
                pass

        # 电量消耗
        if self.status == DeviceStatus.CHARGING:
            self._consume_battery(elapsed, rate_per_hour=0)
        elif not self._is_active:
            self._consume_battery(elapsed, rate_per_hour=1.5)  # 待机
        elif self._cpu_usage > 70:
            self._consume_battery(elapsed, rate_per_hour=12.0)  # 高负载
        else:
            self._consume_battery(elapsed, rate_per_hour=6.0)  # 正常使用

        # 高负载警告
        if self._cpu_usage > 90 and self._cpu_temp > 85:
            self._add_alert("high_load", f"CPU 负载过高: {self._cpu_usage:.0f}%, 温度: {self._cpu_temp:.0f}℃")

    def _action_start_work(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """开始工作模式"""
        self._is_active = True
        self._active_apps = params.get("apps", ["浏览器", "编辑器", "终端"])
        return {"success": True, "message": "工作模式已启动", "active_apps": self._active_apps}

    def _action_focus_mode(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """专注模式"""
        duration = params.get("duration", 25)
        self._is_active = True
        return {
            "success": True,
            "message": f"专注模式已启动，时长 {duration} 分钟",
            "session_id": f"focus_{int(time.time())}",
        }

    def _action_sleep(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """睡眠模式"""
        self._is_active = False
        return {"success": True, "message": "笔记本已进入睡眠模式"}

    def _check_alerts(self) -> None:
        """扩展告警检查"""
        super()._check_alerts()

        # CPU 温度过高
        if self._cpu_temp > 90:
            self._add_alert("high_temp", f"CPU 温度过高: {self._cpu_temp:.1f}℃")


# 注册到设备工厂
DeviceFactory.register(
    DeviceType.LAPTOP,
    LaptopSimulator,
)
