"""健康检查路由.

提供健康检查和性能指标相关的 API 端点：
- GET  /health          - 简单健康检查
- GET  /api/v3/health   - M8 标准健康检查
- GET  /api/v3/metrics  - 性能指标
- GET  /api/v1/health   - v1 别名
- GET  /api/v1/metrics  - v1 别名
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import (
    mock_health_data,
    mock_metrics_data,
)
from edge_cloud_kernel.core.kernel_manager import KernelManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Health"])


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/health", summary="健康检查")
async def health_check(request: Request):
    """健康检查端点（白名单，无需认证，不依赖 kernel_manager）.

    即使 kernel_manager 未初始化也能正常返回，避免 500。
    """
    kernel: KernelManager | None = getattr(request.state, "kernel_manager", None)
    uptime = kernel.uptime_seconds if kernel and hasattr(kernel, "uptime_seconds") else 0
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": "healthy",
            "version": "2.1.2",
            "module": "m3",
            "uptime_seconds": uptime,
        },
    }


@router.get("/api/v3/health", summary="M8 标准健康检查")
async def m8_health_check(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准健康检查接口（白名单，无需鉴权）.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        M8 标准健康检查响应.
    """
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics is not None and not kernel.is_mock("health_metrics"):
        try:
            result = await health_metrics.get_health(request_id=trace_id)
            result["mode"] = "real"
            return {
                "code": 0,
                "message": "ok",
                "data": result,
            }
        except Exception as e:
            logger.error("health_check.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return {
        "code": 0,
        "message": "ok",
        "data": mock_health_data(kernel),
    }


@router.get("/api/v3/metrics", summary="性能指标")
async def m8_metrics(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取性能指标（需鉴权，当前开放）.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        性能指标响应.
    """
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics is not None and not kernel.is_mock("health_metrics"):
        try:
            result = await health_metrics.get_metrics(request_id=trace_id)
            result["mode"] = "real"
            return {
                "code": 0,
                "message": "ok",
                "data": result,
            }
        except Exception as e:
            logger.error("metrics.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return {
        "code": 0,
        "message": "ok",
        "data": mock_metrics_data(),
    }


# ---------------------------------------------------------------------------
# v1 别名路由
# ---------------------------------------------------------------------------

@router.get("/api/v1/health", tags=["V1 Alias"], summary="v1健康检查（别名）")
async def v1_health(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 健康检查别名，转发到 v3 接口."""
    return await m8_health_check(request, trace_id=trace_id, kernel=kernel)


@router.get("/api/v1/metrics", tags=["V1 Alias"], summary="v1性能指标（别名）")
async def v1_metrics(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 性能指标别名，转发到 v3 接口."""
    return await m8_metrics(request, trace_id=trace_id, kernel=kernel)
