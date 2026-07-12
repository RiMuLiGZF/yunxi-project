"""
M0 主理人管控台 - 路由层
"""

from .dashboard import router as dashboard_router
from .modules import router as modules_router
from .config import router as config_router
from .access_control import router as access_control_router
from .audit import router as audit_router
from .upgrade import router as upgrade_router
from .emergency import router as emergency_router
from .principal_tools import router as principal_tools_router
from .auth import router as auth_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "modules_router",
    "config_router",
    "access_control_router",
    "audit_router",
    "upgrade_router",
    "emergency_router",
    "principal_tools_router",
]
