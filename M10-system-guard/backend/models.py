"""
云汐 M10 系统卫士 - 数据模型模块
使用 SQLAlchemy 定义数据库表结构，包含7张核心表
"""

import sys
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

# 兼容相对导入和直接运行
try:
    from .database import Base, engine, SessionLocal, init_db
except ImportError:
    from database import Base, engine, SessionLocal, init_db

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    JSON,
    Index,
)


# ===== 工具函数：统一响应格式 =====

def make_response(data: Any = None, code: int = 0, message: str = "success") -> dict:
    """
    构造统一格式的API响应

    Args:
        data: 响应数据
        code: 状态码，0表示成功
        message: 状态消息

    Returns:
        统一格式的响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data,
    }


def make_error_response(message: str, code: int = -1, data: Any = None) -> dict:
    """
    构造错误响应

    Args:
        message: 错误消息
        code: 错误码
        data: 附加数据

    Returns:
        错误响应字典
    """
    return make_response(data=data, code=code, message=message)


# ===== 数据模型定义 =====

class SystemMetric(Base):
    """系统指标表 - 秒级原始数据"""
    __tablename__ = "system_metrics"

    id = Column(Integer, primary_key=True, index=True, comment="记录ID")
    timestamp = Column(DateTime, default=datetime.now, index=True, comment="采集时间")

    # CPU 指标
    cpu_percent = Column(Float, default=0.0, comment="整体CPU使用率(%)")
    cpu_percent_per_core = Column(JSON, default=list, comment="各核心使用率列表")
    cpu_load_avg = Column(JSON, default=list, comment="1/5/15分钟负载均值")
    cpu_freq_current = Column(Float, default=0.0, comment="当前主频(MHz)")
    cpu_freq_min = Column(Float, default=0.0, comment="最低主频(MHz)")
    cpu_freq_max = Column(Float, default=0.0, comment="最高主频(MHz)")
    cpu_temp = Column(Float, default=0.0, comment="CPU温度(°C)")
    cpu_fan_speed = Column(Float, default=0.0, comment="风扇转速(RPM)")

    # 内存指标
    mem_total_gb = Column(Float, default=0.0, comment="总内存(GB)")
    mem_available_gb = Column(Float, default=0.0, comment="可用内存(GB)")
    mem_used_gb = Column(Float, default=0.0, comment="已用内存(GB)")
    mem_percent = Column(Float, default=0.0, comment="内存使用率(%)")
    mem_swap_total_gb = Column(Float, default=0.0, comment="虚拟内存总量(GB)")
    mem_swap_used_gb = Column(Float, default=0.0, comment="虚拟内存已用(GB)")
    mem_swap_percent = Column(Float, default=0.0, comment="虚拟内存使用率(%)")
    mem_cache_gb = Column(Float, default=0.0, comment="缓存内存(GB)")

    # 磁盘指标
    disk_read_speed_mb = Column(Float, default=0.0, comment="磁盘读取速度(MB/s)")
    disk_write_speed_mb = Column(Float, default=0.0, comment="磁盘写入速度(MB/s)")
    disk_read_count = Column(Integer, default=0, comment="累计读次数")
    disk_write_count = Column(Integer, default=0, comment="累计写次数")
    disk_busy_percent = Column(Float, default=0.0, comment="磁盘繁忙度(%)")
    disk_usage = Column(JSON, default=dict, comment="各分区使用率详情")

    # 网络指标
    net_up_speed_kb = Column(Float, default=0.0, comment="上传速度(KB/s)")
    net_down_speed_kb = Column(Float, default=0.0, comment="下载速度(KB/s)")
    net_total_sent_mb = Column(Float, default=0.0, comment="累计上传(MB)")
    net_total_recv_mb = Column(Float, default=0.0, comment="累计下载(MB)")
    net_connection_count = Column(Integer, default=0, comment="网络连接数")
    net_latency_ms = Column(Float, default=0.0, comment="网络延迟(ms)")
    net_packet_loss = Column(Float, default=0.0, comment="丢包率(%)")

    # GPU 指标
    gpu_count = Column(Integer, default=0, comment="GPU数量")
    gpu_name = Column(String(255), default="", comment="GPU型号名称")
    gpu_percent = Column(Float, default=0.0, comment="GPU使用率(%)")
    gpu_mem_total_gb = Column(Float, default=0.0, comment="显存总量(GB)")
    gpu_mem_used_gb = Column(Float, default=0.0, comment="显存已用(GB)")
    gpu_mem_percent = Column(Float, default=0.0, comment="显存使用率(%)")
    gpu_temp = Column(Float, default=0.0, comment="GPU温度(°C)")
    gpu_power_watt = Column(Float, default=0.0, comment="GPU功耗(W)")

    # 电池指标
    battery_percent = Column(Float, default=100.0, comment="电池电量(%)")
    battery_power_plugged = Column(Boolean, default=True, comment="是否接通电源")
    battery_secs_left = Column(Integer, default=0, comment="剩余续航(秒)")
    battery_health_percent = Column(Float, default=100.0, comment="电池健康度(%)")
    battery_cycle_count = Column(Integer, default=0, comment="电池循环次数")

    # 系统信息
    uptime_seconds = Column(Integer, default=0, comment="系统已运行时长(秒)")
    process_count = Column(Integer, default=0, comment="进程总数")

    __table_args__ = (
        Index("idx_system_metrics_timestamp", "timestamp"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "cpu": {
                "percent": self.cpu_percent,
                "percent_per_core": self.cpu_percent_per_core or [],
                "load_avg": self.cpu_load_avg or [],
                "freq_current": self.cpu_freq_current,
                "freq_min": self.cpu_freq_min,
                "freq_max": self.cpu_freq_max,
                "temp": self.cpu_temp,
                "fan_speed": self.cpu_fan_speed,
            },
            "memory": {
                "total_gb": self.mem_total_gb,
                "available_gb": self.mem_available_gb,
                "used_gb": self.mem_used_gb,
                "percent": self.mem_percent,
                "swap_total_gb": self.mem_swap_total_gb,
                "swap_used_gb": self.mem_swap_used_gb,
                "swap_percent": self.mem_swap_percent,
                "cache_gb": self.mem_cache_gb,
            },
            "disk": {
                "read_speed_mb": self.disk_read_speed_mb,
                "write_speed_mb": self.disk_write_speed_mb,
                "read_count": self.disk_read_count,
                "write_count": self.disk_write_count,
                "busy_percent": self.disk_busy_percent,
                "usage": self.disk_usage or {},
            },
            "network": {
                "up_speed_kb": self.net_up_speed_kb,
                "down_speed_kb": self.net_down_speed_kb,
                "total_sent_mb": self.net_total_sent_mb,
                "total_recv_mb": self.net_total_recv_mb,
                "connection_count": self.net_connection_count,
                "latency_ms": self.net_latency_ms,
                "packet_loss": self.net_packet_loss,
            },
            "gpu": {
                "count": self.gpu_count,
                "name": self.gpu_name,
                "percent": self.gpu_percent,
                "mem_total_gb": self.gpu_mem_total_gb,
                "mem_used_gb": self.gpu_mem_used_gb,
                "mem_percent": self.gpu_mem_percent,
                "temp": self.gpu_temp,
                "power_watt": self.gpu_power_watt,
            },
            "battery": {
                "percent": self.battery_percent,
                "power_plugged": self.battery_power_plugged,
                "secs_left": self.battery_secs_left,
                "health_percent": self.battery_health_percent,
                "cycle_count": self.battery_cycle_count,
            },
            "system": {
                "uptime_seconds": self.uptime_seconds,
                "process_count": self.process_count,
            },
        }


class ProcessSnapshot(Base):
    """进程快照表"""
    __tablename__ = "process_snapshot"

    id = Column(Integer, primary_key=True, index=True, comment="记录ID")
    snapshot_time = Column(DateTime, default=datetime.now, index=True, comment="快照时间")
    pid = Column(Integer, index=True, comment="进程ID")
    ppid = Column(Integer, default=0, comment="父进程ID")
    name = Column(String(255), index=True, default="", comment="进程名")
    exe_path = Column(String(1024), default="", comment="可执行文件路径")
    cmdline = Column(Text, default="", comment="命令行参数")
    username = Column(String(255), default="", comment="运行用户")
    cpu_percent = Column(Float, default=0.0, comment="CPU使用率(%)")
    cpu_time_user = Column(Float, default=0.0, comment="用户态CPU时间(秒)")
    cpu_time_system = Column(Float, default=0.0, comment="内核态CPU时间(秒)")
    mem_rss_mb = Column(Float, default=0.0, comment="物理内存(MB)")
    mem_vms_mb = Column(Float, default=0.0, comment="虚拟内存(MB)")
    mem_percent = Column(Float, default=0.0, comment="内存占比(%)")
    num_threads = Column(Integer, default=0, comment="线程数")
    num_handles = Column(Integer, default=0, comment="句柄数")
    status = Column(String(50), default="running", comment="进程状态")
    create_time = Column(DateTime, nullable=True, comment="进程启动时间")
    io_read_mb = Column(Float, default=0.0, comment="累计读磁盘(MB)")
    io_write_mb = Column(Float, default=0.0, comment="累计写磁盘(MB)")
    net_connections = Column(Integer, default=0, comment="网络连接数")
    category = Column(String(100), default="unknown", comment="进程分类")
    is_yunxi = Column(Boolean, default=False, comment="是否云汐系统进程")
    yunxi_module = Column(String(50), default="", comment="所属云汐模块")

    __table_args__ = (
        Index("idx_process_snapshot_time", "snapshot_time"),
        Index("idx_process_snapshot_pid", "pid"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "snapshot_time": self.snapshot_time.isoformat() if self.snapshot_time else None,
            "pid": self.pid,
            "ppid": self.ppid,
            "name": self.name,
            "exe_path": self.exe_path,
            "cmdline": self.cmdline,
            "username": self.username,
            "cpu_percent": self.cpu_percent,
            "cpu_time_user": self.cpu_time_user,
            "cpu_time_system": self.cpu_time_system,
            "mem_rss_mb": self.mem_rss_mb,
            "mem_vms_mb": self.mem_vms_mb,
            "mem_percent": self.mem_percent,
            "num_threads": self.num_threads,
            "num_handles": self.num_handles,
            "status": self.status,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "io_read_mb": self.io_read_mb,
            "io_write_mb": self.io_write_mb,
            "net_connections": self.net_connections,
            "category": self.category,
            "is_yunxi": self.is_yunxi,
            "yunxi_module": self.yunxi_module,
        }


class Alert(Base):
    """告警记录表"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True, comment="告警ID")
    alert_type = Column(String(100), index=True, default="", comment="告警类型")
    level = Column(String(50), index=True, default="info", comment="告警级别")
    title = Column(String(255), default="", comment="告警标题")
    message = Column(Text, default="", comment="告警详情")
    metric_name = Column(String(100), default="", comment="关联指标名")
    metric_value = Column(Float, default=0.0, comment="指标当前值")
    threshold = Column(Float, default=0.0, comment="告警阈值")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="告警时间")
    acknowledged = Column(Boolean, default=False, comment="是否已确认")
    acknowledged_at = Column(DateTime, nullable=True, comment="确认时间")
    resolved = Column(Boolean, default=False, comment="是否已解决")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")
    resolution_note = Column(Text, default="", comment="解决说明")
    source = Column(String(100), default="system", comment="告警来源")
    extra_data = Column(JSON, default=dict, comment="附加数据")

    __table_args__ = (
        Index("idx_alerts_created_at", "created_at"),
        Index("idx_alerts_level", "level"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "alert_type": self.alert_type,
            "level": self.level,
            "title": self.title,
            "message": self.message,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_note": self.resolution_note,
            "source": self.source,
            "extra_data": self.extra_data or {},
        }


class TideModeHistory(Base):
    """潮汐模式历史表（B部分用，先占位）"""
    __tablename__ = "tide_mode_history"

    id = Column(Integer, primary_key=True, index=True, comment="记录ID")
    mode_name = Column(String(50), default="normal", comment="潮汐模式名称")
    mode_type = Column(String(50), default="normal", comment="模式类型")
    trigger_reason = Column(String(255), default="", comment="切换原因")
    started_at = Column(DateTime, default=datetime.now, comment="开始时间")
    ended_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_seconds = Column(Integer, default=0, comment="持续时长(秒)")
    cpu_saved_percent = Column(Float, default=0.0, comment="节省CPU(%)")
    memory_saved_mb = Column(Float, default=0.0, comment="节省内存(MB)")
    battery_saved_percent = Column(Float, default=0.0, comment="节省电量(%)")
    status = Column(String(50), default="active", comment="状态")
    notes = Column(Text, default="", comment="备注")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "mode_name": self.mode_name,
            "mode_type": self.mode_type,
            "trigger_reason": self.trigger_reason,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "cpu_saved_percent": self.cpu_saved_percent,
            "memory_saved_mb": self.memory_saved_mb,
            "battery_saved_percent": self.battery_saved_percent,
            "status": self.status,
            "notes": self.notes,
        }


