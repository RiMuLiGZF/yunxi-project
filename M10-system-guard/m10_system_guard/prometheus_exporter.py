"""
M10 系统卫士 - Prometheus 指标导出器 (增强版)

暴露云汐系统指标为 Prometheus 格式，支持 /metrics 端点。
提供完整的指标体系：系统指标、GPU 指标、潮汐引擎指标、防护引擎指标、进程指标。
如果 prometheus_client 不可用，自动降级为 JSON 模拟指标。

特性：
- 指标注册中心，支持动态注册新指标
- 定时采集（默认 15 秒），缓存结果
- 多维度标签（hostname、gpu_id、module_name、level 等）
- /health 端点返回 exporter 健康状态
- 可通过环境变量或配置启用/禁用
- 与 M8 监控体系打通，支持主动上报
"""

from __future__ import annotations

import os
import time
import socket
import threading
from typing import Any, Optional, Dict, List, Callable
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 可选依赖：prometheus_client
# ---------------------------------------------------------------------------
try:
    from prometheus_client import (
        Gauge, Counter, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
        Histogram, Summary,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
DEFAULT_COLLECT_INTERVAL = 15  # 默认采集间隔（秒）
DEFAULT_M8_REPORT_INTERVAL = 60  # 默认 M8 上报间隔（秒）
ENV_PROMETHEUS_ENABLED = "M10_PROMETHEUS_ENABLED"
ENV_COLLECT_INTERVAL = "M10_PROMETHEUS_COLLECT_INTERVAL"
ENV_M8_REPORT_ENABLED = "M10_M8_REPORT_ENABLED"
ENV_M8_REPORT_INTERVAL = "M10_M8_REPORT_INTERVAL"
ENV_M8_BASE_URL = "M10_M8_BASE_URL"
ENV_M8_REPORT_TOKEN = "M10_M8_REPORT_TOKEN"


# ---------------------------------------------------------------------------
# 指标元数据定义
# ---------------------------------------------------------------------------
@dataclass
class MetricInfo:
    """指标元信息."""
    name: str
    metric_type: str  # gauge / counter / histogram / summary
    help_text: str
    labels: List[str] = field(default_factory=list)
    category: str = "system"  # system / gpu / tide / guard / process


# ---------------------------------------------------------------------------
# 全局指标注册表
# ---------------------------------------------------------------------------
class MetricRegistry:
    """
    指标注册中心

    管理所有 Prometheus 指标的注册、查询和更新。
    支持动态注册新指标，自动处理 prometheus_client 不可用的降级。
    """

    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._metric_infos: Dict[str, MetricInfo] = {}
        self._lock = threading.Lock()

        if _PROMETHEUS_AVAILABLE:
            self._registry = CollectorRegistry()
        else:
            self._registry = None

        # 用于降级模式的模拟数据存储
        self._fallback_values: Dict[str, Dict] = {}

    @property
    def prometheus_available(self) -> bool:
        return _PROMETHEUS_AVAILABLE

    @property
    def registry(self) -> Optional[CollectorRegistry]:
        return self._registry

    def register_gauge(self, name: str, help_text: str,
                       labels: Optional[List[str]] = None,
                       category: str = "system") -> Optional[Gauge]:
        """注册一个 Gauge 指标.

        Args:
            name: 指标名称
            help_text: 帮助文本
            labels: 标签列表
            category: 指标类别

        Returns:
            Gauge 对象（prometheus_client 可用时），否则 None
        """
        labels = labels or []
        info = MetricInfo(name=name, metric_type="gauge", help_text=help_text,
                          labels=labels, category=category)

        with self._lock:
            self._metric_infos[name] = info

            if _PROMETHEUS_AVAILABLE:
                if labels:
                    gauge = Gauge(name, help_text, labels, registry=self._registry)
                else:
                    gauge = Gauge(name, help_text, registry=self._registry)
                self._metrics[name] = gauge
                return gauge
            else:
                # 降级模式：初始化空值存储
                self._fallback_values[name] = {
                    "type": "gauge",
                    "help": help_text,
                    "values": {},  # label_tuple -> value
                    "labels": labels,
                }
                return None

    def register_counter(self, name: str, help_text: str,
                         labels: Optional[List[str]] = None,
                         category: str = "system") -> Optional[Counter]:
        """注册一个 Counter 指标."""
        labels = labels or []
        info = MetricInfo(name=name, metric_type="counter", help_text=help_text,
                          labels=labels, category=category)

        with self._lock:
            self._metric_infos[name] = info

            if _PROMETHEUS_AVAILABLE:
                if labels:
                    counter = Counter(name, help_text, labels, registry=self._registry)
                else:
                    counter = Counter(name, help_text, registry=self._registry)
                self._metrics[name] = counter
                return counter
            else:
                self._fallback_values[name] = {
                    "type": "counter",
                    "help": help_text,
                    "values": {},
                    "labels": labels,
                }
                return None

    def get_metric(self, name: str) -> Optional[Any]:
        """获取已注册的指标对象."""
        return self._metrics.get(name)

    def get_metric_info(self, name: str) -> Optional[MetricInfo]:
        """获取指标元信息."""
        return self._metric_infos.get(name)

    def list_metrics(self, category: Optional[str] = None) -> List[MetricInfo]:
        """列出所有指标（可按类别过滤）."""
        if category:
            return [m for m in self._metric_infos.values() if m.category == category]
        return list(self._metric_infos.values())

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """设置 Gauge 指标值.

        Args:
            name: 指标名称
            value: 指标值
            labels: 标签字典
        """
        labels = labels or {}
        metric = self._metrics.get(name)

        if _PROMETHEUS_AVAILABLE and metric is not None:
            if labels:
                metric.labels(**labels).set(value)
            else:
                metric.set(value)
        else:
            # 降级模式
            if name in self._fallback_values:
                label_key = tuple(sorted(labels.items())) if labels else ()
                self._fallback_values[name]["values"][label_key] = value

    def inc_counter(self, name: str, amount: float = 1,
                    labels: Optional[Dict[str, str]] = None) -> None:
        """增加 Counter 指标值."""
        labels = labels or {}
        metric = self._metrics.get(name)

        if _PROMETHEUS_AVAILABLE and metric is not None:
            if labels:
                metric.labels(**labels).inc(amount)
            else:
                metric.inc(amount)
        else:
            # 降级模式
            if name in self._fallback_values:
                label_key = tuple(sorted(labels.items())) if labels else ()
                current = self._fallback_values[name]["values"].get(label_key, 0)
                self._fallback_values[name]["values"][label_key] = current + amount

    def generate_text(self) -> str:
        """生成 Prometheus 文本格式的指标数据."""
        if _PROMETHEUS_AVAILABLE and self._registry is not None:
            return generate_latest(self._registry).decode("utf-8")
        else:
            return self._generate_fallback_text()

    def _generate_fallback_text(self) -> str:
        """生成降级模式下的 Prometheus 文本格式."""
        lines = []
        for name, info in self._fallback_values.items():
            lines.append(f"# HELP {name} {info['help']}")
            lines.append(f"# TYPE {name} {info['type']}")
            for label_key, value in info["values"].items():
                if label_key:
                    label_str = ",".join(f'{k}="{v}"' for k, v in label_key)
                    lines.append(f"{name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"

    def to_dict(self) -> Dict[str, Any]:
        """将所有指标转为字典格式（用于 JSON 输出）."""
        result = {}
        for name, info in self._metric_infos.items():
            metric_data = {
                "type": info.metric_type,
                "help": info.help_text,
                "labels": info.labels,
                "category": info.category,
                "values": {},
            }

            if _PROMETHEUS_AVAILABLE and name in self._metrics:
                # 注意：prometheus_client 的 Gauge/Counter 不直接暴露所有标签值
                # 这里通过 samples 方式获取
                metric = self._metrics[name]
                try:
                    for sample in metric.collect():
                        for s in sample.samples:
                            labels_key = ",".join(f"{k}={v}" for k, v in s.labels.items())
                            if not labels_key:
                                labels_key = "_default"
                            metric_data["values"][labels_key] = s.value
                except Exception:
                    pass
            else:
                fb = self._fallback_values.get(name, {})
                for label_key, value in fb.get("values", {}).items():
                    if label_key:
                        labels_key = ",".join(f"{k}={v}" for k, v in label_key)
                    else:
                        labels_key = "_default"
                    metric_data["values"][labels_key] = value

            result[name] = metric_data

        return result


# ---------------------------------------------------------------------------
# Prometheus Exporter 主类
# ---------------------------------------------------------------------------
class PrometheusExporter:
    """
    M10 Prometheus 指标导出器

    负责：
    - 注册所有系统指标
    - 定时采集并更新指标值
    - 提供 HTTP 端点所需的指标数据
    - 管理 M8 监控上报
    """

    def __init__(self):
        self._enabled = self._check_enabled()
        self._collect_interval = self._get_collect_interval()
        self._hostname = socket.gethostname()

        # 指标注册中心
        self.registry = MetricRegistry()

        # 运行状态
        self._running = False
        self._collect_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 缓存的采集结果
        self._last_collect_time: float = 0.0
        self._cached_metrics: Dict[str, Any] = {}

        # M8 上报器（延迟初始化）
        self._m8_reporter: Optional["M8MetricsReporter"] = None

        # 指标对象引用（便于快速访问）
        self._metrics_ref: Dict[str, Any] = {}

        # 初始化指标（如果启用）
        if self._enabled:
            self._register_all_metrics()

    # ============================================================
    # 配置相关
    # ============================================================

    def _check_enabled(self) -> bool:
        """检查 Prometheus 功能是否启用."""
        env_val = os.environ.get(ENV_PROMETHEUS_ENABLED, "true").lower()
        return env_val in ("true", "1", "yes", "enabled")

    def _get_collect_interval(self) -> int:
        """获取采集间隔（秒）."""
        try:
            return int(os.environ.get(ENV_COLLECT_INTERVAL, str(DEFAULT_COLLECT_INTERVAL)))
        except (ValueError, TypeError):
            return DEFAULT_COLLECT_INTERVAL

    @property
    def enabled(self) -> bool:
        """是否启用."""
        return self._enabled

    @property
    def collect_interval(self) -> int:
        """采集间隔."""
        return self._collect_interval

    @property
    def hostname(self) -> str:
        """主机名标签值."""
        return self._hostname

    @property
    def running(self) -> bool:
        """采集器是否在运行."""
        return self._running

    # ============================================================
    # 指标注册
    # ============================================================

    def _register_all_metrics(self) -> None:
        """注册所有指标类别."""
        self._register_system_metrics()
        self._register_gpu_metrics()
        self._register_tide_metrics()
        self._register_guard_metrics()
        self._register_process_metrics()
        self._register_exporter_metrics()

    def _register_system_metrics(self) -> None:
        """注册系统指标."""
        common_labels = ["hostname"]

        self._metrics_ref["system_cpu_percent"] = self.registry.register_gauge(
            "system_cpu_percent", "CPU 使用率 (%)", common_labels, "system"
        )
        self._metrics_ref["system_memory_percent"] = self.registry.register_gauge(
            "system_memory_percent", "内存使用率 (%)", common_labels, "system"
        )
        self._metrics_ref["system_memory_used_bytes"] = self.registry.register_gauge(
            "system_memory_used_bytes", "已用内存字节数", common_labels, "system"
        )
        self._metrics_ref["system_memory_total_bytes"] = self.registry.register_gauge(
            "system_memory_total_bytes", "总内存字节数", common_labels, "system"
        )
        self._metrics_ref["system_disk_percent"] = self.registry.register_gauge(
            "system_disk_percent", "磁盘使用率 (%)", common_labels, "system"
        )
        self._metrics_ref["system_disk_used_bytes"] = self.registry.register_gauge(
            "system_disk_used_bytes", "已用磁盘字节数", common_labels, "system"
        )
        self._metrics_ref["system_network_io_sent_bytes"] = self.registry.register_gauge(
            "system_network_io_sent_bytes", "网络发送字节数", common_labels, "system"
        )
        self._metrics_ref["system_network_io_recv_bytes"] = self.registry.register_gauge(
            "system_network_io_recv_bytes", "网络接收字节数", common_labels, "system"
        )
        self._metrics_ref["system_process_count"] = self.registry.register_gauge(
            "system_process_count", "系统进程总数", common_labels, "system"
        )

    def _register_gpu_metrics(self) -> None:
        """注册 GPU 指标（多 GPU 使用 gpu_id 标签区分）."""
        gpu_labels = ["hostname", "gpu_id", "gpu_name"]

        self._metrics_ref["gpu_utilization_percent"] = self.registry.register_gauge(
            "gpu_utilization_percent", "GPU 利用率 (%)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_memory_percent"] = self.registry.register_gauge(
            "gpu_memory_percent", "GPU 显存使用率 (%)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_memory_used_mb"] = self.registry.register_gauge(
            "gpu_memory_used_mb", "GPU 显存使用量 (MB)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_memory_total_mb"] = self.registry.register_gauge(
            "gpu_memory_total_mb", "GPU 显存总量 (MB)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_temperature_celsius"] = self.registry.register_gauge(
            "gpu_temperature_celsius", "GPU 温度 (°C)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_power_watts"] = self.registry.register_gauge(
            "gpu_power_watts", "GPU 功耗 (W)", gpu_labels, "gpu"
        )
        self._metrics_ref["gpu_count"] = self.registry.register_gauge(
            "gpu_count", "GPU 设备数量", ["hostname"], "gpu"
        )

    def _register_tide_metrics(self) -> None:
        """注册潮汐引擎指标."""
        tide_labels = ["hostname", "module_name"]

        self._metrics_ref["tide_active_tasks"] = self.registry.register_gauge(
            "tide_active_tasks", "潮汐引擎活跃任务数", tide_labels, "tide"
        )
        self._metrics_ref["tide_completed_total"] = self.registry.register_counter(
            "tide_completed_total", "潮汐引擎已完成任务总数", tide_labels, "tide"
        )
        self._metrics_ref["tide_failed_total"] = self.registry.register_counter(
            "tide_failed_total", "潮汐引擎失败任务总数", tide_labels, "tide"
        )
        self._metrics_ref["tide_gpu_allocated_mb"] = self.registry.register_gauge(
            "tide_gpu_allocated_mb", "潮汐引擎已分配显存 (MB)",
            ["hostname", "gpu_id"], "tide"
        )
        self._metrics_ref["tide_scheduler_runs_total"] = self.registry.register_counter(
            "tide_scheduler_runs_total", "潮汐调度器运行次数", tide_labels, "tide"
        )
        self._metrics_ref["tide_current_phase"] = self.registry.register_gauge(
            "tide_current_phase", "潮汐当前阶段 (0=涨潮,1=平潮,2=退潮,3=枯潮)",
            tide_labels, "tide"
        )

    def _register_guard_metrics(self) -> None:
        """注册防护引擎指标."""
        guard_labels = ["hostname", "level"]

        self._metrics_ref["guard_alerts_total"] = self.registry.register_counter(
            "guard_alerts_total", "防护引擎告警总数", guard_labels, "guard"
        )
        self._metrics_ref["guard_active_alerts"] = self.registry.register_gauge(
            "guard_active_alerts", "防护引擎当前活跃告警数", guard_labels, "guard"
        )
        self._metrics_ref["guard_blocked_total"] = self.registry.register_counter(
            "guard_blocked_total", "防护引擎拦截次数", ["hostname", "metric_type"], "guard"
        )
        self._metrics_ref["guard_circuit_breaker_state"] = self.registry.register_gauge(
            "guard_circuit_breaker_state", "熔断器状态 (0=关闭,1=半开,2=打开)",
            ["hostname"], "guard"
        )
        self._metrics_ref["guard_current_level"] = self.registry.register_gauge(
            "guard_current_level",
            "当前防护级别 (0=info,1=warning,2=critical,3=emergency)",
            ["hostname", "metric_type"], "guard"
        )
        self._metrics_ref["guard_throttling_active"] = self.registry.register_gauge(
            "guard_throttling_active", "限流是否激活 (0=否,1=是)",
            ["hostname"], "guard"
        )

    def _register_process_metrics(self) -> None:
        """注册进程监控指标."""
        proc_labels = ["hostname"]

        self._metrics_ref["process_count"] = self.registry.register_gauge(
            "process_count", "受监控进程总数", proc_labels, "process"
        )
        self._metrics_ref["process_yunxi_count"] = self.registry.register_gauge(
            "process_yunxi_count", "云汐相关进程数", proc_labels, "process"
        )
        self._metrics_ref["process_cpu_percent"] = self.registry.register_gauge(
            "process_cpu_percent", "受监控进程 CPU 使用率 (%)",
            ["hostname", "process_name"], "process"
        )
        self._metrics_ref["process_memory_mb"] = self.registry.register_gauge(
            "process_memory_mb", "受监控进程内存使用 (MB)",
            ["hostname", "process_name"], "process"
        )

    def _register_exporter_metrics(self) -> None:
        """注册 Exporter 自身的指标."""
        self._metrics_ref["exporter_up"] = self.registry.register_gauge(
            "exporter_up", "Exporter 是否运行 (0=否,1=是)",
            ["hostname", "module"], "exporter"
        )
        self._metrics_ref["exporter_collect_duration_seconds"] = self.registry.register_gauge(
            "exporter_collect_duration_seconds", "采集耗时 (秒)",
            ["hostname", "module"], "exporter"
        )
        self._metrics_ref["exporter_collect_total"] = self.registry.register_counter(
            "exporter_collect_total", "采集总次数",
            ["hostname", "module"], "exporter"
        )

    # ============================================================
    # 数据采集
    # ============================================================

    def collect_metrics(self) -> Dict[str, Any]:
        """执行一次完整的指标采集.

        Returns:
            采集结果字典
        """
        start_time = time.time()

        result: Dict[str, Any] = {
            "timestamp": time.time(),
            "hostname": self._hostname,
        }

        try:
            # 系统指标
            result["system"] = self._collect_system_metrics()

            # GPU 指标
            result["gpu"] = self._collect_gpu_metrics()

            # 潮汐引擎指标
            result["tide"] = self._collect_tide_metrics()

            # 防护引擎指标
            result["guard"] = self._collect_guard_metrics()

            # 进程指标
            result["process"] = self._collect_process_metrics()

        except Exception as e:
            result["error"] = str(e)

        # 更新 exporter 自身指标
        duration = time.time() - start_time
        self.registry.set_gauge("exporter_collect_duration_seconds", duration,
                                {"hostname": self._hostname, "module": "m10"})
        self.registry.inc_counter("exporter_collect_total", 1,
                                  {"hostname": self._hostname, "module": "m10"})

        self._last_collect_time = time.time()
        self._cached_metrics = result

        return result

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """采集系统指标."""
        try:
            from .system_monitor import get_system_monitor
            sm = get_system_monitor()
            latest = sm.get_latest()

            cpu_percent = latest.cpu.usage_percent
            mem_percent = latest.memory.usage_percent
            mem_used_bytes = latest.memory.used_mb * 1024 * 1024
            mem_total_bytes = latest.memory.total_mb * 1024 * 1024
            disk_percent = latest.disk.usage_percent
            disk_used_bytes = latest.disk.used_gb * (1024 ** 3)
            net_sent_bytes = latest.network.bytes_sent_mb * 1024 * 1024
            net_recv_bytes = latest.network.bytes_recv_mb * 1024 * 1024

            # 更新指标
            base_labels = {"hostname": self._hostname}
            self.registry.set_gauge("system_cpu_percent", cpu_percent, base_labels)
            self.registry.set_gauge("system_memory_percent", mem_percent, base_labels)
            self.registry.set_gauge("system_memory_used_bytes", mem_used_bytes, base_labels)
            self.registry.set_gauge("system_memory_total_bytes", mem_total_bytes, base_labels)
            self.registry.set_gauge("system_disk_percent", disk_percent, base_labels)
            self.registry.set_gauge("system_disk_used_bytes", disk_used_bytes, base_labels)
            self.registry.set_gauge("system_network_io_sent_bytes", net_sent_bytes, base_labels)
            self.registry.set_gauge("system_network_io_recv_bytes", net_recv_bytes, base_labels)

            # 进程总数需要从 process_manager 获取
            try:
                from .process_manager import get_process_manager
                pm = get_process_manager()
                proc_stats = pm.get_process_stats()
                proc_count = proc_stats.get("total_processes", 0)
            except Exception:
                proc_count = 0

            self.registry.set_gauge("system_process_count", proc_count, base_labels)

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": mem_percent,
                "memory_used_bytes": mem_used_bytes,
                "memory_total_bytes": mem_total_bytes,
                "disk_percent": disk_percent,
                "disk_used_bytes": disk_used_bytes,
                "network_sent_bytes": net_sent_bytes,
                "network_recv_bytes": net_recv_bytes,
                "process_count": proc_count,
            }
        except Exception as e:
            return {"error": str(e)}

    def _collect_gpu_metrics(self) -> Dict[str, Any]:
        """采集 GPU 指标（多 GPU）."""
        try:
            from .system_monitor import get_system_monitor
            sm = get_system_monitor()
            latest = sm.get_latest()
            gpu = latest.gpu

            gpu_count = gpu.count if gpu else 0
            self.registry.set_gauge("gpu_count", gpu_count, {"hostname": self._hostname})

            devices_data = []

            if gpu and gpu.devices:
                for dev in gpu.devices:
                    gpu_id = str(getattr(dev, "gpu_id", 0))
                    gpu_name = getattr(dev, "name", f"GPU{gpu_id}")

                    labels = {
                        "hostname": self._hostname,
                        "gpu_id": gpu_id,
                        "gpu_name": gpu_name,
                    }

                    util = getattr(dev, "usage_percent", 0.0)
                    mem_percent = getattr(dev, "memory_percent", 0.0)
                    mem_used = getattr(dev, "memory_used_mb", 0.0)
                    mem_total = getattr(dev, "memory_total_mb", 0.0)
                    temp = getattr(dev, "temperature_celsius", 0.0)
                    power = getattr(dev, "power_watt", 0.0)

                    self.registry.set_gauge("gpu_utilization_percent", util, labels)
                    self.registry.set_gauge("gpu_memory_percent", mem_percent, labels)
                    self.registry.set_gauge("gpu_memory_used_mb", mem_used, labels)
                    self.registry.set_gauge("gpu_memory_total_mb", mem_total, labels)
                    self.registry.set_gauge("gpu_temperature_celsius", temp, labels)
                    self.registry.set_gauge("gpu_power_watts", power, labels)

                    devices_data.append({
                        "gpu_id": gpu_id,
                        "gpu_name": gpu_name,
                        "utilization": util,
                        "memory_percent": mem_percent,
                        "memory_used_mb": mem_used,
                        "memory_total_mb": mem_total,
                        "temperature": temp,
                        "power_watts": power,
                    })
            elif gpu and gpu_count > 0:
                # 只有汇总数据，没有设备详情
                labels = {
                    "hostname": self._hostname,
                    "gpu_id": "0",
                    "gpu_name": "GPU0",
                }
                self.registry.set_gauge("gpu_utilization_percent",
                                        gpu.usage_percent, labels)
                self.registry.set_gauge("gpu_memory_percent",
                                        gpu.memory_percent, labels)
                self.registry.set_gauge("gpu_memory_used_mb",
                                        gpu.memory_used_mb, labels)
                self.registry.set_gauge("gpu_memory_total_mb",
                                        gpu.memory_total_mb, labels)
                self.registry.set_gauge("gpu_temperature_celsius",
                                        gpu.temperature_celsius, labels)
                self.registry.set_gauge("gpu_power_watts",
                                        gpu.power_watt, labels)
                devices_data.append({
                    "gpu_id": "0",
                    "gpu_name": "GPU0",
                    "utilization": gpu.usage_percent,
                    "memory_percent": gpu.memory_percent,
                    "memory_used_mb": gpu.memory_used_mb,
                    "memory_total_mb": gpu.memory_total_mb,
                    "temperature": gpu.temperature_celsius,
                    "power_watts": gpu.power_watt,
                })

            return {
                "gpu_count": gpu_count,
                "devices": devices_data,
            }
        except Exception as e:
            return {"error": str(e), "gpu_count": 0, "devices": []}

    def _collect_tide_metrics(self) -> Dict[str, Any]:
        """采集潮汐引擎指标."""
        try:
            from .tide_engine.tide_engine import get_tide_engine
            tide = get_tide_engine()

            if not tide or not tide.initialized:
                return {"active": False}

            stats = tide.scheduler.get_stats()
            tide_stats = stats.get("tide", {})
            gpu_stats = stats.get("gpu_orchestrator", {})

            base_labels = {"hostname": self._hostname, "module_name": "m10-tide"}

            # 活跃任务数
            active_tasks = tide_stats.get("current_running", 0)
            self.registry.set_gauge("tide_active_tasks", active_tasks, base_labels)

            # 已完成任务（Counter 用差值方式更新）
            completed = tide_stats.get("total_missions_completed", 0)
            failed = tide_stats.get("total_missions_failed", 0)
            self._update_counter_from_total("tide_completed_total", completed, base_labels)
            self._update_counter_from_total("tide_failed_total", failed, base_labels)

            # 调度次数
            scheduler_runs = tide_stats.get("phase_transition_count", 0)
            self._update_counter_from_total("tide_scheduler_runs_total",
                                            scheduler_runs, base_labels)

            # 当前潮汐阶段
            phase_map = {"flood": 0, "slack": 1, "ebb": 2, "low": 3}
            current_phase = stats.get("current_phase", "slack")
            phase_value = phase_map.get(current_phase, 1)
            self.registry.set_gauge("tide_current_phase", phase_value, base_labels)

            # GPU 已分配显存
            gpu_devices = gpu_stats.get("devices", {})
            for gpu_id_str, dev_info in gpu_devices.items():
                allocated = dev_info.get("used_mb", 0.0)
                self.registry.set_gauge("tide_gpu_allocated_mb", allocated, {
                    "hostname": self._hostname,
                    "gpu_id": str(gpu_id_str),
                })

            return {
                "active": True,
                "active_tasks": active_tasks,
                "completed_total": completed,
                "failed_total": failed,
                "scheduler_runs_total": scheduler_runs,
                "current_phase": current_phase,
            }
        except Exception as e:
            return {"error": str(e), "active": False}

    # Counter 跟踪：记录上次的 total 值，用于计算增量
    _counter_totals: Dict[str, float] = {}

    def _update_counter_from_total(self, metric_name: str, total_value: float,
                                    labels: Dict[str, str]) -> None:
        """根据 total 值更新 Counter（只增不减）.

        Args:
            metric_name: 指标名称
            total_value: 当前总量
            labels: 标签
        """
        label_key = metric_name + ":" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        prev = self._counter_totals.get(label_key, 0)
        delta = total_value - prev
        if delta > 0:
            self.registry.inc_counter(metric_name, delta, labels)
        self._counter_totals[label_key] = max(prev, total_value)

    def _collect_guard_metrics(self) -> Dict[str, Any]:
        """采集防护引擎指标."""
        try:
            from .guard_engine import get_guard_engine
            from .models import GuardLevel
            ge = get_guard_engine()
            status = ge.get_status_summary()

            base_labels = {"hostname": self._hostname}

            # 告警总数（按级别）
            alerts = ge.get_alerts(limit=500)
            level_counts = {"info": 0, "warning": 0, "critical": 0, "emergency": 0}
            active_counts = {"info": 0, "warning": 0, "critical": 0, "emergency": 0}

            for alert in alerts:
                level = getattr(alert, "level", GuardLevel.INFO)
                level_str = level.value if hasattr(level, "value") else str(level)
                if level_str not in level_counts:
                    level_str = "info"
                level_counts[level_str] += 1
                if not getattr(alert, "acknowledged", False):
                    active_counts[level_str] += 1

            for level_str in ["info", "warning", "critical", "emergency"]:
                labels = {"hostname": self._hostname, "level": level_str}
                self._update_counter_from_total("guard_alerts_total",
                                                level_counts[level_str], labels)
                self.registry.set_gauge("guard_active_alerts",
                                        active_counts[level_str], labels)

            # 当前防护级别
            metric_levels = status.get("metric_levels", {})
            level_value_map = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}
            for metric_type, level_str in metric_levels.items():
                level_val = level_value_map.get(level_str, 0)
                self.registry.set_gauge("guard_current_level", level_val, {
                    "hostname": self._hostname,
                    "metric_type": metric_type,
                })

            # 限流状态
            throttling = 1 if status.get("throttling_active", False) else 0
            self.registry.set_gauge("guard_throttling_active", throttling, base_labels)

            # 熔断器状态（M10 中用限流状态近似）
            overall_level = status.get("overall_level", "info")
            cb_state = 2 if overall_level == "emergency" else (1 if overall_level == "critical" else 0)
            self.registry.set_gauge("guard_circuit_breaker_state", cb_state, base_labels)

            # 拦截次数（用告警总数近似）
            total_blocked = sum(level_counts.values())
            self._update_counter_from_total("guard_blocked_total", total_blocked, {
                "hostname": self._hostname,
                "metric_type": "overall",
            })

            return {
                "total_alerts": status.get("total_alerts", 0),
                "active_alerts": sum(active_counts.values()),
                "overall_level": overall_level,
                "throttling_active": status.get("throttling_active", False),
                "level_counts": level_counts,
                "active_counts": active_counts,
            }
        except Exception as e:
            return {"error": str(e)}

    def _collect_process_metrics(self) -> Dict[str, Any]:
        """采集进程监控指标."""
        try:
            from .process_manager import get_process_manager
            pm = get_process_manager()
            stats = pm.get_process_stats()

            base_labels = {"hostname": self._hostname}

            total_count = stats.get("total_processes", 0)
            yunxi_count = stats.get("yunxi_processes", 0)

            self.registry.set_gauge("process_count", total_count, base_labels)
            self.registry.set_gauge("process_yunxi_count", yunxi_count, base_labels)

            # Top 进程的 CPU/内存
            top_procs = stats.get("top_processes", [])
            if not top_procs:
                # 尝试获取进程列表
                try:
                    procs = pm.get_all_processes()
                    # 按内存排序取前 5
                    sorted_procs = sorted(
                        procs,
                        key=lambda p: getattr(p, "memory_mb", 0),
                        reverse=True
                    )[:5]
                    for proc in sorted_procs:
                        name = getattr(proc, "name", "unknown")[:50]
                        cpu = getattr(proc, "cpu_percent", 0.0)
                        mem = getattr(proc, "memory_mb", 0.0)
                        proc_labels = {"hostname": self._hostname, "process_name": name}
                        self.registry.set_gauge("process_cpu_percent", cpu, proc_labels)
                        self.registry.set_gauge("process_memory_mb", mem, proc_labels)
                except Exception:
                    pass

            return {
                "total_processes": total_count,
                "yunxi_processes": yunxi_count,
            }
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # 生命周期管理
    # ============================================================

    def start(self) -> bool:
        """启动定时采集.

        Returns:
            True 表示成功启动，False 表示已在运行或未启用
        """
        if not self._enabled:
            return False

        with self._lock:
            if self._running:
                return False

            self._running = True
            self._stop_event.clear()

            # 设置 exporter_up 指标
            self.registry.set_gauge("exporter_up", 1.0, {
                "hostname": self._hostname,
                "module": "m10",
            })

            # 先执行一次采集
            self.collect_metrics()

            # 启动后台采集线程
            self._collect_thread = threading.Thread(
                target=self._collect_loop,
                daemon=True,
                name="prometheus-exporter",
            )
            self._collect_thread.start()

            return True

    def stop(self) -> bool:
        """停止定时采集.

        Returns:
            True 表示成功停止
        """
        with self._lock:
            if not self._running:
                return False

            self._running = False
            self._stop_event.set()

            self.registry.set_gauge("exporter_up", 0.0, {
                "hostname": self._hostname,
                "module": "m10",
            })

            if self._collect_thread:
                self._collect_thread.join(timeout=5.0)
                self._collect_thread = None

            return True

    def _collect_loop(self) -> None:
        """后台采集循环."""
        while not self._stop_event.is_set():
            try:
                self.collect_metrics()
            except Exception:
                pass
            # 分段 sleep 以便快速响应 stop
            self._stop_event.wait(self._collect_interval)

    # ============================================================
    # 输出方法
    # ============================================================

    def generate_metrics_text(self) -> tuple[str, str]:
        """生成 Prometheus 格式的指标文本.

        Returns:
            (content_type, body) 元组
        """
        if not self._enabled:
            return "text/plain", "# Prometheus exporter is disabled\n"

        # 确保至少有一次采集
        if self._last_collect_time == 0:
            self.collect_metrics()

        content_type = CONTENT_TYPE_LATEST if _PROMETHEUS_AVAILABLE else "text/plain; version=0.0.4; charset=utf-8"
        body = self.registry.generate_text()
        return content_type, body

    def generate_metrics_json(self) -> Dict[str, Any]:
        """生成 JSON 格式的指标数据."""
        return {
            "metrics": self.registry.to_dict(),
            "prometheus_available": _PROMETHEUS_AVAILABLE,
            "exporter_enabled": self._enabled,
            "exporter_running": self._running,
            "hostname": self._hostname,
            "last_collect_time": self._last_collect_time,
            "collect_interval": self._collect_interval,
            "metric_count": len(self.registry.list_metrics()),
            "timestamp": time.time(),
        }

    def health_check(self) -> Dict[str, Any]:
        """Exporter 健康检查.

        Returns:
            健康状态字典
        """
        return {
            "status": "healthy" if self._running else "degraded",
            "enabled": self._enabled,
            "prometheus_available": _PROMETHEUS_AVAILABLE,
            "running": self._running,
            "hostname": self._hostname,
            "last_collect_time": self._last_collect_time,
            "collect_interval": self._collect_interval,
            "metric_count": len(self.registry.list_metrics()),
            "uptime_seconds": time.time() - self._last_collect_time if self._last_collect_time > 0 else 0,
        }

    # ============================================================
    # 动态注册支持
    # ============================================================

    def register_custom_gauge(self, name: str, help_text: str,
                               labels: Optional[List[str]] = None,
                               category: str = "custom") -> Optional[Gauge]:
        """动态注册自定义 Gauge 指标."""
        return self.registry.register_gauge(name, help_text, labels, category)

    def register_custom_counter(self, name: str, help_text: str,
                                 labels: Optional[List[str]] = None,
                                 category: str = "custom") -> Optional[Counter]:
        """动态注册自定义 Counter 指标."""
        return self.registry.register_counter(name, help_text, labels, category)


