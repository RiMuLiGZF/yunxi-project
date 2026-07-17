"""
云汐 API 网关 - 管理 API 模块
"""

from .admin_api import create_admin_router

__all__ = [
    "create_admin_router",
]
