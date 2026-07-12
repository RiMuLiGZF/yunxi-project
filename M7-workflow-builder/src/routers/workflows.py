"""M7 积木平台 - 工作流管理路由.

提供工作流的 CRUD、复制、运行等 API。
"""

from __future__ import annotations

import copy
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from ..models import (
    ApiResponse,
    WorkflowCreateRequest,
    WorkflowRunRequest,
    WorkflowUpdateRequest,
)
from ..services.storage import get_storage
from ..services.engine import WorkflowEngine
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/workflows", tags=["工作流管理"])

_storage = get_storage()
_engine = WorkflowEngine()


def _now_iso() -> str:
    """获取当前 ISO 格式时间字符串."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ============================================================
# 工作流 CRUD
# ============================================================

@router.get("")
async def list_workflows(
    request: Request,
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词（名称/描述）"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页数量"),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流列表（支持分类筛选、搜索、状态筛选、分页）."""
    workflows = _storage.load_workflows()
    items = list(workflows.values())

    # 分类筛选
    if category:
        items = [w for w in items if w.get("category") == category]

    # 状态筛选
    if status:
        items = [w for w in items if w.get("status") == status]

    # 搜索
    if search:
        keyword = search.lower()
        items = [
            w for w in items
            if keyword in w.get("name", "").lower()
            or keyword in w.get("description", "").lower()
        ]

    # 按更新时间倒序
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    total = len(items)

    # 分页
    start = (page - 1) * page_size
    end = start + page_size
    paged_items = items[start:end]

    return ApiResponse.success(
        data={
            "total": total,
            "items": paged_items,
            "page": page,
            "page_size": page_size,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("")
async def create_workflow(
    request: Request,
    req: WorkflowCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建工作流."""
    now = _now_iso()
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"

    workflow = {
        "id": workflow_id,
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "status": req.status.value if hasattr(req.status, 'value') else req.status,
        "blocks": [b.model_dump() for b in req.blocks],
        "connections": [c.model_dump() for c in req.connections],
        "variables": [v.model_dump() for v in req.variables],
        "trigger": req.trigger.model_dump() if req.trigger else {"type": "manual", "config": {}},
        "created_at": now,
        "updated_at": now,
        "run_count": 0,
        "created_by": current_user.get("username", ""),
    }

    _storage.upsert_workflow(workflow_id, workflow)

    return ApiResponse.success(
        message="工作流创建成功",
        data=workflow,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{workflow_id}")
async def get_workflow(
    request: Request,
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取工作流详情."""
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=workflow,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.put("/{workflow_id}")
async def update_workflow(
    request: Request,
    workflow_id: str,
    req: WorkflowUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """更新工作流."""
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 更新字段
    if req.name is not None:
        workflow["name"] = req.name
    if req.description is not None:
        workflow["description"] = req.description
    if req.category is not None:
        workflow["category"] = req.category
    if req.blocks is not None:
        workflow["blocks"] = [b.model_dump() for b in req.blocks]
    if req.connections is not None:
        workflow["connections"] = [c.model_dump() for c in req.connections]
    if req.variables is not None:
        workflow["variables"] = [v.model_dump() for v in req.variables]
    if req.trigger is not None:
        workflow["trigger"] = req.trigger.model_dump()
    if req.status is not None:
        workflow["status"] = req.status.value if hasattr(req.status, 'value') else req.status

    workflow["updated_at"] = _now_iso()
    _storage.upsert_workflow(workflow_id, workflow)

    return ApiResponse.success(
        message="工作流更新成功",
        data=workflow,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.delete("/{workflow_id}")
async def delete_workflow(
    request: Request,
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除工作流."""
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    _storage.delete_workflow(workflow_id)
    # 同时删除运行历史
    _storage.delete_workflow_runs(workflow_id)

    return ApiResponse.success(
        message="工作流已删除",
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/{workflow_id}/duplicate")
async def duplicate_workflow(
    request: Request,
    workflow_id: str,
    current_user: dict = Depends(get_current_user),
):
    """复制工作流."""
    source = _storage.get_workflow(workflow_id)
    if not source:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    now = _now_iso()
    new_id = f"wf_{uuid.uuid4().hex[:12]}"
    new_workflow = copy.deepcopy(source)
    new_workflow["id"] = new_id
    new_workflow["name"] = f"{source.get('name', '')} (副本)"
    new_workflow["created_at"] = now
    new_workflow["updated_at"] = now
    new_workflow["status"] = "draft"
    new_workflow["run_count"] = 0
    new_workflow["created_by"] = current_user.get("username", "")

    _storage.upsert_workflow(new_id, new_workflow)

    return ApiResponse.success(
        message="工作流复制成功",
        data=new_workflow,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 工作流运行
# ============================================================

@router.post("/{workflow_id}/run")
async def run_workflow(
    request: Request,
    workflow_id: str,
    req: WorkflowRunRequest = WorkflowRunRequest(),
    current_user: dict = Depends(get_current_user),
):
    """运行工作流.

    支持线性串行和 DAG 两种执行模式，自动检测工作流结构。
    记录每步的输入/输出/状态/耗时。
    """
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    blocks = workflow.get("blocks", [])
    if not blocks:
        return ApiResponse.error(
            code=400,
            message="工作流中没有积木块",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 执行工作流
    run_result = await _engine.run_workflow(
        workflow=workflow,
        input_data=req.input_data,
        start_block=req.start_block,
        runtime_variables=req.variables,
        triggered_by=current_user.get("username", ""),
    )

    # 保存运行记录
    _storage.add_run(workflow_id, run_result)

    # 更新运行计数
    _storage.increment_run_count(workflow_id)

    # 记录指标
    from ..m8_api.health_endpoints import record_run
    record_run(run_result.get("status") == "success")

    success = run_result.get("status") == "success"

    return ApiResponse.success(
        message="工作流执行完成" if success else "工作流执行失败",
        data=run_result,
        request_id=request.headers.get("X-Request-ID", ""),
    )
