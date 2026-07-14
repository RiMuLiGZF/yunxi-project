"""
M8 管理工作台 - 巡检Agent模型

包含 StartupCheckRecord, PrincipalChatSession, PrincipalChatMessage。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class StartupCheckRecord(Base):
    """巡检Agent - 启动快速检查记录表"""
    __tablename__ = "inspection_startup_checks"

    id = Column(Integer, primary_key=True, index=True)
    check_id = Column(String(64), unique=True, index=True, comment="检查记录ID")
    overall_status = Column(String(20), default="unknown", comment="总体状态：healthy/degraded/unhealthy/unknown")
    total_checks = Column(Integer, default=0, comment="总检查项数")
    passed_checks = Column(Integer, default=0, comment="通过检查项数")
    failed_checks = Column(Integer, default=0, comment="失败检查项数")
    duration_ms = Column(Integer, default=0, comment="检查耗时(ms)")
    check_results = Column(JSON, default=dict, comment="各检查项详细结果(JSON)")
    error_summary = Column(Text, default="", comment="错误摘要")
    triggered_by = Column(String(50), default="system", comment="触发方式：system/manual")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "check_id": self.check_id,
            "overall_status": self.overall_status,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "duration_ms": self.duration_ms,
            "check_results": self.check_results or {},
            "error_summary": self.error_summary or "",
            "triggered_by": self.triggered_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PrincipalChatSession(Base):
    """巡检Agent - 主理人调度Agent对话会话表"""
    __tablename__ = "inspection_principal_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), unique=True, index=True, comment="会话ID")
    title = Column(String(255), default="新会话", comment="会话标题")
    status = Column(String(20), default="active", comment="状态：active/archived")
    model_count = Column(Integer, default=0, comment="参与模型数量")
    total_tokens = Column(Integer, default=0, comment="总token数")
    total_cost = Column(Float, default=0.0, comment="总成本(元)")
    message_count = Column(Integer, default=0, comment="消息数")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status,
            "model_count": self.model_count,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PrincipalChatMessage(Base):
    """巡检Agent - 主理人调度Agent对话消息表"""
    __tablename__ = "inspection_principal_messages"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String(64), unique=True, index=True, comment="消息ID")
    session_id = Column(String(64), index=True, comment="所属会话ID")
    role = Column(String(20), default="user", comment="角色：user/assistant/system/tool")
    content = Column(Text, default="", comment="消息内容")
    model_key = Column(String(100), default="", comment="使用的模型key")
    model_name = Column(String(100), default="", comment="模型显示名称")
    source_id = Column(String(64), default="", comment="算力源ID")
    input_tokens = Column(Integer, default=0, comment="输入token数")
    output_tokens = Column(Integer, default=0, comment="输出token数")
    cost = Column(Float, default=0.0, comment="成本(元)")
    latency_ms = Column(Integer, default=0, comment="延迟(ms)")
    route_id = Column(String(64), default="", comment="路由ID")
    tool_calls = Column(JSON, default=list, comment="工具调用列表")
    extra_metadata = Column(JSON, default=dict, comment="额外元数据")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")

    def to_dict(self):
        return {
            "id": self.id,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "model_key": self.model_key,
            "model_name": self.model_name,
            "source_id": self.source_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": (self.input_tokens or 0) + (self.output_tokens or 0),
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "route_id": self.route_id,
            "tool_calls": self.tool_calls or [],
            "metadata": self.extra_metadata or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
