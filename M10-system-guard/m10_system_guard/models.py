"""
M10 系统卫士 - 数据模型

包含系统指标、进程快照、防护策略、告警记录、审计日志、
沙箱任务、硬件保护报告等所有数据模型定义。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 枚举定义
# ============================================================

class GuardLevel(str, Enum):
    """防护级别.

    分级拦截策略：提示/警告/严重/紧急 四级
    """
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class SecurityLevel(str, Enum):
    """安全评估级别.

    启动安全检查的三级评估结果
    """
    SAFE = "safe"
    WARNING = "warning"
    DANGER = "danger"


class TaskLevel(str, Enum):
    """任务级别.

    沙箱任务分级：轻量/普通/重型/超重型
    """
    LIGHT = "light"
    NORMAL = "normal"
    HEAVY = "heavy"
    SUPER_HEAVY = "super_heavy"


class TaskStatus(str, Enum):
    """任务状态."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class AuditLogLevel(str, Enum):
    """审计日志级别."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """指标类型."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    GPU = "gpu"
    TEMPERATURE = "temperature"
    BATTERY = "battery"


class AggregationLevel(str, Enum):
    """数据聚合级别."""
    RAW = "raw"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


# ============================================================
# 系统指标模型
# ============================================================

@dataclass
class CPUMetric:
    """CPU 指标."""
    usage_percent: float = 0.0
    core_count: int = 0
    per_core_usage: list = field(default_factory=list)
    load_avg_1min: float = 0.0
    load_avg_5min: float = 0.0
    load_avg_15min: float = 0.0


@dataclass
class MemoryMetric:
    """内存指标."""
    total_mb: float = 0.0
    used_mb: float = 0.0
    available_mb: float = 0.0
    usage_percent: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0
    swap_percent: float = 0.0


