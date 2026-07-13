"""
云汐内核 V9 - MemoryInterface 桥接实现

解决评审 P3-004：TraceToMemory 提取结果未写入记忆系统，数据流断裂。

核心设计：
- MemoryBridge 实现 MemoryInterface 抽象接口
- 同时持有 RBACMemoryGuard（权限守卫）和目标存储（dict 模拟）
- write() 方法支持接收 TraceToMemory 的 ExtractedMemory 数据
- 连接 TraceToMemory 提取与实际记忆存储之间的数据流
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from interfaces import MemoryInterface
from rbac_memory import RBACMemoryGuard, AgentIdentity, AgentRole, MemoryAccessPolicy, Visibility
from swarm_and_innovation import ExtractedMemory, MemoryTier

logger = structlog.get_logger(__name__)


class MemoryBridge(MemoryInterface):
    """MemoryInterface 桥接实现

    实现 MemoryInterface 的三个抽象方法（query/write/permission_check），
    同时持有 RBACMemoryGuard 用于权限控制，以及内部 dict 存储作为目标。
    生产环境由模块四替换为真实记忆存储后端。

    支持：
    1. 标准 MemoryInterface 调用（query/write/permission_check）
    2. TraceToMemory ExtractedMemory 数据写入
    3. RBAC 权限检查集成
    """

    def __init__(
        self,
        rbac_guard: RBACMemoryGuard | None = None,
        storage: dict[str, dict[str, Any]] | None = None,
        max_entries: int = 100000,
        entry_ttl_seconds: float = 604800.0,
    ) -> None:
        self._rbac = rbac_guard or RBACMemoryGuard()
        self._storage: dict[str, dict[str, Any]] = storage if storage is not None else {}
        self._write_count: int = 0
        self._query_count: int = 0
        # [P1-6-1] 容量与 TTL 治理
        self._max_entries = max_entries
        self._entry_ttl_seconds = entry_ttl_seconds
        self._logger = logger.bind(service="memory_bridge")

    # ── MemoryInterface 实现 ──────────────────────────────

    async def query(
        self,
        agent_id: str,
        query: str,
        visibility: str,
        role: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """RBAC过滤后的记忆查询"""
        self._query_count += 1
        identity = self._make_identity(agent_id, role)

        # [P1-6-1] TTL 清理：移除过期条目
        now = time.time()
        expired_ids = [
            eid for eid, e in self._storage.items()
            if now - e.get("created_at", 0) > self._entry_ttl_seconds
        ]
        for eid in expired_ids:
            del self._storage[eid]

        # [P1-6-1] 分页优化：只扫描最近的 limit * 2 条，然后过滤
        sorted_entries = sorted(
            self._storage.items(),
            key=lambda x: x[1].get("created_at", 0),
            reverse=True,
        )
        candidate_entries = sorted_entries[: limit * 2]

        results: list[dict[str, Any]] = []
        for entry_id, entry in candidate_entries:
            # 构建访问策略
            policy = MemoryAccessPolicy(
                owner=entry.get("owner", ""),
                visibility=Visibility(entry.get("visibility", "public")),
            )

            # RBAC 权限检查
            if not self._rbac.can_read(identity, policy):
                continue

            # visibility 过滤
            if visibility and entry.get("visibility") != visibility:
                continue

            # 关键词匹配（简单实现）
            if query and query.lower() not in entry.get("content", "").lower():
                continue

            results.append(entry)

            if len(results) >= limit:
                break

        self._logger.debug(
            "memory_query",
            agent_id=agent_id,
            results_count=len(results),
        )
        return results

    async def write(
        self,
        agent_id: str,
        content: str,
        visibility: str,
        metadata: dict[str, Any],
    ) -> bool:
        """写入记忆，模块四负责沉降与归档"""
        identity = self._make_identity(
            agent_id,
            metadata.get("role", "general"),
        )

        # 权限检查
        policy = MemoryAccessPolicy(
            owner=agent_id,
            visibility=Visibility(visibility),
        )
        if not self._rbac.can_write(identity, policy):
            self._logger.warning(
                "memory_write_permission_denied",
                agent_id=agent_id,
                visibility=visibility,
            )
            return False

        # [P1-6-1] TTL 清理：移除过期条目
        now = time.time()
        expired_ids = [
            eid for eid, e in self._storage.items()
            if now - e.get("created_at", 0) > self._entry_ttl_seconds
        ]
        for eid in expired_ids:
            del self._storage[eid]

        # [P1-6-1] 容量治理：超限时淘汰最旧条目
        if len(self._storage) >= self._max_entries:
            oldest_id = min(self._storage.items(), key=lambda x: x[1].get("created_at", 0))[0]
            del self._storage[oldest_id]

        entry_id = f"mem_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        self._storage[entry_id] = {
            "entry_id": entry_id,
            "content": content,
            "owner": agent_id,
            "visibility": visibility,
            "metadata": metadata,
            "created_at": now,
        }
        self._write_count += 1

        self._logger.debug(
            "memory_written",
            entry_id=entry_id,
            agent_id=agent_id,
        )
        return True

    async def permission_check(
        self, agent_id: str, action: str, memory_id: str
    ) -> bool:
        """权限预检"""
        entry = self._storage.get(memory_id)
        if entry is None:
            return False

        identity = self._make_identity(
            agent_id,
            entry.get("metadata", {}).get("role", "general"),
        )
        policy = MemoryAccessPolicy(
            owner=entry.get("owner", ""),
            visibility=Visibility(entry.get("visibility", "public")),
        )

        if action == "read":
            return self._rbac.can_read(identity, policy)
        elif action == "write":
            return self._rbac.can_write(identity, policy)
        elif action == "delete":
            return self._rbac.can_delete(identity, policy)

        return False

    # ── TraceToMemory 集成写入 ────────────────────────────

    async def write_extracted_memory(
        self,
        extracted: ExtractedMemory,
        agent_id: str = "system",
        visibility: str = "public",
    ) -> bool:
        """写入 TraceToMemory 提取的记忆条目

        将 ExtractedMemory 转换为标准记忆格式并写入存储。
        """
        metadata: dict[str, Any] = {
            "source": extracted.source,
            "memory_type": extracted.memory_type,
            "importance": extracted.importance,
            "tags": extracted.tags,
            "tier": extracted.tier.value,
        }
        metadata.update(extracted.metadata)

        return await self.write(
            agent_id=agent_id,
            content=extracted.content,
            visibility=visibility,
            metadata=metadata,
        )

    async def write_extracted_memories(
        self,
        extracted_list: list[ExtractedMemory],
        agent_id: str = "system",
        visibility: str = "public",
    ) -> int:
        """批量写入 TraceToMemory 提取的记忆条目

        Returns:
            成功写入的数量
        """
        count = 0
        for extracted in extracted_list:
            if await self.write_extracted_memory(extracted, agent_id, visibility):
                count += 1
        return count

    # ── 辅助方法 ──────────────────────────────────────────

    def _make_identity(self, agent_id: str, role: str) -> AgentIdentity:
        """根据 agent_id 和 role 字符串构建 AgentIdentity"""
        try:
            agent_role = AgentRole(role)
        except ValueError:
            agent_role = AgentRole.GENERAL
        return AgentIdentity(agent_id=agent_id, role=agent_role)

    def get_all_entries(self) -> dict[str, dict[str, Any]]:
        """获取所有存储条目（主要用于测试）"""
        return dict(self._storage)

    def clear(self) -> None:
        """清空存储"""
        self._storage.clear()
        self._write_count = 0
        self._query_count = 0

    def stats(self) -> dict[str, Any]:
        return {
            "total_entries": len(self._storage),
            "write_count": self._write_count,
            "query_count": self._query_count,
        }
