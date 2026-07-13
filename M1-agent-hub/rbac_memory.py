"""
云汐内核 V8 - RBAC 记忆权限隔离

解决评审报告 P2 问题：
- 所有 Agent 共享 MemoryManager，零权限隔离
- 无记忆沙箱机制
- 记忆传播不可控

核心设计：
- 角色定义（admin / expert / general / guest）
- 记忆所有权 + 可见范围（private / team / public / sensitive）
- 策略引擎控制读写权限
- 与 MemoryManager 集成，查询时自动过滤
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── 角色定义 ──────────────────────────────────────────────


class AgentRole(str, Enum):
    ADMIN = "admin"
    EXPERT = "expert"
    GENERAL = "general"
    GUEST = "guest"


class Visibility(str, Enum):
    PRIVATE = "private"    # 仅创建者
    TEAM = "team"          # 同组 Agent
    PUBLIC = "public"      # 所有 Agent
    SENSITIVE = "sensitive"  # 仅 admin + 特定角色


# ── 访问策略 ──────────────────────────────────────────────


# 权限矩阵：role x visibility x action -> allowed
_PERMISSION_MATRIX: dict[str, dict[str, dict[str, bool]]] = {
    AgentRole.ADMIN: {
        Visibility.PRIVATE: {"read": True, "write": True, "delete": True},
        Visibility.TEAM:    {"read": True, "write": True, "delete": True},
        Visibility.PUBLIC:  {"read": True, "write": True, "delete": False},
        Visibility.SENSITIVE: {"read": True, "write": True, "delete": True},
    },
    AgentRole.EXPERT: {
        Visibility.PRIVATE: {"read": True, "write": True, "delete": False},
        Visibility.TEAM:    {"read": True, "write": False, "delete": False},
        Visibility.PUBLIC:  {"read": True, "write": False, "delete": False},
        Visibility.SENSITIVE: {"read": False, "write": False, "delete": False},
    },
    AgentRole.GENERAL: {
        Visibility.PRIVATE: {"read": True, "write": True, "delete": False},
        Visibility.TEAM:    {"read": False, "write": False, "delete": False},
        Visibility.PUBLIC:  {"read": True, "write": False, "delete": False},
        Visibility.SENSITIVE: {"read": False, "write": False, "delete": False},
    },
    AgentRole.GUEST: {
        Visibility.PRIVATE: {"read": False, "write": False, "delete": False},
        Visibility.TEAM:    {"read": False, "write": False, "delete": False},
        Visibility.PUBLIC:  {"read": True, "write": False, "delete": False},
        Visibility.SENSITIVE: {"read": False, "write": False, "delete": False},
    },
}


@dataclass
class AgentIdentity:
    """Agent 身份信息"""

    agent_id: str
    role: AgentRole = AgentRole.GENERAL
    team: str = ""  # 组名，同组可访问 team 级记忆


@dataclass
class MemoryAccessPolicy:
    """记忆访问策略"""

    owner: str = ""  # 记忆创建者 agent_id
    visibility: Visibility = Visibility.PUBLIC
    allowed_roles: list[AgentRole] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=list)  # 额外白名单


class RBACMemoryGuard:
    """RBAC 记忆权限守卫

    检查 Agent 对记忆条目的读写权限。
    """

    def can_read(
        self,
        identity: AgentIdentity,
        policy: MemoryAccessPolicy,
    ) -> bool:
        """检查读权限"""
        # owner 总是可以读
        if identity.agent_id == policy.owner:
            return True

        # 白名单检查
        if identity.agent_id in policy.allowed_agents:
            return True

        # 角色检查
        role_perms = _PERMISSION_MATRIX.get(identity.role, {})
        vis_perms = role_perms.get(policy.visibility, {})
        if not vis_perms.get("read", False):
            return False

        # [P2-014] 修复 team 级记忆权限检查
        # 原bug: identity.team != identity.team 是永假条件
        # 修复: team 级记忆仅 owner（已在上面检查）和 admin 可读
        # 由于 MemoryAccessPolicy 不存储 owner_team 字段，
        # 非 owner 非 admin 的角色即使有 team read 权限，也无法验证同组关系
        if policy.visibility == Visibility.TEAM:
            if identity.role == AgentRole.ADMIN:
                return True
            # 非 owner、非 admin 不可读 team 级记忆
            return False

        return True

    def can_write(
        self,
        identity: AgentIdentity,
        policy: MemoryAccessPolicy,
    ) -> bool:
        """检查写权限"""
        if identity.agent_id == policy.owner:
            return True

        if identity.agent_id in policy.allowed_agents:
            return True

        role_perms = _PERMISSION_MATRIX.get(identity.role, {})
        vis_perms = role_perms.get(policy.visibility, {})
        return vis_perms.get("write", False)

    def can_delete(
        self,
        identity: AgentIdentity,
        policy: MemoryAccessPolicy,
    ) -> bool:
        """检查删除权限"""
        if identity.agent_id == policy.owner:
            return True

        role_perms = _PERMISSION_MATRIX.get(identity.role, {})
        vis_perms = role_perms.get(policy.visibility, {})
        return vis_perms.get("delete", False)

    def filter_entries(
        self,
        identity: AgentIdentity,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """过滤记忆条目，仅返回有读权限的"""
        filtered = []
        for entry in entries:
            policy = MemoryAccessPolicy(
                owner=entry.get("owner", ""),
                visibility=Visibility(entry.get("visibility", "public")),
            )
            if self.can_read(identity, policy):
                filtered.append(entry)
        return filtered

    def stats(self) -> dict[str, Any]:
        return {
            "roles_defined": [r.value for r in AgentRole],
            "visibility_levels": [v.value for v in Visibility],
        }
