"""M11 MCP Bus - Pydantic 数据模型.

定义 API 请求和响应的数据结构。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举类型
# ============================================================

class ServerStatus(str, Enum):
    """MCP 服务状态."""
    ONLINE = "online"
    OFFLINE = "offline"


class TransportType(str, Enum):
    """传输类型."""
    HTTP = "http"
    SSE = "sse"
    STDIO = "stdio"


class CallStatus(str, Enum):
    """调用状态."""
    SUCCESS = "success"
    FAILED = "failed"


# ============================================================
# MCP 服务相关模型
# ============================================================

class McpServerCreate(BaseModel):
    """创建 MCP 服务请求."""
    name: str = Field(..., min_length=1, max_length=100, description="服务名称")
    description: str = Field(default="", max_length=500, description="服务描述")
    transport_type: TransportType = Field(default=TransportType.HTTP, description="传输类型")
    endpoint: str = Field(default="", max_length=500, description="服务端点地址")
    api_key: str = Field(default="", max_length=200, description="服务鉴权密钥")
    health_check_url: str = Field(default="", max_length=500, description="健康检查地址")


class McpServerUpdate(BaseModel):
    """更新 MCP 服务请求."""
    description: Optional[str] = Field(default=None, max_length=500, description="服务描述")
    transport_type: Optional[TransportType] = Field(default=None, description="传输类型")
    endpoint: Optional[str] = Field(default=None, max_length=500, description="服务端点地址")
    api_key: Optional[str] = Field(default=None, max_length=200, description="服务鉴权密钥")
    health_check_url: Optional[str] = Field(default=None, max_length=500, description="健康检查地址")
    status: Optional[ServerStatus] = Field(default=None, description="服务状态")


class McpServerResponse(BaseModel):
    """MCP 服务响应."""
    id: int
    name: str
    description: str = ""
    transport_type: str = "http"
    endpoint: str = ""
    status: str = "offline"
    health_check_url: str = ""
    last_heartbeat: Optional[datetime] = None
    created_at: datetime
    tool_count: int = Field(default=0, description="工具数量")

    class Config:
        from_attributes = True


class McpServerListResponse(BaseModel):
    """MCP 服务列表响应."""
    items: List[McpServerResponse]
    total: int
    page: int = 1
    page_size: int = 20


class HeartbeatRequest(BaseModel):
    """心跳上报请求."""
    status: ServerStatus = Field(default=ServerStatus.ONLINE, description="服务状态")


# ============================================================
# MCP 工具相关模型
# ============================================================

class McpToolResponse(BaseModel):
    """MCP 工具响应."""
    id: int
    server_id: int
    server_name: str = ""
    name: str
    description: str = ""
    category: str = "general"
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入参数 Schema")
    cached_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class McpToolListResponse(BaseModel):
    """MCP 工具列表响应."""
    items: List[McpToolResponse]
    total: int
    page: int = 1
    page_size: int = 50
    categories: List[str] = Field(default_factory=list, description="可用分类列表")


class ToolRefreshRequest(BaseModel):
    """工具刷新请求."""
    force: bool = Field(default=False, description="是否强制刷新")


# ============================================================
# 工具调用相关模型
# ============================================================

class McpCallRequest(BaseModel):
    """MCP 工具调用请求."""
    tool_name: str = Field(..., min_length=1, description="工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="调用参数")
    consumer: str = Field(default="", description="调用方标识")


class McpCallResponse(BaseModel):
    """MCP 工具调用响应."""
    call_id: int
    tool_name: str
    status: str
    duration_ms: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime


class McpCallRecordResponse(BaseModel):
    """调用记录响应."""
    id: int
    tool_name: str
    server_id: Optional[int] = None
    consumer: str = ""
    status: str
    duration_ms: int = 0
    error_message: str = ""
    request_snippet: str = ""
    response_snippet: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class McpCallListResponse(BaseModel):
    """调用记录列表响应."""
    items: List[McpCallRecordResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ============================================================
# API Key 相关模型
# ============================================================

class ApiKeyCreate(BaseModel):
    """创建 API Key 请求."""
    name: str = Field(..., min_length=1, max_length=100, description="密钥名称")
    permissions: List[str] = Field(default_factory=list, description="权限列表")
    rate_limit: int = Field(default=100, ge=1, le=10000, description="限流阈值（次/分钟）")
    expires_days: Optional[int] = Field(default=None, ge=1, description="有效天数")


class ApiKeyResponse(BaseModel):
    """API Key 响应."""
    id: int
    name: str
    permissions: List[str] = Field(default_factory=list)
    rate_limit: int = 100
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    key: Optional[str] = Field(default=None, description="明文密钥（仅创建时返回一次）")

    class Config:
        from_attributes = True


class ApiKeyListResponse(BaseModel):
    """API Key 列表响应."""
    items: List[ApiKeyResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ============================================================
# M8 标准接口模型
# ============================================================

class HealthResponse(BaseModel):
    """健康检查响应（M8 标准）."""
    status: str = "healthy"
    module: str = "m11"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)


class MetricsResponse(BaseModel):
    """性能指标响应（M8 标准）."""
    module: str = "m11"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_servers: int = 0
    online_servers: int = 0
    total_tools: int = 0
    total_calls: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0


class ConfigResponse(BaseModel):
    """配置查询响应（M8 标准）."""
    module: str = "m11"
    version: str = "0.1.0"
    env: str = "development"
    port: int = 8011
    heartbeat_timeout: int = 30
    tool_refresh_interval: int = 300
    db_path: str = ""
    log_level: str = "info"
