"""上下文管理路由.

提供获取上下文、保存上下文、清空上下文、上下文状态等接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Query

from src.models import ContextSaveRequest, make_response

router = APIRouter(prefix="/api/v1/context", tags=["上下文管理"])


def _get_context_store(request: Request) -> Any:
    """从 request state 获取上下文存储服务."""
    return request.app.state.context_store


# ---------------------------------------------------------------------------
# 获取上下文
# ---------------------------------------------------------------------------

@router.get("/{scene_id}", summary="获取场景上下文")
async def get_context(
    request: Request,
    scene_id: str,
    user_id: str = Query("default", description="用户ID"),
):
    """获取指定场景的上下文数据.

    路径参数:
        scene_id: 场景ID
    查询参数:
        user_id: 用户ID
    """
    context_store = _get_context_store(request)

    result = context_store.get_context(scene_id, user_id=user_id)

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 保存上下文
# ---------------------------------------------------------------------------

@router.post("/{scene_id}", summary="保存场景上下文")
async def save_context(
    request: Request,
    scene_id: str,
    body: ContextSaveRequest,
    user_id: str = Query("default", description="用户ID"),
    merge: bool = Query(True, description="是否合并现有上下文"),
):
    """保存指定场景的上下文数据.

    路径参数:
        scene_id: 场景ID
    请求体:
        context_json: 上下文数据字典
    查询参数:
        user_id: 用户ID
        merge: 是否合并（True合并，False覆盖）
    """
    context_store = _get_context_store(request)

    result = context_store.save_context(
        scene_id=scene_id,
        context_data=body.context_json,
        user_id=user_id,
        merge=merge,
    )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 清空上下文
# ---------------------------------------------------------------------------

@router.delete("/{scene_id}", summary="清空场景上下文")
async def clear_context(
    request: Request,
    scene_id: str,
    user_id: str = Query("default", description="用户ID"),
):
    """清空指定场景的上下文数据.

    路径参数:
        scene_id: 场景ID
    查询参数:
        user_id: 用户ID
    """
    context_store = _get_context_store(request)

    result = context_store.clear_context(scene_id, user_id=user_id)

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 上下文状态概览
# ---------------------------------------------------------------------------

@router.get("/status", summary="上下文状态概览")
async def get_context_status(
    request: Request,
    user_id: str = Query("default", description="用户ID"),
):
    """获取所有场景的上下文状态概览.

    查询参数:
        user_id: 用户ID
    """
    context_store = _get_context_store(request)

    status = context_store.get_status(user_id=user_id)

    return make_response(data=status)
