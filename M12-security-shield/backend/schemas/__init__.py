"""
M12 安全盾 - Pydantic 数据模型包
包含所有 API 请求和响应的数据验证模型
"""

from .common import ApiResponse, PageRequest, PageResponse
from .waf import (
    WafRuleCreate,
    WafRuleUpdate,
    WafRuleResponse,
    WafStatusResponse,
    WafCheckRequest,
    WafCheckResponse,
)
from .auth import (
    LoginRequest,
    LoginResponse,
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyUpdate,
    TokenRefreshRequest,
    TokenRefreshResponse,
)
from .ip import (
    IpBlacklistCreate,
    IpBlacklistResponse,
    IpWhitelistCreate,
    IpWhitelistResponse,
    IpCheckResponse,
)
from .audit import (
    SecurityEventResponse,
    AuditLogResponse,
    AuditStatsResponse,
    EventQueryParams,
)

__all__ = [
    # common
    "ApiResponse",
    "PageRequest",
    "PageResponse",
    # waf
    "WafRuleCreate",
    "WafRuleUpdate",
    "WafRuleResponse",
    "WafStatusResponse",
    "WafCheckRequest",
    "WafCheckResponse",
    # auth
    "LoginRequest",
    "LoginResponse",
    "ApiKeyCreate",
    "ApiKeyResponse",
    "ApiKeyUpdate",
    "TokenRefreshRequest",
    "TokenRefreshResponse",
    # ip
    "IpBlacklistCreate",
    "IpBlacklistResponse",
    "IpWhitelistCreate",
    "IpWhitelistResponse",
    "IpCheckResponse",
    # audit
    "SecurityEventResponse",
    "AuditLogResponse",
    "AuditStatsResponse",
    "EventQueryParams",
]
