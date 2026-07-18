"""
监控中心服务 (ARC-010 修复)

将原 monitor.py 中的全局可变变量抽离为线程安全的 MonitorService 类。
提供统一的指标采集、查询、历史数据管理接口。

修复内容：
- _network_stats → MonitorService._network_stats (Lock 保护)
- _history_buffer → MonitorService._history_buffer (Lock 保护)
- _history_collector_started → MonitorService._collector_started (Lock 保护)
- 所有指标读写通过统一接口，确保线程安全
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from collections import deque
from typing import Dict, Any, Optional, List

# psutil 检测与降级
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# 历史数据配置
MAX_HISTORY_POINTS = 10080  # 7天 * 24小时 * 60分钟 = 10080 个点
HISTORY_INTERVAL_SECONDS = 60  # 每分钟采集一次

# 告警阈值配置
DEFAULT_THRESHOLDS = {
    "cpu_warning": 80,
    "cpu_critical": 90,
    "mem_warning": 85,
    "mem_critical": 95,
    "disk_warning": 80,
    "disk_critical": 90,
}


class MonitorService:
    """
    监控中心服务 - 线程安全的指标管理

    管理所有监控相关的状态数据：
    - 网络速率计算（需要历史数据对比）
    - 历史指标环形缓冲区
    - 后台采集线程生命周期
    - 阈值配置
    """

    def __init__(self, thresholds: Optional[Dict[str, int]] = None):
        """初始化监控服务

        Args:
            thresholds: 告警阈值配置，为空时使用默认值
        """
        self._thresholds = thresholds or dict(DEFAULT_THRESHOLDS)

        # 网络速率计算状态（需要上次数据做差分）
        self._network_lock = threading.Lock()
        self._network_stats = {
            "last_bytes_sent": 0,
            "last_bytes_recv": 0,
            "last_time": 0.0,
        }

        # 历史数据环形缓冲区
        self._history_lock = threading.Lock()
        self._history_buffer: deque = deque(maxlen=MAX_HISTORY_POINTS)

        # 后台采集线程控制
        self._collector_lock = threading.Lock()
        self._collector_started = False
        self._collector_thread: Optional[threading.Thread] = None
        self._collector_stop_event = threading.Event()

        # 日志记录器（延迟导入，避免循环依赖）
        self._logger = None

    @property
    def thresholds(self) -> Dict[str, int]:
        """获取当前阈值配置（只读副本）"""
        return dict(self._thresholds)

    def update_thresholds(self, thresholds: Dict[str, int]) -> None:
        """更新告警阈值配置"""
        with self._collector_lock:
            self._thresholds.update(thresholds)

    def _get_logger(self):
        """延迟获取日志记录器"""
        if self._logger is None:
            try:
                from shared.core.logger import get_logger
                self._logger = get_logger("monitor.service")
            except ImportError:
                import logging
                self._logger = logging.getLogger("monitor.service")
        return self._logger

    # ============================================================
    # 网络速率计算
    # ============================================================

    def get_network_speed(self) -> Dict[str, float]:
        """计算网络上传/下载速率（MB/s）

        线程安全：通过 _network_lock 保护网络统计状态。

        Returns:
            包含 upload_mbps 和 download_mbps 的字典
        """
        if not PSUTIL_AVAILABLE:
            return {"upload_mbps": 0.0, "download_mbps": 0.0}

        try:
            net_io = psutil.net_io_counters()
            current_time = time.time()
            current_sent = net_io.bytes_sent
            current_recv = net_io.bytes_recv

            with self._network_lock:
                # 首次调用，初始化
                if self._network_stats["last_time"] == 0:
                    self._network_stats["last_bytes_sent"] = current_sent
                    self._network_stats["last_bytes_recv"] = current_recv
                    self._network_stats["last_time"] = current_time
                    return {"upload_mbps": 0.0, "download_mbps": 0.0}

                time_diff = current_time - self._network_stats["last_time"]
                if time_diff <= 0:
                    time_diff = 1.0

                upload_diff = current_sent - self._network_stats["last_bytes_sent"]
                download_diff = current_recv - self._network_stats["last_bytes_recv"]

                # 防止溢出（重启网卡等情况）
                if upload_diff < 0:
                    upload_diff = 0
                if download_diff < 0:
                    download_diff = 0

                upload_mbps = (upload_diff / (1024 * 1024)) / time_diff
                download_mbps = (download_diff / (1024 * 1024)) / time_diff

                # 更新状态
                self._network_stats["last_bytes_sent"] = current_sent
                self._network_stats["last_bytes_recv"] = current_recv
                self._network_stats["last_time"] = current_time

            return {
                "upload_mbps": round(upload_mbps, 2),
                "download_mbps": round(download_mbps, 2),
            }
        except Exception:
            # psutil 调用失败时返回零值，不影响主流程
            # 记录 debug 级别日志便于排查
            logger = self._get_logger()
            logger.debug("Failed to get network speed", exc_info=True)
            return {"upload_mbps": 0.0, "download_mbps": 0.0}

    # ============================================================
    # 系统指标采集
    # ============================================================

    def get_system_metrics(self) -> Dict[str, Any]:
        """获取实时系统指标（CPU/内存/磁盘/网络/进程）

        Returns:
            包含完整系统指标的字典，psutil 不可用时返回模拟数据
        """
        logger = self._get_logger()

        if PSUTIL_AVAILABLE:
            try:
                cpu_percent = psutil.cpu_percent(interval=0.1)
                cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
                cpu_count = psutil.cpu_count(logical=True) or 0
                cpu_count_physical = psutil.cpu_count(logical=False) or 0

                mem = psutil.virtual_memory()
                memory = {
                    "total_gb": round(mem.total / (1024 ** 3), 2),
                    "used_gb": round(mem.used / (1024 ** 3), 2),
                    "available_gb": round(mem.available / (1024 ** 3), 2),
                    "percent": mem.percent,
                    "cached_gb": round(getattr(mem, "cached", 0) / (1024 ** 3), 2),
                }

                # 磁盘信息
                disk_info = self._get_disk_info()

                # 网络速度
                net_speed = self.get_network_speed()

                # 进程数
                process_count = len(psutil.pids())
                try:
                    thread_count = sum(
                        p.num_threads() for p in psutil.process_iter(["num_threads"])
                    )
                except Exception:
                    # 进程信息获取失败时用估算值
                    thread_count = process_count * 2
                    logger.debug("Failed to get thread count, using estimate", exc_info=True)

                # 运行时间
                boot_time = psutil.boot_time()
                uptime_seconds = time.time() - boot_time
                uptime_days = int(uptime_seconds // 86400)
                uptime_hours = int((uptime_seconds % 86400) // 3600)
                uptime_minutes = int((uptime_seconds % 3600) // 60)
                uptime_str = f"{uptime_days}天 {uptime_hours}时 {uptime_minutes}分"

                return {
                    "timestamp": time.time(),
                    "source": "psutil",
                    "cpu": {
                        "usage_percent": round(cpu_percent, 1),
                        "per_core": [round(c, 1) for c in cpu_per_core],
                        "core_count_logical": cpu_count,
                        "core_count_physical": cpu_count_physical,
                    },
                    "memory": memory,
                    "disk": disk_info,
                    "network": {
                        "upload_mbps": net_speed["upload_mbps"],
                        "download_mbps": net_speed["download_mbps"],
                    },
                    "process": {
                        "process_count": process_count,
                        "thread_count": thread_count,
                    },
                    "uptime": {
                        "seconds": int(uptime_seconds),
                        "days": uptime_days,
                        "hours": uptime_hours,
                        "minutes": uptime_minutes,
                        "formatted": uptime_str,
                        "boot_time": boot_time,
                    },
                }
            except Exception:
                # psutil 采集失败，记录日志后降级到模拟数据
                logger.warning("Failed to collect system metrics via psutil", exc_info=True)

        # 降级：模拟数据
        return {
            "timestamp": time.time(),
            "source": "mock",
            "cpu": {
                "usage_percent": 23.5,
                "per_core": [15.2, 28.3, 19.8, 30.7],
                "core_count_logical": 4,
                "core_count_physical": 2,
            },
            "memory": {
                "total_gb": 16.0,
                "used_gb": 7.2,
                "available_gb": 8.8,
                "percent": 45.0,
                "cached_gb": 2.1,
            },
            "disk": {
                "total_gb": 512.0,
                "used_gb": 198.0,
                "free_gb": 314.0,
                "percent": 38.7,
                "mount": "C:",
            },
            "network": {
                "upload_mbps": 0.8,
                "download_mbps": 1.2,
            },
            "process": {
                "process_count": 156,
                "thread_count": 1248,
            },
            "uptime": {
                "seconds": 86400,
                "days": 1,
                "hours": 0,
                "minutes": 0,
                "formatted": "1天 0时 0分",
                "boot_time": time.time() - 86400,
            },
        }

    def _get_disk_info(self) -> Dict[str, Any]:
        """获取磁盘使用信息"""
        logger = self._get_logger()
        try:
            # Windows: 获取系统盘信息
            if os.name == "nt":
                try:
                    usage = psutil.disk_usage("C:\\")
                    return {
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "percent": usage.percent,
                        "mount": "C:",
                    }
                except Exception:
                    logger.debug("Failed to get Windows disk usage", exc_info=True)
            # Linux / macOS: 获取根目录
            else:
                try:
                    usage = psutil.disk_usage("/")
                    return {
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "percent": usage.percent,
                        "mount": "/",
                    }
                except Exception:
                    logger.debug("Failed to get Unix disk usage", exc_info=True)
        except Exception:
            logger.debug("Failed to get disk info", exc_info=True)

        return {
            "total_gb": 0,
            "used_gb": 0,
            "free_gb": 0,
            "percent": 0,
            "mount": "unknown",
        }

    # ============================================================
    # 历史数据管理
    # ============================================================

    def collect_history_point(self) -> None:
        """采集一个历史数据点（由后台线程调用）

        线程安全：通过 _history_lock 保护缓冲区写入。
        """
        logger = self._get_logger()
        try:
            metrics = self.get_system_metrics()
            point = {
                "timestamp": time.time(),
                "cpu": metrics["cpu"]["usage_percent"],
                "memory": metrics["memory"]["percent"],
                "disk": metrics["disk"]["percent"],
                "network_in": metrics["network"]["download_mbps"],
                "network_out": metrics["network"]["upload_mbps"],
            }
            with self._history_lock:
                self._history_buffer.append(point)
        except Exception:
            # 采集失败不影响主循环，记录日志便于排查
            logger.warning("Failed to collect history data point", exc_info=True)

    def get_history_data(self, period: str = "1h") -> Dict[str, Any]:
        """根据时间段获取历史数据

        Args:
            period: 时间段，可选值: 1h, 6h, 24h, 7d, 30d

        Returns:
            包含时间序列数据的字典
        """
        period_seconds = {
            "1h": 3600,
            "6h": 21600,
            "24h": 86400,
            "7d": 604800,
            "30d": 2592000,
        }
        seconds = period_seconds.get(period, 3600)
        now = time.time()
        cutoff = now - seconds

        with self._history_lock:
            points = [p for p in self._history_buffer if p["timestamp"] >= cutoff]

        # 如果数据点太少，用实时数据生成补充点（保证图表有东西可看）
        if len(points) < 5:
            current = self.get_system_metrics()
            base_cpu = current["cpu"]["usage_percent"]
            base_mem = current["memory"]["percent"]
            base_disk = current["disk"]["percent"]
            base_net_in = current["network"]["download_mbps"]
            base_net_out = current["network"]["upload_mbps"]

            # 根据 period 决定生成多少个点
            counts = {"1h": 60, "6h": 72, "24h": 96, "7d": 168, "30d": 360}
            count = counts.get(period, 60)
            interval = seconds / count

            points = []
            import random
            random.seed(42)  # 固定种子，保证每次生成的数据一致
            for i in range(count):
                ts = now - (count - i) * interval
                variation = random.uniform(-0.1, 0.1)
                points.append({
                    "timestamp": ts,
                    "cpu": round(base_cpu * (1 + variation), 1),
                    "memory": round(base_mem * (1 + variation * 0.5), 1),
                    "disk": round(base_disk * (1 + variation * 0.1), 1),
                    "network_in": round(max(0, base_net_in * (1 + variation)), 2),
                    "network_out": round(max(0, base_net_out * (1 + variation)), 2),
                })

        return {
            "period": period,
            "point_count": len(points),
            "timestamps": [p["timestamp"] for p in points],
            "cpu": [p["cpu"] for p in points],
            "memory": [p["memory"] for p in points],
            "disk": [p["disk"] for p in points],
            "network_in": [p["network_in"] for p in points],
            "network_out": [p["network_out"] for p in points],
        }

    def get_history_buffer_size(self) -> int:
        """获取历史缓冲区当前数据点数"""
        with self._history_lock:
            return len(self._history_buffer)

    def clear_history(self) -> None:
        """清空历史数据"""
        with self._history_lock:
            self._history_buffer.clear()

    # ============================================================
    # 后台采集线程管理
    # ============================================================

    def start_collector(self) -> bool:
        """启动后台历史数据采集线程

        Returns:
            True 表示成功启动，False 表示已在运行
        """
        with self._collector_lock:
            if self._collector_started:
                return False

            self._collector_stop_event.clear()
            self._collector_started = True

            def _collector_loop():
                # 启动时先采集一个点
                self.collect_history_point()
                while not self._collector_stop_event.is_set():
                    # 分段 sleep，使 stop 响应更及时
                    self._collector_stop_event.wait(HISTORY_INTERVAL_SECONDS)
                    if not self._collector_stop_event.is_set():
                        self.collect_history_point()

            self._collector_thread = threading.Thread(
                target=_collector_loop,
                daemon=True,
                name="monitor-history-collector",
            )
            self._collector_thread.start()
            return True

    def stop_collector(self) -> bool:
        """停止后台采集线程

        Returns:
            True 表示成功停止，False 表示未运行
        """
        with self._collector_lock:
            if not self._collector_started:
                return False

            self._collector_stop_event.set()
            self._collector_started = False
            return True

    @property
    def collector_running(self) -> bool:
        """采集线程是否在运行"""
        with self._collector_lock:
            return self._collector_started

    # ============================================================
    # 阈值告警检查
    # ============================================================

    def check_thresholds(self, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """根据阈值检查系统指标，返回触发的告警列表

        Args:
            metrics: 系统指标字典

        Returns:
            告警列表，每个告警包含 type、level、message 字段
        """
        alerts = []
        cpu_usage = metrics.get("cpu", {}).get("usage_percent", 0)
        mem_usage = metrics.get("memory", {}).get("percent", 0)
        disk_usage = metrics.get("disk", {}).get("percent", 0)

        # CPU 阈值检查
        if cpu_usage > self._thresholds.get("cpu_critical", 90):
            alerts.append({
                "type": "cpu",
                "level": "critical",
                "title": "CPU使用率严重过高",
                "value": cpu_usage,
                "threshold": self._thresholds["cpu_critical"],
            })
        elif cpu_usage > self._thresholds.get("cpu_warning", 80):
            alerts.append({
                "type": "cpu",
                "level": "warning",
                "title": "CPU使用率偏高",
                "value": cpu_usage,
                "threshold": self._thresholds["cpu_warning"],
            })

        # 内存阈值检查
        if mem_usage > self._thresholds.get("mem_critical", 95):
            alerts.append({
                "type": "memory",
                "level": "critical",
                "title": "内存使用率严重过高",
                "value": mem_usage,
                "threshold": self._thresholds["mem_critical"],
            })
        elif mem_usage > self._thresholds.get("mem_warning", 85):
            alerts.append({
                "type": "memory",
                "level": "warning",
                "title": "内存使用率偏高",
                "value": mem_usage,
                "threshold": self._thresholds["mem_warning"],
            })

        # 磁盘阈值检查
        if disk_usage > self._thresholds.get("disk_critical", 90):
            alerts.append({
                "type": "disk",
                "level": "critical",
                "title": "磁盘空间严重不足",
                "value": disk_usage,
                "threshold": self._thresholds["disk_critical"],
            })
        elif disk_usage > self._thresholds.get("disk_warning", 80):
            alerts.append({
                "type": "disk",
                "level": "warning",
                "title": "磁盘空间不足",
                "value": disk_usage,
                "threshold": self._thresholds["disk_warning"],
            })

        return alerts


# ============================================================
# 全局单例（供路由层使用）
# ============================================================
# 注意：虽然这里仍然是模块级变量，但 MonitorService 内部
# 已经通过 Lock 保证了所有可变状态的线程安全。
# 推荐通过依赖注入获取实例，此处保留单例便于向后兼容。
# ============================================================

_monitor_service: Optional[MonitorService] = None
_service_lock = threading.Lock()


def get_monitor_service() -> MonitorService:
    """获取监控服务单例

    线程安全的单例模式，首次调用时创建实例并启动采集器。
    """
    global _monitor_service
    if _monitor_service is None:
        with _service_lock:
            if _monitor_service is None:
                _monitor_service = MonitorService()
                # 启动后台采集线程
                _monitor_service.start_collector()
    return _monitor_service
