"""
云汐标准化监控指标定义（OB-002, P1级）
====================================

统一定义全系统的监控指标规范，确保各模块上报的指标一致。

指标分类：
1. 系统指标（System Metrics）：CPU、内存、磁盘、网络
2. 业务指标（Business Metrics）：请求量、响应时间、错误率
3. 模块指标（Module Metrics）：各模块健康状态、QPS、延迟
4. 安全指标（Security Metrics）：攻击次数、拦截数、安全事件

每个指标包含：
- name: 指标名称（命名空间_模块_指标名_单位）
- type: 指标类型（counter/gauge/histogram/summary）
- help: 帮助文本
- unit: 单位
- labels: 标签列表
- default_value: 默认值

使用方式：
    from shared.core.observability.metric_definitions import (
        SYSTEM_METRICS,
        BUSINESS_METRICS,
        SECURITY_METRICS,
        MODULE_METRICS,
        MetricDefinition,
        register_standard_metrics,
    )

    # 注册所有标准指标
    register_standard_metrics(metrics_collector, module_name="m8")
"""

from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum


# ============================================================================
# 指标类型枚举
# ============================================================================

class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


# ============================================================================
# 指标定义数据类
# ============================================================================

@dataclass
class MetricDefinition:
    """标准化指标定义

    遵循 Prometheus 命名规范：
    - 命名空间_子系统_指标名_单位
    - 使用下划线分隔
    - 全小写
    """
    name: str
    metric_type: MetricType
    help: str
    unit: str = ""
    labels: List[str] = field(default_factory=list)
    buckets: Optional[List[float]] = None  # histogram 专用
    category: str = "system"  # system/business/module/security
    subcategory: str = ""

    @property
    def full_name(self) -> str:
        """完整指标名（带单位后缀）"""
        if self.unit and not self.name.endswith(f"_{self.unit}"):
            return f"{self.name}_{self.unit}"
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.metric_type.value,
            "help": self.help,
            "unit": self.unit,
            "labels": self.labels,
            "category": self.category,
            "subcategory": self.subcategory,
            "buckets": self.buckets,
        }


# ============================================================================
# 系统指标（System Metrics）
# ============================================================================

