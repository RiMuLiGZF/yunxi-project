"""M7 积木平台 - 数据模型定义.

定义工作流、积木块、连接、变量、触发器、运行记录等核心数据结构。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举类型
# ============================================================

class WorkflowStatus(str, Enum):
    """工作流状态."""
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TriggerType(str, Enum):
    """触发器类型."""
    MANUAL = "manual"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"


class RunStatus(str, Enum):
    """运行状态."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlockStatus(str, Enum):
    """积木块执行状态."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# 积木块相关模型
# ============================================================

class BlockPosition(BaseModel):
    """积木块在画布上的位置."""
    x: int = 0
    y: int = 0


class BlockConfig(BaseModel):
    """积木块配置.

    Attributes:
        id: 积木块实例 ID（工作流内唯一）
        type: 积木类型（对应技能 ID，如 skill.web_fetch）
        name: 显示名称
        config: 积木配置参数
        position: 画布位置
        next: 后继积木块 ID 列表（用于构建 DAG）
    """
    id: str
    type: str
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)
    position: BlockPosition = Field(default_factory=BlockPosition)
    next: List[str] = Field(default_factory=list)


class Connection(BaseModel):
    """积木块之间的连接线."""
    from_block: str = Field(..., alias="from")
    to_block: str = Field(..., alias="to")
    from_port: str = "output"
    to_port: str = "input"

    class Config:
        populate_by_name = True


# ============================================================
# 变量系统
# ============================================================

class VariableDef(BaseModel):
    """工作流变量定义."""
    name: str
    type: str = "string"  # string/number/boolean/object/array
    default: Any = None
    description: str = ""


# ============================================================
# 触发器
# ============================================================

class TriggerConfig(BaseModel):
    """触发器配置."""
    type: TriggerType = TriggerType.MANUAL
    config: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 工作流模型
# ============================================================

class Workflow(BaseModel):
    """工作流完整定义."""
    id: str
    name: str
    description: str = ""
    category: str = "未分类"
    status: WorkflowStatus = WorkflowStatus.DRAFT
    blocks: List[BlockConfig] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    variables: List[VariableDef] = Field(default_factory=list)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    created_at: str = ""
    updated_at: str = ""
    run_count: int = 0
    created_by: str = ""

    class Config:
        use_enum_values = True


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求."""
    name: str
    description: str = ""
    category: str = "未分类"
    blocks: List[BlockConfig] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    variables: List[VariableDef] = Field(default_factory=list)
    trigger: Optional[TriggerConfig] = None
    status: WorkflowStatus = WorkflowStatus.DRAFT


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    blocks: Optional[List[BlockConfig]] = None
    connections: Optional[List[Connection]] = None
    variables: Optional[List[VariableDef]] = None
    trigger: Optional[TriggerConfig] = None
    status: Optional[WorkflowStatus] = None


# ============================================================
# 运行记录模型
# ============================================================

class BlockStepResult(BaseModel):
    """单个积木块的执行结果."""
    block_id: str
    block_name: str
    skill_id: str
    action: str = "default"
    status: BlockStatus = BlockStatus.PENDING
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: Optional[float] = None
    duration_ms: int = 0
    retry_count: int = 0


class WorkflowRunRecord(BaseModel):
    """工作流运行记录."""
    run_id: str
    workflow_id: str
    workflow_name: str = ""
    status: RunStatus = RunStatus.PENDING
    started_at: float = 0.0
    finished_at: Optional[float] = None
    duration_ms: int = 0
    steps: List[BlockStepResult] = Field(default_factory=list)
    total_blocks: int = 0
    success_blocks: int = 0
    failed_blocks: int = 0
    skipped_blocks: int = 0
    triggered_by: str = ""
    trigger_type: str = "manual"
    input_data: Dict[str, Any] = Field(default_factory=dict)
    final_output: Any = None
    error: Optional[str] = None

    class Config:
        use_enum_values = True


class WorkflowRunRequest(BaseModel):
    """运行工作流请求."""
    input_data: Dict[str, Any] = Field(default_factory=dict)
    start_block: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 积木（技能）模型
# ============================================================

class BlockInfo(BaseModel):
    """积木（技能）信息."""
    id: str
    name: str
    description: str = ""
    category: str = "其他"
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    enabled: bool = True
    icon: str = ""
    inputs: List[Dict[str, Any]] = Field(default_factory=list)
    outputs: List[Dict[str, Any]] = Field(default_factory=list)


class BlockCategory(BaseModel):
    """积木分类."""
    id: str
    name: str
    icon: str = ""
    color: str = "#6B7280"
    count: int = 0


# ============================================================
# 模板模型
# ============================================================

class WorkflowTemplate(BaseModel):
    """工作流模板."""
    id: str
    name: str
    description: str = ""
    category: str = "未分类"
    icon: str = ""
    blocks: List[BlockConfig] = Field(default_factory=list)
    connections: List[Connection] = Field(default_factory=list)
    variables: List[VariableDef] = Field(default_factory=list)
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    tags: List[str] = Field(default_factory=list)


class TemplateApplyRequest(BaseModel):
    """应用模板请求."""
    name: Optional[str] = None
    category: Optional[str] = None


# ============================================================
# 分页响应
# ============================================================

class PaginatedResponse(BaseModel):
    """分页响应通用结构."""
    total: int
    items: List[Any]
    page: int = 1
    page_size: int = 50


