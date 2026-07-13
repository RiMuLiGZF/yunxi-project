"""
云汐内核 - 多 Agent 集群调度系统
Agent 注册中心模块

管理所有 Agent 的注册、注销、查询与健康检查。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from interfaces import IAgentPlugin, RegistryError

logger = structlog.get_logger(__name__)


class AgentRegistry:
    """Agent 注册中心

    负责 Agent 的生命周期管理：
    - 注册：校验 agent_id 唯一性，调用 agent.on_mount()
    - 注销：调用 agent.on_unmount()，清理引用
    - 查询：按 agent_id、capability 查询
    - 健康检查：遍历所有 Agent 调用 health()
    """

    def __init__(self) -> None:
        self._agents: dict[str, IAgentPlugin] = {}
        # [V9.6] 能力反向索引：capability -> set(agent_id)，O(1) 查询
        self._capability_index: dict[str, set[str]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._logger = logger.bind(service="agent_registry")

    # ── 注册与注销 ────────────────────────────────────────

    async def register(self, agent: IAgentPlugin) -> None:
        """注册 Agent

        Args:
            agent: 实现了 IAgentPlugin 接口的 Agent 实例

        Raises:
            RegistryError: 如果 agent_id 已存在或注册过程出错
        """
        async with self._lock:
            if agent.agent_id in self._agents:
                raise RegistryError(
                    f"Agent '{agent.agent_id}' 已存在，无法重复注册"
                )
            self._agents[agent.agent_id] = agent
            # [V9.6] 更新能力反向索引
            if hasattr(agent, "capabilities") and agent.capabilities:
                for cap in agent.capabilities:
                    self._capability_index.setdefault(cap, set()).add(agent.agent_id)

        try:
            await agent.on_mount(self)
        except Exception as exc:
            # 注册失败回滚
            async with self._lock:
                self._agents.pop(agent.agent_id, None)
            raise RegistryError(
                f"Agent '{agent.agent_id}' on_mount 失败: {exc}"
            ) from exc

        self._logger.info(
            "agent_registered",
            agent_id=agent.agent_id,
            version=agent.version,
            capabilities=agent.capabilities,
        )

    async def unregister(self, agent_id: str) -> None:
        """注销 Agent

        Args:
            agent_id: Agent 标识
        """
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            # [V9.6] 清理能力反向索引
            if agent and hasattr(agent, "capabilities") and agent.capabilities:
                for cap in agent.capabilities:
                    cap_set = self._capability_index.get(cap)
                    if cap_set:
                        cap_set.discard(agent_id)
                        if not cap_set:
                            del self._capability_index[cap]

        if agent is None:
            self._logger.warning("agent_not_found_for_unregister", agent_id=agent_id)
            return

        try:
            await agent.on_unmount()
        except Exception as exc:
            self._logger.error(
                "agent_unmount_failed",
                agent_id=agent_id,
                error=str(exc),
            )

        self._logger.info("agent_unregistered", agent_id=agent_id)

    # ── 查询方法 ──────────────────────────────────────────

    def get(self, agent_id: str) -> IAgentPlugin | None:
        """根据 agent_id 获取 Agent 实例"""
        return self._agents.get(agent_id)

    def list_all(self) -> list[IAgentPlugin]:
        """列出所有已注册的 Agent"""
        return list(self._agents.values())

    def find_by_capability(self, capability: str) -> list[IAgentPlugin]:
        """[V9.6] 按能力查找 Agent（O(1) 索引查询）"""
        agent_ids = self._capability_index.get(capability, set())
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    def list_ids(self) -> list[str]:
        """列出所有已注册的 Agent ID"""
        return list(self._agents.keys())

    def register_sync(self, agent: IAgentPlugin) -> None:
        """同步注册 Agent（不调用 on_mount，用于测试场景）"""
        if agent.agent_id in self._agents:
            raise RegistryError(f"Agent '{agent.agent_id}' 已存在，无法重复注册")
        self._agents[agent.agent_id] = agent
        # [V9.6] 更新能力反向索引
        if hasattr(agent, "capabilities") and agent.capabilities:
            for cap in agent.capabilities:
                self._capability_index.setdefault(cap, set()).add(agent.agent_id)
        self._logger.info(
            "agent_registered_sync",
            agent_id=agent.agent_id,
            version=agent.version,
        )

    async def get_status(self, agent_id: str) -> dict[str, Any] | None:
        """[V10.0-R04] 查询单个Agent的状态

        Returns:
            Agent状态字典，含agent_id、registered、capabilities、health。
            若Agent未注册，返回None。
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return None

        health = {}
        try:
            health = await agent.health()
        except Exception as exc:
            health = {"status": "unhealthy", "error": str(exc)}

        return {
            "agent_id": agent_id,
            "registered": True,
            "version": getattr(agent, "version", "unknown"),
            "capabilities": getattr(agent, "capabilities", []),
            "health": health,
        }

    # ── 健康检查 ──────────────────────────────────────────

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """对所有已注册 Agent 执行健康检查

        Returns:
            agent_id -> health_status 的字典
        """
        results: dict[str, dict[str, Any]] = {}

        async with self._lock:
            agents = list(self._agents.items())

        for agent_id, agent in agents:
            try:
                status = await agent.health()
                results[agent_id] = status
                self._logger.debug("health_check_ok", agent_id=agent_id)
            except Exception as exc:
                results[agent_id] = {
                    "agent_id": agent_id,
                    "status": "unhealthy",
                    "error": str(exc),
                }
                self._logger.error(
                    "health_check_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

        return results