"""API 路由层.

包含所有 HTTP 路由端点，按领域划分到独立文件。
"""

from edge_cloud_kernel.api.health_router import router as health_router
from edge_cloud_kernel.api.config_router import router as config_router
from edge_cloud_kernel.api.sync_router import router as sync_router
from edge_cloud_kernel.api.device_router import router as device_router
from edge_cloud_kernel.api.m8_router import router as m8_router

__all__ = [
    "health_router",
    "config_router",
    "sync_router",
    "device_router",
    "m8_router",
]
