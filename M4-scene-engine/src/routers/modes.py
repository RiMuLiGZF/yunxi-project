"""业务模式路由.

提供业务模式列表、模式详情、进入模式、离开模式等接口。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Request, Query, HTTPException

from src.models import make_response
from src.modes import mode_registry
from src.schemas import ModeEnterRequest, ModeLeaveRequest

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/modes", tags=["业务模式"])


# ---------------------------------------------------------------------------
# 模式列表
# ---------------------------------------------------------------------------

@router.get("", summary="获取所有业务模式列表")
async def list_modes(
    request: Request,
    category: str = Query("", description="按分类筛选，空字符串表示全部"),
    only_enabled: bool = Query(True, description="是否只返回已启用的模式"),
):
    """获取所有业务模式列表.

    Args:
        request: FastAPI 请求对象
        category: 按分类筛选
        only_enabled: 是否只返回已启用的模式

    Returns:
        业务模式列表
    """
    if category:
        modes = mode_registry.get_by_category(category)
    elif only_enabled:
        modes = mode_registry.list_enabled()
    else:
        modes = mode_registry.list_all()

    mode_list = [m.get_info() for m in modes]

    return make_response(data={
        "total": len(mode_list),
        "modes": mode_list,
    })


# ---------------------------------------------------------------------------
# 单个模式信息
# ---------------------------------------------------------------------------

@router.get("/{mode_id}", summary="获取单个业务模式信息")
async def get_mode(
    request: Request,
    mode_id: str,
):
    """获取指定业务模式的详细信息.

    Args:
        request: FastAPI 请求对象
        mode_id: 模式 ID

    Returns:
        业务模式详细信息
    """
    mode = mode_registry.get(mode_id)
    if mode is None:
        return make_response(
            code=41001,
            message=f"模式 {mode_id} 不存在",
            data={},
        )

    mode_info = mode.get_info()
    # 附加配置信息
    try:
        config = await mode.get_config()
        mode_info["config"] = config
    except Exception as e:
        logger.warning("modes.get_config_failed", mode_id=mode_id,
                       error_type=type(e).__name__, error=str(e))
        mode_info["config"] = {}

    return make_response(data=mode_info)


# ---------------------------------------------------------------------------
# 进入模式
# ---------------------------------------------------------------------------

@router.post("/{mode_id}/enter", summary="进入业务模式")
async def enter_mode(
    request: Request,
    mode_id: str,
    body: ModeEnterRequest,
):
    """进入指定的业务模式.

    调用模式的 on_enter 生命周期方法，执行模式初始化。

    Args:
        request: FastAPI 请求对象
        mode_id: 模式 ID
        body: 进入模式请求体

    Returns:
        进入模式结果
    """
    mode = mode_registry.get(mode_id)
    if mode is None:
        return make_response(
            code=41001,
            message=f"模式 {mode_id} 不存在",
            data={},
        )

    if not mode.is_enabled:
        return make_response(
            code=41003,
            message=f"模式 {mode_id} 未启用",
            data={},
        )

    context = {
        "user_id": body.user_id,
        **body.context,
    }

    try:
        result = await mode.on_enter(context)
        return make_response(data=result)
    except Exception as e:
        return make_response(
            code=50000,
            message=f"进入模式失败：{str(e)}",
            data={"mode_id": mode_id},
        )


# ---------------------------------------------------------------------------
# 离开模式
# ---------------------------------------------------------------------------

@router.post("/{mode_id}/leave", summary="离开业务模式")
async def leave_mode(
    request: Request,
    mode_id: str,
    body: ModeLeaveRequest,
):
    """离开指定的业务模式.

    调用模式的 on_leave 生命周期方法，执行资源释放和状态保存。

    Args:
        request: FastAPI 请求对象
        mode_id: 模式 ID
        body: 离开模式请求体

    Returns:
        离开模式结果
    """
    mode = mode_registry.get(mode_id)
    if mode is None:
        return make_response(
            code=41001,
            message=f"模式 {mode_id} 不存在",
            data={},
        )

    context = {
        "user_id": body.user_id,
        **body.context,
    }

    try:
        result = await mode.on_leave(context)
        return make_response(data=result)
    except Exception as e:
        return make_response(
            code=50000,
            message=f"离开模式失败：{str(e)}",
            data={"mode_id": mode_id},
        )


# ---------------------------------------------------------------------------
# 默认模式
# ---------------------------------------------------------------------------

@router.get("/default/info", summary="获取默认模式信息")
async def get_default_mode(request: Request):
    """获取当前的默认业务模式.

    Args:
        request: FastAPI 请求对象

    Returns:
        默认模式信息
    """
    default_mode = mode_registry.get_default()
    if default_mode is None:
        return make_response(
            code=41001,
            message="没有可用的默认模式",
            data={},
        )

    return make_response(data=default_mode.get_info())


# ---------------------------------------------------------------------------
# 模式分类列表
# ---------------------------------------------------------------------------

@router.get("/categories/list", summary="获取所有模式分类")
async def list_categories(request: Request):
    """获取所有业务模式的分类列表.

    Args:
        request: FastAPI 请求对象

    Returns:
        分类列表及各分类下的模式数量
    """
    modes = mode_registry.list_enabled()
    categories: dict[str, dict[str, Any]] = {}

    for mode in modes:
        cat = mode.category
        if cat not in categories:
            categories[cat] = {
                "category": cat,
                "count": 0,
                "modes": [],
            }
        categories[cat]["count"] += 1
        categories[cat]["modes"].append({
            "mode_id": mode.mode_id,
            "mode_name": mode.mode_name,
            "icon": mode.icon,
        })

    category_list = list(categories.values())

    return make_response(data={
        "total": len(category_list),
        "categories": category_list,
    })
