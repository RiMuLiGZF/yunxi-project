"""
云汐 M10 系统卫士 - A1 系统资源监控服务
负责系统资源的实时监控、历史数据查询和系统信息管理
沙盒模式下全部使用模拟数据，不调用真实系统API
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 兼容相对导入和直接运行
try:
    from ..config import get_settings
    from ..mock_data_engine import get_mock_engine
    from ..database import get_session
    from ..models import SystemMetric
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_settings
    from mock_data_engine import get_mock_engine
    from database import get_session
    from models import SystemMetric


class SystemMonitorService:
    """
    系统资源监控服务
    提供实时状态查询、历史数据获取、系统信息管理等功能
    """

    def __init__(self):
        """初始化系统监控服务"""
        self.settings = get_settings()
        self.mock_engine = get_mock_engine()
        self._history_cache = []
        self._history_cache_size = 3600  # 缓存1小时数据

    def get_realtime_status(self) -> dict:
        """
        获取实时系统状态

        Returns:
            包含所有系统指标的实时状态字典
        """
        if self.settings.sandbox_mode:
            # 沙盒模式：使用模拟数据
            metrics = self.mock_engine.generate_system_metrics()
            # 缓存历史数据
            self._cache_metric(metrics)
            return metrics
        else:
            # 非沙盒模式（预留，当前版本仅支持沙盒）
            return self.mock_engine.generate_system_metrics()

    def _cache_metric(self, metrics: dict):
        """
        缓存指标数据到内存

        Args:
            metrics: 指标数据字典
        """
        self._history_cache.append(metrics)
        if len(self._history_cache) > self._history_cache_size:
            self._history_cache = self._history_cache[-self._history_cache_size:]

    def get_history(self, start_time: Optional[str] = None,
                    end_time: Optional[str] = None,
                    metric: Optional[str] = None,
                    limit: int = 60) -> List[dict]:
        """
        获取历史数据

        Args:
            start_time: 开始时间（ISO格式）
            end_time: 结束时间（ISO格式）
            metric: 指标名称（可选，如 cpu_percent, mem_percent 等）
            limit: 返回数据点数量限制

        Returns:
            历史数据点列表
        """
        if self.settings.sandbox_mode:
            # 沙盒模式：生成模拟历史数据
            return self._generate_mock_history(start_time, end_time, metric, limit)
        else:
            # 非沙盒模式：从数据库查询
            return self._query_db_history(start_time, end_time, metric, limit)

    def _generate_mock_history(self, start_time: Optional[str],
                                end_time: Optional[str],
                                metric: Optional[str],
                                limit: int) -> List[dict]:
        """
        生成模拟历史数据

        Args:
            start_time: 开始时间
            end_time: 结束时间
            metric: 指标名称
            limit: 数据点数量

        Returns:
            模拟历史数据列表
        """
        # 如果有缓存数据，优先使用
        if len(self._history_cache) >= 10:
            history = self._history_cache[-min(limit, len(self._history_cache)):]
            if metric:
                # 只返回指定指标
                result = []
                for item in history:
                    metric_value = self._extract_metric(item, metric)
                    result.append({
                        "timestamp": item["timestamp"],
                        metric: metric_value,
                    })
                return result
            return history

        # 生成模拟历史数据
        result = []
        now = datetime.now()
        interval = self.settings.sampling_interval

        for i in range(limit - 1, -1, -1):
            timestamp = now - timedelta(seconds=i * interval)
            # 基于当前种子值生成有连贯性的历史数据
            metrics = self.mock_engine.generate_system_metrics()
            metrics["timestamp"] = timestamp.isoformat()

            if metric:
                metric_value = self._extract_metric(metrics, metric)
                result.append({
                    "timestamp": timestamp.isoformat(),
                    metric: metric_value,
                })
            else:
                result.append(metrics)

        return result

    def _extract_metric(self, metrics: dict, metric_name: str) -> float:
        """
        从指标字典中提取指定指标值

        Args:
            metrics: 完整指标字典
            metric_name: 指标名称

        Returns:
            指标值
        """
        # 支持简单点号路径，如 cpu.percent, memory.percent
        if "." in metric_name:
            parts = metric_name.split(".")
            value = metrics
            for part in parts:
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return 0.0
            return value if isinstance(value, (int, float)) else 0.0

        # 直接匹配常见指标名
        metric_map = {
            "cpu_percent": metrics["cpu"]["percent"],
            "mem_percent": metrics["memory"]["percent"],
            "memory_percent": metrics["memory"]["percent"],
            "disk_busy_percent": metrics["disk"]["busy_percent"],
            "net_down_speed_kb": metrics["network"]["down_speed_kb"],
            "net_up_speed_kb": metrics["network"]["up_speed_kb"],
            "gpu_percent": metrics["gpu"]["percent"],
            "battery_percent": metrics["battery"]["percent"],
            "cpu_temp": metrics["cpu"]["temp"],
            "gpu_temp": metrics["gpu"]["temp"],
        }
        return metric_map.get(metric_name, 0.0)

    def _query_db_history(self, start_time: Optional[str],
                          end_time: Optional[str],
                          metric: Optional[str],
                          limit: int) -> List[dict]:
        """
        从数据库查询历史数据

        Args:
            start_time: 开始时间
            end_time: 结束时间
            metric: 指标名称
            limit: 数据点数量

        Returns:
            历史数据列表
        """
        try:
            db = get_session()
            query = db.query(SystemMetric)

            if start_time:
                query = query.filter(SystemMetric.timestamp >= start_time)
            if end_time:
                query = query.filter(SystemMetric.timestamp <= end_time)

            query = query.order_by(SystemMetric.timestamp.desc()).limit(limit)
            records = query.all()
            db.close()

            result = [r.to_dict() for r in reversed(records)]
            return result
        except Exception:
            return []

    def get_system_info(self) -> dict:
        """
        获取系统基本信息

        Returns:
            系统基本信息字典
        """
        if self.settings.sandbox_mode:
            return self.mock_engine.get_system_info()
        else:
            return self.mock_engine.get_system_info()

    def list_supported_metrics(self) -> List[dict]:
        """
        列出支持的监控指标

        Returns:
            支持的指标列表
        """
        return [
            # CPU 指标
            {"name": "cpu_percent", "category": "cpu", "unit": "%", "description": "整体CPU使用率"},
            {"name": "cpu_percent_per_core", "category": "cpu", "unit": "%", "description": "各核心使用率"},
            {"name": "cpu_load_avg", "category": "cpu", "unit": "", "description": "1/5/15分钟负载均值"},
            {"name": "cpu_freq_current", "category": "cpu", "unit": "MHz", "description": "当前主频"},
            {"name": "cpu_temp", "category": "cpu", "unit": "°C", "description": "CPU温度"},
            {"name": "cpu_fan_speed", "category": "cpu", "unit": "RPM", "description": "风扇转速"},

            # 内存指标
            {"name": "mem_percent", "category": "memory", "unit": "%", "description": "内存使用率"},
            {"name": "mem_used_gb", "category": "memory", "unit": "GB", "description": "已用内存"},
            {"name": "mem_available_gb", "category": "memory", "unit": "GB", "description": "可用内存"},
            {"name": "mem_swap_percent", "category": "memory", "unit": "%", "description": "虚拟内存使用率"},

            # 磁盘指标
            {"name": "disk_read_speed_mb", "category": "disk", "unit": "MB/s", "description": "磁盘读取速度"},
            {"name": "disk_write_speed_mb", "category": "disk", "unit": "MB/s", "description": "磁盘写入速度"},
            {"name": "disk_busy_percent", "category": "disk", "unit": "%", "description": "磁盘繁忙度"},

            # 网络指标
            {"name": "net_down_speed_kb", "category": "network", "unit": "KB/s", "description": "下载速度"},
            {"name": "net_up_speed_kb", "category": "network", "unit": "KB/s", "description": "上传速度"},
            {"name": "net_latency_ms", "category": "network", "unit": "ms", "description": "网络延迟"},
            {"name": "net_packet_loss", "category": "network", "unit": "%", "description": "丢包率"},
            {"name": "net_connection_count", "category": "network", "unit": "个", "description": "网络连接数"},

            # GPU 指标
            {"name": "gpu_percent", "category": "gpu", "unit": "%", "description": "GPU使用率"},
            {"name": "gpu_mem_percent", "category": "gpu", "unit": "%", "description": "显存使用率"},
            {"name": "gpu_temp", "category": "gpu", "unit": "°C", "description": "GPU温度"},
            {"name": "gpu_power_watt", "category": "gpu", "unit": "W", "description": "GPU功耗"},

            # 电池指标
            {"name": "battery_percent", "category": "battery", "unit": "%", "description": "电池电量"},
            {"name": "battery_power_plugged", "category": "battery", "unit": "bool", "description": "是否接通电源"},

            # 系统指标
            {"name": "process_count", "category": "system", "unit": "个", "description": "进程总数"},
            {"name": "uptime_seconds", "category": "system", "unit": "秒", "description": "系统运行时长"},
        ]

    def save_metric_to_db(self, metrics: dict) -> bool:
        """
        将指标数据保存到数据库

        Args:
            metrics: 指标数据字典

        Returns:
            是否保存成功
        """
        try:
            db = get_session()
            metric_record = SystemMetric(
                cpu_percent=metrics["cpu"]["percent"],
                cpu_percent_per_core=metrics["cpu"]["percent_per_core"],
                cpu_load_avg=metrics["cpu"]["load_avg"],
                cpu_freq_current=metrics["cpu"]["freq_current"],
                cpu_freq_min=metrics["cpu"]["freq_min"],
                cpu_freq_max=metrics["cpu"]["freq_max"],
                cpu_temp=metrics["cpu"]["temp"],
                cpu_fan_speed=metrics["cpu"]["fan_speed"],
                mem_total_gb=metrics["memory"]["total_gb"],
                mem_available_gb=metrics["memory"]["available_gb"],
                mem_used_gb=metrics["memory"]["used_gb"],
                mem_percent=metrics["memory"]["percent"],
                mem_swap_total_gb=metrics["memory"]["swap_total_gb"],
                mem_swap_used_gb=metrics["memory"]["swap_used_gb"],
                mem_swap_percent=metrics["memory"]["swap_percent"],
                mem_cache_gb=metrics["memory"]["cache_gb"],
                disk_read_speed_mb=metrics["disk"]["read_speed_mb"],
                disk_write_speed_mb=metrics["disk"]["write_speed_mb"],
                disk_read_count=metrics["disk"]["read_count"],
                disk_write_count=metrics["disk"]["write_count"],
                disk_busy_percent=metrics["disk"]["busy_percent"],
                disk_usage=metrics["disk"]["usage"],
                net_up_speed_kb=metrics["network"]["up_speed_kb"],
                net_down_speed_kb=metrics["network"]["down_speed_kb"],
                net_total_sent_mb=metrics["network"]["total_sent_mb"],
                net_total_recv_mb=metrics["network"]["total_recv_mb"],
                net_connection_count=metrics["network"]["connection_count"],
                net_latency_ms=metrics["network"]["latency_ms"],
                net_packet_loss=metrics["network"]["packet_loss"],
                gpu_count=metrics["gpu"]["count"],
                gpu_name=metrics["gpu"]["name"],
                gpu_percent=metrics["gpu"]["percent"],
                gpu_mem_total_gb=metrics["gpu"]["mem_total_gb"],
                gpu_mem_used_gb=metrics["gpu"]["mem_used_gb"],
                gpu_mem_percent=metrics["gpu"]["mem_percent"],
                gpu_temp=metrics["gpu"]["temp"],
                gpu_power_watt=metrics["gpu"]["power_watt"],
                battery_percent=metrics["battery"]["percent"],
                battery_power_plugged=metrics["battery"]["power_plugged"],
                battery_secs_left=metrics["battery"]["secs_left"],
                battery_health_percent=metrics["battery"]["health_percent"],
                battery_cycle_count=metrics["battery"]["cycle_count"],
                uptime_seconds=metrics["system"]["uptime_seconds"],
                process_count=metrics["system"]["process_count"],
            )
            db.add(metric_record)
            db.commit()
            db.close()
            return True
        except Exception as e:
            print(f"[SystemMonitor] 保存指标数据失败: {e}")
            return False


# 全局单例
_system_monitor: Optional[SystemMonitorService] = None


def get_system_monitor() -> SystemMonitorService:
    """获取系统监控服务单例"""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitorService()
    return _system_monitor


# 兼容直接运行测试
if __name__ == "__main__":
    service = get_system_monitor()

    print("=== 实时状态 ===")
    status = service.get_realtime_status()
    print(f"CPU: {status['cpu']['percent']}%, 内存: {status['memory']['percent']}%")

    print("\n=== 历史数据（最近10个点） ===")
    history = service.get_history(limit=10, metric="cpu_percent")
    for item in history[-5:]:
        print(f"  {item['timestamp']}: CPU {item.get('cpu_percent', 'N/A')}%")

    print("\n=== 支持的指标数量 ===")
    metrics = service.list_supported_metrics()
    print(f"共 {len(metrics)} 个指标")