class ProcessWhitelist(Base):
    """进程白名单表"""
    __tablename__ = "process_whitelist"

    id = Column(Integer, primary_key=True, index=True, comment="白名单ID")
    process_name = Column(String(255), unique=True, nullable=False, comment="进程名")
    process_path = Column(String(1024), default="", comment="进程路径（可选）")
    category = Column(String(100), default="system", comment="分类")
    description = Column(Text, default="", comment="说明")
    added_by = Column(String(100), default="system", comment="添加者")
    added_at = Column(DateTime, default=datetime.now, comment="添加时间")
    is_builtin = Column(Boolean, default=True, comment="是否内置")
    enabled = Column(Boolean, default=True, comment="是否启用")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "process_name": self.process_name,
            "process_path": self.process_path,
            "category": self.category,
            "description": self.description,
            "added_by": self.added_by,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "is_builtin": self.is_builtin,
            "enabled": self.enabled,
        }


class ProcessBlacklist(Base):
    """进程黑名单表"""
    __tablename__ = "process_blacklist"

    id = Column(Integer, primary_key=True, index=True, comment="黑名单ID")
    process_name = Column(String(255), unique=True, nullable=False, comment="进程名")
    process_path = Column(String(1024), default="", comment="进程路径（可选）")
    threat_level = Column(String(50), default="low", comment="威胁等级")
    description = Column(Text, default="", comment="威胁说明")
    added_by = Column(String(100), default="system", comment="添加者")
    added_at = Column(DateTime, default=datetime.now, comment="添加时间")
    is_builtin = Column(Boolean, default=True, comment="是否内置")
    enabled = Column(Boolean, default=True, comment="是否启用")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "process_name": self.process_name,
            "process_path": self.process_path,
            "threat_level": self.threat_level,
            "description": self.description,
            "added_by": self.added_by,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "is_builtin": self.is_builtin,
            "enabled": self.enabled,
        }


