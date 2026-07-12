"""
M0 主理人管控台 - 权限与角色管理路由

管理系统用户、角色和权限。
MVP 版本：展示角色体系，具体用户管理对接 M8。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends

from ..auth import get_principal_user
from ..models import ApiResponse, RoleItem

router = APIRouter(tags=["权限管理"])


# 角色定义（与 M8 保持一致）
ROLES: List[RoleItem] = [
    RoleItem(
        name="主理人",
        key="owner",
        level=100,
        description="系统最高权限，拥有所有模块的完全控制权",
        permissions=[
            "system:*", "modules:*", "config:*", "users:*",
            "audit:*", "emergency:*", "upgrade:*",
        ],
    ),
    RoleItem(
        name="管理员",
        key="admin",
        level=80,
        description="系统管理员，可管理模块和用户，但无紧急操作权限",
        permissions=[
            "system:read", "system:write",
            "modules:*", "config:read", "config:write",
            "users:read", "users:write",
            "audit:read",
        ],
    ),
    RoleItem(
        name="审计员",
        key="auditor",
        level=60,
        description="只读权限，可查看所有数据和审计日志",
        permissions=[
            "system:read", "modules:read", "config:read",
            "audit:read", "users:read",
        ],
    ),
    RoleItem(
        name="普通用户",
        key="user",
        level=40,
        description="普通登录用户，可使用基本功能",
        permissions=[
            "system:read", "modules:read",
        ],
    ),
    RoleItem(
        name="访客",
        key="viewer",
        level=20,
        description="访客，仅可查看公开信息",
        permissions=["system:read"],
    ),
]


@router.get("/roles", summary="获取角色列表")
async def list_roles(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[RoleItem]]:
    """
    获取系统所有角色及其权限列表
    """
    return ApiResponse.success(data=ROLES, message=f"共 {len(ROLES)} 个角色")


@router.get("/roles/{role_key}", summary="获取角色详情")
async def get_role(
    role_key: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[RoleItem]:
    """
    获取单个角色的详细信息
    """
    for role in ROLES:
        if role.key == role_key:
            return ApiResponse.success(data=role, message="获取成功")
    return ApiResponse.error(message=f"角色 {role_key} 不存在", code=40400)


@router.get("/users", summary="获取用户列表")
async def list_users(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[list]:
    """
    获取系统用户列表（MVP 版本：返回 mock 数据）

    生产环境应从 M8 或数据库中获取。
    """
    mock_users = [
        {"id": 1, "username": "owner", "role": "owner", "display_name": "主理人", "status": "active", "created_at": "2026-01-01"},
        {"id": 2, "username": "admin01", "role": "admin", "display_name": "管理员A", "status": "active", "created_at": "2026-02-01"},
        {"id": 3, "username": "auditor01", "role": "auditor", "display_name": "审计员", "status": "active", "created_at": "2026-03-01"},
        {"id": 4, "username": "user01", "role": "user", "display_name": "用户A", "status": "active", "created_at": "2026-04-01"},
    ]
    return ApiResponse.success(data=mock_users, message=f"共 {len(mock_users)} 个用户")


@router.post("/users/{user_id}/role", summary="修改用户角色")
async def change_user_role(
    user_id: int,
    role: str,
    current_user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    修改用户角色（MVP 版本：模拟操作）

    Args:
        user_id: 用户 ID
        role: 新角色
    """
    # MVP 版本：模拟操作
    return ApiResponse.success(
        data={"user_id": user_id, "new_role": role},
        message=f"用户角色已更新为 {role}",
    )
