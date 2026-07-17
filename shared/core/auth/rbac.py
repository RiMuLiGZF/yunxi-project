"""
统一认证体系 - 角色权限控制（RBAC）模块

提供基于角色的访问控制（RBAC）能力，包括：
- 预定义角色与层级映射
- 权限范围（Scope）管理
- 角色检查与权限检查函数
- FastAPI 依赖装饰器

用法：
    from shared.core.auth.rbac import (
        has_role, has_scope, require_role, require_scope,
        ROLE_ADMIN, ROLE_VIEWER,
    )

    # 检查角色
    if has_role(user_roles, ROLE_ADMIN):
        ...

    # 作为 FastAPI 依赖使用
    @app.get("/admin")
    async def admin_endpoint(user=Depends(require_role(ROLE_ADMIN))):
        ...
"""

from typing import List, Callable, Any, Optional


# ===========================================================================
# 角色定义
# ===========================================================================

# 标准角色
ROLE_SUPER_ADMIN = "super_admin"    # 超级管理员（最高权限）
ROLE_ADMIN = "admin"                # 管理员
ROLE_OPERATOR = "operator"          # 运维人员
ROLE_VIEWER = "viewer"              # 只读用户
ROLE_API = "api"                    # API 调用者（服务间调用）

# 角色层级映射（数值越大权限越高）
# 高级别角色自动拥有低级别角色的所有权限
ROLE_HIERARCHY = {
    ROLE_SUPER_ADMIN: 100,
    ROLE_ADMIN: 80,
    ROLE_OPERATOR: 60,
    ROLE_VIEWER: 40,
    ROLE_API: 20,
}

ALL_ROLES = list(ROLE_HIERARCHY.keys())


# ===========================================================================
# 权限范围（Scope）定义
# ===========================================================================

# 通用权限范围命名规范: "{资源}:{操作}"
SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_DELETE = "delete"
SCOPE_ADMIN = "admin"

# 通配符
SCOPE_ALL = "*"


# ===========================================================================
# 角色检查函数
# ===========================================================================

def has_role(user_roles: List[str], required_role: str) -> bool:
    """检查用户是否拥有指定角色（按层级判断）

    高级别角色自动包含低级别角色的权限。
    例如：拥有 ROLE_ADMIN 的用户自动满足 ROLE_VIEWER 的要求。

    Args:
        user_roles: 用户拥有的角色列表
        required_role: 需要的最低角色

    Returns:
        True 表示用户有权限，False 表示没有
    """
    if not user_roles or not required_role:
        return False

    required_level = ROLE_HIERARCHY.get(required_role, 0)

    for role in user_roles:
        user_level = ROLE_HIERARCHY.get(role, 0)
        if user_level >= required_level:
            return True

    return False


def has_any_role(user_roles: List[str], required_roles: List[str]) -> bool:
    """检查用户是否拥有任意一个指定角色

    Args:
        user_roles: 用户拥有的角色列表
        required_roles: 需要的角色列表（满足任意一个即可）

    Returns:
        True 表示用户拥有其中至少一个角色
    """
    if not user_roles or not required_roles:
        return False

    for role in required_roles:
        if has_role(user_roles, role):
            return True

    return False


def has_all_roles(user_roles: List[str], required_roles: List[str]) -> bool:
    """检查用户是否拥有所有指定角色

    Args:
        user_roles: 用户拥有的角色列表
        required_roles: 需要的所有角色列表

    Returns:
        True 表示用户拥有所有需要的角色
    """
    if not user_roles or not required_roles:
        return False

    for role in required_roles:
        if not has_role(user_roles, role):
            return False

    return True


# ===========================================================================
# 权限范围（Scope）检查函数
# ===========================================================================

def has_scope(user_scopes: List[str], required_scope: str) -> bool:
    """检查用户是否拥有指定权限范围

    支持通配符 "*"，表示拥有所有权限。

    Args:
        user_scopes: 用户拥有的权限范围列表
        required_scope: 需要的权限范围

    Returns:
        True 表示用户拥有该权限
    """
    if not user_scopes or not required_scope:
        return False

    # 通配符支持
    if SCOPE_ALL in user_scopes:
        return True

    return required_scope in user_scopes


