"""
M8 管理工作台 - 审计日志模型
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from datetime import datetime

from .base import Base


class AuditLog(Base):
    """算力调度 - 审计日志表"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=0, index=True, comment="用户ID")
    username = Column(String(50), index=True, comment="用户名")
    action = Column(String(50), index=True, comment="操作：create/update/delete/enable/disable/rotate_key等")
    module = Column(String(50), index=True, comment="模块：compute_source/compute_group/compute_model等")
    result = Column(String(20), default="success", comment="结果：success/failed")
    ip = Column(String(50), default="", comment="客户端IP")
    user_agent = Column(String(500), default="", comment="用户代理")
    details = Column(JSON, default=dict, comment="操作详情（JSON）")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "module": self.module,
            "result": self.result,
            "ip": self.ip,
            "user_agent": self.user_agent,
            "details": self.details or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