SYSTEM_METRICS: List[MetricDefinition] = [
    # ---- CPU ----
    MetricDefinition(
        name="system_cpu_usage_percent",
        metric_type=MetricType.GAUGE,
        help="CPU usage percentage",
        unit="percent",
        labels=["cpu"],
        category="system",
        subcategory="cpu",
    ),
    MetricDefinition(
        name="system_cpu_cores_total",
        metric_type=MetricType.GAUGE,
        help="Total number of CPU cores",
        unit="cores",
        category="system",
        subcategory="cpu",
    ),
    MetricDefinition(
        name="system_cpu_load_avg",
        metric_type=MetricType.GAUGE,
        help="System load average",
        labels=["period"],  # 1m, 5m, 15m
        category="system",
        subcategory="cpu",
    ),

    # ---- 内存 ----
    MetricDefinition(
        name="system_memory_usage_bytes",
        metric_type=MetricType.GAUGE,
        help="Memory usage in bytes",
        unit="bytes",
        category="system",
        subcategory="memory",
    ),
    MetricDefinition(
        name="system_memory_total_bytes",
        metric_type=MetricType.GAUGE,
        help="Total memory in bytes",
        unit="bytes",
        category="system",
        subcategory="memory",
    ),
    MetricDefinition(
        name="system_memory_available_bytes",
        metric_type=MetricType.GAUGE,
        help="Available memory in bytes",
        unit="bytes",
        category="system",
        subcategory="memory",
    ),
    MetricDefinition(
        name="system_memory_usage_percent",
        metric_type=MetricType.GAUGE,
        help="Memory usage percentage",
        unit="percent",
        category="system",
        subcategory="memory",
    ),
    MetricDefinition(
        name="system_swap_usage_bytes",
        metric_type=MetricType.GAUGE,
        help="Swap usage in bytes",
        unit="bytes",
        category="system",
        subcategory="memory",
    ),

    # ---- 磁盘 ----
    MetricDefinition(
        name="system_disk_usage_bytes",
        metric_type=MetricType.GAUGE,
        help="Disk usage in bytes",
        unit="bytes",
        labels=["mount_point"],
        category="system",
        subcategory="disk",
    ),
    MetricDefinition(
        name="system_disk_total_bytes",
        metric_type=MetricType.GAUGE,
        help="Total disk space in bytes",
        unit="bytes",
        labels=["mount_point"],
        category="system",
        subcategory="disk",
    ),
    MetricDefinition(
        name="system_disk_free_bytes",
        metric_type=MetricType.GAUGE,
        help="Free disk space in bytes",
        unit="bytes",
        labels=["mount_point"],
        category="system",
        subcategory="disk",
    ),
    MetricDefinition(
        name="system_disk_usage_percent",
        metric_type=MetricType.GAUGE,
        help="Disk usage percentage",
        unit="percent",
        labels=["mount_point"],
        category="system",
        subcategory="disk",
    ),
    MetricDefinition(
        name="system_disk_read_bytes_total",
        metric_type=MetricType.COUNTER,
        help="Total bytes read from disk",
        unit="bytes",
        labels=["device"],
        category="system",
        subcategory="disk",
    ),
    MetricDefinition(
        name="system_disk_write_bytes_total",
        metric_type=MetricType.COUNTER,
        help="Total bytes written to disk",
        unit="bytes",
        labels=["device"],
        category="system",
        subcategory="disk",
    ),

    # ---- 网络 ----
    MetricDefinition(
        name="system_network_receive_bytes_total",
        metric_type=MetricType.COUNTER,
        help="Total bytes received over network",
        unit="bytes",
        labels=["interface"],
        category="system",
        subcategory="network",
    ),
    MetricDefinition(
        name="system_network_transmit_bytes_total",
        metric_type=MetricType.COUNTER,
        help="Total bytes transmitted over network",
        unit="bytes",
        labels=["interface"],
        category="system",
        subcategory="network",
    ),
    MetricDefinition(
        name="system_network_connections",
        metric_type=MetricType.GAUGE,
        help="Current network connections",
        labels=["state"],  # ESTABLISHED, LISTEN, etc.
        category="system",
        subcategory="network",
    ),

    # ---- 进程 ----
    MetricDefinition(
        name="system_process_count",
        metric_type=MetricType.GAUGE,
        help="Number of running processes",
        category="system",
        subcategory="process",
    ),
    MetricDefinition(
        name="system_process_memory_bytes",
        metric_type=MetricType.GAUGE,
        help="Process memory usage in bytes",
        unit="bytes",
        labels=["pid", "process_name"],
        category="system",
        subcategory="process",
    ),
    MetricDefinition(
        name="system_uptime_seconds",
        metric_type=MetricType.GAUGE,
        help="System uptime in seconds",
        unit="seconds",
        category="system",
        subcategory="process",
    ),
]


# ============================================================================
# 业务指标（Business Metrics）
# ============================================================================

