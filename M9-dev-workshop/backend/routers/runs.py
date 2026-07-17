"""M9 开发者工坊 - 运行历史路由.

提供代码运行历史记录的 API 接口。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query, Body

try:
    from core.response import ApiResponse
except ImportError:
    from ..core.response import ApiResponse

try:
    from core.auth_middleware import get_current_user
except ImportError:
    from ..core.auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/runs", tags=["运行历史"])

_run_history_mgr = None


def _get_run_history_manager():
    """获取运行历史管理器实例."""
    global _run_history_mgr
    if _run_history_mgr is None:
        try:
            from run_history import get_run_history_manager as _grhm
            _run_history_mgr = _grhm()
        except ImportError:
            pass
    return _run_history_mgr


@router.get("/history", summary="获取运行历史列表")
async def get_run_history(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    limit: int = Query(20, description="返回数量限制"),
    offset: int = Query(0, description="偏移量"),
    success_only: bool = Query(False, description="仅返回成功记录"),
    language: Optional[str] = Query(None, description="按语言过滤"),
    current_user: dict = Depends(get_current_user),
):
    """获取指定项目的代码运行历史记录。"""
    mgr = _get_run_history_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="运行历史管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.get_run_history(
        project_path=project_path,
        limit=limit,
        offset=offset,
        success_only=success_only,
        language=language,
    )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{run_id}", summary="获取运行详情")
async def get_run_detail(
    request: Request,
    run_id: str,
    project_path: str = Query(..., description="项目路径"),
    current_user: dict = Depends(get_current_user),
):
    """获取单次代码运行的详细信息。"""
    mgr = _get_run_history_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="运行历史管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.get_run_detail(
        project_path=project_path,
        run_id=run_id,
    )

    if not result:
        return ApiResponse.error(
            code=404,
            message=f"运行记录不存在: {run_id}",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/stats/summary", summary="获取运行统计")
async def get_run_stats(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    current_user: dict = Depends(get_current_user),
):
    """获取指定项目的代码运行统计信息。"""
    mgr = _get_run_history_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="运行历史管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.get_stats(project_path=project_path)

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.delete("/history", summary="清除运行历史")
async def clear_run_history(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    current_user: dict = Depends(get_current_user),
):
    """清除指定项目的所有运行历史记录。"""
    mgr = _get_run_history_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="运行历史管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    success = mgr.clear_history(project_path=project_path)

    if not success:
        return ApiResponse.error(
            code=500,
            message="清除历史失败",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="运行历史已清除",
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/record", summary="添加运行记录")
async def add_run_record(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """手动添加一条运行记录（主要供内部使用）。

    请求体：
    - project_path: 项目路径
    - config: 运行配置
    - result: 运行结果
    """
    mgr = _get_run_history_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="运行历史管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    project_path = body.get("project_path", "")
    config = body.get("config", {})
    result = body.get("result", {})

    if not project_path:
        return ApiResponse.error(
            code=400,
            message="项目路径不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    record = mgr.add_run_record(
        project_path=project_path,
        config=config,
        result=result,
    )

    return ApiResponse.success(
        message="记录添加成功",
        data=record,
        request_id=request.headers.get("X-Request-ID", ""),
    )
