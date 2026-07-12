"""
M0 主理人管控台 - 数据模型（Pydantic Schemas）

定义所有 API 请求/响应的数据模型，与 M8 风格保持一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Generic, TypeVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 通用响应模型
# ---------------------------------------------------------------------------

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    统一 API 响应格式

    与 M8 保持一致的 {code, message, data} 结构。
    """
    code: int = Field(default=0, description="状态码，0 表示成功")
    message: str = Field(default="success", description="响应消息")
    data: Optional[T] = Field(default=None, description="响应数据")

    @classmethod
    def success(cls, data: Any = None, message: str = "success") -> "ApiResponse[Any]":
        """创建成功响应"""
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, code: int = -1, message: str = "error", data: Any = None) -> "ApiResponse[Any]":
        """创建错误响应"""
        return cls(code=code, message=message, data=data)


class PaginationParams(BaseModel):
    """分页查询参数"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据"""
    items: List[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")


# ---------------------------------------------------------------------------
# 认证相关模型
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class LoginData(BaseModel):
    """登录成功返回数据"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    username: str = Field(..., description="用户名")
    role: str = Field(..., description="角色")
    expires_in: int = Field(..., description="过期时间（秒）")


class UserInfo(BaseModel):
    """用户信息"""
    username: str = Field(..., description="用户名")
    role: str = Field(..., description="角色")
    display_name: Optional[str] = Field(default=None, description="显示名称")


# ---------------------------------------------------------------------------
# 健康检查模型
# ---------------------------------------------------------------------------

class HealthStatus(BaseModel):
    """健康检查状态"""
    status: str = Field(default="healthy", description="健康状态")
    version: str = Field(..., description="版本号")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    m8_connected: bool = Field(default=False, description="M8 是否已连接")
    uptime: float = Field(default=0.0, description="运行时长（秒）")


# ---------------------------------------------------------------------------
# 仪表盘模型
# ---------------------------------------------------------------------------

class ModuleStatusItem(BaseModel):
    """模块状态项"""
    key: str = Field(..., description="模块标识")
    name: str = Field(..., description="模块名称")
    status: str = Field(default="unknown", description="状态: running/stopped/degraded/unknown")
    port: Optional[int] = Field(default=None, description="端口")
    version: Optional[str] = Field(default=None, description="版本")
    last_heartbeat: Optional[datetime] = Field(default=None, description="上次心跳时间")


class SystemResources(BaseModel):
    """系统资源概览"""
    cpu_usage: float = Field(default=0.0, description="CPU 使用率 %")
    memory_usage: float = Field(default=0.0, description="内存使用率 %")
    memory_total_gb: float = Field(default=0.0, description="总内存 GB")
    memory_used_gb: float = Field(default=0.0, description="已用内存 GB")
    disk_usage: float = Field(default=0.0, description="磁盘使用率 %")


class AlertItem(BaseModel):
    """告警项"""
    id: str = Field(..., description="告警 ID")
    level: str = Field(default="info", description="告警级别: critical/warning/info")
    title: str = Field(..., description="告警标题")
    module: str = Field(..., description="来源模块")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    resolved: bool = Field(default=False, description="是否已处理")


class DashboardSummary(BaseModel):
    """仪表盘总览数据"""
    module_count: int = Field(default=0, description="模块总数")
    module_running: int = Field(default=0, description="运行中模块数")
    module_stopped: int = Field(default=0, description="已停止模块数")
    system_resources: SystemResources = Field(default_factory=SystemResources, description="系统资源")
    alerts: List[AlertItem] = Field(default_factory=list, description="告警列表")
    alert_critical_count: int = Field(default=0, description="严重告警数")
    alert_warning_count: int = Field(default=0, description="警告数")
    version: str = Field(default="0.1.0", description="当前版本")
    today_conversations: int = Field(default=0, description="今日对话数")
    memory_total: int = Field(default=0, description="记忆总数")
    uptime_hours: float = Field(default=0.0, description="运行时长（小时）")


# ---------------------------------------------------------------------------
# 模块管理模型
# ---------------------------------------------------------------------------

class ModuleDetail(BaseModel):
    """模块详情"""
    key: str = Field(..., description="模块标识")
    name: str = Field(..., description="模块名称")
    description: Optional[str] = Field(default=None, description="模块描述")
    status: str = Field(default="unknown", description="状态")
    port: Optional[int] = Field(default=None, description="端口")
    version: Optional[str] = Field(default=None, description="版本")
    config: Dict[str, Any] = Field(default_factory=dict, description="模块配置")
    endpoints: List[str] = Field(default_factory=list, description="API 端点列表")
    last_heartbeat: Optional[datetime] = Field(default=None, description="上次心跳")


# ---------------------------------------------------------------------------
# 配置中心模型
# ---------------------------------------------------------------------------

class ConfigItem(BaseModel):
    """配置项"""
    key: str = Field(..., description="配置键")
    value: Any = Field(..., description="配置值")
    description: Optional[str] = Field(default=None, description="配置说明")
    category: str = Field(default="general", description="配置分类")


class GlobalConfig(BaseModel):
    """全局配置"""
    configs: Dict[str, Any] = Field(default_factory=dict, description="配置字典")
    categories: List[str] = Field(default_factory=list, description="配置分类列表")
    updated_at: datetime = Field(default_factory=datetime.now, description="最后更新时间")


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    key: str = Field(..., description="配置键")
    value: Any = Field(..., description="配置值")


# ---------------------------------------------------------------------------
# 审计日志模型
# ---------------------------------------------------------------------------

class AuditLogItem(BaseModel):
    """审计日志项"""
    id: str = Field(..., description="日志 ID")
    action: str = Field(..., description="操作类型")
    operator: str = Field(..., description="操作人")
    module: str = Field(default="system", description="涉及模块")
    detail: str = Field(default="", description="操作详情")
    ip: Optional[str] = Field(default=None, description="IP 地址")
    created_at: datetime = Field(default_factory=datetime.now, description="操作时间")
    success: bool = Field(default=True, description="是否成功")


# ---------------------------------------------------------------------------
# 权限管理模型
# ---------------------------------------------------------------------------

class RoleItem(BaseModel):
    """角色项"""
    name: str = Field(..., description="角色名称")
    key: str = Field(..., description="角色标识")
    level: int = Field(default=0, description="角色层级")
    description: Optional[str] = Field(default=None, description="角色描述")
    permissions: List[str] = Field(default_factory=list, description="权限列表")


# ---------------------------------------------------------------------------
# 系统升级模型
# ---------------------------------------------------------------------------

class VersionInfo(BaseModel):
    """版本信息"""
    current_version: str = Field(..., description="当前版本")
    latest_version: Optional[str] = Field(default=None, description="最新版本")
    release_notes: Optional[str] = Field(default=None, description="发布说明")
    upgrade_available: bool = Field(default=False, description="是否有新版本")
    last_check_time: Optional[datetime] = Field(default=None, description="上次检查时间")


# ---------------------------------------------------------------------------
# 紧急操作模型
# ---------------------------------------------------------------------------

class EmergencyAction(BaseModel):
    """紧急操作"""
    action: str = Field(..., description="操作类型")
    reason: str = Field(default="", description="操作原因")
    operator: str = Field(..., description="操作人")


class EmergencyActionResult(BaseModel):
    """紧急操作结果"""
    success: bool = Field(default=False, description="是否成功")
    action: str = Field(..., description="执行的操作")
    message: str = Field(default="", description="结果消息")
    executed_at: datetime = Field(default_factory=datetime.now, description="执行时间")