BUSINESS_METRICS: List[MetricDefinition] = [
    # ---- 请求指标 ----
    MetricDefinition(
        name="http_requests_total",
        metric_type=MetricType.COUNTER,
        help="Total number of HTTP requests",
        labels=["method", "path", "status", "module"],
        category="business",
        subcategory="requests",
    ),
    MetricDefinition(
        name="http_request_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        help="HTTP request duration in seconds",
        unit="seconds",
        labels=["method", "path", "module"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
        category="business",
        subcategory="requests",
    ),
    MetricDefinition(
        name="http_requests_in_flight",
        metric_type=MetricType.GAUGE,
        help="Number of in-flight HTTP requests",
        labels=["method", "module"],
        category="business",
        subcategory="requests",
    ),
    MetricDefinition(
        name="http_requests_error_total",
        metric_type=MetricType.COUNTER,
        help="Total number of error responses (4xx + 5xx)",
        labels=["status", "method", "path", "module"],
        category="business",
        subcategory="requests",
    ),
    MetricDefinition(
        name="http_requests_slow_total",
        metric_type=MetricType.COUNTER,
        help="Total number of slow requests (>1s)",
        labels=["method", "path", "module"],
        category="business",
        subcategory="requests",
    ),

    # ---- 业务质量 ----
    MetricDefinition(
        name="business_error_rate",
        metric_type=MetricType.GAUGE,
        help="Business error rate (errors / total requests)",
        unit="ratio",
        labels=["module"],
        category="business",
        subcategory="quality",
    ),
    MetricDefinition(
        name="business_success_rate",
        metric_type=MetricType.GAUGE,
        help="Business success rate (successful / total requests)",
        unit="ratio",
        labels=["module"],
        category="business",
        subcategory="quality",
    ),

    # ---- 用户活跃度 ----
    MetricDefinition(
        name="user_active_total",
        metric_type=MetricType.GAUGE,
        help="Number of active users",
        labels=["period", "module"],  # period: 1m/5m/1h/1d
        category="business",
        subcategory="users",
    ),
    MetricDefinition(
        name="user_sessions_total",
        metric_type=MetricType.COUNTER,
        help="Total number of user sessions",
        labels=["module"],
        category="business",
        subcategory="users",
    ),
    MetricDefinition(
        name="user_registrations_total",
        metric_type=MetricType.COUNTER,
        help="Total number of user registrations",
        labels=["module"],
        category="business",
        subcategory="users",
    ),

    # ---- 任务处理 ----
    MetricDefinition(
        name="task_queue_size",
        metric_type=MetricType.GAUGE,
        help="Current task queue size",
        labels=["queue_name", "module"],
        category="business",
        subcategory="tasks",
    ),
    MetricDefinition(
        name="task_processed_total",
        metric_type=MetricType.COUNTER,
        help="Total number of processed tasks",
        labels=["task_type", "status", "module"],
        category="business",
        subcategory="tasks",
    ),
    MetricDefinition(
        name="task_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        help="Task processing duration in seconds",
        unit="seconds",
        labels=["task_type", "module"],
        buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
        category="business",
        subcategory="tasks",
    ),
    MetricDefinition(
        name="task_failed_total",
        metric_type=MetricType.COUNTER,
        help="Total number of failed tasks",
        labels=["task_type", "error_type", "module"],
        category="business",
        subcategory="tasks",
    ),

    # ---- 数据库 ----
    MetricDefinition(
        name="db_query_duration_seconds",
        metric_type=MetricType.HISTOGRAM,
        help="Database query duration in seconds",
        unit="seconds",
        labels=["operation", "table", "module"],
        buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        category="business",
        subcategory="database",
    ),
    MetricDefinition(
        name="db_connections_active",
        metric_type=MetricType.GAUGE,
        help="Active database connections",
        labels=["module"],
        category="business",
        subcategory="database",
    ),
    MetricDefinition(
        name="db_connections_total",
        metric_type=MetricType.GAUGE,
        help="Total database connections",
        labels=["module"],
        category="business",
        subcategory="database",
    ),
]


# ============================================================================
# 模块指标（Module Metrics）
# ============================================================================

MODULE_METRICS: List[MetricDefinition] = [
    MetricDefinition(
        name="module_health_status",
        metric_type=MetricType.GAUGE,
        help="Module health status (1=healthy, 0=unhealthy, 0.5=degraded)",
        labels=["module_id", "module_name"],
        category="module",
        subcategory="health",
    ),
    MetricDefinition(
        name="module_up",
        metric_type=MetricType.GAUGE,
        help="Module up status (1=running, 0=stopped)",
        labels=["module_id", "module_name", "version"],
        category="module",
        subcategory="health",
    ),
    MetricDefinition(
        name="module_uptime_seconds",
        metric_type=MetricType.GAUGE,
        help="Module uptime in seconds",
        unit="seconds",
        labels=["module_id"],
        category="module",
        subcategory="health",
    ),
    MetricDefinition(
        name="module_start_time",
        metric_type=MetricType.GAUGE,
        help="Module start time (Unix timestamp)",
        labels=["module_id"],
        category="module",
        subcategory="health",
    ),
    MetricDefinition(
        name="module_requests_per_second",
        metric_type=MetricType.GAUGE,
        help="Module requests per second (QPS)",
        unit="qps",
        labels=["module_id"],
        category="module",
        subcategory="performance",
    ),
    MetricDefinition(
        name="module_latency_p50_seconds",
        metric_type=MetricType.GAUGE,
        help="Module P50 latency in seconds",
        unit="seconds",
        labels=["module_id"],
        category="module",
        subcategory="performance",
    ),
    MetricDefinition(
        name="module_latency_p95_seconds",
        metric_type=MetricType.GAUGE,
        help="Module P95 latency in seconds",
        unit="seconds",
        labels=["module_id"],
        category="module",
        subcategory="performance",
    ),
    MetricDefinition(
        name="module_latency_p99_seconds",
        metric_type=MetricType.GAUGE,
        help="Module P99 latency in seconds",
        unit="seconds",
        labels=["module_id"],
        category="module",
        subcategory="performance",
    ),
    MetricDefinition(
        name="module_memory_usage_bytes",
        metric_type=MetricType.GAUGE,
        help="Module memory usage in bytes",
        unit="bytes",
        labels=["module_id"],
        category="module",
        subcategory="resource",
    ),
    MetricDefinition(
        name="module_goroutines",
        metric_type=MetricType.GAUGE,
        help="Number of active threads/async tasks",
        labels=["module_id"],
        category="module",
        subcategory="resource",
    ),
]


# ============================================================================
# 安全指标（Security Metrics）
# ============================================================================

SECURITY_METRICS: List[MetricDefinition] = [
    # ---- 攻击检测 ----
    MetricDefinition(
        name="security_attacks_total",
        metric_type=MetricType.COUNTER,
        help="Total number of detected attacks",
        labels=["attack_type", "severity", "module"],
        category="security",
        subcategory="attacks",
    ),
    MetricDefinition(
        name="security_attacks_blocked_total",
        metric_type=MetricType.COUNTER,
        help="Total number of blocked attacks",
        labels=["attack_type", "module"],
        category="security",
        subcategory="attacks",
    ),
    MetricDefinition(
        name="security_waf_hits_total",
        metric_type=MetricType.COUNTER,
        help="Total WAF rule hits",
        labels=["rule_id", "rule_category", "action"],
        category="security",
        subcategory="waf",
    ),

    # ---- 认证与授权 ----
    MetricDefinition(
        name="security_login_total",
        metric_type=MetricType.COUNTER,
        help="Total login attempts",
        labels=["status", "method", "module"],  # status: success/failed
        category="security",
        subcategory="auth",
    ),
    MetricDefinition(
        name="security_login_failed_total",
        metric_type=MetricType.COUNTER,
        help="Total failed login attempts",
        labels=["reason", "module"],
        category="security",
        subcategory="auth",
    ),
    MetricDefinition(
        name="security_login_brute_force_total",
        metric_type=MetricType.COUNTER,
        help="Total brute force login attempts detected",
        labels=["ip", "module"],
        category="security",
        subcategory="auth",
    ),
    MetricDefinition(
        name="security_unauthorized_total",
        metric_type=MetricType.COUNTER,
        help="Total unauthorized access attempts",
        labels=["reason", "module"],
        category="security",
        subcategory="auth",
    ),

    # ---- 安全事件 ----
    MetricDefinition(
        name="security_events_total",
        metric_type=MetricType.COUNTER,
        help="Total security events",
        labels=["event_type", "severity", "module"],
        category="security",
        subcategory="events",
    ),
    MetricDefinition(
        name="security_events_critical_total",
        metric_type=MetricType.COUNTER,
        help="Total critical security events",
        labels=["event_type", "module"],
        category="security",
        subcategory="events",
    ),

    # ---- 漏洞扫描 ----
    MetricDefinition(
        name="security_vulnerabilities_found",
        metric_type=MetricType.GAUGE,
        help="Number of vulnerabilities found",
        labels=["severity", "scan_id"],
        category="security",
        subcategory="vulnerability",
    ),
    MetricDefinition(
        name="security_vulnerabilities_fixed",
        metric_type=MetricType.COUNTER,
        help="Total vulnerabilities fixed",
        labels=["severity"],
        category="security",
        subcategory="vulnerability",
    ),

    # ---- API 安全 ----
    MetricDefinition(
        name="security_rate_limit_hits_total",
        metric_type=MetricType.COUNTER,
        help="Total rate limit hits",
        labels=["endpoint", "module"],
        category="security",
        subcategory="api",
    ),
    MetricDefinition(
        name="security_api_key_usage_total",
        metric_type=MetricType.COUNTER,
        help="Total API key usage",
        labels=["key_id", "module"],
        category="security",
        subcategory="api",
    ),
]


# ============================================================================
# 告警阈值定义
# ============================================================================

ALERT_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    # 系统资源
    "system_cpu_usage_percent": {"warning": 80, "critical": 90},
    "system_memory_usage_percent": {"warning": 80, "critical": 90},
    "system_disk_usage_percent": {"warning": 80, "critical": 90},
    "system_swap_usage_percent": {"warning": 50, "critical": 80},

    # 业务质量
    "business_error_rate": {"warning": 0.05, "critical": 0.10},  # 5% / 10%
    "http_requests_slow_total": {"warning": 100, "critical": 500},  # 慢请求数

    # 安全
    "security_attacks_total": {"warning": 10, "critical": 50},  # 每小时攻击数
    "security_login_failed_total": {"warning": 5, "critical": 20},  # 每分钟失败登录

    # 任务
    "task_queue_size": {"warning": 100, "critical": 1000},
}


