"""M7 积木平台 - 数据库模型.

P2-25/P2-26: 从 JSON 迁移到 SQLite 的 SQLAlchemy 模型定义。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Index

from .db import Base


class WorkflowDefinition(Base):
    """工作流定义表.

    存储工作流的完整配置，包括积木块、连接、变量、触发器等。
    从 m7_workflows.json 迁移而来。
    """
    __tablename__ = "workflow_definitions"

    id = Column(String(64), primary_key=True, index=True, comment="工作流ID")
    name = Column(String(200), index=True, default="", comment="工作流名称")
    description = Column(Text, default="", comment="描述")
    category = Column(String(50), index=True, default="", comment="分类")
    status = Column(String(20), index=True, default="draft", comment="状态：draft/published/archived")
    blocks = Column(JSON, default=list, comment="积木块列表(JSON)")
    connections = Column(JSON, default=list, comment="连接线列表(JSON)")
    variables = Column(JSON, default=list, comment="变量定义(JSON)")
    trigger = Column(JSON, default=dict, comment="触发器配置(JSON)")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    run_count = Column(Integer, default=0, comment="运行次数")
    created_by = Column(String(50), default="", comment="创建者")
    tags = Column(JSON, default=list, comment="标签列表(JSON)")

    __table_args__ = (
        Index("ix_wf_name_category", "name", "category"),
    )

    def to_dict(self) -> dict:
        """转换为字典（与 JSON 存储格式兼容）."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "status": self.status,
            "blocks": self.blocks or [],
            "connections": self.connections or [],
            "variables": self.variables or [],
            "trigger": self.trigger or {},
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
            "run_count": self.run_count or 0,
            "created_by": self.created_by,
            "tags": self.tags or [],
        }


class WorkflowRunRecord(Base):
    """工作流运行记录表.

    记录每次工作流执行的详细过程和结果。
    从 m7_runs.json 迁移而来。
    """
    __tablename__ = "workflow_runs"

    id = Column(String(64), primary_key=True, index=True, comment="运行ID")
    workflow_id = Column(String(64), index=True, comment="工作流ID")
    workflow_name = Column(String(200), default="", comment="工作流名称快照")
    status = Column(String(20), index=True, default="pending", comment="状态：pending/running/success/failed/cancelled")
    steps = Column(JSON, default=list, comment="各步骤执行结果(JSON)")
    inputs = Column(JSON, default=dict, comment="输入参数(JSON)")
    outputs = Column(JSON, default=dict, comment="输出结果(JSON)")
    error = Column(Text, default="", comment="错误信息")
    started_at = Column(DateTime, nullable=True, index=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_ms = Column(Integer, default=0, comment="耗时(ms)")
    triggered_by = Column(String(50), default="", comment="触发方式：manual/schedule/api")

    __table_args__ = (
        Index("ix_run_wfid_status", "workflow_id", "status"),
    )

    def to_dict(self) -> dict:
        """转换为字典（与 JSON 存储格式兼容）."""
        return {
            "run_id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "steps": self.steps or [],
            "inputs": self.inputs or {},
            "outputs": self.outputs or {},
            "error": self.error,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%Y-%m-%d %H:%M:%S") if self.finished_at else None,
            "duration_ms": self.duration_ms or 0,
            "triggered_by": self.triggered_by,
        }


class CustomBlock(Base):
    """自定义积木表.

    存储用户创建的自定义积木块定义，包括端口配置和代码逻辑。
    """
    __tablename__ = "custom_blocks"

    id = Column(String(64), primary_key=True, index=True, comment="自定义积木ID")
    name = Column(String(200), index=True, default="", comment="积木名称")
    category = Column(String(50), index=True, default="工具块", comment="分类：工具块/数据块/逻辑块")
    description = Column(Text, default="", comment="描述")
    code = Column(Text, default="", comment="积木逻辑代码")
    icon = Column(String(50), default="puzzle", comment="图标标识")
    ports = Column(JSON, default=dict, comment="端口定义(JSON): {inputs: [...], outputs: [...]}")
    user_id = Column(String(50), index=True, default="", comment="创建者用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("ix_cb_user_category", "user_id", "category"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "code": self.code,
            "icon": self.icon,
            "ports": self.ports or {"inputs": [], "outputs": []},
            "user_id": self.user_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }
