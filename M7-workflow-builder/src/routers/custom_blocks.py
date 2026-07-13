"""M7 积木平台 - 自定义积木管理路由.

提供用户自定义积木的 CRUD API。
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db_dependency
from ..models import ApiResponse, CustomBlockCreate, CustomBlockUpdate
from ..models_db import CustomBlock
from ..m8_api.m8_auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/custom-blocks", tags=["自定义积木"])


def _make_block_id() -> str:
    """生成自定义积木 ID."""
    return f"cb_{uuid.uuid4().hex[:12]}"


def _check_block_ownership(block: CustomBlock, user_id: str) -> bool:
    """校验自定义积木所有权.

    Args:
        block: 自定义积木对象
        user_id: 当前用户ID

    Returns:
        bool: 是否有权限

    Note:
        管理员角色可访问所有积木
    """
    if not user_id:
        return False
    # 管理员可访问所有
    if user_id == "admin":
        return True
    return block.user_id == user_id


# ============================================================
# 自定义积木 CRUD
# ============================================================

@router.get("")
async def list_custom_blocks(
    request: Request,
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页数量"),
    db: Session = Depends(get_db_dependency),
    current_user: dict = Depends(get_current_user),
):
    """获取自定义积木列表（支持分类筛选、搜索、分页）."""
    query = db.query(CustomBlock)

    # 按用户筛选
    user_id = current_user.get("username", "")
    if user_id:
        query = query.filter(CustomBlock.user_id == user_id)

    # 分类筛选
    if category:
        query = query.filter(CustomBlock.category == category)

    # 搜索
    if search:
        keyword = f"%{search.lower()}%"
        query = query.filter(
            (CustomBlock.name.ilike(keyword))
            | (CustomBlock.description.ilike(keyword))
        )

    # 按更新时间倒序
    query = query.order_by(CustomBlock.updated_at.desc())

    total = query.count()

    # 分页
    start = (page - 1) * page_size
    items = [cb.to_dict() for cb in query.offset(start).limit(page_size).all()]

    return ApiResponse.success(
        data={
            "total": total,
            "items": items,
            "page": page,
            "page_size": page_size,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("")
async def create_custom_block(
    request: Request,
    req: CustomBlockCreate,
    db: Session = Depends(get_db_dependency),
    current_user: dict = Depends(get_current_user),
):
    """创建自定义积木."""
    block_id = _make_block_id()
    user_id = current_user.get("username", "")

    block = CustomBlock(
        id=block_id,
        name=req.name,
        category=req.category,
        description=req.description,
        code=req.code,
        icon=req.icon,
        ports=req.ports,
        user_id=user_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)

    return ApiResponse.success(
        message="自定义积木创建成功",
        data=block.to_dict(),
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{block_id}")
async def get_custom_block(
    request: Request,
    block_id: str,
    db: Session = Depends(get_db_dependency),
    current_user: dict = Depends(get_current_user),
):
    """获取自定义积木详情."""
    block = db.query(CustomBlock).filter(CustomBlock.id == block_id).first()
    if not block:
        return ApiResponse.error(
            code=404,
            message=f"自定义积木 {block_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 所有权校验
    user_id = current_user.get("username", "")
    if not _check_block_ownership(block, user_id):
        return ApiResponse.error(
            code=403,
            message="无权限访问该自定义积木",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=block.to_dict(),
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.put("/{block_id}")
async def update_custom_block(
    request: Request,
    block_id: str,
    req: CustomBlockUpdate,
    db: Session = Depends(get_db_dependency),
    current_user: dict = Depends(get_current_user),
):
    """更新自定义积木."""
    block = db.query(CustomBlock).filter(CustomBlock.id == block_id).first()
    if not block:
        return ApiResponse.error(
            code=404,
            message=f"自定义积木 {block_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 所有权校验
    user_id = current_user.get("username", "")
    if not _check_block_ownership(block, user_id):
        return ApiResponse.error(
            code=403,
            message="无权限修改该自定义积木",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 更新字段
    if req.name is not None:
        block.name = req.name
    if req.category is not None:
        block.category = req.category
    if req.description is not None:
        block.description = req.description
    if req.code is not None:
        block.code = req.code
    if req.icon is not None:
        block.icon = req.icon
    if req.ports is not None:
        block.ports = req.ports

    db.commit()
    db.refresh(block)

    return ApiResponse.success(
        message="自定义积木更新成功",
        data=block.to_dict(),
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.delete("/{block_id}")
async def delete_custom_block(
    request: Request,
    block_id: str,
    db: Session = Depends(get_db_dependency),
    current_user: dict = Depends(get_current_user),
):
    """删除自定义积木."""
    block = db.query(CustomBlock).filter(CustomBlock.id == block_id).first()
    if not block:
        return ApiResponse.error(
            code=404,
            message=f"自定义积木 {block_id} 不存在",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 所有权校验
    user_id = current_user.get("username", "")
    if not _check_block_ownership(block, user_id):
        return ApiResponse.error(
            code=403,
            message="无权限删除该自定义积木",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    db.delete(block)
    db.commit()

    return ApiResponse.success(
        message="自定义积木已删除",
        request_id=request.headers.get("X-Request-ID", ""),
    )