# ============================================================================
# 工具函数
# ============================================================================

def get_all_metrics() -> List[MetricDefinition]:
    """获取所有标准指标定义"""
    return SYSTEM_METRICS + BUSINESS_METRICS + MODULE_METRICS + SECURITY_METRICS


def get_metrics_by_category(category: str) -> List[MetricDefinition]:
    """按分类获取指标定义"""
    all_metrics = {
        "system": SYSTEM_METRICS,
        "business": BUSINESS_METRICS,
        "module": MODULE_METRICS,
        "security": SECURITY_METRICS,
    }
    return all_metrics.get(category, [])


def get_metric_by_name(name: str) -> Optional[MetricDefinition]:
    """按名称查找指标定义"""
    for metric in get_all_metrics():
        if metric.name == name:
            return metric
    return None


def register_standard_metrics(
    metrics_collector: Any,
    module_name: str = "default",
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """向指标收集器注册所有标准指标

    Args:
        metrics_collector: MetricsCollector 实例
        module_name: 模块名
        categories: 要注册的指标分类，None 表示全部

    Returns:
        注册结果统计
    """
    if categories is None:
        categories = ["system", "business", "module", "security"]

    registered = {"counters": 0, "gauges": 0, "histograms": 0, "summaries": 0}

    for cat in categories:
        metrics = get_metrics_by_category(cat)
        for metric_def in metrics:
            try:
                labels = {"module": module_name}
                if metric_def.metric_type == MetricType.COUNTER:
                    metrics_collector.counter(
                        name=metric_def.name,
                        help_text=metric_def.help,
                        labels=labels,
                    )
                    registered["counters"] += 1
                elif metric_def.metric_type == MetricType.GAUGE:
                    metrics_collector.gauge(
                        name=metric_def.name,
                        help_text=metric_def.help,
                        labels=labels,
                    )
                    registered["gauges"] += 1
                elif metric_def.metric_type == MetricType.HISTOGRAM:
                    metrics_collector.histogram(
                        name=metric_def.name,
                        help_text=metric_def.help,
                        buckets=metric_def.buckets,
                        labels=labels,
                    )
                    registered["histograms"] += 1
                elif metric_def.metric_type == MetricType.SUMMARY:
                    metrics_collector.summary(
                        name=metric_def.name,
                        help_text=metric_def.help,
                        labels=labels,
                    )
                    registered["summaries"] += 1
            except Exception:
                pass

    return registered


def metrics_to_dict(metrics: List[MetricDefinition]) -> List[Dict[str, Any]]:
    """将指标定义列表转换为字典列表"""
    return [m.to_dict() for m in metrics]


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    # 类型
    "MetricType",
    "MetricDefinition",
    # 指标列表
    "SYSTEM_METRICS",
    "BUSINESS_METRICS",
    "MODULE_METRICS",
    "SECURITY_METRICS",
    # 告警阈值
    "ALERT_THRESHOLDS",
    # 函数
    "get_all_metrics",
    "get_metrics_by_category",
    "get_metric_by_name",
    "register_standard_metrics",
    "metrics_to_dict",
]
