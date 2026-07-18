"""
M8 控制塔 - 模块管理 Schema 模型

包含模块列表、模块详情、模块操作、模块健康检查等模块管理相关的 Pydantic 模型。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════
# 模块枚举
# ═══════════════════════════════════════════════════════

class ModuleStatus(str, Enum):
    """模块运行状态"""
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"


class ModuleCategory(str, Enum):
    """模块分类"""
    CORE = "core"           # 核心模块
    BUSINESS = "business"   # 业务模块
    INFRA = "infra"         # 基础设施
    TOOL = "tool"           # 工具模块


class HealthStatus(str, Enum):
    """健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════
# 模块基础信息
# ═══════════════════════════════════════════════════════

class ModuleBase(BaseModel):
    """模块基础信息"""
    key: str = Field(description="模块唯一标识")
    name: str = Field(description="模块名称")
    category: ModuleCategory = Field(default=ModuleCategory.BUSINESS, description="模块分类")
    description: Optional[str] = Field(default=None, description="模块描述")
    version: Optional[str] = Field(default=None, description="版本号")
    port: Optional[int] = Field(default=None, description="服务端口")
    base_url: Optional[str] = Field(default=None, description="服务地址")
    enabled: bool = Field(default=True, description="是否启用")
    auto_start: bool = Field(default=True, description="是否自动启动")
    priority: int = Field(default=100, description="启动优先级，数字越小越优先")


