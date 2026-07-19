"""
security 子域路由
"""

from .auth import router as auth_router
from .users import router as users_router
from .security import router as security_router
from .audit import router as audit_router

__all__ = [
    "auth_router",
    "users_router",
    "security_router",
    "audit_router",
]
