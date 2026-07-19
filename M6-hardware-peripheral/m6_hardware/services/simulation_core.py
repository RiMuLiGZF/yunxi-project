"""
P2 半真实化改造：模拟核心服务

提供硬件延迟模拟和故障异常模拟的核心能力，
让 API 响应更接近真实硬件设备的行为特性。

环境变量控制：
- M6_HARDWARE_DELAY=true/false  控制延迟模拟开关（默认 true）
- M6_FAULT_SIMULATION=true/false  控制故障模拟开关（默认 true）
"""

from __future__ import annotations

import asyncio
import os
import random
import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 延迟模拟
# ---------------------------------------------------------------------------

class DelaySimulator:
    """硬件响应延迟模拟器

    为不同类型的操作模拟真实硬件的响应时间：
    - 读取类操作：50-200ms 随机延迟
    - 写入类操作（开关、调节）：200-500ms 随机延迟
    - 慢速设备（窗帘电机）：500-2000ms 延迟（取决于行程距离）

    可通过环境变量 M6_HARDWARE_DELAY 全局关闭。
    """

    def __init__(self, enabled: Optional[bool] = None):
        """
        Args:
            enabled: 是否启用延迟模拟，None 时从环境变量读取
        """
        if enabled is None:
            env_val = os.environ.get("M6_HARDWARE_DELAY", "true").lower()
            enabled = env_val in ("true", "1", "yes", "on")
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        """是否启用延迟模拟"""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """设置延迟模拟开关"""
        self._enabled = enabled

    async def simulate_read_delay(self) -> None:
        """模拟读取类操作的延迟（50-200ms）"""
        if not self._enabled:
            return
        delay = random.uniform(0.05, 0.2)
        await asyncio.sleep(delay)

    async def simulate_write_delay(self) -> None:
        """模拟写入类操作的延迟（200-500ms）"""
        if not self._enabled:
            return
        delay = random.uniform(0.2, 0.5)
        await asyncio.sleep(delay)

    async def simulate_slow_device_delay(
        self,
        distance_ratio: float = 1.0,
        min_delay: float = 0.5,
        max_delay: float = 2.0,
    ) -> None:
        """模拟慢速设备的延迟（如窗帘电机，取决于行程距离）

        Args:
            distance_ratio: 行程距离比例 (0-1)，0 表示几乎不动，1 表示满行程
            min_delay: 最小延迟（秒）
            max_delay: 最大延迟（秒）
        """
        if not self._enabled:
            return
        distance_ratio = max(0.0, min(1.0, distance_ratio))
        base_delay = min_delay + (max_delay - min_delay) * distance_ratio
        # 添加 ±10% 的随机波动
        jitter = base_delay * 0.1
        delay = base_delay + random.uniform(-jitter, jitter)
        delay = max(min_delay, delay)
        await asyncio.sleep(delay)

    async def simulate_custom_delay(self, min_ms: int, max_ms: int) -> None:
        """模拟自定义范围的延迟

        Args:
            min_ms: 最小延迟（毫秒）
            max_ms: 最大延迟（毫秒）
        """
        if not self._enabled:
            return
        delay = random.uniform(min_ms / 1000.0, max_ms / 1000.0)
        await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# 故障模拟
# ---------------------------------------------------------------------------