class ModuleInfo(ModuleBase):
    """模块详细信息（含运行状态）"""
    status: ModuleStatus = Field(default=ModuleStatus.UNKNOWN, description="运行状态")
    health: HealthStatus = Field(default=HealthStatus.UNKNOWN, description="健康状态")
    pid: Optional[int] = Field(default=None, description="进程ID")
    uptime_seconds: Optional[float] = Field(default=None, description="运行时长（秒）")
    last_health_check: Optional[datetime] = Field(default=None, description="上次健康检查时间")
    latency_ms: Optional[float] = Field(default=None, description="响应延迟（毫秒）")
    error_message: Optional[str] = Field(default=None, description="错误信息")
    cpu_usage: Optional[float] = Field(default=None, description="CPU使用率（%）")
    memory_usage: Optional[float] = Field(default=None, description="内存使用率（%）")
    memory_mb: Optional[float] = Field(default=None, description="内存使用量（MB）")
    created_at: Optional[datetime] = Field(default=None, description="注册时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════
# 模块列表
# ═══════════════════════════════════════════════════════

class ModuleListItem(BaseModel):
    """模块列表项"""
    key: str = Field(description="模块标识")
    name: str = Field(description="模块名称")
    category: ModuleCategory = Field(description="分类")
    description: Optional[str] = Field(default=None, description="描述")
    version: Optional[str] = Field(default=None, description="版本")
    status: ModuleStatus = Field(description="运行状态")
    health: HealthStatus = Field(description="健康状态")
    port: Optional[int] = Field(default=None, description="端口")
    enabled: bool = Field(description="是否启用")
    priority: int = Field(description="优先级")


class ModuleListResponse(BaseModel):
    """模块列表响应"""
    items: List[ModuleListItem] = Field(default_factory=list, description="模块列表")
    total: int = Field(default=0, description="总模块数")
    running_count: int = Field(default=0, description="运行中的模块数")
    stopped_count: int = Field(default=0, description="已停止的模块数")
    error_count: int = Field(default=0, description="异常的模块数")
    healthy_count: int = Field(default=0, description="健康的模块数")


class ModuleStatusSummary(BaseModel):
    """模块状态总览"""
    total: int = Field(description="总模块数")
    running: int = Field(description="运行中")
    stopped: int = Field(description="已停止")
    starting: int = Field(description="启动中")
    stopping: int = Field(description="停止中")
    error: int = Field(description="异常")
    unknown: int = Field(description="未知")
    healthy: int = Field(description="健康")
    degraded: int = Field(description="降级")
    unhealthy: int = Field(description="不健康")


# ═══════════════════════════════════════════════════════
# 模块操作
# ═══════════════════════════════════════════════════════

class ModuleOperationRequest(BaseModel):
    """模块操作请求"""
    action: str = Field(..., description="操作: start/stop/restart/reload")
    force: bool = Field(default=False, description="是否强制执行")
    timeout: int = Field(default=30, description="超时时间（秒）")


class ModuleOperationResult(BaseModel):
    """模块操作结果"""
    module_key: str = Field(description="模块标识")
    action: str = Field(description="执行的操作")
    success: bool = Field(description="是否成功")
    message: str = Field(default="", description="结果消息")
    previous_status: Optional[ModuleStatus] = Field(default=None, description="操作前状态")
    current_status: Optional[ModuleStatus] = Field(default=None, description="操作后状态")
    duration_ms: float = Field(default=0.0, description="耗时（毫秒）")


class BatchModuleOperationRequest(BaseModel):
    """批量模块操作请求"""
    module_keys: List[str] = Field(..., min_length=1, description="模块标识列表")
    action: str = Field(..., description="操作: start/stop/restart")
    force: bool = Field(default=False, description="是否强制执行")


class BatchModuleOperationResult(BaseModel):
    """批量模块操作结果"""
    total: int = Field(description="总操作数")
    succeeded: int = Field(description="成功数")
    failed: int = Field(description="失败数")
    results: List[ModuleOperationResult] = Field(default_factory=list, description="各模块操作结果")


# ═══════════════════════════════════════════════════════
# 模块健康检查
# ═══════════════════════════════════════════════════════

class ModuleHealthCheckRequest(BaseModel):
    """健康检查请求"""
    module_key: Optional[str] = Field(default=None, description="指定模块，为空则检查所有")
    deep_check: bool = Field(default=False, description="是否深度检查")
    timeout: float = Field(default=5.0, description="超时时间（秒）")


class ModuleHealthDetail(BaseModel):
    """模块健康详情"""
    module_key: str = Field(description="模块标识")
    module_name: str = Field(description="模块名称")
    status: ModuleStatus = Field(description="运行状态")
    health: HealthStatus = Field(description="健康状态")
    checks: Dict[str, Any] = Field(default_factory=dict, description="各项检查结果")
    latency_ms: Optional[float] = Field(default=None, description="响应延迟")
    last_check: datetime = Field(default_factory=datetime.now, description="检查时间")
    error_details: Optional[str] = Field(default=None, description="错误详情")


# ═══════════════════════════════════════════════════════
# 模块配置
# ═══════════════════════════════════════════════════════

class ModuleConfigUpdate(BaseModel):
    """模块配置更新"""
    config: Dict[str, Any] = Field(description="配置项")


class ModuleConfigResponse(BaseModel):
    """模块配置响应"""
    module_key: str = Field(description="模块标识")
    config: Dict[str, Any] = Field(default_factory=dict, description="配置内容")
    config_schema: Optional[Dict[str, Any]] = Field(default=None, description="配置 schema（用于UI渲染）")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")


# ═══════════════════════════════════════════════════════
# 模块注册/发现
# ═══════════════════════════════════════════════════════

class ModuleRegisterRequest(BaseModel):
    """模块注册请求"""
    key: str = Field(description="模块标识")
    name: str = Field(description="模块名称")
    category: str = Field(default="business", description="分类")
    port: int = Field(description="服务端口")
    base_url: Optional[str] = Field(default=None, description="服务地址")
    version: Optional[str] = Field(default=None, description="版本")
    description: Optional[str] = Field(default=None, description="描述")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    health_check_path: str = Field(default="/health", description="健康检查路径")


class ModuleRegisterResponse(BaseModel):
    """模块注册响应"""
    success: bool = Field(description="是否成功")
    module_key: str = Field(description="模块标识")
    registered: bool = Field(description="是否新注册")
    message: str = Field(default="", description="消息")


# ═══════════════════════════════════════════════════════
# 模块代理/转发
# ═══════════════════════════════════════════════════════

class ModuleProxyRequest(BaseModel):
    """模块代理请求（用于手动测试代理转发）"""
    module_key: str = Field(description="目标模块")
    path: str = Field(description="目标路径")
    method: str = Field(default="GET", description="HTTP方法")
    params: Optional[Dict[str, Any]] = Field(default=None, description="查询参数")
    body: Optional[Dict[str, Any]] = Field(default=None, description="请求体")


class ModuleProxyResponse(BaseModel):
    """模块代理响应"""
    module_key: str = Field(description="目标模块")
    path: str = Field(description="请求路径")
    proxied: bool = Field(description="是否成功代理")
    status_code: Optional[int] = Field(default=None, description="目标响应状态码")
    data: Optional[Any] = Field(default=None, description="响应数据")
    latency_ms: float = Field(default=0.0, description="耗时（毫秒）")
    error: Optional[str] = Field(default=None, description="错误信息")
