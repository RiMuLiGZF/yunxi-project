"""同步管理路由.

提供同步管理相关的 API 端点：
- GET  /api/v3/sync/status                    - 同步状态
- POST /api/v3/sync/trigger                   - 触发同步
- GET  /api/v3/sync/conflicts                 - 冲突列表
- POST /api/v3/sync/conflicts/{id}/resolve    - 解决冲突
- GET  /api/v1/sync/status                    - v1 别名
- GET  /api/v1/sync/conflicts                 - v1 别名
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Body, Depends, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.common import SyncTriggerRequest

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Sync"])


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

@router.get("/api/v3/sync/status", summary="同步状态")
async def sync_status(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取同步状态.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        同步状态响应.
    """
    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.get_sync_status(trace_id=trace_id)
            return result.to_dict()
        except Exception as e:
            logger.error("sync.status.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "status": "idle",
        "last_sync_at": None,
        "last_sync_result": None,
        "pending_changes": 0,
        "conflict_count": 0,
        "queue_depth": 0,
        "network_state": "unknown",
        "health_endpoints": [],
    })


@router.post("/api/v3/sync/trigger", summary="触发同步")
async def sync_trigger(
    request: Request,
    body: SyncTriggerRequest | None = None,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """手动触发同步.

    Args:
        request: FastAPI 请求对象.
        body: 同步触发请求体（可选）.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        触发结果响应.
    """
    m8_api = kernel.get_component("m8_api")

    scope = body.scope if body else None
    conflict_strategy = body.conflict_strategy if body else "newest_wins"

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.trigger_sync(
                scope=scope,
                conflict_strategy=conflict_strategy,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("sync.trigger.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "sync_id": uuid.uuid4().hex[:16],
        "scope": scope or ["all"],
        "conflict_strategy": conflict_strategy,
        "status": "triggered",
        "triggered_at": time.time(),
    })


@router.get("/api/v3/sync/conflicts", summary="冲突列表")
async def sync_conflicts(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取冲突列表.

    Args:
        request: FastAPI 请求对象.
        page: 页码（从 1 开始）.
        page_size: 每页条数.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        冲突列表响应.
    """
    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.list_conflicts(
                page=page,
                page_size=page_size,
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error("sync.conflicts.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data={
        "total": 0,
        "page": page,
        "page_size": page_size,
        "conflicts": [],
    })


@router.post("/api/v3/sync/conflicts/{conflict_id}/resolve", summary="解决冲突")
async def resolve_conflict(
    request: Request,
    conflict_id: str,
    body: dict = Body(default_factory=dict),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """解决同步冲突.

    Args:
        request: FastAPI 请求对象.
        conflict_id: 冲突 ID.
        body: 请求体，包含 resolution 字段.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        解决结果响应.
    """
    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.resolve_conflict(
                conflict_id=conflict_id,
                resolution=body.get("resolution", ""),
                trace_id=trace_id,
            )
            return result.to_dict()
        except Exception as e:
            logger.error(
                "sync.conflict.resolve.failed",
                error=str(e),
                trace_id=trace_id,
            )

    # Mock 模式
    return _mock_m8_response(data={
        "conflict_id": conflict_id,
        "resolved": True,
        "resolution": body.get("resolution", ""),
        "source": "mock",
    })


# ---------------------------------------------------------------------------
# v1 别名路由
# ---------------------------------------------------------------------------

@router.get("/api/v1/sync/status", tags=["V1 Alias"], summary="v1同步状态（别名）")
async def v1_sync_status(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 同步状态别名，转发到 v3 接口."""
    return await sync_status(request, trace_id=trace_id, kernel=kernel)


@router.get("/api/v1/sync/conflicts", tags=["V1 Alias"], summary="v1冲突列表（别名）")
async def v1_sync_conflicts(
    request: Request,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 冲突列表别名，转发到 v3 接口."""
    return await sync_conflicts(
        request, page=page, page_size=page_size, trace_id=trace_id, kernel=kernel
    )