class StartupCheckLog(Base):
    """启动安全检查调用记录表"""
    __tablename__ = "startup_check_log"

    id = Column(Integer, primary_key=True, index=True, comment="记录ID")
    module = Column(String(50), index=True, default="", comment="调用模块")
    task_type = Column(String(100), default="", comment="任务类型")
    expected_memory_mb = Column(Integer, default=0, comment="预期内存(MB)")
    expected_cpu_percent = Column(Float, default=0.0, comment="预期CPU(%)")
    instance_count = Column(Integer, default=1, comment="实例数量")
    priority = Column(String(50), default="normal", comment="优先级")
    score = Column(Float, default=0.0, comment="安全评分")
    level = Column(String(50), default="safe", comment="安全等级")
    can_start = Column(Boolean, default=True, comment="是否建议启动")
    recommendation = Column(Text, default="", comment="建议")
    current_state = Column(JSON, default=dict, comment="检查时系统状态")
    after_projection = Column(JSON, default=dict, comment="启动后预测状态")
    suggestions = Column(JSON, default=list, comment="建议列表")
    checked_at = Column(DateTime, default=datetime.now, index=True, comment="检查时间")

    __table_args__ = (
        Index("idx_startup_check_module", "module"),
        Index("idx_startup_check_time", "checked_at"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "module": self.module,
            "task_type": self.task_type,
            "expected_memory_mb": self.expected_memory_mb,
            "expected_cpu_percent": self.expected_cpu_percent,
            "instance_count": self.instance_count,
            "priority": self.priority,
            "score": self.score,
            "level": self.level,
            "can_start": self.can_start,
            "recommendation": self.recommendation,
            "current_state": self.current_state or {},
            "after_projection": self.after_projection or {},
            "suggestions": self.suggestions or [],
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


# ===== Pydantic 响应模型（如果可用） =====
try:
    from pydantic import BaseModel, Field
    from typing import List as PydanticList

    class StartupCheckRequest(BaseModel):
        """启动安全检查请求"""
        module: str
        task_type: str
        expected_memory_mb: int = 0
        expected_cpu_percent: float = 0.0
        instance_count: int = 1
        priority: str = "normal"

    class WhitelistAddRequest(BaseModel):
        """添加白名单请求"""
        process_name: str
        process_path: str = ""
        category: str = "custom"
        description: str = ""

    class BlacklistAddRequest(BaseModel):
        """添加黑名单请求"""
        process_name: str
        process_path: str = ""
        threat_level: str = "medium"
        description: str = ""

    class AlertResolveRequest(BaseModel):
        """告警解决请求"""
        note: str = ""

    class AlertSettingsUpdate(BaseModel):
        """告警设置更新请求"""
        memory_warning_threshold: float = 80.0
        memory_danger_threshold: float = 90.0
        cpu_warning_threshold: float = 80.0
        cpu_danger_threshold: float = 90.0
        alert_suppression_minutes: int = 5
        enabled: bool = True

except ImportError:
    # 如果没有 pydantic，跳过响应模型定义
    pass


# 兼容直接运行：初始化数据库
if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化")
    print("已创建表:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