@dataclass
class DiskMetric:
    """磁盘指标."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    usage_percent: float = 0.0
    read_mb_per_sec: float = 0.0
    write_mb_per_sec: float = 0.0
    io_wait_percent: float = 0.0


@dataclass
class NetworkMetric:
    """网络指标."""
    bytes_sent_mb: float = 0.0
    bytes_recv_mb: float = 0.0
    send_mb_per_sec: float = 0.0
    recv_mb_per_sec: float = 0.0
    connection_count: int = 0
    interface: str = "eth0"


@dataclass
class GPUProcessInfo:
    """GPU 进程级信息."""
    pid: int = 0
    process_name: str = ""
    memory_used_mb: float = 0.0
    gpu_id: int = 0
    sm_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0


@dataclass
class GPUDeviceInfo:
    """单块 GPU 设备信息."""
    gpu_id: int = 0
    name: str = ""
    uuid: str = ""
    usage_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    memory_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_watt: float = 0.0
    power_limit_watt: float = 0.0
    fan_speed_percent: float = 0.0
    memory_clock_mhz: float = 0.0
    graphics_clock_mhz: float = 0.0
    pci_bus_id: str = ""
    processes: list = field(default_factory=list)  # List[GPUProcessInfo]

    def to_dict(self):
        return {
            "gpu_id": self.gpu_id,
            "name": self.name,
            "uuid": self.uuid,
            "usage_percent": self.usage_percent,
            "memory_total_mb": self.memory_total_mb,
            "memory_used_mb": self.memory_used_mb,
            "memory_free_mb": self.memory_free_mb,
            "memory_percent": self.memory_percent,
            "temperature_celsius": self.temperature_celsius,
            "power_watt": self.power_watt,
            "power_limit_watt": self.power_limit_watt,
            "fan_speed_percent": self.fan_speed_percent,
            "memory_clock_mhz": self.memory_clock_mhz,
            "graphics_clock_mhz": self.graphics_clock_mhz,
            "pci_bus_id": self.pci_bus_id,
            "processes": [
                p.to_dict() if hasattr(p, "to_dict") else {"pid": getattr(p, "pid", 0)}
                for p in self.processes
            ],
        }


@dataclass
class GPUMetric:
    """GPU 指标（支持多 GPU）."""
    count: int = 0
    # 汇总值（所有 GPU 的平均/总计）
    usage_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_watt: float = 0.0
    # 增强字段
    driver_version: str = ""
    cuda_version: str = ""
    devices: list = field(default_factory=list)  # List[GPUDeviceInfo]
    processes: list = field(default_factory=list)  # List[GPUProcessInfo]
    nvlink_throughput_gbs: float = 0.0
    ecc_errors_total: int = 0


@dataclass
class TemperatureMetric:
    """温度指标."""
    cpu_temp_celsius: float = 0.0
    gpu_temp_celsius: float = 0.0
    motherboard_temp_celsius: float = 0.0
    highest_temp_celsius: float = 0.0
    highest_temp_source: str = ""


@dataclass
class BatteryMetric:
    """电池指标."""
    percent: float = 0.0
    is_charging: bool = False
    remaining_minutes: int = 0
    power_plugged: bool = False
    design_capacity_mwh: float = 0.0
    current_capacity_mwh: float = 0.0


@dataclass
class SystemMetric:
    """系统指标快照.

    包含一次采样的所有系统指标数据。
    """
    timestamp: float = field(default_factory=time.time)
    cpu: CPUMetric = field(default_factory=CPUMetric)
    memory: MemoryMetric = field(default_factory=MemoryMetric)
    disk: DiskMetric = field(default_factory=DiskMetric)
    network: NetworkMetric = field(default_factory=NetworkMetric)
    gpu: GPUMetric = field(default_factory=GPUMetric)
    temperature: TemperatureMetric = field(default_factory=TemperatureMetric)
    battery: BatteryMetric = field(default_factory=BatteryMetric)
    aggregation_level: AggregationLevel = AggregationLevel.RAW

    def to_dict(self):
        """转换为字典."""
        return {
            "timestamp": self.timestamp,
            "aggregation_level": self.aggregation_level.value,
            "cpu": {
                "usage_percent": self.cpu.usage_percent,
                "core_count": self.cpu.core_count,
                "per_core_usage": self.cpu.per_core_usage,
                "load_avg_1min": self.cpu.load_avg_1min,
                "load_avg_5min": self.cpu.load_avg_5min,
                "load_avg_15min": self.cpu.load_avg_15min,
            },
            "memory": {
                "total_mb": self.memory.total_mb,
                "used_mb": self.memory.used_mb,
                "available_mb": self.memory.available_mb,
                "usage_percent": self.memory.usage_percent,
                "swap_total_mb": self.memory.swap_total_mb,
                "swap_used_mb": self.memory.swap_used_mb,
                "swap_percent": self.memory.swap_percent,
            },
            "disk": {
                "total_gb": self.disk.total_gb,
                "used_gb": self.disk.used_gb,
                "free_gb": self.disk.free_gb,
                "usage_percent": self.disk.usage_percent,
                "read_mb_per_sec": self.disk.read_mb_per_sec,
                "write_mb_per_sec": self.disk.write_mb_per_sec,
                "io_wait_percent": self.disk.io_wait_percent,
            },
            "network": {
                "bytes_sent_mb": self.network.bytes_sent_mb,
                "bytes_recv_mb": self.network.bytes_recv_mb,
                "send_mb_per_sec": self.network.send_mb_per_sec,
                "recv_mb_per_sec": self.network.recv_mb_per_sec,
                "connection_count": self.network.connection_count,
                "interface": self.network.interface,
            },
            "gpu": {
                "count": self.gpu.count,
                "usage_percent": self.gpu.usage_percent,
                "memory_total_mb": self.gpu.memory_total_mb,
                "memory_used_mb": self.gpu.memory_used_mb,
                "memory_percent": self.gpu.memory_percent,
                "temperature_celsius": self.gpu.temperature_celsius,
                "power_watt": self.gpu.power_watt,
                "driver_version": self.gpu.driver_version,
                "cuda_version": self.gpu.cuda_version,
                "devices": [d.to_dict() if hasattr(d, "to_dict") else {} for d in self.gpu.devices],
                "processes": [
                    p.to_dict() if hasattr(p, "to_dict") else {}
                    for p in self.gpu.processes
                ],
            },
            "temperature": {
                "cpu_temp_celsius": self.temperature.cpu_temp_celsius,
                "gpu_temp_celsius": self.temperature.gpu_temp_celsius,
                "motherboard_temp_celsius": self.temperature.motherboard_temp_celsius,
                "highest_temp_celsius": self.temperature.highest_temp_celsius,
                "highest_temp_source": self.temperature.highest_temp_source,
            },
            "battery": {
                "percent": self.battery.percent,
                "is_charging": self.battery.is_charging,
                "remaining_minutes": self.battery.remaining_minutes,
                "power_plugged": self.battery.power_plugged,
                "design_capacity_mwh": self.battery.design_capacity_mwh,
                "current_capacity_mwh": self.battery.current_capacity_mwh,
            },
        }


# ============================================================
# 进程模型
# ============================================================

@dataclass
class ProcessSnapshot:
    """进程快照.

    单个进程的完整信息快照。
    """
    pid: int = 0
    name: str = ""
    path: str = ""
    cmdline: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    status: str = "running"
    username: str = ""
    create_time: float = 0.0
    thread_count: int = 0
    ppid: int = 0
    is_yunxi_process: bool = False
    yunxi_module: str = ""
    is_vscode_process: bool = False

    def to_dict(self):
        """转换为字典."""
        return {
            "pid": self.pid,
            "name": self.name,
            "path": self.path,
            "cmdline": self.cmdline,
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "memory_percent": self.memory_percent,
            "status": self.status,
            "username": self.username,
            "create_time": self.create_time,
            "thread_count": self.thread_count,
            "ppid": self.ppid,
            "is_yunxi_process": self.is_yunxi_process,
            "yunxi_module": self.yunxi_module,
            "is_vscode_process": self.is_vscode_process,
        }


@dataclass
class ProcessTreeNode:
    """进程树节点."""
    process: ProcessSnapshot
    children: list = field(default_factory=list)


# ============================================================
# 防护模型
# ============================================================

@dataclass
class GuardPolicy:
    """防护策略.

    定义各项资源的阈值和对应动作。
    """
    name: str = ""
    description: str = ""
    metric_type: MetricType = MetricType.CPU
    info_threshold: float = 0.0
    warning_threshold: float = 0.0
    critical_threshold: float = 0.0
    emergency_threshold: float = 0.0
    enabled: bool = True
    action_on_warning: str = "log"
    action_on_critical: str = "throttle"
    action_on_emergency: str = "pause_heavy_tasks"


@dataclass
class GuardAlert:
    """告警记录.

    防护引擎触发的告警记录。
    """
    alert_id: str = ""
    timestamp: float = field(default_factory=time.time)
    level: GuardLevel = GuardLevel.INFO
    metric_type: MetricType = MetricType.CPU
    metric_value: float = 0.0
    threshold: float = 0.0
    message: str = ""
    action_taken: str = ""
    acknowledged: bool = False

    def to_dict(self):
        """转换为字典."""
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "metric_type": self.metric_type.value,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "message": self.message,
            "action_taken": self.action_taken,
            "acknowledged": self.acknowledged,
        }


# ============================================================
# 审计日志模型
# ============================================================

@dataclass
class AuditLog:
    """审计日志.

    所有拦截操作的审计记录。
    """
    log_id: str = ""
    timestamp: float = field(default_factory=time.time)
    level: AuditLogLevel = AuditLogLevel.INFO
    log_type: str = ""
    trigger_condition: str = ""
    action: str = ""
    result: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self):
        """转换为字典."""
        return {
            "log_id": self.log_id,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "log_type": self.log_type,
            "trigger_condition": self.trigger_condition,
            "action": self.action,
            "result": self.result,
            "details": self.details,
        }


# ============================================================
# 沙箱任务模型
# ============================================================

@dataclass
class SandboxTask:
    """沙箱任务.

    沙箱调度器管理的任务对象。
    """
    task_id: str = ""
    name: str = ""
    level: TaskLevel = TaskLevel.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5
    estimated_cpu_percent: float = 10.0
    estimated_memory_mb: float = 100.0
    estimated_duration_seconds: float = 60.0
    submit_time: float = field(default_factory=time.time)
    start_time: float = 0.0
    end_time: float = 0.0
    queue_position: int = 0
    callback_url: str = ""
    task_data: dict = field(default_factory=dict)

    def to_dict(self):
        """转换为字典."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "level": self.level.value,
            "status": self.status.value,
            "priority": self.priority,
            "estimated_cpu_percent": self.estimated_cpu_percent,
            "estimated_memory_mb": self.estimated_memory_mb,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "submit_time": self.submit_time,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "queue_position": self.queue_position,
            "task_data": self.task_data,
        }


