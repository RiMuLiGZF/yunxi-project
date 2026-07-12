"""
潮汐记忆系统 Skill 接口（供M2内核调用）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.models import MemoryItem, MemoryDomain, MemoryLayer


class TideSkillInterface:
    """
    潮汐记忆系统对外Skill接口
    
    提供给M2内核调用的标准接口：
    - recall: 记忆检索
    - archive: 记忆归档
    - compress: 记忆压缩
    - reflect: 反思复盘
    """

    def __init__(self, recall_engine, domain_manager, audit_logger):
        self._recall = recall_engine
        self._domain = domain_manager
        self._audit = audit_logger
        self._registered_agents = set()  # 已注册的Agent集合

    def _ensure_agent_registered(self, agent_id: str) -> None:
        """确保Agent已注册到域管理器（首次出现自动注册）."""
        if agent_id not in self._registered_agents:
            self._domain.register_agent(agent_id)
            self._registered_agents.add(agent_id)

    def recall(
        self,
        query: str,
        layer_range: Optional[List[str]] = None,
        emotion_context: Optional[Dict] = None,
        permission_check: Optional[Dict] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """
        记忆检索接口
        
        Args:
            query: 查询文本
            layer_range: 搜索层级范围
            emotion_context: 情绪上下文
            permission_check: 权限校验信息
            top_k: 返回数量
        
        Returns:
            检索结果（已脱敏）
        """
        # 权限校验
        agent_id = (permission_check or {}).get("agent_id", "unknown")
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(
            (permission_check or {}).get("domain", "private"),
            agent_id,
        )

        if not self._domain.check_permission(agent_id, domain, "read"):
            self._audit.record("none", "read", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied", "results": []}

        # 执行检索
        results = self._recall.search(
            query=query,
            layers=layer_range or ["l1_shallow", "l2_deep"],
            emotion_context=emotion_context,
            top_k=top_k,
            domain=domain,
        )
        
        # 审计记录
        for r in results:
            self._audit.record(r.get("memory_id", "unknown"), "read", agent_id, domain, True)
        
        return {
            "success": True,
            "results": results,
            "total": len(results),
        }

    def archive(
        self,
        content: str,
        source: str = "conversation",
        domain: str = "private",
        agent_id: str = "system",
        tags: Optional[List[str]] = None,
        emotion_context: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        记忆归档接口
        
        Returns:
            archive_id, layer, content_hash 等
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "write"):
            self._audit.record("none", "write", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        # 计算内容哈希（用于同步，不存原文）
        import hashlib
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        result = self._recall.archive_memory(
            content_hash=content_hash,
            source=source,
            domain=domain,
            agent_id=agent_id,
            tags=tags or [],
            emotion_context=emotion_context,
            metadata=metadata or {},
        )
        
        self._audit.record(result["memory_id"], "write", agent_id, domain, True)
        
        return {
            "success": True,
            "archive_id": result["memory_id"],
            "layer": result["layer"],
            "content_hash": content_hash,
            "created_at": result["created_at"],
        }

    def compress(self, target_layer: str = "l2_deep") -> Dict[str, Any]:
        """触发记忆压缩"""
        result = self._recall.compress_layer(target_layer)
        return {"success": True, **result}

    def batch_archive(
        self,
        items: List[Dict],
        domain: str = "private",
        agent_id: str = "system",
    ) -> Dict[str, Any]:
        """
        批量归档记忆

        Args:
            items: 记忆项字典列表
            domain: 记忆域
            agent_id: 所属 agent

        Returns:
            {"success": True, "success_count": n, "failed": [ids]}
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "write"):
            self._audit.record("none", "batch_write", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        result = self._recall.batch_archive(items, domain=domain, agent_id=agent_id)

        # 审计记录（只记录一次批量操作）
        self._audit.record("batch", "batch_write", agent_id, domain, True,
                           f"count={result['success_count']}")

        return {"success": True, **result}

    def batch_delete(
        self,
        memory_ids: List[str],
        domain: str = "private",
        agent_id: str = "system",
    ) -> Dict[str, Any]:
        """
        批量删除记忆

        Args:
            memory_ids: 记忆ID列表
            domain: 记忆域
            agent_id: 操作者 AgentID

        Returns:
            {"success": True, "deleted_count": n}
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "delete"):
            self._audit.record("none", "batch_delete", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        result = self._recall.batch_delete(memory_ids, domain=domain)

        # 审计记录
        self._audit.record("batch", "batch_delete", agent_id, domain, True,
                           f"count={result['deleted_count']}")

        return {"success": True, **result}

    def list_memories(
        self,
        page_size: int = 20,
        cursor: str = None,
        domain: str = "private",
        agent_id: str = "unknown",
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> Dict[str, Any]:
        """
        分页查询记忆列表

        Args:
            page_size: 每页数量
            cursor: 游标值
            domain: 记忆域
            agent_id: 操作者 AgentID
            sort_by: 排序字段
            order: 排序方向

        Returns:
            {"success": True, "items": [...], "next_cursor": ..., "has_more": ..., "total": n}
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "read"):
            self._audit.record("none", "list", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        result = self._recall.list_memories(
            page_size=page_size,
            cursor=cursor,
            domain=domain,
            sort_by=sort_by,
            order=order,
        )

        # 审计记录
        self._audit.record("list", "list", agent_id, domain, True,
                           f"count={len(result['items'])}")

        return {"success": True, **result}

    def reflect(self, scope: str = "weekly", domain: str = "private") -> Dict[str, Any]:
        """生成反思复盘报告"""
        result = self._recall.generate_reflection(scope, domain)
        return {"success": True, **result}

    def get_memory(self, memory_id: str, domain: str = "private",
                   agent_id: str = "unknown") -> Dict[str, Any]:
        """获取单条记忆（返回元数据，不含原文）.

        Args:
            memory_id: 记忆ID
            domain: 域
            agent_id: 操作者AgentID

        Returns:
            记忆元数据字典，不存在返回 None
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "read"):
            self._audit.record(memory_id, "read", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        result = self._recall.get_by_id(memory_id, domain)
        if result:
            self._audit.record(memory_id, "read", agent_id, domain, True)
            return {"success": True, **result}
        else:
            self._audit.record(memory_id, "read", agent_id, domain, False, "not_found")
            return {"success": False, "error": "not_found"}

    def delete_memory(self, memory_id: str, domain: str = "private",
                      agent_id: str = "unknown") -> Dict[str, Any]:
        """删除记忆.

        Args:
            memory_id: 记忆ID
            domain: 域
            agent_id: 操作者AgentID

        Returns:
            删除结果
        """
        # 权限校验
        self._ensure_agent_registered(agent_id)
        domain = self._normalize_domain(domain, agent_id)
        if not self._domain.check_permission(agent_id, domain, "delete"):
            self._audit.record(memory_id, "delete", agent_id, domain, False, "permission_denied")
            return {"success": False, "error": "permission_denied"}

        deleted = self._recall.delete_by_id(memory_id, domain)
        if deleted:
            self._audit.record(memory_id, "delete", agent_id, domain, True)
            return {
                "success": True,
                "memory_id": memory_id,
                "deleted": True,
                "secure_delete": True,
            }
        else:
            self._audit.record(memory_id, "delete", agent_id, domain, False, "not_found")
            return {"success": False, "error": "not_found"}

    def get_stats(self, domain: str = "private") -> Dict[str, Any]:
        """获取记忆统计"""
        return self._recall.get_stats(domain)

    def _normalize_domain(self, domain: str, agent_id: str) -> str:
        """归一化域格式.

        将简写的域名称转换为完整格式：
        - "private" → "private:{agent_id}"
        - "shared:xxx" → 保持不变
        - "core" → "core"

        Args:
            domain: 原始域名称
            agent_id: Agent ID（用于私有域）

        Returns:
            完整格式的域名称
        """
        if domain == "private":
            return f"private:{agent_id}"
        if domain == "core":
            return "core"
        # shared:xxx 或其他格式保持不变
        return domain
# vim: set et ts=4 sw=4:
