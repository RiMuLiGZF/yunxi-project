"""
M8 管理工作台 - 工作流与系统设置模型

包含 WorkflowDefinition, WorkflowRun, SystemSetting。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from datetime import datetime

from .base import Base


class SystemSetting(Base):
    """系统设置表（key-value 存储）

    存储全局系统配置，如主题、语言、通知开关等。
    从 settings.json 迁移而来。
    """
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(100), unique=True, index=True, comment="设置键")
    setting_value = Column(JSON, default=dict, comment="设置值(JSON)")
    description = Column(String(255), default="", comment="说明")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="归属用户ID")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "key": self.setting_key,
            "value": self.setting_value,
            "description": self.description,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkflowDefinition(Base):
    """工作流定义表

    存储工作流的完整定义，包括积木块配置和连接关系。
    从 workflows.json 迁移而来。
    """
    __tablename__ = "workflow_definitions"

    id = Column(String(64), primary_key=True, index=True, comment="工作流ID")
    name = Column(String(200), index=True, default="", comment="工作流名称")
    description = Column(String(500), default="", comment="描述")
    category = Column(String(50), index=True, default="", comment="分类")
    icon = Column(String(20), default="", comment="图标")
    blocks = Column(JSON, default=list, comment="积木块配置(JSON数组)")
    status = Column(String(20), default="draft", index=True, comment="状态：draft/active/archived")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    user_id = Column(Integer, default=1, index=True, comment="归属用户ID")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "blocks": self.blocks or [],
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkflowRun(Base):
    """工作流运行历史表

    记录每次工作流执行的结果和耗时。
    从 workflow_runs.json 迁移而来。
    """
    __tablename__ = "workflow_runs"

    id = Column(String(64), primary_key=True, index=True, comment="运行ID")
    workflow_id = Column(String(64), index=True, comment="工作流ID")
    workflow_name = Column(String(200), default="", comment="工作流名称快照")
    status = Column(String(20), index=True, default="pending", comment="状态：pending/running/success/failed")
    inputs = Column(JSON, default=dict, comment="输入参数")
    outputs = Column(JSON, default=dict, comment="输出结果")
    error_message = Column(Text, default="", comment="错误信息")
    started_at = Column(DateTime, nullable=True, index=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, default=0, comment="耗时(ms)")
    user_id = Column(Integer, default=1, index=True, comment="归属用户ID")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "inputs": self.inputs or {},
            "outputs": self.outputs or {},
            "error_message": self.error_message,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "duration_ms": self.duration_ms,
        }
