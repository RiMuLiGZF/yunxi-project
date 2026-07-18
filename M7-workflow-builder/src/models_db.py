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


# ============================================================
# P2 持久化执行引擎 - 增强运行时表
# ============================================================

class PersistentWorkflowRun(Base):
    """持久化工作流运行表.

    增强版运行记录，支持断点恢复、上下文快照、优先级、并发控制。
    与 workflow_runs 表并存，作为持久化执行引擎的主表。
    """
    __tablename__ = "persistent_workflow_runs"

    id = Column(String(64), primary_key=True, index=True, comment="运行ID")
    workflow_id = Column(String(64), index=True, comment="工作流ID")
    workflow_name = Column(String(200), default="", comment="工作流名称快照")
    status = Column(String(20), index=True, default="pending",
                    comment="状态：pending/running/completed/failed/cancelled/dead_letter")
    current_node_id = Column(String(64), default="", comment="当前执行节点ID")
    context_data = Column(JSON, default=dict, comment="执行上下文快照(JSON)")
    step_results = Column(JSON, default=dict, comment="节点执行结果映射(JSON)")
    start_time = Column(DateTime, nullable=True, index=True, comment="开始时间")
    end_time = Column(DateTime, nullable=True, comment="结束时间")
    created_by = Column(String(50), default="", comment="创建者/触发者")
    priority = Column(Integer, default=5, index=True, comment="优先级 1-10，默认5，越大越高")
    result_summary = Column(JSON, default=dict, comment="结果摘要(JSON)")
    error_message = Column(Text, default="", comment="错误信息")
    retry_count = Column(Integer, default=0, comment="重试次数")
    max_retries = Column(Integer, default=0, comment="最大重试次数")
    trigger_type = Column(String(20), default="manual", comment="触发方式：manual/schedule/webhook/event")
    trigger_id = Column(String(64), default="", index=True, comment="触发器ID")
    input_data = Column(JSON, default=dict, comment="输入数据(JSON)")
    timeout_seconds = Column(Integer, default=300, comment="超时时间(秒)")
    last_heartbeat = Column(DateTime, nullable=True, index=True, comment="最后心跳时间")
    version = Column(Integer, default=1, comment="乐观锁版本号")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("ix_persist_wfid_status", "workflow_id", "status"),
        Index("ix_persist_status_priority", "status", "priority"),
        Index("ix_persist_trigger_type", "trigger_type", "status"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "run_id": self.id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "current_node_id": self.current_node_id,
            "context_data": self.context_data or {},
            "step_results": self.step_results or {},
            "start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S") if self.start_time else None,
            "end_time": self.end_time.strftime("%Y-%m-%d %H:%M:%S") if self.end_time else None,
            "created_by": self.created_by,
            "priority": self.priority,
            "result_summary": self.result_summary or {},
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "trigger_type": self.trigger_type,
            "trigger_id": self.trigger_id,
            "input_data": self.input_data or {},
            "timeout_seconds": self.timeout_seconds,
            "last_heartbeat": self.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S") if self.last_heartbeat else None,
            "version": self.version,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class ExecutionContextSnapshot(Base):
    """执行上下文快照表.

    存储工作流执行过程中的上下文快照，用于断点恢复和调试。
    """
    __tablename__ = "execution_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="快照ID")
    run_id = Column(String(64), index=True, comment="运行ID")
    node_id = Column(String(64), default="", comment="快照所在节点ID")
    context_data = Column(JSON, default=dict, comment="上下文数据(JSON)")
    step_results = Column(JSON, default=dict, comment="已完成节点结果(JSON)")
    variables = Column(JSON, default=dict, comment="变量状态(JSON)")
    snapshot_type = Column(String(20), default="node_complete",
                           comment="快照类型：node_start/node_complete/error/checkpoint")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    __table_args__ = (
        Index("ix_ctx_runid_type", "run_id", "snapshot_type"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "context_data": self.context_data or {},
            "step_results": self.step_results or {},
            "variables": self.variables or {},
            "snapshot_type": self.snapshot_type,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


# ============================================================
# P2 触发器系统 - 触发器表
# ============================================================

class TriggerDefinition(Base):
    """触发器定义表.

    存储所有类型的触发器配置，支持 Schedule/Webhook/Event。
    """
    __tablename__ = "triggers"

    id = Column(String(64), primary_key=True, index=True, comment="触发器ID")
    name = Column(String(200), default="", comment="触发器名称")
    description = Column(Text, default="", comment="描述")
    workflow_id = Column(String(64), index=True, comment="关联的工作流ID")
    trigger_type = Column(String(20), index=True, default="schedule",
                          comment="类型：schedule/webhook/event")
    enabled = Column(Integer, default=0, index=True, comment="是否启用 0=否 1=是")
    config = Column(JSON, default=dict, comment="触发器配置(JSON)")
    input_mapping = Column(JSON, default=dict, comment="输入参数映射(JSON)")
    filter_config = Column(JSON, default=dict, comment="事件过滤配置(JSON)")
    webhook_secret = Column(String(100), default="", comment="Webhook签名密钥")
    webhook_path = Column(String(200), default="", index=True, comment="Webhook路径")
    timezone = Column(String(50), default="Asia/Shanghai", comment="时区")
    last_triggered_at = Column(DateTime, nullable=True, comment="上次触发时间")
    trigger_count = Column(Integer, default=0, comment="触发次数")
    success_count = Column(Integer, default=0, comment="成功次数")
    failed_count = Column(Integer, default=0, comment="失败次数")
    created_by = Column(String(50), default="", comment="创建者")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("ix_trigger_wfid_type", "workflow_id", "trigger_type"),
        Index("ix_trigger_enabled_type", "enabled", "trigger_type"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "workflow_id": self.workflow_id,
            "trigger_type": self.trigger_type,
            "enabled": bool(self.enabled),
            "config": self.config or {},
            "input_mapping": self.input_mapping or {},
            "filter_config": self.filter_config or {},
            "webhook_secret": self.webhook_secret,
            "webhook_path": self.webhook_path,
            "timezone": self.timezone,
            "last_triggered_at": self.last_triggered_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_triggered_at else None,
            "trigger_count": self.trigger_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "created_by": self.created_by,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class TriggerHistory(Base):
    """触发历史表.

    记录每次触发器的执行情况。
    """
    __tablename__ = "trigger_history"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="历史记录ID")
    trigger_id = Column(String(64), index=True, comment="触发器ID")
    workflow_id = Column(String(64), index=True, comment="工作流ID")
    run_id = Column(String(64), default="", index=True, comment="生成的运行ID")
    trigger_type = Column(String(20), default="schedule", comment="触发器类型")
    status = Column(String(20), default="success", comment="状态：success/failed/skipped")
    payload = Column(JSON, default=dict, comment="触发载荷(JSON)")
    input_data = Column(JSON, default=dict, comment="输入数据(JSON)")
    result_data = Column(JSON, default=dict, comment="结果数据(JSON)")
    error_message = Column(Text, default="", comment="错误信息")
    triggered_at = Column(DateTime, default=datetime.utcnow, index=True, comment="触发时间")
    duration_ms = Column(Integer, default=0, comment="耗时(ms)")
    source_info = Column(JSON, default=dict, comment="来源信息(JSON)")

    __table_args__ = (
        Index("ix_th_triggerid_time", "trigger_id", "triggered_at"),
        Index("ix_th_wfid_status", "workflow_id", "status"),
    )

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "trigger_id": self.trigger_id,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "payload": self.payload or {},
            "input_data": self.input_data or {},
            "result_data": self.result_data or {},
            "error_message": self.error_message,
            "triggered_at": self.triggered_at.strftime("%Y-%m-%d %H:%M:%S") if self.triggered_at else None,
            "duration_ms": self.duration_ms,
            "source_info": self.source_info or {},
        }
