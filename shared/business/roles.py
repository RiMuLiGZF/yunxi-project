"""
云汐系统角色与权限模块
提供系统角色枚举、角色层级定义和权限检查工具函数
"""

from enum import Enum
from typing import Dict, List, Optional


class SystemRole(str, Enum):
    """系统角色枚举

    定义云汐系统中所有内置角色，按权限从高到低排列。

    Attributes:
        OWNER: 主理人 - 最高权限，拥有系统完全控制权
        ADMIN: 管理员 - 仅次于主理人，可管理大部分系统功能
        OPERATOR: 运维 - 负责系统运维操作，无用户管理权限
        VIEWER: 只读 - 仅可查看数据，不可修改
        USER: 普通用户 - 基础访问权限
    """

    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    USER = "user"


# ==================== 角色层级定义 ====================

ROLE_HIERARCHY: Dict[str, int] = {
    "owner": 100,
    "admin": 80,
    "operator": 60,
    "viewer": 30,
    "user": 10,
}
"""角色权限等级映射，数字越大权限越高

- owner:    100  主理人（最高权限）
- admin:     80  管理员
- operator:  60  运维
- viewer:    30  只读
- user:      10  普通用户
"""


# ==================== 角色显示名称 ====================

ROLE_DISPLAY_NAMES: Dict[str, str] = {
    "owner": "主理人",
    "admin": "管理员",
    "operator": "运维",
    "viewer": "只读用户",
    "user": "普通用户",
}
"""角色中文显示名称映射"""


# ==================== 权限检查工具函数 ====================

def get_role_level(role: str) -> int:
    """获取角色的权限等级值

    Args:
        role: 角色标识字符串，如 "owner"、"admin" 等

    Returns:
        角色对应的权限等级数值，未知角色返回 0

    Examples:
        >>> get_role_level("owner")
        100
        >>> get_role_level("unknown")
        0
    """
    return ROLE_HIERARCHY.get(role, 0)


def has_min_role(user_role: str, min_role: str) -> bool:
    """检查用户角色是否达到最低权限要求

    比较用户角色与最低要求角色的权限等级，
    用户角色等级大于等于最低要求时返回 True。

    Args:
        user_role: 用户当前角色，如 "admin"、"operator" 等
        min_role: 最低要求角色，如 "viewer"、"admin" 等

    Returns:
        True 表示用户角色满足最低权限要求，False 表示不满足

    Examples:
        >>> has_min_role("admin", "viewer")
        True
        >>> has_min_role("user", "admin")
        False
        >>> has_min_role("owner", "owner")
        True
    """
    user_level = get_role_level(user_role)
    min_level = get_role_level(min_role)
    return user_level >= min_level


def is_owner(user_role: str) -> bool:
    """检查用户是否为主理人角色

    Args:
        user_role: 用户角色字符串

    Returns:
        True 表示是主理人，False 表示不是

    Examples:
        >>> is_owner("owner")
        True
        >>> is_owner("admin")
        False
    """
    return user_role == SystemRole.OWNER.value


def is_admin(user_role: str) -> bool:
    """检查用户是否为管理员及以上角色

    Args:
        user_role: 用户角色字符串

    Returns:
        True 表示是管理员或主理人，False 表示不是

    Examples:
        >>> is_admin("admin")
        True
        >>> is_admin("owner")
        True
        >>> is_admin("operator")
        False
    """
    return has_min_role(user_role, SystemRole.ADMIN.value)


def is_operator(user_role: str) -> bool:
    """检查用户是否为运维及以上角色

    Args:
        user_role: 用户角色字符串

    Returns:
        True 表示是运维、管理员或主理人，False 表示不是

    Examples:
        >>> is_operator("operator")
        True
        >>> is_operator("admin")
        True
        >>> is_operator("viewer")
        False
    """
    return has_min_role(user_role, SystemRole.OPERATOR.value)


def is_viewer(user_role: str) -> bool:
    """检查用户是否为只读用户及以上角色

    Args:
        user_role: 用户角色字符串

    Returns:
        True 表示是 viewer 及以上角色，False 表示不是

    Examples:
        >>> is_viewer("viewer")
        True
        >>> is_viewer("user")
        False
    """
    return has_min_role(user_role, SystemRole.VIEWER.value)


def get_role_display_name(role: str) -> str:
    """获取角色的中文显示名称

    Args:
        role: 角色标识字符串

    Returns:
        角色的中文显示名称，未知角色返回原字符串

    Examples:
        >>> get_role_display_name("owner")
        '主理人'
        >>> get_role_display_name("unknown")
        'unknown'
    """
    return ROLE_DISPLAY_NAMES.get(role, role)


def get_all_roles() -> List[str]:
    """获取所有系统角色列表

    Returns:
        所有角色标识字符串的列表，按权限从高到低排列

    Examples:
        >>> get_all_roles()
        ['owner', 'admin', 'operator', 'viewer', 'user']
    """
    return [role.value for role in SystemRole]


def get_role_info(role: str) -> Optional[Dict[str, object]]:
    """获取角色的完整信息

    Args:
        role: 角色标识字符串

    Returns:
        角色信息字典，包含 name、level、display_name 字段，
        未知角色返回 None

    Examples:
        >>> get_role_info("owner")
        {'name': 'owner', 'level': 100, 'display_name': '主理人'}
    """
    if role not in ROLE_HIERARCHY:
        return None
    return {
        "name": role,
        "level": ROLE_HIERARCHY[role],
        "display_name": ROLE_DISPLAY_NAMES.get(role, role),
    }