# ---------------------------------------------------------------------------
# M8 指标上报器
# ---------------------------------------------------------------------------
class M8MetricsReporter:
    """
    M8 监控指标上报器

    定时将 M10 的核心指标推送到 M8 监控中心。
    支持 HTTP 上报、失败重试、可配置上报频率。
    """

    def __init__(self, exporter: PrometheusExporter):
        self._exporter = exporter
        self._enabled = self._check_enabled()
        self._report_interval = self._get_report_interval()
        self._m8_base_url = os.environ.get(ENV_M8_BASE_URL, "http://localhost:8008")
        self._report_token = os.environ.get(ENV_M8_REPORT_TOKEN, "")

        # 运行状态
        self._running = False
        self._report_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 统计
        self._report_count = 0
        self._success_count = 0
        self._fail_count = 0
        self._last_report_time = 0.0
        self._last_success_time = 0.0
        self._consecutive_failures = 0

        # 重试配置
        self._max_retries = 3
        self._retry_delay = 2.0  # 秒

    def _check_enabled(self) -> bool:
        """检查 M8 上报是否启用."""
        env_val = os.environ.get(ENV_M8_REPORT_ENABLED, "false").lower()
        return env_val in ("true", "1", "yes", "enabled")

    def _get_report_interval(self) -> int:
        """获取上报间隔（秒）."""
        try:
            return int(os.environ.get(ENV_M8_REPORT_INTERVAL,
                                       str(DEFAULT_M8_REPORT_INTERVAL)))
        except (ValueError, TypeError):
            return DEFAULT_M8_REPORT_INTERVAL

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._running

    @property
    def report_interval(self) -> int:
        return self._report_interval

    def get_stats(self) -> Dict[str, Any]:
        """获取上报统计信息."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "report_interval": self._report_interval,
            "m8_base_url": self._m8_base_url,
            "report_count": self._report_count,
            "success_count": self._success_count,
            "fail_count": self._fail_count,
            "last_report_time": self._last_report_time,
            "last_success_time": self._last_success_time,
            "consecutive_failures": self._consecutive_failures,
        }

    def _get_sandbox_mode(self) -> bool:
        """获取沙盒模式状态."""
        try:
            from .config import get_config
            cfg = get_config()
            return cfg.sandbox.enabled
        except Exception:
            return False

    def build_report_payload(self) -> Dict[str, Any]:
        """构建上报到 M8 的指标数据.

        Returns:
            符合 M8 监控格式的指标字典
        """
        try:
            from .system_monitor import get_system_monitor
            from .process_manager import get_process_manager
            from .guard_engine import get_guard_engine

            sm = get_system_monitor()
            pm = get_process_manager()
            ge = get_guard_engine()

            latest = sm.get_latest()
            proc_stats = pm.get_process_stats()
            guard_status = ge.get_status_summary()

            payload = {
                "module": "m10",
                "module_name": "系统卫士",
                "hostname": self._exporter.hostname,
                "timestamp": time.time(),
                "metrics": {
                    "cpu": {
                        "usage_percent": latest.cpu.usage_percent,
                        "core_count": latest.cpu.core_count,
                        "load_avg_1min": latest.cpu.load_avg_1min,
                    },
                    "memory": {
                        "usage_percent": latest.memory.usage_percent,
                        "used_mb": latest.memory.used_mb,
                        "total_mb": latest.memory.total_mb,
                    },
                    "disk": {
                        "usage_percent": latest.disk.usage_percent,
                        "used_gb": latest.disk.used_gb,
                        "total_gb": latest.disk.total_gb,
                    },
                    "network": {
                        "send_mb_per_sec": latest.network.send_mb_per_sec,
                        "recv_mb_per_sec": latest.network.recv_mb_per_sec,
                    },
                    "gpu": {
                        "count": latest.gpu.count if latest.gpu else 0,
                        "usage_percent": latest.gpu.usage_percent if latest.gpu else 0,
                        "memory_percent": latest.gpu.memory_percent if latest.gpu else 0,
                        "memory_used_mb": latest.gpu.memory_used_mb if latest.gpu else 0,
                        "memory_total_mb": latest.gpu.memory_total_mb if latest.gpu else 0,
                        "temperature_celsius": latest.gpu.temperature_celsius if latest.gpu else 0,
                        "power_watt": latest.gpu.power_watt if latest.gpu else 0,
                    },
                    "process": {
                        "total_count": proc_stats.get("total_processes", 0),
                        "yunxi_count": proc_stats.get("yunxi_processes", 0),
                    },
                    "guard": {
                        "overall_level": guard_status.get("overall_level", "info"),
                        "total_alerts": guard_status.get("total_alerts", 0),
                        "throttling_active": guard_status.get("throttling_active", False),
                    },
                    "temperature": {
                        "highest_celsius": latest.temperature.highest_temp_celsius,
                        "source": latest.temperature.highest_temp_source,
                    },
                },
                "status": {
                    "sandbox_mode": self._get_sandbox_mode(),
                },
            }

            return payload
        except Exception as e:
            return {
                "module": "m10",
                "module_name": "系统卫士",
                "hostname": self._exporter.hostname,
                "timestamp": time.time(),
                "error": str(e),
            }

    def report_to_m8(self) -> bool:
        """上报指标到 M8 监控中心.

        Returns:
            True 表示上报成功
        """
        if not self._enabled:
            return False

        payload = self.build_report_payload()
        self._report_count += 1
        self._last_report_time = time.time()

        success = False
        for attempt in range(self._max_retries):
            try:
                import httpx
                url = f"{self._m8_base_url.rstrip('/')}/api/v1/monitor/metrics/receive"
                headers = {
                    "Content-Type": "application/json",
                }
                if self._report_token:
                    headers["X-M8-Token"] = self._report_token

                response = httpx.post(url, json=payload, timeout=10.0)

                if response.status_code == 200:
                    success = True
                    self._success_count += 1
                    self._last_success_time = time.time()
                    self._consecutive_failures = 0
                    break
                else:
                    # 非 200 响应，可能重试
                    if attempt < self._max_retries - 1:
                        time.sleep(self._retry_delay * (attempt + 1))
            except ImportError:
                # httpx 不可用，尝试 requests
                try:
                    import requests
                    url = f"{self._m8_base_url.rstrip('/')}/api/v1/monitor/metrics/receive"
                    headers = {"Content-Type": "application/json"}
                    if self._report_token:
                        headers["X-M8-Token"] = self._report_token

                    response = requests.post(url, json=payload, timeout=10.0)
                    if response.status_code == 200:
                        success = True
                        self._success_count += 1
                        self._last_success_time = time.time()
                        self._consecutive_failures = 0
                        break
                except ImportError:
                    # 都不可用，直接失败
                    break
                except Exception:
                    if attempt < self._max_retries - 1:
                        time.sleep(self._retry_delay * (attempt + 1))
            except Exception:
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay * (attempt + 1))

        if not success:
            self._fail_count += 1
            self._consecutive_failures += 1

        return success

    def start(self) -> bool:
        """启动定时上报.

        Returns:
            True 表示成功启动
        """
        if not self._enabled:
            return False

        with self._lock:
            if self._running:
                return False

            self._running = True
            self._stop_event.clear()

            self._report_thread = threading.Thread(
                target=self._report_loop,
                daemon=True,
                name="m8-metrics-reporter",
            )
            self._report_thread.start()

            return True

    def stop(self) -> bool:
        """停止定时上报."""
        with self._lock:
            if not self._running:
                return False

            self._running = False
            self._stop_event.set()

            if self._report_thread:
                self._report_thread.join(timeout=5.0)
                self._report_thread = None

            return True

    def _report_loop(self) -> None:
        """上报循环."""
        while not self._stop_event.is_set():
            try:
                self.report_to_m8()
            except Exception:
                pass
            self._stop_event.wait(self._report_interval)


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_exporter_instance: Optional[PrometheusExporter] = None
_instance_lock = threading.Lock()


def get_prometheus_exporter() -> PrometheusExporter:
    """获取 Prometheus Exporter 单例."""
    global _exporter_instance
    if _exporter_instance is None:
        with _instance_lock:
            if _exporter_instance is None:
                _exporter_instance = PrometheusExporter()
    return _exporter_instance


def get_m8_reporter() -> Optional[M8MetricsReporter]:
    """获取 M8 上报器单例（延迟创建）."""
    exporter = get_prometheus_exporter()
    if exporter._m8_reporter is None:
        with _instance_lock:
            if exporter._m8_reporter is None:
                exporter._m8_reporter = M8MetricsReporter(exporter)
    return exporter._m8_reporter


# ---------------------------------------------------------------------------
# 向后兼容的函数接口（保留旧 API）
# ---------------------------------------------------------------------------

def is_prometheus_available() -> bool:
    """检查 prometheus_client 是否可用（向后兼容）."""
    return _PROMETHEUS_AVAILABLE


def generate_prometheus_metrics() -> tuple[str, str]:
    """生成 Prometheus 格式的指标文本（向后兼容）.

    Returns:
        (content_type, body) 元组
    """
    exporter = get_prometheus_exporter()
    return exporter.generate_metrics_text()


def generate_metrics_json() -> Dict[str, Any]:
    """生成 JSON 格式的指标（向后兼容）."""
    exporter = get_prometheus_exporter()
    return exporter.generate_metrics_json()


def start_prometheus_exporter() -> bool:
    """启动 Prometheus 采集器（便捷函数）."""
    exporter = get_prometheus_exporter()
    return exporter.start()


def stop_prometheus_exporter() -> bool:
    """停止 Prometheus 采集器（便捷函数）."""
    exporter = get_prometheus_exporter()
    return exporter.stop()


def exporter_health_check() -> Dict[str, Any]:
    """Exporter 健康检查（便捷函数）."""
    exporter = get_prometheus_exporter()
    return exporter.health_check()
