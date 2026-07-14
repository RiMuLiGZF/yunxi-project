"""
M8 管理工作台 - 用户与模块模型

包含用户表、模块记录表、任务记录表、告警记录表。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float, JSON
from datetime import datetime

from .base import Base


class User(Base):
    """用户表

    P2-21: 扩展字段以对齐 users.json 数据结构，
    支持 nickname/email/status 等完整用户属性。
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="viewer", index=True)  # owner/admin/operator/viewer
    nickname = Column(String(100), default="")  # P2-21: 昵称
    email = Column(String(255), default="")     # P2-21: 邮箱
    status = Column(String(20), default="active", index=True)  # P2-21: active/disabled
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "nickname": self.nickname,
            "email": self.email,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "last_login": self.last_login.strftime("%Y-%m-%d %H:%M:%S") if self.last_login else None,
        }


class ModuleRecord(Base):
    """模块记录表"""
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True, index=True)
    module_key = Column(String(20), unique=True, index=True)
    name = Column(String(100))
    version = Column(String(50))
    status = Column(String(20), default="stopped")  # running/stopped/error
    port = Column(Integer)
    base_url = Column(String(255))
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskRecord(Base):
    """任务记录表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, index=True)
    title = Column(String(255))
    status = Column(String(20), default="pending")  # pending/running/completed/failed
    module = Column(String(20))  # 提交到的模块
    input_data = Column(Text)
    output_data = Column(Text, nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AlertRecord(Base):
    """告警记录表"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20))  # info/warning/error/critical
    title = Column(String(255))
    content = Column(Text)  # 告警详情内容
    source = Column(String(50))  # 来源模块（system/m1/m2/...）
    status = Column(String(20), default="active")  # active/acknowledged/resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)  # 确认时间
    acknowledged_by = Column(String(50), nullable=True)  # 确认人
    resolved_at = Column(DateTime, nullable=True)  # 解决时间
    resolved_by = Column(String(50), nullable=True)  # 解决人
