"""配置管理路由.

提供配置管理相关的 API 端点：
- GET  /api/v3/config          - 获取配置（敏感字段脱敏）
- POST /api/v3/config/update   - 更新配置（点路径，热更新）
- GET  /api/v1/config          - v1 别名
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import (
    mock_config_data,
    mock_config_update_result,
    mock_response,
)
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.api_requests import ConfigUpdateRequest

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Config"])


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/api/v3/config", summary="获取配置")
async def get_config(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取配置（敏感字段脱敏）.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        配置数据响应.
    """
    config_manager = kernel.get_component("config_manager")

    if config_manager is not None and not kernel.is_mock("config_manager"):
        try:
            result = config_manager.get_config_sanitized(request_id=trace_id)
            return mock_response(data=result, trace_id=trace_id)
        except Exception as e:
            logger.error("config.get.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(data=mock_config_data(), trace_id=trace_id)


@router.post("/api/v3/config/update", summary="更新配置")
async def update_config(
    request: Request,
    body: ConfigUpdateRequest,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """更新配置（点路径方式，热更新）.

    Args:
        request: FastAPI 请求对象.
        body: 配置更新请求体.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        更新结果响应.
    """
    config_manager = kernel.get_component("config_manager")

    if config_manager is not None and not kernel.is_mock("config_manager"):
        try:
            success, result = config_manager.update_config(
                updates=body.updates,
                request_id=trace_id,
            )
            if not success:
                raise HTTPException(status_code=400, detail=result)
            return mock_response(data=result, trace_id=trace_id)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("config.update.failed", error=str(e), trace_id=trace_id)
            raise HTTPException(status_code=500, detail=str(e))

    # Mock 模式
    return mock_response(
        data=mock_config_update_result(body.updates),
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# v1 别名路由
# ---------------------------------------------------------------------------

@router.get("/api/v1/config", tags=["V1 Alias"], summary="v1获取配置（别名）")
async def v1_config(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 获取配置别名，转发到 v3 接口."""
    return await get_config(request, trace_id=trace_id, kernel=kernel)