def has_any_scope(user_scopes: List[str], required_scopes: List[str]) -> bool:
    """检查用户是否拥有任意一个指定权限范围

    Args:
        user_scopes: 用户拥有的权限范围列表
        required_scopes: 需要的权限范围列表（满足任意一个即可）

    Returns:
        True 表示用户拥有其中至少一个权限
    """
    if not user_scopes or not required_scopes:
        return False

    for scope in required_scopes:
        if has_scope(user_scopes, scope):
            return True

    return False


def has_all_scopes(user_scopes: List[str], required_scopes: List[str]) -> bool:
    """检查用户是否拥有所有指定权限范围

    Args:
        user_scopes: 用户拥有的权限范围列表
        required_scopes: 需要的所有权限范围列表

    Returns:
        True 表示用户拥有所有需要的权限
    """
    if not user_scopes or not required_scopes:
        return False

    for scope in required_scopes:
        if not has_scope(user_scopes, scope):
            return False

    return True


# ===========================================================================
# FastAPI 依赖装饰器
# ===========================================================================

def require_role(required_role: str) -> Callable:
    """角色权限检查装饰器（作为 FastAPI 依赖使用）

    返回一个依赖函数，检查当前用户是否拥有指定角色。
    用户信息从上游依赖的 current_user 字典中获取。

    Args:
        required_role: 需要的最低角色

    Returns:
        FastAPI 依赖函数，返回用户信息字典

    用法：
        @app.get("/admin")
        async def admin_endpoint(
            current_user: dict = Depends(require_role(ROLE_ADMIN))
        ):
            return {"message": "欢迎管理员"}
    """
    def role_checker(current_user: dict) -> dict:
        if not isinstance(current_user, dict):
            # 尝试兼容不同的用户对象类型
            user_roles = getattr(current_user, "roles", [])
        else:
            user_roles = current_user.get("roles", [])

        if not has_role(user_roles, required_role):
            try:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要 {required_role} 角色权限",
                )
            except ImportError:
                raise PermissionError(f"需要 {required_role} 角色权限")

        return current_user

    return role_checker


def require_scope(required_scope: str) -> Callable:
    """权限范围检查装饰器（作为 FastAPI 依赖使用）

    返回一个依赖函数，检查当前用户是否拥有指定权限范围。

    Args:
        required_scope: 需要的权限范围

    Returns:
        FastAPI 依赖函数，返回用户信息字典

    用法：
        @app.get("/data")
        async def data_endpoint(
            current_user: dict = Depends(require_scope("data:read"))
        ):
            return {"data": "..."}
    """
    def scope_checker(current_user: dict) -> dict:
        if not isinstance(current_user, dict):
            user_scopes = getattr(current_user, "scopes", [])
        else:
            user_scopes = current_user.get("scopes", [])

        if not has_scope(user_scopes, required_scope):
            try:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要 {required_scope} 权限",
                )
            except ImportError:
                raise PermissionError(f"需要 {required_scope} 权限")

        return current_user

    return scope_checker


def require_any_scope(required_scopes: List[str]) -> Callable:
    """多权限范围检查装饰器（满足任意一个即可）

    Args:
        required_scopes: 需要的权限范围列表

    Returns:
        FastAPI 依赖函数
    """
    def scope_checker(current_user: dict) -> dict:
        if not isinstance(current_user, dict):
            user_scopes = getattr(current_user, "scopes", [])
        else:
            user_scopes = current_user.get("scopes", [])

        if not has_any_scope(user_scopes, required_scopes):
            try:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"需要以下任一权限: {', '.join(required_scopes)}",
                )
            except ImportError:
                raise PermissionError(
                    f"需要以下任一权限: {', '.join(required_scopes)}"
                )

        return current_user

    return scope_checker