# ============================================================
# API 通用响应
# ============================================================

class ApiResponse(BaseModel):
    """API 统一响应格式."""
    code: int = 0
    message: str = "ok"
    data: Any = None
    request_id: str = ""

    @classmethod
    def success(cls, data: Any = None, message: str = "ok", request_id: str = "") -> "ApiResponse":
        return cls(code=0, message=message, data=data, request_id=request_id)

    @classmethod
    def error(cls, code: int = -1, message: str = "error", data: Any = None, request_id: str = "") -> "ApiResponse":
        return cls(code=code, message=message, data=data, request_id=request_id)


# ============================================================
# 自定义积木模型
# ============================================================

class CustomBlockCreate(BaseModel):
    """创建自定义积木请求."""
    name: str
    category: str = "工具块"
    description: str = ""
    code: str = ""
    icon: str = "puzzle"
    ports: Dict[str, Any] = Field(default_factory=lambda: {"inputs": [], "outputs": []})


class CustomBlockUpdate(BaseModel):
    """更新自定义积木请求."""
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    icon: Optional[str] = None
    ports: Optional[Dict[str, Any]] = None


class CustomBlockInfo(BaseModel):
    """自定义积木信息."""
    id: str
    name: str
    category: str = "工具块"
    description: str = ""
    code: str = ""
    icon: str = "puzzle"
    ports: Dict[str, Any] = Field(default_factory=lambda: {"inputs": [], "outputs": []})
    user_id: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============================================================
# P2 持久化执行引擎 - 持久化运行模型
# ============================================================

class PersistentRunStatus(str, Enum):
    """持久化运行状态."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class PersistentWorkflowRun(BaseModel):
    """持久化工作流运行记录."""
    run_id: str
    workflow_id: str
    workflow_name: str = ""
    status: PersistentRunStatus = PersistentRunStatus.PENDING
    current_node_id: str = ""
    context_data: Dict[str, Any] = Field(default_factory=dict)
    step_results: Dict[str, Any] = Field(default_factory=dict)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    created_by: str = ""
    priority: int = 5
    result_summary: Dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 0
    trigger_type: str = "manual"
    trigger_id: str = ""
    input_data: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300
    last_heartbeat: Optional[str] = None
    version: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        use_enum_values = True


class PersistentRunCreateRequest(BaseModel):
    """创建持久化运行请求."""
    workflow_id: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    max_retries: int = 0
    timeout_seconds: int = 300


class PersistentRunListResponse(BaseModel):
    """持久化运行列表响应."""
    total: int
    items: List[PersistentWorkflowRun]
    page: int = 1
    page_size: int = 20


class ExecutionContextSnapshot(BaseModel):
    """执行上下文快照."""
    id: int
    run_id: str
    node_id: str = ""
    context_data: Dict[str, Any] = Field(default_factory=dict)
    step_results: Dict[str, Any] = Field(default_factory=dict)
    variables: Dict[str, Any] = Field(default_factory=dict)
    snapshot_type: str = "node_complete"
    created_at: Optional[str] = None


# ============================================================
# P2 触发器系统 - 触发器模型
# ============================================================

class TriggerTypeEnum(str, Enum):
    """触发器类型."""
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    EVENT = "event"


class TriggerStatusEnum(str, Enum):
    """触发历史状态."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TriggerDefinition(BaseModel):
    """触发器定义."""
    id: str
    name: str
    description: str = ""
    workflow_id: str
    trigger_type: TriggerTypeEnum = TriggerTypeEnum.SCHEDULE
    enabled: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)
    input_mapping: Dict[str, Any] = Field(default_factory=dict)
    filter_config: Dict[str, Any] = Field(default_factory=dict)
    webhook_secret: str = ""
    webhook_path: str = ""
    timezone: str = "Asia/Shanghai"
    last_triggered_at: Optional[str] = None
    trigger_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    created_by: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        use_enum_values = True


class TriggerCreateRequest(BaseModel):
    """创建触发器请求."""
    name: str
    workflow_id: str
    trigger_type: TriggerTypeEnum = TriggerTypeEnum.SCHEDULE
    description: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    input_mapping: Dict[str, Any] = Field(default_factory=dict)
    filter_config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    timezone: str = "Asia/Shanghai"


class TriggerUpdateRequest(BaseModel):
    """更新触发器请求."""
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    input_mapping: Optional[Dict[str, Any]] = None
    filter_config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    timezone: Optional[str] = None


class TriggerHistoryRecord(BaseModel):
    """触发历史记录."""
    id: int
    trigger_id: str
    workflow_id: str
    run_id: str = ""
    trigger_type: str = "schedule"
    status: TriggerStatusEnum = TriggerStatusEnum.SUCCESS
    payload: Dict[str, Any] = Field(default_factory=dict)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    result_data: Dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    triggered_at: Optional[str] = None
    duration_ms: int = 0
    source_info: Dict[str, Any] = Field(default_factory=dict)


class TriggerListResponse(BaseModel):
    """触发器列表响应."""
    total: int
    items: List[TriggerDefinition]
    page: int = 1
    page_size: int = 20


class TriggerHistoryResponse(BaseModel):
    """触发历史列表响应."""
    total: int
    items: List[TriggerHistoryRecord]
    page: int = 1
    page_size: int = 20
