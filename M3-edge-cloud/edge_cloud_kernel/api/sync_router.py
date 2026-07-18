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

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import (
    mock_conflict_list,
    mock_conflict_resolve_result,
    mock_response,
    mock_sync_status,
    mock_sync_trigger_result,
)
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.api_requests import (
    SyncResolveRequest,
    SyncTriggerRequest,
    validate_conflict_id,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Sync"])


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
    return mock_response(data=mock_sync_status(), trace_id=trace_id)


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
    return mock_response(
        data=mock_sync_trigger_result(scope=scope, conflict_strategy=conflict_strategy),
        trace_id=trace_id,
    )


@router.get("/api/v3/sync/conflicts", summary="冲突列表")
async def sync_conflicts(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
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
    return mock_response(
        data=mock_conflict_list(page=page, page_size=page_size),
        trace_id=trace_id,
    )


@router.post("/api/v3/sync/conflicts/{conflict_id}/resolve", summary="解决冲突")
async def resolve_conflict(
    request: Request,
    body: SyncResolveRequest,
    conflict_id: str = Path(..., description="冲突 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """解决同步冲突.

    Args:
        request: FastAPI 请求对象.
        conflict_id: 冲突 ID.
        body: 冲突解决请求体，包含 resolution 字段.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        解决结果响应.
    """
    # Path 参数格式校验
    validate_conflict_id(conflict_id)

    m8_api = kernel.get_component("m8_api")

    if m8_api is not None and not kernel.is_mock("m8_api"):
        try:
            result = await m8_api.resolve_conflict(
                conflict_id=conflict_id,
                resolution=body.resolution,
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
    return mock_response(
        data=mock_conflict_resolve_result(conflict_id, body.resolution),
        trace_id=trace_id,
    )


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
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 冲突列表别名，转发到 v3 接口."""
    return await sync_conflicts(
        request, page=page, page_size=page_size, trace_id=trace_id, kernel=kernel
    )


# ---------------------------------------------------------------------------
# 新增：增强版同步接口（端云协同增强）
# ---------------------------------------------------------------------------


@router.post("/api/v3/sync/handshake", summary="设备握手")
async def sync_handshake(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """设备握手 - 建立同步会话.

    端云协同增强接口：建立端云同步会话，协商协议版本和同步范围。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    sync_engine = kernel.get_component("sync_engine")
    sync_protocol = kernel.get_component("sync_protocol")

    if sync_protocol is not None and not kernel.is_mock("sync_protocol"):
        try:
            from edge_cloud_kernel.services.protocol import HandshakeRequest

            req = HandshakeRequest(
                device_id=body.get("device_id", ""),
                device_type=body.get("device_type", "unknown"),
                device_name=body.get("device_name", ""),
                client_version=body.get("client_version", ""),
                supported_protocols=body.get("supported_protocols", ["1.0.0"]),
                capabilities=body.get("capabilities", []),
                sync_scopes=body.get("sync_scopes", []),
            )
            result = sync_protocol.handshake(req)
            return mock_response(
                data={
                    "success": result.success,
                    "session_id": result.session_id,
                    "server_version": result.server_version,
                    "negotiated_protocol": result.negotiated_protocol,
                    "heartbeat_interval": result.heartbeat_interval,
                    "sync_cursor": result.sync_cursor,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("sync.handshake.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "success": True,
            "session_id": f"session-{trace_id[:8]}",
            "server_version": "2.1.0",
            "negotiated_protocol": "1.0.0",
            "heartbeat_interval": 30,
            "sync_cursor": {"conversation": 0, "memory": 0, "config": 0},
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/sync/push", summary="推送本地变更")
async def sync_push(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """推送本地变更到云端.

    端云协同增强接口：推送本地增量变更，支持基于时间戳和操作日志的同步。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    sync_engine = kernel.get_component("sync_engine")
    sync_protocol = kernel.get_component("sync_protocol")

    session_id = body.get("session_id", "")
    changes = body.get("changes", [])
    version_vector = body.get("version_vector", {})

    if sync_protocol is not None and not kernel.is_mock("sync_protocol"):
        try:
            result = sync_protocol.push_changes(
                session_id=session_id,
                changes=changes,
                version_vector=version_vector,
            )
            return mock_response(data=result, trace_id=trace_id)
        except Exception as e:
            logger.error("sync.push.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    accepted = [c.get("item_id", "") for c in changes]
    return mock_response(
        data={
            "accepted": accepted,
            "rejected": [],
            "conflicts": [],
            "new_cursor": version_vector,
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/sync/pull", summary="拉取云端变更")
async def sync_pull(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """拉取云端变更到本地.

    端云协同增强接口：根据游标拉取云端增量变更。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    sync_protocol = kernel.get_component("sync_protocol")
    session_id = body.get("session_id", "")
    since_cursor = body.get("since_cursor", {})

    if sync_protocol is not None and not kernel.is_mock("sync_protocol"):
        try:
            result = sync_protocol.pull_changes(
                session_id=session_id,
                since_cursor=since_cursor,
            )
            return mock_response(data=result, trace_id=trace_id)
        except Exception as e:
            logger.error("sync.pull.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "changes": [],
            "cursor": since_cursor,
            "server_version": "2.1.0",
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/sync/status/details", summary="同步状态详情")
async def sync_status_details(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取同步状态详情（增强版）.

    端云协同增强接口：返回详细的同步进度、队列状态和历史记录。
    保持原 /api/v3/sync/status 不变，此为增强详情接口。
    """
    sync_engine = kernel.get_component("sync_engine")

    if sync_engine is not None and not kernel.is_mock("sync_engine"):
        try:
            progress_list = sync_engine.get_all_progress()
            history = sync_engine.get_sync_history(limit=10)
            queue_size = sync_engine.get_queue_size()
            return mock_response(
                data={
                    "active_syncs": len(progress_list),
                    "queue_size": queue_size,
                    "recent_progress": [
                        {
                            "sync_id": p.sync_id,
                            "strategy": p.strategy.value if hasattr(p.strategy, "value") else str(p.strategy),
                            "direction": p.direction.value if hasattr(p.direction, "value") else str(p.direction),
                            "status": p.status,
                            "progress_percent": p.progress_percent,
                            "total_items": p.total_items,
                            "processed_items": p.processed_items,
                        }
                        for p in progress_list[:10]
                    ],
                    "recent_history": [
                        {
                            "history_id": h.history_id,
                            "sync_id": h.sync_id,
                            "strategy": h.strategy.value if hasattr(h.strategy, "value") else str(h.strategy),
                            "status": h.status,
                            "items_count": h.items_count,
                            "duration_seconds": h.duration_seconds,
                        }
                        for h in history
                    ],
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("sync.status_details.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "active_syncs": 0,
            "queue_size": 0,
            "recent_progress": [],
            "recent_history": [],
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/sync/resolve", summary="解决冲突")
async def sync_resolve(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """解决同步冲突.

    端云协同增强接口：批量解决同步冲突，支持多种解决策略。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    sync_protocol = kernel.get_component("sync_protocol")
    session_id = body.get("session_id", "")
    conflict_ids = body.get("conflict_ids", [])
    resolution = body.get("resolution", "last_write_wins")

    if sync_protocol is not None and not kernel.is_mock("sync_protocol"):
        try:
            result = sync_protocol.resolve_conflicts(
                session_id=session_id,
                conflict_ids=conflict_ids,
                resolution=resolution,
            )
            return mock_response(data=result, trace_id=trace_id)
        except Exception as e:
            logger.error("sync.resolve.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "resolved": conflict_ids,
            "failed": [],
            "resolution": resolution,
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/sync/history", summary="同步历史")
async def sync_history(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    strategy: str | None = Query(None, description="按策略过滤"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取同步历史记录.

    端云协同增强接口：返回历史同步任务的详细记录。
    """
    sync_engine = kernel.get_component("sync_engine")

    if sync_engine is not None and not kernel.is_mock("sync_engine"):
        try:
            from edge_cloud_kernel.services.sync_engine import SyncStrategy

            strat = None
            if strategy:
                try:
                    strat = SyncStrategy(strategy)
                except ValueError:
                    pass

            history = sync_engine.get_sync_history(limit=page_size, strategy=strat)
            items = [
                {
                    "history_id": h.history_id,
                    "sync_id": h.sync_id,
                    "strategy": h.strategy.value if hasattr(h.strategy, "value") else str(h.strategy),
                    "direction": h.direction.value if hasattr(h.direction, "value") else str(h.direction),
                    "items_count": h.items_count,
                    "conflicts_count": h.conflicts_count,
                    "status": h.status,
                    "started_at": h.started_at,
                    "finished_at": h.finished_at,
                    "duration_seconds": h.duration_seconds,
                }
                for h in history
            ]
            return mock_response(
                data={
                    "items": items,
                    "total": len(items),
                    "page": page,
                    "page_size": page_size,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("sync.history.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "items": [
                {
                    "history_id": "hist-mock-001",
                    "sync_id": "sync-mock-001",
                    "strategy": "timestamp",
                    "direction": "bidirectional",
                    "items_count": 50,
                    "conflicts_count": 2,
                    "status": "completed",
                    "started_at": 0,
                    "finished_at": 0,
                    "duration_seconds": 2.5,
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        },
        trace_id=trace_id,
    )
