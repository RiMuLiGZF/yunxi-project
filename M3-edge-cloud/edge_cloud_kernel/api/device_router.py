"""设备管理路由.

提供设备管理相关的 API 端点：
- GET  /api/v3/devices              - 设备列表
- POST /api/v3/devices/{id}/remove  - 移除设备
- GET  /api/v1/devices              - v1 别名
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.api_requests import (
    DeviceStatus,
    validate_device_id_path,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Devices"])


# ---------------------------------------------------------------------------
# Mock 响应辅助函数
# ---------------------------------------------------------------------------

def _mock_m8_response(
    data: Any = None,
    code: int = 0,
    message: str = "Success",
) -> dict[str, Any]:
    """Mock M8 标准响应格式（带 mock 标识）.

    Args:
        data: 响应数据.
        code: 错误码.
        message: 消息.

    Returns:
        标准 M8 响应字典.
    """
    if isinstance(data, dict):
        data = {"mode": "mock", **data}
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/api/v3/devices", summary="设备列表")
async def list_devices(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: DeviceStatus | None = Query(None, description="按状态过滤"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取设备列表.

    Args:
        request: FastAPI 请求对象.
        page: 页码（从 1 开始）.
        page_size: 每页条数.
        status: 按设备状态过滤.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        设备列表响应.
    """
    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.list_devices(
                page=page,
                page_size=page_size,
                status=status.value if status else None,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("devices.list.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "total": 0,
        "page": page,
        "page_size": page_size,
        "devices": [],
    })


@router.post("/api/v3/devices/{device_id}/remove", summary="移除设备")
async def remove_device(
    request: Request,
    device_id: str = Path(..., description="设备 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """移除设备.

    Args:
        request: FastAPI 请求对象.
        device_id: 设备 ID.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        移除结果响应.
    """
    # Path 参数格式校验
    validate_device_id_path(device_id)

    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.remove_device(
                device_id=device_id,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("devices.remove.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "device_id": device_id,
        "removed": True,
        "source": "mock",
    })


# ---------------------------------------------------------------------------
# v1 别名路由
# ---------------------------------------------------------------------------

@router.get("/api/v1/devices", tags=["V1 Alias"], summary="v1设备列表（别名）")
async def v1_devices(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: DeviceStatus | None = Query(None, description="按状态过滤"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 设备列表别名，转发到 v3 接口."""
    return await list_devices(
        request,
        page=page,
        page_size=page_size,
        status=status,
        trace_id=trace_id,
        kernel=kernel,
    )
