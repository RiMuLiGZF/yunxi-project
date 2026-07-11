"""
潮汐引擎主入口

整合所有潮汐组件，提供单例访问。
与 M10 现有系统（SystemMonitor、GuardEngine）集成。
"""

from __future__ import annotations

from typing import Optional, Tuple

import structlog

from .tide_scheduler import TideScheduler
from .models import TideStrategy

logger = structlog.get_logger(__name__)

# 全局单例
_instance: Optional["TideEngine"] = None


class TideEngine:
    """M10 潮汐引擎

    基于 GPU/系统资源潮汐式变化的智能调度系统。

    与 M10 现有模块的关系：
    - 从 SystemMonitor 获取实时资源数据
    - 与 GuardEngine 的防护策略联动
    - 为 SandboxScheduler 提供 GPU 任务调度能力
    - 为 M8 算力调度提供潮汐式资源管理
    """

    def __init__(self):
        self._scheduler: Optional[TideScheduler] = None
        self._strategy = TideStrategy()
        self._initialized = False

    def initialize(
        self,
        system_monitor=None,
        strategy: Optional[TideStrategy] = None,
        poll_interval_sec: float = 2.0,
    ):
        """初始化潮汐引擎

        Args:
            system_monitor: M10 SystemMonitor 实例（用于获取资源数据）
            strategy: 潮汐策略
            poll_interval_sec: 轮询间隔
        """
        if self._initialized:
            return

        if strategy:
            self._strategy = strategy

        self._scheduler = TideScheduler(self._strategy)

        # 如果有 system_monitor，设置资源回调
        if system_monitor:
            callback = _MonitorResourceCallback(system_monitor)
            self._scheduler.start(
                resource_callback=callback,
                poll_interval_sec=poll_interval_sec,
            )
        else:
            # 无监控时也启动，但资源数据为 0
            self._scheduler.start(
                resource_callback=lambda: (0.0, 0.0, 0.0, 0.0),
                poll_interval_sec=poll_interval_sec,
            )

        self._initialized = True
        logger.info("潮汐引擎初始化完成")

    @property
    def scheduler(self) -> TideScheduler:
        if not self._scheduler:
            raise RuntimeError("潮汐引擎未初始化")
        return self._scheduler

    @property
    def initialized(self) -> bool:
        return self._initialized

    def shutdown(self):
        """关闭潮汐引擎"""
        if self._scheduler:
            self._scheduler.stop()
            self._scheduler = None
        self._initialized = False
        logger.info("潮汐引擎已关闭")


class _MonitorResourceCallback:
    """SystemMonitor 资源获取适配器

    从 M10 SystemMonitor 中提取 GPU/CPU/内存数据。
    """

    def __init__(self, system_monitor):
        self._monitor = system_monitor

    def __call__(self) -> Tuple[float, float, float, float]:
        """获取资源水位

        Returns:
            (gpu_memory_pct, gpu_util_pct, cpu_pct, memory_pct)
        """
        metric = self._monitor.get_latest_metric()
        if not metric:
            return (0.0, 0.0, 0.0, 0.0)

        gpu_mem = metric.gpu.memory_percent if metric.gpu else 0.0
        gpu_util = metric.gpu.usage_percent if metric.gpu else 0.0
        cpu = metric.cpu.usage_percent if metric.cpu else 0.0
        mem = metric.memory.usage_percent if metric.memory else 0.0

        return (gpu_mem, gpu_util, cpu, mem)

    def get_gpu_devices(self):
        """获取 GPU 设备列表"""
        metric = self._monitor.get_latest_metric()
        if not metric or not metric.gpu or not metric.gpu.devices:
            return []

        devices = []
        for dev in metric.gpu.devices:
            devices.append({
                "gpu_id": getattr(dev, "gpu_id", 0),
                "memory_total_mb": getattr(dev, "memory_total_mb", 0),
                "memory_free_mb": getattr(dev, "memory_free_mb", 0),
                "memory_used_mb": getattr(dev, "memory_used_mb", 0),
                "usage_percent": getattr(dev, "usage_percent", 0),
            })
        return devices


def get_tide_engine() -> TideEngine:
    """获取潮汐引擎单例"""
    global _instance
    if _instance is None:
        _instance = TideEngine()
    return _instance
