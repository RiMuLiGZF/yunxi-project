"""
M10 系统卫士 - Prometheus 指标导出器

暴露云汐系统指标为 Prometheus 格式，支持 /metrics 端点。
如果 prometheus_client 不可用，自动降级为 JSON 模拟指标。
"""

from __future__ import annotations

import time
from typing import Any

# ---------------------------------------------------------------------------
# 可选依赖：prometheus_client
# ---------------------------------------------------------------------------
try:
    from prometheus_client import (
        Gauge, Counter, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

# ---------------------------------------------------------------------------
# 指标定义（仅在 prometheus_client 可用时创建）
# ---------------------------------------------------------------------------
if _PROMETHEUS_AVAILABLE:
    _registry = CollectorRegistry()

    yunxi_cpu_usage_percent = Gauge(
        "yunxi_cpu_usage_percent",
        "Current CPU usage percentage",
        registry=_registry,
    )
    yunxi_memory_usage_percent = Gauge(
        "yunxi_memory_usage_percent",
        "Current memory usage percentage",
        registry=_registry,
    )
    yunxi_disk_usage_percent = Gauge(
        "yunxi_disk_usage_percent",
        "Current disk usage percentage",
        registry=_registry,
    )
    yunxi_gpu_usage_percent = Gauge(
        "yunxi_gpu_usage_percent",
        "Current GPU usage percentage (0 if no GPU)",
        registry=_registry,
    )
    yunxi_temperature_celsius = Gauge(
        "yunxi_temperature_celsius",
        "Current CPU temperature in Celsius",
        registry=_registry,
    )
    yunxi_process_count = Gauge(
        "yunxi_process_count",
        "Current total process count",
        registry=_registry,
    )
    yunxi_alert_count_total = Counter(
        "yunxi_alert_count_total",
        "Total number of guard alerts triggered",
        registry=_registry,
    )
else:
    _registry = None
    yunxi_cpu_usage_percent = None
    yunxi_memory_usage_percent = None
    yunxi_disk_usage_percent = None
    yunxi_gpu_usage_percent = None
    yunxi_temperature_celsius = None
    yunxi_process_count = None
    yunxi_alert_count_total = None

# ---------------------------------------------------------------------------
# 内部状态：用于无 prometheus_client 时的 JSON 降级，以及告警计数差值追踪
# ---------------------------------------------------------------------------
_last_alert_count = 0
_last_collect_time = 0.0


def _collect_metrics() -> dict[str, float | int]:
    """从 M10 各组件采集原始指标数据.

    Returns:
        指标名称 -> 数值 的字典
    """
    from .system_monitor import get_system_monitor
    from .process_manager import get_process_manager
    from .guard_engine import get_guard_engine

    sm = get_system_monitor()
    pm = get_process_manager()
    ge = get_guard_engine()

    latest = sm.get_latest()
    proc_stats = pm.get_process_stats()
    guard_status = ge.get_status_summary()

    return {
        "cpu_usage_percent": latest.cpu.usage_percent,
        "memory_usage_percent": latest.memory.usage_percent,
        "disk_usage_percent": latest.disk.usage_percent,
        "gpu_usage_percent": latest.gpu.usage_percent,
        "temperature_celsius": latest.temperature.highest_temp_celsius,
        "process_count": proc_stats.get("total_processes", 0),
        "alert_count_total": guard_status.get("total_alerts", 0),
    }


def _update_prometheus_metrics(data: dict[str, float | int]) -> None:
    """将采集的数据更新到 Prometheus 指标对象.

    Args:
        data: _collect_metrics 返回的字典
    """
    global _last_alert_count

    if not _PROMETHEUS_AVAILABLE:
        return

    yunxi_cpu_usage_percent.set(data["cpu_usage_percent"])
    yunxi_memory_usage_percent.set(data["memory_usage_percent"])
    yunxi_disk_usage_percent.set(data["disk_usage_percent"])
    yunxi_gpu_usage_percent.set(data["gpu_usage_percent"])
    yunxi_temperature_celsius.set(data["temperature_celsius"])
    yunxi_process_count.set(data["process_count"])

    # Counter 只增不减：计算差值并 inc
    current_alerts = int(data["alert_count_total"])
    delta = current_alerts - _last_alert_count
    if delta > 0:
        yunxi_alert_count_total.inc(delta)
    _last_alert_count = current_alerts


def generate_prometheus_metrics() -> tuple[str, str]:
    """生成 Prometheus 格式的指标文本.

    Returns:
        (content_type, body) 元组
    """
    data = _collect_metrics()
    _update_prometheus_metrics(data)

    if _PROMETHEUS_AVAILABLE:
        return CONTENT_TYPE_LATEST, generate_latest(_registry).decode("utf-8")

    # 降级：手动构造 Prometheus 文本格式
    body = (
        f"# HELP yunxi_cpu_usage_percent Current CPU usage percentage\n"
        f"# TYPE yunxi_cpu_usage_percent gauge\n"
        f"yunxi_cpu_usage_percent {data['cpu_usage_percent']}\n"
        f"# HELP yunxi_memory_usage_percent Current memory usage percentage\n"
        f"# TYPE yunxi_memory_usage_percent gauge\n"
        f"yunxi_memory_usage_percent {data['memory_usage_percent']}\n"
        f"# HELP yunxi_disk_usage_percent Current disk usage percentage\n"
        f"# TYPE yunxi_disk_usage_percent gauge\n"
        f"yunxi_disk_usage_percent {data['disk_usage_percent']}\n"
        f"# HELP yunxi_gpu_usage_percent Current GPU usage percentage (0 if no GPU)\n"
        f"# TYPE yunxi_gpu_usage_percent gauge\n"
        f"yunxi_gpu_usage_percent {data['gpu_usage_percent']}\n"
        f"# HELP yunxi_temperature_celsius Current CPU temperature in Celsius\n"
        f"# TYPE yunxi_temperature_celsius gauge\n"
        f"yunxi_temperature_celsius {data['temperature_celsius']}\n"
        f"# HELP yunxi_process_count Current total process count\n"
        f"# TYPE yunxi_process_count gauge\n"
        f"yunxi_process_count {data['process_count']}\n"
        f"# HELP yunxi_alert_count_total Total number of guard alerts triggered\n"
        f"# TYPE yunxi_alert_count_total counter\n"
        f"yunxi_alert_count_total {data['alert_count_total']}\n"
    )
    return "text/plain; version=0.0.4; charset=utf-8", body


def generate_metrics_json() -> dict[str, Any]:
    """生成 JSON 格式的模拟指标（降级方案）.

    Returns:
        包含所有指标的字典
    """
    data = _collect_metrics()
    return {
        "metrics": {
            "yunxi_cpu_usage_percent": {"value": data["cpu_usage_percent"], "type": "gauge"},
            "yunxi_memory_usage_percent": {"value": data["memory_usage_percent"], "type": "gauge"},
            "yunxi_disk_usage_percent": {"value": data["disk_usage_percent"], "type": "gauge"},
            "yunxi_gpu_usage_percent": {"value": data["gpu_usage_percent"], "type": "gauge"},
            "yunxi_temperature_celsius": {"value": data["temperature_celsius"], "type": "gauge"},
            "yunxi_process_count": {"value": data["process_count"], "type": "gauge"},
            "yunxi_alert_count_total": {"value": data["alert_count_total"], "type": "counter"},
        },
        "prometheus_available": _PROMETHEUS_AVAILABLE,
        "timestamp": time.time(),
    }


def is_prometheus_available() -> bool:
    """检查 prometheus_client 是否可用.

    Returns:
        True 表示可用
    """
    return _PROMETHEUS_AVAILABLE