# ============================================================
# 启动检查模型
# ============================================================

@dataclass
class StartupCheckResult:
    """启动安全检查结果."""
    check_id: str = ""
    timestamp: float = field(default_factory=time.time)
    task_name: str = ""
    overall_level: SecurityLevel = SecurityLevel.SAFE
    memory_ok: bool = True
    cpu_ok: bool = True
    temperature_ok: bool = True
    same_process_ok: bool = True
    details: dict = field(default_factory=dict)
    recommended_action: str = ""
    allowed_to_start: bool = True

    def to_dict(self):
        """转换为字典."""
        return {
            "check_id": self.check_id,
            "timestamp": self.timestamp,
            "task_name": self.task_name,
            "overall_level": self.overall_level.value,
            "memory_ok": self.memory_ok,
            "cpu_ok": self.cpu_ok,
            "temperature_ok": self.temperature_ok,
            "same_process_ok": self.same_process_ok,
            "details": self.details,
            "recommended_action": self.recommended_action,
            "allowed_to_start": self.allowed_to_start,
        }


# ============================================================
# 硬件保护报告模型
# ============================================================

@dataclass
class HardwareReport:
    """硬件保护报告.

    每日/每周硬件保护报告。
    """
    report_id: str = ""
    report_type: str = "daily"
    start_time: float = 0.0
    end_time: float = 0.0
    generated_time: float = field(default_factory=time.time)

    total_guard_interventions: int = 0
    cpu_interventions: int = 0
    memory_interventions: int = 0
    temperature_interventions: int = 0
    disk_interventions: int = 0

    avg_cpu_usage: float = 0.0
    avg_memory_usage: float = 0.0
    avg_temperature: float = 0.0
    peak_cpu_usage: float = 0.0
    peak_memory_usage: float = 0.0
    peak_temperature: float = 0.0

    top_cpu_processes: list = field(default_factory=list)
    top_memory_processes: list = field(default_factory=list)

    risk_events: list = field(default_factory=list)

    health_score: float = 100.0

    def to_dict(self):
        """转换为字典."""
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "generated_time": self.generated_time,
            "total_guard_interventions": self.total_guard_interventions,
            "cpu_interventions": self.cpu_interventions,
            "memory_interventions": self.memory_interventions,
            "temperature_interventions": self.temperature_interventions,
            "disk_interventions": self.disk_interventions,
            "avg_cpu_usage": self.avg_cpu_usage,
            "avg_memory_usage": self.avg_memory_usage,
            "avg_temperature": self.avg_temperature,
            "peak_cpu_usage": self.peak_cpu_usage,
            "peak_memory_usage": self.peak_memory_usage,
            "peak_temperature": self.peak_temperature,
            "top_cpu_processes": self.top_cpu_processes,
            "top_memory_processes": self.top_memory_processes,
            "risk_events": self.risk_events,
            "health_score": self.health_score,
        }


