"""
config 子域路由
"""

from .config_center import router as config_center_router
from .i18n import router as i18n_router

__all__ = [
    "config_center_router",
    "i18n_router",
]
