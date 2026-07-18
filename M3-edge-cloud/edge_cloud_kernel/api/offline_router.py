"""离线管理路由.

提供离线管理相关的 API 端点：
- POST /api/v3/offline/queue    - 获取离线队列
- POST /api/v3/offline/flush    - 刷新离线队列
- GET  /api/v3/offline/status   - 离线状态
- GET  /api/v3/offline/cache    - 离线缓存列表
- POST /api/v3/offline/cache/clear - 清理缓存
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import mock_response
from edge_cloud_kernel.core.kernel_manager import KernelManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Offline"])


# ---------------------------------------------------------------------------
# 离线队列
# ---------------------------------------------------------------------------


@router.post("/api/v3/offline/queue", summary="获取离线队列")
async def get_offline_queue(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    status: str | None = Query(None, description="按状态过滤"),
    entity_type: str | None = Query(None, description="按实体类型过滤"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取离线操作队列.

    Args:
        request: FastAPI 请求对象.
        page: 页码.
        page_size: 每页条数.
        status: 状态过滤（pending/failed）.
        entity_type: 实体类型过滤.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        离线队列列表.
    """
    offline_manager = kernel.get_component("offline_manager")

    if offline_manager is not None and not kernel.is_mock("offline_manager"):
        try:
            items = await offline_manager.get_queue_items(
                status=status or "pending",
                limit=page_size,
                entity_type=entity_type,
            )
            total = await offline_manager.get_queue_size(status=status or "pending")
            items_data = [
                {
                    "id": item.id,
                    "operation": item.operation,
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "payload": item.payload,
                    "priority": item.priority,
                    "status": item.status,
                    "queued_at": item.queued_at,
                    "retry_count": item.retry_count,
                    "last_error": item.last_error,
                }
                for item in items
            ]
            return mock_response(
                data={
                    "items": items_data,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("offline.queue.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "items": [
                {
                    "id": 1,
                    "operation": "UPDATE",
                    "entity_type": "conversation",
                    "entity_id": "mock-001",
                    "payload": {"title": "Mock conversation"},
                    "priority": 5,
                    "status": "pending",
                    "queued_at": 0,
                    "retry_count": 0,
                    "last_error": "",
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/offline/flush", summary="刷新离线队列")
async def flush_offline_queue(
    request: Request,
    max_items: int = Query(100, ge=1, le=1000, description="最大刷新条目数"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """刷新离线队列（将队列中的操作发送出去）.

    Args:
        request: FastAPI 请求对象.
        max_items: 最大刷新条目数.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        刷新结果.
    """
    offline_manager = kernel.get_component("offline_manager")

    if offline_manager is not None and not kernel.is_mock("offline_manager"):
        try:
            result = await offline_manager.flush_queue(max_items=max_items)
            return mock_response(
                data={
                    "success": result.get("success", 0),
                    "failed": result.get("failed", 0),
                    "remaining": result.get("remaining", 0),
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("offline.flush.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "success": 1,
            "failed": 0,
            "remaining": 0,
        },
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# 离线状态
# ---------------------------------------------------------------------------


@router.get("/api/v3/offline/status", summary="离线状态")
async def get_offline_status(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取离线状态和统计信息.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        离线状态信息.
    """
    offline_manager = kernel.get_component("offline_manager")

    if offline_manager is not None and not kernel.is_mock("offline_manager"):
        try:
            metrics = await offline_manager.get_metrics()
            return mock_response(
                data={
                    "status": offline_manager.status.value,
                    "is_online": offline_manager.is_online,
                    "queue_size": metrics.current_queue_size,
                    "cache_size": metrics.current_cache_size,
                    "total_queued": metrics.total_queued,
                    "total_flushed": metrics.total_flushed,
                    "total_failed": metrics.total_failed,
                    "cache_hits": metrics.cache_hits,
                    "cache_misses": metrics.cache_misses,
                    "offline_duration": metrics.offline_duration,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("offline.status.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "status": "online",
            "is_online": True,
            "queue_size": 0,
            "cache_size": 1024000,
            "total_queued": 100,
            "total_flushed": 95,
            "total_failed": 2,
            "cache_hits": 500,
            "cache_misses": 50,
            "offline_duration": 3600.0,
        },
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# 离线缓存
# ---------------------------------------------------------------------------


@router.get("/api/v3/offline/cache", summary="离线缓存列表")
async def get_offline_cache(
    request: Request,
    category: str | None = Query(None, description="按分类过滤"),
    limit: int = Query(50, ge=1, le=500, description="返回条数"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取离线缓存列表.

    Args:
        request: FastAPI 请求对象.
        category: 分类过滤.
        limit: 返回条数.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        缓存条目列表.
    """
    offline_manager = kernel.get_component("offline_manager")

    if offline_manager is not None and not kernel.is_mock("offline_manager"):
        try:
            entries = await offline_manager.cache_list(
                category=category, limit=limit
            )
            items = [
                {
                    "cache_key": e.cache_key,
                    "category": e.category,
                    "priority": e.priority.value if hasattr(e.priority, "value") else str(e.priority),
                    "size_bytes": e.size_bytes,
                    "created_at": e.created_at,
                    "expires_at": e.expires_at,
                    "access_count": e.access_count,
                }
                for e in entries
            ]
            return mock_response(
                data={"items": items, "count": len(items)},
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("offline.cache.list.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "items": [
                {
                    "cache_key": "config:theme",
                    "category": "config",
                    "priority": "high",
                    "size_bytes": 1024,
                    "created_at": 0,
                    "expires_at": 0,
                    "access_count": 10,
                }
            ],
            "count": 1,
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/offline/cache/clear", summary="清理缓存")
async def clear_offline_cache(
    request: Request,
    category: str | None = Query(None, description="指定分类，不填清空全部"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """清理离线缓存.

    Args:
        request: FastAPI 请求对象.
        category: 指定分类.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        清理结果.
    """
    offline_manager = kernel.get_component("offline_manager")

    if offline_manager is not None and not kernel.is_mock("offline_manager"):
        try:
            count = await offline_manager.cache_clear(category=category)
            return mock_response(
                data={"cleared": count, "category": category or "all"},
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("offline.cache.clear.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={"cleared": 10, "category": category or "all"},
        trace_id=trace_id,
    )
