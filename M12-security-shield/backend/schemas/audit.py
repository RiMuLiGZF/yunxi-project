"""
云汐 M12 安全盾 - 审计相关 Pydantic 模型
定义安全审计接口的请求和响应数据模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ===========================================================================
# 安全事件模型
# ===========================================================================

class SecurityEventResponse(BaseModel):
    """安全事件响应"""

    id: int = Field(..., description="事件ID")
    event_type: str = Field(default="", description="事件类型")
    severity: str = Field(default="info", description="严重级别")
    source_ip: str = Field(default="", description="来源 IP")
    target_path: str = Field(default="", description="目标路径")
    method: str = Field(default="", description="请求方法")
    description: str = Field(default="", description="事件描述")
    rule_name: str = Field(default="", description="触发的规则名称")
    user_agent: str = Field(default="", description="用户代理")
    status: str = Field(default="active", description="事件状态")
    resolved_by: str = Field(default="", description="处理人")
    resolved_at: Optional[datetime] = Field(default=None, description="处理时间")
    resolution_note: str = Field(default="", description="处理说明")
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="附加数据")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


class EventResolveRequest(BaseModel):
    """处理事件请求"""

    resolution_note: str = Field(default="", description="处理说明")
    status: str = Field(default="resolved", description="事件状态")


# ===========================================================================
# 审计日志模型
# ===========================================================================

class AuditLogResponse(BaseModel):
    """审计日志响应"""

    id: int = Field(..., description="日志ID")
    user_id: str = Field(default="", description="用户ID")
    username: str = Field(default="", description="用户名")
    role: str = Field(default="", description="用户角色")
    module: str = Field(default="", description="操作模块")
    action: str = Field(default="", description="操作类型")
    resource_type: str = Field(default="", description="资源类型")
    resource_id: str = Field(default="", description="资源ID")
    description: str = Field(default="", description="操作描述")
    source_ip: str = Field(default="", description="来源 IP")
    user_agent: str = Field(default="", description="用户代理")
    request_method: str = Field(default="", description="请求方法")
    request_path: str = Field(default="", description="请求路径")
    status: str = Field(default="success", description="操作状态")
    error_message: str = Field(default="", description="错误信息")
    duration_ms: int = Field(default=0, description="耗时（毫秒）")
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="附加数据")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


# ===========================================================================
# 查询参数模型
# ===========================================================================

class EventQueryParams(BaseModel):
    """安全事件查询参数"""

    event_type: Optional[str] = Field(default=None, description="事件类型")
    severity: Optional[str] = Field(default=None, description="严重级别")
    source_ip: Optional[str] = Field(default=None, description="来源 IP")
    status: Optional[str] = Field(default=None, description="事件状态")
    start_time: Optional[datetime] = Field(default=None, description="开始时间")
    end_time: Optional[datetime] = Field(default=None, description="结束时间")
    keyword: Optional[str] = Field(default=None, description="关键词搜索")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class AuditQueryParams(BaseModel):
    """审计日志查询参数"""

    user_id: Optional[str] = Field(default=None, description="用户ID")
    module: Optional[str] = Field(default=None, description="模块")
    action: Optional[str] = Field(default=None, description="操作类型")
    status: Optional[str] = Field(default=None, description="操作状态")
    source_ip: Optional[str] = Field(default=None, description="来源 IP")
    start_time: Optional[datetime] = Field(default=None, description="开始时间")
    end_time: Optional[datetime] = Field(default=None, description="结束时间")
    keyword: Optional[str] = Field(default=None, description="关键词搜索")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


# ===========================================================================
# 统计模型
# ===========================================================================

class AuditStatsResponse(BaseModel):
    """审计统计响应"""

    total_events: int = Field(default=0, description="安全事件总数")
    events_today: int = Field(default=0, description="今日事件数")
    events_this_week: int = Field(default=0, description="本周事件数")
    high_severity_count: int = Field(default=0, description="高危事件数")
    medium_severity_count: int = Field(default=0, description="中危事件数")
    low_severity_count: int = Field(default=0, description="低危事件数")
    events_by_type: Dict[str, int] = Field(default_factory=dict, description="按类型统计")
    events_by_severity: Dict[str, int] = Field(default_factory=dict, description="按级别统计")
    top_source_ips: List[Dict[str, Any]] = Field(default_factory=list, description="攻击来源 IP 排行")
    trend_data: List[Dict[str, Any]] = Field(default_factory=list, description="趋势数据")
    total_audit_logs: int = Field(default=0, description="审计日志总数")
