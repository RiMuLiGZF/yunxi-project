"""M7 积木平台 - 工作流版本管理路由.

提供工作流版本的列表、详情、对比、回滚等 API。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..models import ApiResponse
from ..services.storage import get_storage
from ..services.version_manager import get_version_manager
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/workflows", tags=["版本管理"])

_version_mgr = get_version_manager()
_storage = get_storage()


# ============================================================
# 请求模型
# ============================================================

class CreateVersionRequest(BaseModel):
    """创建版本请求."""
    version_note: str = ""
    bump_type: str = Field(default="patch", description="递增类型: major/minor/patch")


class RollbackRequest(BaseModel):
    """回滚请求."""
    rollback_note: str = ""


# ============================================================
# 版本列表
# ============================================================

@router.get("/{workflow_id}/versions")
async def list_versions(
    request: Request,
    workflow_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """获取工作流的版本列表."""
    # 检查工作流是否存在
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = _version_mgr.list_versions(workflow_id, limit=limit, offset=offset)

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 版本详情
# ============================================================

@router.get("/{workflow_id}/versions/{version_id}")
async def get_version_detail(
    request: Request,
    workflow_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取指定版本的详情（含完整工作流定义）."""
    version = _version_mgr.get_version(workflow_id, version_id=version_id)
    if not version:
        return ApiResponse.error(
            code=404,
            message=f"版本 {version_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=version,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 创建版本（发布）
# ============================================================

@router.post("/{workflow_id}/versions")
async def create_version(
    request: Request,
    workflow_id: str,
    req: CreateVersionRequest = CreateVersionRequest(),
    current_user: dict = Depends(get_current_user),
):
    """创建工作流新版本（发布）.

    基于当前工作流定义创建一个新版本快照。
    """
    workflow = _storage.get_workflow(workflow_id)
    if not workflow:
        return ApiResponse.error(
            code=404,
            message=f"工作流 {workflow_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    version_record = _version_mgr.create_version(
        workflow_id=workflow_id,
        workflow_data=workflow,
        version_note=req.version_note,
        bump_type=req.bump_type,
        created_by=current_user.get("username", ""),
    )

    # 更新工作流状态为已发布
    workflow["status"] = "published"
    workflow["current_version"] = version_record["version"]
    _storage.upsert_workflow(workflow_id, workflow)

    return ApiResponse.success(
        message="版本创建成功",
        data=version_record,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 版本对比
# ============================================================

@router.get("/{workflow_id}/versions/compare")
async def compare_versions(
    request: Request,
    workflow_id: str,
    version_a: str = Query(..., description="版本 A 的 ID"),
    version_b: str = Query(..., description="版本 B 的 ID"),
    current_user: dict = Depends(get_current_user),
):
    """对比两个版本的差异."""
    result = _version_mgr.compare_versions(
        workflow_id=workflow_id,
        version_a_id=version_a,
        version_b_id=version_b,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=404,
            message=result.get("error", "版本对比失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 版本回滚
# ============================================================

@router.post("/{workflow_id}/versions/{version_id}/rollback")
async def rollback_version(
    request: Request,
    workflow_id: str,
    version_id: str,
    req: RollbackRequest = RollbackRequest(),
    current_user: dict = Depends(get_current_user),
):
    """回滚到指定版本.

    会创建一个新版本，内容与目标版本相同，并更新当前工作流定义。
    """
    result = _version_mgr.rollback_to_version(
        workflow_id=workflow_id,
        version_id=version_id,
        storage=_storage,
        rollback_note=req.rollback_note,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "回滚失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="版本回滚成功",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 删除版本
# ============================================================

@router.delete("/{workflow_id}/versions/{version_id}")
async def delete_version(
    request: Request,
    workflow_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定版本."""
    success = _version_mgr.delete_version(workflow_id, version_id)
    if not success:
        return ApiResponse.error(
            code=404,
            message=f"版本 {version_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="版本已删除",
        request_id=request.headers.get("X-Request-ID", ""),
    )


# ============================================================
# 按版本号执行工作流
# ============================================================

@router.post("/{workflow_id}/versions/{version_id}/run")
async def run_version(
    request: Request,
    workflow_id: str,
    version_id: str,
    current_user: dict = Depends(get_current_user),
):
    """使用指定版本的工作流定义执行.

    返回指定版本的工作流定义，前端可基于此发起执行。
    """
    version = _version_mgr.get_version(workflow_id, version_id=version_id)
    if not version:
        return ApiResponse.error(
            code=404,
            message=f"版本 {version_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="版本执行入口",
        data={
            "version_id": version_id,
            "version": version.get("version"),
            "workflow_data": version.get("workflow_data"),
            "note": "使用 workflow_data 字段作为工作流定义进行执行",
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )
