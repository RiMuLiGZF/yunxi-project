"""
M6 硬件外设 - API 路由包
设备管理、传感器数据、设备控制、健康检查等 API
"""

from fastapi import APIRouter

from .devices import router as devices_router
from .sensors import router as sensors_router
from .control import router as control_router
from .health import router as health_router
from .wearable import router as wearable_router

# 主 API 路由
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(devices_router, prefix="/devices", tags=["设备管理"])
api_router.include_router(sensors_router, prefix="/sensors", tags=["传感器数据"])
api_router.include_router(control_router, prefix="/control", tags=["设备控制"])
api_router.include_router(health_router, prefix="/health", tags=["健康检查"])
api_router.include_router(wearable_router, prefix="/wearable", tags=["可穿戴设备"])

__all__ = ["api_router"]