class FaultSimulator:
    """硬件故障与异常模拟器

    模拟真实硬件可能出现的各种异常情况：
    - 设备离线：随机 1-5% 概率返回设备离线
    - 传感器异常：随机 0.5% 概率返回异常读数
    - 过载保护：智能插座功率超过阈值时自动断电
    - 低电量警告：电池 < 20% 时返回警告

    可通过环境变量 M6_FAULT_SIMULATION 全局关闭。
    """

    # 故障概率配置（可通过环境变量微调）
    DEFAULT_OFFLINE_PROBABILITY = 0.03      # 3% 概率设备离线
    DEFAULT_SENSOR_FAULT_PROBABILITY = 0.005  # 0.5% 概率传感器异常

    def __init__(self, enabled: Optional[bool] = None):
        """
        Args:
            enabled: 是否启用故障模拟，None 时从环境变量读取
        """
        if enabled is None:
            env_val = os.environ.get("M6_FAULT_SIMULATION", "true").lower()
            enabled = env_val in ("true", "1", "yes", "on")
        self._enabled = enabled

        # 从环境变量读取概率配置
        self._offline_probability = float(os.environ.get(
            "M6_FAULT_OFFLINE_PROB",
            str(self.DEFAULT_OFFLINE_PROBABILITY),
        ))
        self._sensor_fault_probability = float(os.environ.get(
            "M6_FAULT_SENSOR_PROB",
            str(self.DEFAULT_SENSOR_FAULT_PROBABILITY),
        ))

    @property
    def enabled(self) -> bool:
        """是否启用故障模拟"""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """设置故障模拟开关"""
        self._enabled = enabled

    def check_offline(self, device_id: str = "") -> bool:
        """检查是否触发设备离线故障

        Args:
            device_id: 设备ID（用于日志）

        Returns:
            True 表示设备应处于离线状态
        """
        if not self._enabled:
            return False
        is_offline = random.random() < self._offline_probability
        if is_offline:
            logger.debug("故障模拟：设备 %s 触发离线状态", device_id)
        return is_offline

    def check_sensor_fault(self, sensor_type: str = "") -> bool:
        """检查是否触发传感器异常故障

        Args:
            sensor_type: 传感器类型（用于日志）

        Returns:
            True 表示传感器读数异常
        """
        if not self._enabled:
            return False
        is_fault = random.random() < self._sensor_fault_probability
        if is_fault:
            logger.debug("故障模拟：传感器 %s 触发异常读数", sensor_type)
        return is_fault

    def generate_abnormal_reading(
        self,
        normal_value: float,
        fault_type: str = "spike",
    ) -> float:
        """生成异常传感器读数

        Args:
            normal_value: 正常值
            fault_type: 故障类型
                - "spike": 尖峰（正常值的 3-5 倍）
                - "drop": 骤降（接近 0 或负数）
                - "stuck": 卡死（固定在某个不合理值）
                - "noise": 巨大噪声（±50% 以上）

        Returns:
            异常读数
        """
        if fault_type == "spike":
            return normal_value * random.uniform(3.0, 5.0)
        elif fault_type == "drop":
            return max(0.0, normal_value * random.uniform(0.0, 0.1))
        elif fault_type == "stuck":
            return 0.0 if normal_value > 0 else -normal_value
        elif fault_type == "noise":
            return normal_value * random.uniform(0.3, 1.7)
        else:
            return normal_value * random.uniform(2.0, 4.0)

    def check_overload(self, current_power: float, threshold: float) -> bool:
        """检查是否触发过载保护

        Args:
            current_power: 当前功率（W）
            threshold: 功率阈值（W）

        Returns:
            True 表示触发过载保护
        """
        if not self._enabled:
            return False
        return current_power > threshold

    def check_low_battery(self, battery: Optional[float], threshold: float = 20.0) -> bool:
        """检查是否触发低电量警告

        Args:
            battery: 电量百分比（None 表示有线供电）
            threshold: 低电量阈值（%）

        Returns:
            True 表示低电量警告
        """
        if battery is None:
            return False
        return battery < threshold


# ---------------------------------------------------------------------------
# 全局单例（便捷访问）
# ---------------------------------------------------------------------------

_default_delay_simulator: Optional[DelaySimulator] = None
_default_fault_simulator: Optional[FaultSimulator] = None


def get_delay_simulator() -> DelaySimulator:
    """获取延迟模拟器全局单例"""
    global _default_delay_simulator
    if _default_delay_simulator is None:
        _default_delay_simulator = DelaySimulator()
    return _default_delay_simulator


def get_fault_simulator() -> FaultSimulator:
    """获取故障模拟器全局单例"""
    global _default_fault_simulator
    if _default_fault_simulator is None:
        _default_fault_simulator = FaultSimulator()
    return _default_fault_simulator
