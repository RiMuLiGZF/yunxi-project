"""
M12 安全盾 - 路由层包
统一导出所有路由，便于主应用注册
"""

from .status import router as status_router
from .waf import router as waf_router
from .auth_api import router as auth_router
from .ip_control import router as ip_router
from .audit import router as audit_router
from .dashboard import router as dashboard_router

__all__ = [
    "status_router",
    "waf_router",
    "auth_router",
    "ip_router",
    "audit_router",
    "dashboard_router",
]
