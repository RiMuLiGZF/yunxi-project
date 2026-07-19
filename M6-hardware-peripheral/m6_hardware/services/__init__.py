"""
M6 硬件外设 - 业务服务包
设备管理、数据采集、通知推送等核心服务

P2 半真实化改造：
- 新增状态持久化服务
- 新增模拟核心服务（延迟/故障模拟）
"""

from .device_manager import DeviceManager
from .data_collector import DataCollector
from .notification import NotificationService
from .state_persistence import StatePersistence
from .simulation_core import DelaySimulator, FaultSimulator

__all__ = [
    "DeviceManager",
    "DataCollector",
    "NotificationService",
    "StatePersistence",
    "DelaySimulator",
    "FaultSimulator",
]
