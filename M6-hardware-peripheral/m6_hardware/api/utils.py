"""
M6 硬件外设 - API 统一响应工具
"""

import uuid
import time
from typing import Any

from fastapi import HTTPException
from starlette.responses import JSONResponse

from ..services.device_manager import DeviceManager


def success_response(
    data: Any = None,
    message: str = "ok",
    code: int = 0,
) -> JSONResponse:
    """构造统一成功 JSON 响应"""
    return JSONResponse(
        content={
            "code": code,
            "message": message,
            "data": data,
            "request_id": uuid.uuid4().hex[:16],
            "timestamp": time.time(),
        }
    )


def error_response(
    message: str,
    code: int,
    status_code: int = 400,
) -> JSONResponse:
    """构造统一错误 JSON 响应"""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "data": None,
            "request_id": uuid.uuid4().hex[:16],
            "timestamp": time.time(),
        },
    )


def get_device_or_404(dm: DeviceManager, device_id: str) -> Any:
    """获取设备实例，不存在则抛出 404"""
    device = dm.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"设备不存在: {device_id}")
    return device


def create_sensor_response(data: Any, device_id: str) -> dict[str, Any]:
    """封装传感器数据响应格式"""
    return {
        "device_id": device_id,
        "data": data,
    }
