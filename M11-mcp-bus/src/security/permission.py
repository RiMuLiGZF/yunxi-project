"""M11 MCP Bus - 安全层 - 权限检查.

提供细粒度的权限控制，支持：
- 基于角色的权限（RBAC 简化版）
- 通配符权限匹配
- 超级权限（*）
- 按资源粒度控制

权限格式:
    资源:操作    如 "servers:read", "tools:call", "admin:apikeys:write"
    资源:*       如 "servers:*" 表示对 servers 资源的所有操作
    *            超级权限，拥有所有权限
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import List, Optional

from ..models_db import ApiKey


# ============================================================
# 标准权限常量
# ============================================================

# 超级权限
SUPER_PERMISSION = "*"

# 资源类型
RESOURCE_SERVERS = "servers"
RESOURCE_TOOLS = "tools"
RESOURCE_ADMIN = "admin"
RESOURCE_MCP = "mcp"
RESOURCE_AUDIT = "audit"

# 操作类型
ACTION_READ = "read"
ACTION_WRITE = "write"
ACTION_CALL = "call"
ACTION_DELETE = "delete"
ACTION_MANAGE = "manage"

# 常用权限组合
COMMON_PERMISSIONS = {
    "read_only": [
        "servers:read",
        "tools:read",
        "tools:call",
        "mcp:read",
        "mcp:call",
    ],
    "admin": [
        "*",
    ],
    "mcp_user": [
        "mcp:read",
        "mcp:call",
        "tools:call",
    ],
}


# ============================================================
# 权限检查服务
# ============================================================

class PermissionChecker:
    """权限检查服务.

    提供灵活的权限检查功能，支持通配符匹配和层级权限。

    权限匹配规则:
    1. 超级权限 "*" 匹配所有权限
    2. 通配符匹配：如 "admin:*" 匹配所有 admin 开头的权限
    3. 精确匹配：权限字符串完全相同
    4. fnmatch 匹配：支持更复杂的通配符模式

    使用方式:
        checker = PermissionChecker()
        if checker.has_permission(api_key, "servers:read"):
            ...
    """

    def __init__(self) -> None:
        """初始化权限检查器."""
        pass

    # --------------------------------------------------------
    # 核心检查方法
    # --------------------------------------------------------

    def has_permission(
        self,
        api_key: Optional[ApiKey],
        permission: str,
    ) -> bool:
        """检查 API Key 是否拥有指定权限.

        Args:
            api_key: API Key 对象（None 表示未认证）
            permission: 需要的权限标识（如 "servers:read"）

        Returns:
            True 表示拥有权限
        """
        if api_key is None:
            return False

        permissions = api_key.permissions or []
        return self._check_permission(permissions, permission)

    def has_any_permission(
        self,
        api_key: Optional[ApiKey],
        permissions: List[str],
    ) -> bool:
        """检查是否拥有列表中任意一个权限.

        Args:
            api_key: API Key 对象
            permissions: 权限列表

        Returns:
            True 表示拥有其中至少一个权限
        """
        if api_key is None:
            return False

        for perm in permissions:
            if self.has_permission(api_key, perm):
                return True
        return False

    def has_all_permissions(
        self,
        api_key: Optional[ApiKey],
        permissions: List[str],
    ) -> bool:
        """检查是否拥有列表中所有权限.

        Args:
            api_key: API Key 对象
            permissions: 权限列表

        Returns:
            True 表示拥有所有权限
        """
        if api_key is None:
            return False

        for perm in permissions:
            if not self.has_permission(api_key, perm):
                return False
        return True

    # --------------------------------------------------------
    # 便捷检查方法
    # --------------------------------------------------------

    def is_super_admin(self, api_key: Optional[ApiKey]) -> bool:
        """检查是否为超级管理员（拥有 "*" 权限）.

        Args:
            api_key: API Key 对象

        Returns:
            True 表示是超级管理员
        """
        if api_key is None:
            return False
        permissions = api_key.permissions or []
        return SUPER_PERMISSION in permissions

    def can_read_servers(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以读取服务器信息."""
        return self.has_permission(api_key, "servers:read")

    def can_manage_servers(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以管理服务器（增删改）."""
        return self.has_any_permission(
            api_key, ["servers:write", "servers:manage", "admin:servers"]
        )

    def can_call_tools(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以调用工具."""
        return self.has_any_permission(
            api_key, ["tools:call", "mcp:call"]
        )

    def can_read_tools(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以查询工具列表."""
        return self.has_any_permission(
            api_key, ["tools:read", "mcp:read"]
        )

    def can_manage_api_keys(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以管理 API Key."""
        return self.has_any_permission(
            api_key, ["admin:apikeys", "admin:*", "admin:manage"]
        )

    def can_view_audit_logs(self, api_key: Optional[ApiKey]) -> bool:
        """是否可以查看审计日志."""
        return self.has_any_permission(
            api_key, ["audit:read", "admin:audit", "admin:*"]
        )

    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------

    @staticmethod
    def _check_permission(
        user_permissions: List[str],
        required_permission: str,
    ) -> bool:
        """检查用户权限列表中是否包含所需权限.

        Args:
            user_permissions: 用户拥有的权限列表
            required_permission: 需要的权限

        Returns:
            True 表示有权限
        """
        if not user_permissions:
            return False

        for perm in user_permissions:
            # 超级权限
            if perm == SUPER_PERMISSION:
                return True

            # 精确匹配
            if perm == required_permission:
                return True

            # 通配符匹配（用户权限是模式，目标权限是具体值）
            # 如用户有 "admin:*"，需要 "admin:servers" -> 匹配
            if "*" in perm:
                if fnmatch(required_permission, perm):
                    return True

            # 反向匹配：用户权限是具体值，需要的是模式
            # 这种情况一般不适用，跳过

        return False

    # --------------------------------------------------------
    # 权限验证工具
    # --------------------------------------------------------

    @staticmethod
    def validate_permission_format(permission: str) -> bool:
        """验证权限字符串格式是否合法.

        合法格式:
        - "*"
        - "resource:action"
        - "resource:subresource:action"
        - 带通配符的模式

        Args:
            permission: 权限字符串

        Returns:
            True 表示格式合法
        """
        if not permission or not isinstance(permission, str):
            return False

        if permission == "*":
            return True

        # 至少包含一个冒号分隔符
        if ":" not in permission:
            return False

        parts = permission.split(":")
        if not all(parts):  # 所有分段都非空
            return False

        return True

    @staticmethod
    def normalize_permissions(permissions: List[str]) -> List[str]:
        """规范化权限列表.

        去重、排序、过滤无效权限。

        Args:
            permissions: 权限列表

        Returns:
            规范化后的权限列表
        """
        valid_perms = [
            p.strip() for p in permissions
            if p and p.strip() and PermissionChecker.validate_permission_format(p.strip())
        ]
        # 去重
        unique_perms = list(set(valid_perms))
        # 排序
        unique_perms.sort()
        return unique_perms


# ============================================================
# 全局单例
# ============================================================

_permission_checker: Optional[PermissionChecker] = None


def get_permission_checker() -> PermissionChecker:
    """获取全局权限检查器单例.

    Returns:
        PermissionChecker 实例
    """
    global _permission_checker
    if _permission_checker is None:
        _permission_checker = PermissionChecker()
    return _permission_checker


__all__ = [
    # 常量
    "SUPER_PERMISSION",
    "RESOURCE_SERVERS",
    "RESOURCE_TOOLS",
    "RESOURCE_ADMIN",
    "RESOURCE_MCP",
    "RESOURCE_AUDIT",
    "ACTION_READ",
    "ACTION_WRITE",
    "ACTION_CALL",
    "ACTION_DELETE",
    "ACTION_MANAGE",
    "COMMON_PERMISSIONS",
    # 服务类
    "PermissionChecker",
    "get_permission_checker",
]
