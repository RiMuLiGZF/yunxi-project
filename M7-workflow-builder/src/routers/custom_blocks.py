"""M7 积木平台 - 自定义积木管理路由.

提供用户自定义积木的 CRUD API。

安全说明：
- 自定义积木的 code 字段当前仅作存储用途，不会被执行
- 所有代码写入前均经过安全校验（关键字黑名单 + AST 检查）
- 操作均记录安全审计日志
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
from ..utils.security import (
    validate_custom_block_code,
    sanitize_custom_block_name,
    _add_audit_log,
)


router = APIRouter(prefix="/api/v1/custom-blocks", tags=["自定义积木"])

# 自定义积木名称最大长度
MAX_BLOCK_NAME_LENGTH = 200
# 自定义积木描述最大长度
MAX_BLOCK_DESCRIPTION_LENGTH = 2000


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
    user_id = current_user.get("username", "")

    # 安全校验：名称清洗
    clean_name = sanitize_custom_block_name(req.name, MAX_BLOCK_NAME_LENGTH)
    if not clean_name:
        return ApiResponse.error(
            code=400,
            message="积木名称无效",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 安全校验：描述长度限制
    description = req.description or ""
    if len(description) > MAX_BLOCK_DESCRIPTION_LENGTH:
        description = description[:MAX_BLOCK_DESCRIPTION_LENGTH]

    # 安全校验：代码安全检查
    is_safe, safe_reason = validate_custom_block_code(
        req.code or "",
        user_id=user_id,
    )
    if not is_safe:
        return ApiResponse.error(
            code=400,
            message=f"代码安全校验失败：{safe_reason}",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    block_id = _make_block_id()

    block = CustomBlock(
        id=block_id,
        name=clean_name,
        category=req.category,
        description=description,
        code=req.code or "",
        icon=req.icon,
        ports=req.ports,
        user_id=user_id,
    )
    db.add(block)
    db.commit()
    db.refresh(block)

    # 审计日志
    _add_audit_log(
        event_type="custom_block_created",
        severity="info",
        user_id=user_id,
        block_id=block_id,
        details=f"创建自定义积木：{clean_name}",
    )

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
        _add_audit_log(
            event_type="custom_block_unauthorized_access",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details="无权限访问自定义积木",
        )
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
        _add_audit_log(
            event_type="custom_block_unauthorized_modify",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details="无权限修改自定义积木",
        )
        return ApiResponse.error(
            code=403,
            message="无权限修改该自定义积木",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 更新字段
    if req.name is not None:
        clean_name = sanitize_custom_block_name(req.name, MAX_BLOCK_NAME_LENGTH)
        if not clean_name:
            return ApiResponse.error(
                code=400,
                message="积木名称无效",
                request_id=request.headers.get("X-Request-ID", ""),
            )
        block.name = clean_name

    if req.category is not None:
        block.category = req.category

    if req.description is not None:
        description = req.description
        if len(description) > MAX_BLOCK_DESCRIPTION_LENGTH:
            description = description[:MAX_BLOCK_DESCRIPTION_LENGTH]
        block.description = description

    if req.code is not None:
        # 安全校验：代码安全检查
        is_safe, safe_reason = validate_custom_block_code(
            req.code,
            user_id=user_id,
            block_id=block_id,
        )
        if not is_safe:
            return ApiResponse.error(
                code=400,
                message=f"代码安全校验失败：{safe_reason}",
                request_id=request.headers.get("X-Request-ID", ""),
            )
        block.code = req.code

    if req.icon is not None:
        block.icon = req.icon
    if req.ports is not None:
        block.ports = req.ports

    db.commit()
    db.refresh(block)

    # 审计日志
    _add_audit_log(
        event_type="custom_block_updated",
        severity="info",
        user_id=user_id,
        block_id=block_id,
        details=f"更新自定义积木：{block.name}",
    )

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
        _add_audit_log(
            event_type="custom_block_unauthorized_delete",
            severity="warning",
            user_id=user_id,
            block_id=block_id,
            details="无权限删除自定义积木",
        )
        return ApiResponse.error(
            code=403,
            message="无权限删除该自定义积木",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    block_name = block.name
    db.delete(block)
    db.commit()

    # 审计日志
    _add_audit_log(
        event_type="custom_block_deleted",
        severity="info",
        user_id=user_id,
        block_id=block_id,
        details=f"删除自定义积木：{block_name}",
    )

    return ApiResponse.success(
        message="自定义积木已删除",
        request_id=request.headers.get("X-Request-ID", ""),
    )