# ============================================================
# API 请求/响应模型 (Pydantic)
# ============================================================

class GuardPolicyUpdateRequest(BaseModel):
    """防护策略更新请求."""
    metric_type: str = Field(..., description="指标类型")
    info_threshold: float | None = Field(None, description="提示阈值")
    warning_threshold: float | None = Field(None, description="警告阈值")
    critical_threshold: float | None = Field(None, description="严重阈值")
    emergency_threshold: float | None = Field(None, description="紧急阈值")
    enabled: bool | None = Field(None, description="是否启用")


class StartupCheckRequest(BaseModel):
    """启动安全检查请求."""
    task_name: str = Field(..., description="任务名称")
    task_level: str = Field("normal", description="任务级别")
    estimated_cpu_percent: float = Field(10.0, description="预估CPU占用(%)")
    estimated_memory_mb: float = Field(100.0, description="预估内存占用(MB)")
    same_process_name: str | None = Field(None, description="同类进程名称")


class SandboxTaskSubmitRequest(BaseModel):
    """沙箱任务提交请求."""
    name: str = Field(..., description="任务名称")
    level: str = Field("normal", description="任务级别")
    priority: int = Field(5, ge=1, le=10, description="优先级(1-10)")
    estimated_cpu_percent: float = Field(10.0, description="预估CPU占用(%)")
    estimated_memory_mb: float = Field(100.0, description="预估内存占用(MB)")
    estimated_duration_seconds: float = Field(60.0, description="预估时长(秒)")
    callback_url: str = Field("", description="回调URL")
    task_data: dict = Field(default_factory=dict, description="任务数据")


class ReportGenerateRequest(BaseModel):
    """报告生成请求."""
    report_type: str = Field("daily", description="报告类型: daily/weekly")
    format: str = Field("markdown", description="输出格式: markdown/html")
    start_time: float | None = Field(None, description="开始时间戳")
    end_time: float | None = Field(None, description="结束时间戳")


# ============================================================
# 响应辅助函数
# ============================================================

def make_response(data=None, code: int = 0, message: str = "ok"):
    """构造统一响应格式.

    Args:
        data: 响应数据
        code: 状态码，0 表示成功
        message: 状态消息

    Returns:
        标准响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }
