"""
三级域权限管理器

域层级：
- private: Agent私有域（仅创建者可访问）
- shared: 协作共享域（授权Agent可访问）
- core: 全局核心域（仅系统级访问）
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Set


class DomainLevel(str, Enum):
    PRIVATE = "private"    # Agent私有域
    SHARED = "shared"      # 协作共享域
    CORE = "core"          # 全局核心域


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"


class DomainManager:
    """
    三级域权限管理器
    
    权限矩阵：
    ┌─────────┬────────┬────────┬──────┐
    │ 权限    │ private│ shared │ core │
    ├─────────┼────────┼────────┼──────┤
    │ 所有者  │ 全部   │ 读写   │ 只读 │
    │ 授权方  │ 无     │ 读写   │ 只读 │
    │ 其他    │ 无     │ 只读   │ 无   │
    └─────────┴────────┴────────┴──────┘
    """

    def __init__(self):
        self._agents: Dict[str, dict] = {}  # agent_id -> {role, domains}
        self._domain_acls: Dict[str, Dict[str, Set[str]]] = {}  # domain -> agent_id -> permissions
        self._init_default_agents()

    def _init_default_agents(self) -> None:
        """初始化默认Agent权限"""
        self.register_agent("system", role="admin")
        self.register_agent("m2_core", role="core")

    def register_agent(self, agent_id: str, role: str = "normal",
                       domains: List[str] = None) -> bool:
        """注册Agent及其权限"""
        self._agents[agent_id] = {
            "role": role,
            "domains": domains or ["private"],
        }
        # 默认私有域
        private_domain = f"private:{agent_id}"
        self._grant(agent_id, private_domain, [Permission.READ, Permission.WRITE, Permission.DELETE])
        return True

    def check_permission(self, agent_id: str, domain: str, action: str) -> bool:
        """
        检查Agent在指定域是否有指定权限
        
        Args:
            agent_id: Agent ID
            domain: 域 (private / shared / core)
            action: 操作 (read / write / delete / admin)
        """
        # 系统管理员拥有全部权限
        if agent_id == "system":
            return True

        # 解析域
        domain_parts = domain.split(":")
        domain_type = domain_parts[0] if domain_parts else "private"

        # 私有域：只有所有者有全部权限，其他Agent一律无权限
        if domain_type == "private":
            owner = domain_parts[1] if len(domain_parts) > 1 else None
            if owner and agent_id == owner:
                return True
            return False

        # 共享域：检查ACL
        if domain_type == "shared":
            return self._check_acl(agent_id, domain, action)

        # 核心域：只有核心Agent可读
        if domain_type == "core":
            if action == "read":
                return self._is_core_agent(agent_id)
            return False  # 核心域不允许外部写入

        return False

    def _check_acl(self, agent_id: str, domain: str, action: str) -> bool:
        """检查访问控制列表"""
        if domain not in self._domain_acls:
            return action == "read"  # 默认共享域可读

        acl = self._domain_acls[domain]
        if agent_id not in acl:
            return action == "read"

        perms = acl[agent_id]
        if Permission.ADMIN.value in perms:
            return True
        return action in perms

    def _grant(self, agent_id: str, domain: str, permissions: List[Permission]) -> None:
        """授予权限"""
        if domain not in self._domain_acls:
            self._domain_acls[domain] = {}
        if agent_id not in self._domain_acls[domain]:
            self._domain_acls[domain][agent_id] = set()
        for perm in permissions:
            self._domain_acls[domain][agent_id].add(perm.value)

    def revoke(self, agent_id: str, domain: str, permissions: List[Permission]) -> bool:
        """撤销权限"""
        if domain in self._domain_acls and agent_id in self._domain_acls[domain]:
            for perm in permissions:
                self._domain_acls[domain][agent_id].discard(perm.value)
            return True
        return False

    def _is_core_agent(self, agent_id: str) -> bool:
        """是否是核心级Agent"""
        agent = self._agents.get(agent_id, {})
        return agent.get("role") in ["admin", "core"]

    def _is_trusted_agent(self, agent_id: str) -> bool:
        """是否是受信任Agent"""
        return agent_id in self._agents

    def get_agent_domains(self, agent_id: str) -> List[str]:
        """获取Agent可访问的域列表"""
        domains = [f"private:{agent_id}"]
        for domain, acl in self._domain_acls.items():
            if agent_id in acl:
                domains.append(domain)
        # 共享域默认可读
        for domain in self._domain_acls:
            if domain.startswith("shared:") and domain not in domains:
                domains.append(domain)
        return domains

    def get_stats(self) -> Dict:
        return {
            "total_agents": len(self._agents),
            "total_domains": len(self._domain_acls),
        }
# vim: set et ts=4 sw=4:
