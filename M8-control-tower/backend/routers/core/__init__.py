"""
core 子域路由
"""

from .modules import router as modules_router
from .system import router as system_router
from .deploy import router as deploy_router
from .modes import router as modes_router
from .registry import router as registry_router
from .m4_gateway import router as m4_gateway_router

__all__ = [
    "modules_router",
    "system_router",
    "deploy_router",
    "modes_router",
    "registry_router",
    "m4_gateway_router",
]
