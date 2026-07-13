"""M7 积木平台 - 运行历史路由.

提供工作流运行历史的查询 API，以及运行中工作流的取消/恢复 API。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from ..models import ApiResponse
from ..services.storage import get_storage
from ..services.engine import WorkflowEngine
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(tags=["运行历史"])

_storage = get_storage()
_engine = WorkflowEngine()


# ============================================================
# 工作流运行历史
# ============================================================

@router.get("/api/v1/workflows/{workflow_id}/runs")
async def list_workflow_runs(
    request: Request,
    workflow_id: str,
    status: Optional[str] = Query(default=None, description="状态筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流的运行历史列表."""
    # 先检查工作流是否存在
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    runs = _storage.get_workflow_runs(workflow_id, limit=limit, offset=offset)

    # 状态筛选
    if status:
        runs = [r for r in runs if r.get("status") == status]

    total = len(runs) + offset  # 近似总数

    return ApiResponse.success(
        data={
            "total": total,
            "items": runs,
            "limit": limit,
            "offset": offset,
            "workflow_id": workflow_id,
            "workflow_name": workflow.get("name", ""),
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 单次运行详情
# ============================================================

@router.get("/api/v1/runs/{run_id}")
async def get_run_detail(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单次运行的详细信息."""
    run = _storage.get_run(run_id)
    if not run:
        return ApiResponse.error(
            code=404,
            message=f"运行记录 {run_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=run,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# P1-04: 运行控制（取消）
# ============================================================

@router.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(
    request: Request,
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """取消正在运行的工作流.

    协作式取消，发送取消信号后工作流会在下一个检查点终止。
    """
    success = await WorkflowEngine.cancel_run(run_id)
    if success:
        # 更新运行记录状态
        run = _storage.get_run(run_id)
        if run:
            _storage.update_run(
                run.get("workflow_id", ""),
                run_id,
                {"status": "cancelled", "error": "用户取消"},
            )
        return ApiResponse.success(
            message="工作流取消请求已发送",
            data={"run_id": run_id, "cancelled": True},
            request_id=request.headers.get("X-Request-ID", ""),
        )
    else:
        return ApiResponse.error(
            code=404,
            message=f"运行 {run_id} 不存在或已完成",
            request_id=request.headers.get("X-Request-ID", ""),
        )


# ============================================================
# 引擎状态查询
# ============================================================

@router.get("/api/v1/engine/status")
async def engine_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """查询工作流引擎当前状态.

    返回运行中工作流数量、并发限制等。
    """
    return ApiResponse.success(
        data={
            "running_count": WorkflowEngine.get_running_count(),
            "max_running": WorkflowEngine._get_max_running(),
            "active_tasks": len(WorkflowEngine._active_tasks),
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )
