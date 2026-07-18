"""设备管理路由.

提供设备管理相关的 API 端点：
- GET  /api/v3/devices              - 设备列表
- POST /api/v3/devices/{id}/remove  - 移除设备
- GET  /api/v1/devices              - v1 别名
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import (
    mock_device_list,
    mock_device_remove_result,
    mock_response,
)
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.api_requests import (
    DeviceStatus,
    validate_device_id_path,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Devices"])


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
    return mock_response(
        data=mock_device_list(page=page, page_size=page_size, status=status.value if status else None),
        trace_id=trace_id,
    )


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
    return mock_response(
        data=mock_device_remove_result(device_id),
        trace_id=trace_id,
    )


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


# ---------------------------------------------------------------------------
# 新增：增强版设备管理接口（端云协同增强）
# ---------------------------------------------------------------------------


@router.post("/api/v3/devices/register", summary="设备注册")
async def register_device(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """注册设备（增强版）.

    端云协同增强接口：注册设备并上报设备硬件/软件信息。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    device_manager = kernel.get_component("device_manager_enhanced")

    if device_manager is not None and not kernel.is_mock("device_manager_enhanced"):
        try:
            device = device_manager.register_device(
                device_id=body.get("device_id", ""),
                name=body.get("name", ""),
                device_type=body.get("device_type", "unknown"),
                model=body.get("model", ""),
                manufacturer=body.get("manufacturer", ""),
                os_name=body.get("os_name", ""),
                os_version=body.get("os_version", ""),
                app_version=body.get("app_version", ""),
                firmware_version=body.get("firmware_version", ""),
                capabilities=body.get("capabilities", []),
                metadata=body.get("metadata", {}),
                cpu_cores=body.get("cpu_cores", 0),
                total_memory_gb=body.get("total_memory_gb", 0.0),
                total_storage_gb=body.get("total_storage_gb", 0.0),
                has_gpu=body.get("has_gpu", False),
            )
            return mock_response(
                data={
                    "device_id": device.device_id,
                    "name": device.name,
                    "status": device.status.value if hasattr(device.status, "value") else str(device.status),
                    "trust_level": device.trust_level.value if hasattr(device.trust_level, "value") else str(device.trust_level),
                    "registered_at": device.registered_at,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("devices.register.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    device_id = body.get("device_id", f"dev-{trace_id[:8]}")
    return mock_response(
        data={
            "device_id": device_id,
            "name": body.get("name", "Unknown Device"),
            "status": "online",
            "trust_level": "untrusted",
            "registered_at": time.time(),
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/devices/{device_id}", summary="设备详情")
async def get_device_detail(
    request: Request,
    device_id: str = Path(..., description="设备 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取设备详情（增强版）.

    端云协同增强接口：返回设备的完整信息，包括硬件/软件/能力等。
    """
    # Path 参数格式校验
    validate_device_id_path(device_id)

    device_manager = kernel.get_component("device_manager_enhanced")

    if device_manager is not None and not kernel.is_mock("device_manager_enhanced"):
        try:
            device = device_manager.get_device(device_id)
            if device:
                return mock_response(
                    data={
                        "device_id": device.device_id,
                        "name": device.name,
                        "device_type": device.device_type,
                        "model": device.model,
                        "manufacturer": device.manufacturer,
                        "os_name": device.os_name,
                        "os_version": device.os_version,
                        "app_version": device.app_version,
                        "firmware_version": device.firmware_version,
                        "status": device.status.value if hasattr(device.status, "value") else str(device.status),
                        "trust_level": device.trust_level.value if hasattr(device.trust_level, "value") else str(device.trust_level),
                        "last_seen": device.last_seen,
                        "registered_at": device.registered_at,
                        "groups": device.groups,
                        "capabilities": device.capabilities,
                        "cpu_cores": device.cpu_cores,
                        "total_memory_gb": device.total_memory_gb,
                        "total_storage_gb": device.total_storage_gb,
                        "has_gpu": device.has_gpu,
                        "metadata": device.metadata,
                    },
                    trace_id=trace_id,
                )
        except Exception as e:
            logger.error("devices.detail.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "device_id": device_id,
            "name": "Mock Device",
            "device_type": "desktop",
            "model": "Mock Model",
            "manufacturer": "Mock Inc.",
            "os_name": "Mock OS",
            "os_version": "1.0.0",
            "app_version": "2.1.0",
            "firmware_version": "",
            "status": "online",
            "trust_level": "medium",
            "last_seen": 0,
            "registered_at": 0,
            "groups": ["default"],
            "capabilities": ["sync", "edge_compute"],
            "cpu_cores": 8,
            "total_memory_gb": 16.0,
            "total_storage_gb": 512.0,
            "has_gpu": True,
            "metadata": {},
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/devices/{device_id}/health", summary="设备健康")
async def get_device_health(
    request: Request,
    device_id: str = Path(..., description="设备 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取设备健康状态.

    端云协同增强接口：返回设备的健康评分和性能指标。
    """
    # Path 参数格式校验
    validate_device_id_path(device_id)

    device_manager = kernel.get_component("device_manager_enhanced")

    if device_manager is not None and not kernel.is_mock("device_manager_enhanced"):
        try:
            score = device_manager.get_health_score(device_id)
            if score:
                return mock_response(
                    data={
                        "device_id": device_id,
                        "overall_score": score.overall_score,
                        "status": score.status.value if hasattr(score.status, "value") else str(score.status),
                        "cpu_score": score.cpu_score,
                        "memory_score": score.memory_score,
                        "network_score": score.network_score,
                        "battery_score": score.battery_score,
                        "thermal_score": score.thermal_score,
                        "stability_score": score.stability_score,
                        "recommendations": score.recommendations,
                        "last_updated": score.last_updated,
                    },
                    trace_id=trace_id,
                )
        except Exception as e:
            logger.error("devices.health.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "device_id": device_id,
            "overall_score": 85.5,
            "status": "healthy",
            "cpu_score": 90.0,
            "memory_score": 85.0,
            "network_score": 80.0,
            "battery_score": 95.0,
            "thermal_score": 88.0,
            "stability_score": 75.0,
            "recommendations": [],
            "last_updated": time.time(),
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/devices/{device_id}/notify", summary="推送通知")
async def send_device_notification(
    request: Request,
    device_id: str = Path(..., description="设备 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """向设备推送通知.

    端云协同增强接口：向指定设备发送通知消息。
    """
    # Path 参数格式校验
    validate_device_id_path(device_id)

    try:
        body = await request.json()
    except Exception:
        body = {}

    device_manager = kernel.get_component("device_manager_enhanced")

    if device_manager is not None and not kernel.is_mock("device_manager_enhanced"):
        try:
            result = await device_manager.send_notification(
                device_id=device_id,
                title=body.get("title", ""),
                body=body.get("body", ""),
                notification_type=body.get("type", "info"),
                priority=body.get("priority", "normal"),
                data=body.get("data"),
            )
            return mock_response(data=result, trace_id=trace_id)
        except Exception as e:
            logger.error("devices.notify.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "success": True,
            "notification_id": f"notif-{trace_id[:8]}",
            "device_id": device_id,
            "queued": False,
        },
        trace_id=trace_id,
    )
