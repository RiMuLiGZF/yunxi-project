'''
M10 系统卫士 - 数据库 ORM 模型

使用 SQLAlchemy ORM 定义所有持久化数据表：
- audit_logs: 审计日志
- guard_alerts: 防护告警记录
- metric_history: 系统指标历史
- guard_policies: 防护策略配置
- startup_checks: 启动检查记录
- reports: 报告记录
- tide_missions: 潮汐任务记录
'''

from __future__ import annotations

import time
import json

from sqlalchemy import Column, Integer, String, Float, Text, Boolean, DateTime, Index
from sqlalchemy import func

from .database import Base


class AuditLogDB(Base):
    '''审计日志表.'''
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(String(32), unique=True, index=True)
    timestamp = Column(Float, index=True, default=time.time)
    level = Column(String(20), index=True)  # info/warning/critical
    log_type = Column(String(100), index=True)
    trigger_condition = Column(String(500))
    action = Column(String(500))
    result = Column(String(500))
    details_json = Column(Text, default='{}')  # JSON 字符串存储详细信息
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_audit_time_level', 'timestamp', 'level'),
    )

    def to_dict(self):
        return {
            'log_id': self.log_id,
            'timestamp': self.timestamp,
            'level': self.level,
            'log_type': self.log_type,
            'trigger_condition': self.trigger_condition,
            'action': self.action,
            'result': self.result,
            'details': json.loads(self.details_json) if self.details_json else {},
        }


class GuardAlertDB(Base):
    '''防护告警记录表.'''
    __tablename__ = 'guard_alerts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(32), unique=True, index=True)
    timestamp = Column(Float, index=True, default=time.time)
    level = Column(String(20), index=True)  # info/warning/critical/emergency
    metric_type = Column(String(50), index=True)  # cpu/memory/disk/temperature
    current_value = Column(Float)
    threshold_value = Column(Float)
    message = Column(String(500))
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(Float, nullable=True)
    acknowledged_by = Column(String(100), nullable=True)
    details_json = Column(Text, default='{}')
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_alert_time_level', 'timestamp', 'level'),
    )

    def to_dict(self):
        return {
            'alert_id': self.alert_id,
            'timestamp': self.timestamp,
            'level': self.level,
            'metric_type': self.metric_type,
            'current_value': self.current_value,
            'threshold_value': self.threshold_value,
            'message': self.message,
            'acknowledged': self.acknowledged,
            'acknowledged_at': self.acknowledged_at,
            'details': json.loads(self.details_json) if self.details_json else {},
        }


class MetricHistoryDB(Base):
    '''系统指标历史表.'''
    __tablename__ = 'metric_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Float, index=True, default=time.time)
    metric_type = Column(String(50), index=True)  # cpu/memory/disk/network/gpu/temperature/battery
    aggregation_level = Column(String(20), index=True, default='raw')  # raw/minute/hour/day
    value_json = Column(Text, default='{}')  # JSON 存储完整指标数据
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_metric_time_type_agg', 'timestamp', 'metric_type', 'aggregation_level'),
    )

    def to_dict(self):
        return {
            'timestamp': self.timestamp,
            'metric_type': self.metric_type,
            'aggregation_level': self.aggregation_level,
            'value': json.loads(self.value_json) if self.value_json else {},
        }


class GuardPolicyDB(Base):
    '''防护策略配置表.'''
    __tablename__ = 'guard_policies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    metric_type = Column(String(50), unique=True, index=True)  # cpu/memory/disk/temperature
    info_threshold = Column(Float)
    warning_threshold = Column(Float)
    critical_threshold = Column(Float)
    emergency_threshold = Column(Float)
    enabled = Column(Boolean, default=True)
    updated_at = Column(Float, default=time.time, onupdate=time.time)
    created_at = Column(Float, default=time.time)

    def to_dict(self):
        return {
            'metric_type': self.metric_type,
            'info_threshold': self.info_threshold,
            'warning_threshold': self.warning_threshold,
            'critical_threshold': self.critical_threshold,
            'emergency_threshold': self.emergency_threshold,
            'enabled': self.enabled,
            'updated_at': self.updated_at,
        }


class StartupCheckDB(Base):
    '''启动检查记录表.'''
    __tablename__ = 'startup_checks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(String(32), unique=True, index=True)
    timestamp = Column(Float, index=True, default=time.time)
    overall_level = Column(String(20), index=True)  # safe/warning/danger
    memory_free_percent = Column(Float)
    cpu_usage_percent = Column(Float)
    max_temperature = Column(Float)
    same_process_count = Column(Integer)
    details_json = Column(Text, default='{}')
    recommendation = Column(Text, default='')
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_startup_time_level', 'timestamp', 'overall_level'),
    )

    def to_dict(self):
        return {
            'check_id': self.check_id,
            'timestamp': self.timestamp,
            'overall_level': self.overall_level,
            'memory_free_percent': self.memory_free_percent,
            'cpu_usage_percent': self.cpu_usage_percent,
            'max_temperature': self.max_temperature,
            'same_process_count': self.same_process_count,
            'details': json.loads(self.details_json) if self.details_json else {},
            'recommendation': self.recommendation,
        }


class ReportDB(Base):
    '''报告记录表.'''
    __tablename__ = 'reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(32), unique=True, index=True)
    report_type = Column(String(20), index=True)  # daily/weekly
    period_start = Column(Float, index=True)
    period_end = Column(Float, index=True)
    title = Column(String(200))
    health_score = Column(Float)
    summary = Column(Text, default='')
    markdown_content = Column(Text, default='')
    html_content = Column(Text, default='')
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_report_type_time', 'report_type', 'period_start'),
    )

    def to_dict(self):
        return {
            'report_id': self.report_id,
            'report_type': self.report_type,
            'period_start': self.period_start,
            'period_end': self.period_end,
            'title': self.title,
            'health_score': self.health_score,
            'summary': self.summary,
            'created_at': self.created_at,
        }


class TideMissionDB(Base):
    '''潮汐任务记录表.'''
    __tablename__ = 'tide_missions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    mission_id = Column(String(32), unique=True, index=True)
    timestamp = Column(Float, index=True, default=time.time)
    name = Column(String(200))
    priority = Column(String(20), index=True)  # critical/high/normal/low/batch
    status = Column(String(20), index=True)  # pending/running/completed/cancelled/rejected
    estimated_memory_mb = Column(Float)
    actual_memory_mb = Column(Float)
    estimated_duration_sec = Column(Float)
    actual_duration_sec = Column(Float, nullable=True)
    submitted_by = Column(String(100), default='system')
    started_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=True)
    result_json = Column(Text, default='{}')
    created_at = Column(Float, default=time.time)

    __table_args__ = (
        Index('idx_tide_status_time', 'status', 'timestamp'),
    )

    def to_dict(self):
        return {
            'mission_id': self.mission_id,
            'timestamp': self.timestamp,
            'name': self.name,
            'priority': self.priority,
            'status': self.status,
            'estimated_memory_mb': self.estimated_memory_mb,
            'actual_memory_mb': self.actual_memory_mb,
            'estimated_duration_sec': self.estimated_duration_sec,
            'actual_duration_sec': self.actual_duration_sec,
            'submitted_by': self.submitted_by,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'result': json.loads(self.result_json) if self.result_json else {},
        }
