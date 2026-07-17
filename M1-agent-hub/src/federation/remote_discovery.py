"""跨节点远程 Agent 发现 -- 通过集群总线发现其他节点的 Agent

职责：
- 从集群总线获取所有健康节点
- 对每个节点调用其 /agents 端点获取 Agent 列表
- 按能力查找远程 Agent
- 通过集群消息总线调用远程 Agent
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# 跨节点调用超时（秒）
REMOTE_CALL_TIMEOUT = 30.0

# 发现缓存有效期（秒），避免频繁查询集群
DISCOVERY_CACHE_TTL = 60.0


@dataclass
class RemoteAgent:
    """远程节点上的 Agent 描述"""

    agent_id: str
    node_id: str
    capabilities: list[str] = field(default_factory=list)
    host: str = ""
    port: int = 0
    status: str = "unknown"
    display_name: str = ""
    agent_type: str = "llm"
    quality_rating: float = 3.0
    response_speed: str = "medium"
    discovered_at: float = field(default_factory=time.time)


class RemoteAgentDiscovery:
    """远程 Agent 发现器

    通过集群总线（shared.distributed.cluster_bus）发现其他节点上的 Agent，
    并提供按能力查找和远程调用能力。

    使用方式：
        discovery = RemoteAgentDiscovery()
        agents = discovery.discover_from_cluster()
        agent = discovery.find_agent("code_generation")
        if agent:
            result = discovery.call_remote_agent(agent.agent_id, {"prompt": "..."})
    """

    def __init__(self) -> None:
        self._cache: dict[str, RemoteAgent] = {}
        self._cache_updated_at: float = 0.0
        self._logger = logger.bind(component="remote_agent_discovery")

    # ── 集群总线（延迟导入，shared.distributed 尚未就绪时优雅降级） ──

    def _get_cluster_bus(self) -> Any:
        """获取集群总线实例（延迟导入）

        Returns:
            cluster_bus 对象，若模块不可用则返回 None
        """
        try:
            from shared.business.distributed.cluster_bus import get_cluster_bus
            return get_cluster_bus()
        except (ImportError, AttributeError):
            self._logger.warning(
                "cluster_bus_unavailable",
                hint="shared.distributed.cluster_bus 模块未就绪，跨节点发现降级为空",
            )
            return None

    def _get_node_registry(self) -> Any:
        """获取节点注册表实例（延迟导入）

        Returns:
            NodeRegistry 对象，若模块不可用则返回 None
        """
        try:
            from shared.business.distributed.node_registry import NodeRegistry
            return NodeRegistry()
        except (ImportError, AttributeError):
            self._logger.warning(
                "node_registry_unavailable",
                hint="shared.distributed.node_registry 模块未就绪，跨节点发现降级为空",
            )
            return None

    # ── 发现 ────────────────────────────────────────────────

    def discover_from_cluster(self, force_refresh: bool = False) -> list[RemoteAgent]:
        """从集群总线获取所有节点的 Agent 列表

        流程：
        1. 调用 NodeRegistry 获取所有健康节点
        2. 对每个节点调用其 /agents 端点获取 Agent 列表
        3. 合并到本地缓存

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            远程 Agent 列表
        """
        # 缓存未过期且不强制刷新 → 直接返回缓存
        if (
            not force_refresh
            and self._cache
            and (time.time() - self._cache_updated_at) < DISCOVERY_CACHE_TTL
        ):
            return list(self._cache.values())

        # 尝试从节点注册表获取健康节点
        node_registry = self._get_node_registry()
        if node_registry is None:
            self._logger.debug("discover_skipped_no_node_registry")
            return list(self._cache.values())

        nodes = self._get_healthy_nodes(node_registry)
        if not nodes:
            self._logger.debug("discover_skipped_no_healthy_nodes")
            return list(self._cache.values())

        # 逐节点查询 Agent
        new_agents: list[RemoteAgent] = []
        for node in nodes:
            node_agents = self._fetch_agents_from_node(node)
            new_agents.extend(node_agents)

        # 更新缓存
        self._cache.clear()
        for agent in new_agents:
            self._cache[agent.agent_id] = agent
        self._cache_updated_at = time.time()

        self._logger.info(
            "remote_agents_discovered",
            total=len(new_agents),
            nodes_queried=len(nodes),
        )

        return list(self._cache.values())

    def _get_healthy_nodes(self, node_registry: Any) -> list[dict[str, Any]]:
        """从 NodeRegistry 获取健康节点列表"""
        try:
            nodes = node_registry.list_healthy_nodes()
            return nodes if isinstance(nodes, list) else []
        except Exception as exc:
            self._logger.warning("get_healthy_nodes_failed", error=str(exc))
            return []

    def _fetch_agents_from_node(self, node: dict[str, Any]) -> list[RemoteAgent]:
        """从单个节点获取 Agent 列表

        Args:
            node: 节点信息，需包含 host, port, node_id

        Returns:
            该节点上的远程 Agent 列表
        """
        host = node.get("host", "")
        port = node.get("port", 0)
        node_id = node.get("node_id", node.get("id", "unknown"))

        if not host or not port:
            self._logger.warning(
                "node_missing_host_port",
                node_id=node_id,
                node_info=node,
            )
            return []

        url = f"http://{host}:{port}/agents"
        try:
            with httpx.Client(timeout=REMOTE_CALL_TIMEOUT) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()

            agents: list[RemoteAgent] = []
            for item in data if isinstance(data, list) else data.get("agents", []):
                agent = RemoteAgent(
                    agent_id=item.get("agent_id", ""),
                    node_id=node_id,
                    capabilities=item.get("capabilities", []),
                    host=host,
                    port=port,
                    status=item.get("status", "unknown"),
                    display_name=item.get("display_name", item.get("agent_id", "")),
                    agent_type=item.get("agent_type", "llm"),
                    quality_rating=float(item.get("quality_rating", 3.0)),
                    response_speed=item.get("response_speed", "medium"),
                )
                agents.append(agent)

            self._logger.debug(
                "fetched_agents_from_node",
                node_id=node_id,
                count=len(agents),
            )
            return agents

        except httpx.HTTPError as exc:
            self._logger.warning(
                "fetch_agents_from_node_failed",
                node_id=node_id,
                url=url,
                error=str(exc),
            )
            return []
        except Exception as exc:
            self._logger.error(
                "unexpected_error_fetching_agents",
                node_id=node_id,
                error=str(exc),
            )
            return []

    # ── 查找 ────────────────────────────────────────────────

    def find_agent(self, capability: str) -> Optional[RemoteAgent]:
        """按能力查找远程 Agent（跨节点）

        优先返回状态为 active 且评分最高的 Agent。

        Args:
            capability: 需要的能力标签

        Returns:
            匹配的远程 Agent，无匹配则返回 None
        """
        # 确保缓存较新
        self.discover_from_cluster()

        candidates = [
            agent
            for agent in self._cache.values()
            if capability in agent.capabilities and agent.status == "active"
        ]

        if not candidates:
            self._logger.debug(
                "no_remote_agent_for_capability",
                capability=capability,
            )
            return None

        # 按质量评分降序排列
        candidates.sort(key=lambda a: a.quality_rating, reverse=True)
        best = candidates[0]

        self._logger.info(
            "remote_agent_found",
            agent_id=best.agent_id,
            node_id=best.node_id,
            capability=capability,
            quality_rating=best.quality_rating,
        )

        return best

    def find_agents(self, capability: str) -> list[RemoteAgent]:
        """按能力查找所有匹配的远程 Agent（按质量评分降序）

        Args:
            capability: 需要的能力标签

        Returns:
            匹配的远程 Agent 列表
        """
        self.discover_from_cluster()

        candidates = [
            agent
            for agent in self._cache.values()
            if capability in agent.capabilities and agent.status == "active"
        ]
        candidates.sort(key=lambda a: a.quality_rating, reverse=True)
        return candidates

    # ── 远程调用 ────────────────────────────────────────────

    def call_remote_agent(
        self,
        agent_id: str,
        task: dict[str, Any],
        timeout: float = REMOTE_CALL_TIMEOUT,
    ) -> dict[str, Any]:
        """调用远程 Agent（通过集群消息总线）

        优先使用 cluster_bus.request() 方法进行跨节点 RPC 调用。
        如果集群总线不可用，降级为 HTTP 直连。

        Args:
            agent_id: 远程 Agent ID
            task: 任务字典，包含 prompt、system_prompt 等
            timeout: 调用超时（秒），默认 30s

        Returns:
            调用结果字典，包含 success、output、error 等字段
        """
        remote_agent = self._cache.get(agent_id)
        if not remote_agent:
            return {
                "success": False,
                "error": f"远程 Agent {agent_id} 不在缓存中，请先执行发现",
            }

        # 优先尝试集群总线
        cluster_bus = self._get_cluster_bus()
        if cluster_bus is not None:
            return self._call_via_bus(cluster_bus, remote_agent, task, timeout)

        # 降级：HTTP 直连
        self._logger.warning(
            "cluster_bus_unavailable_fallback_http",
            agent_id=agent_id,
        )
        return self._call_via_http(remote_agent, task, timeout)

    def _call_via_bus(
        self,
        cluster_bus: Any,
        agent: RemoteAgent,
        task: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """通过集群消息总线调用远程 Agent"""
        try:
            result = cluster_bus.request(
                target_node=agent.node_id,
                method="agent.invoke",
                params={
                    "agent_id": agent.agent_id,
                    "task": task,
                },
                timeout=timeout,
            )
            self._logger.info(
                "remote_agent_called_via_bus",
                agent_id=agent.agent_id,
                node_id=agent.node_id,
                success=result.get("success", False),
            )
            return result
        except Exception as exc:
            self._logger.error(
                "remote_agent_bus_call_failed",
                agent_id=agent.agent_id,
                node_id=agent.node_id,
                error=str(exc),
            )
            return {
                "success": False,
                "error": f"集群总线调用失败: {exc}",
            }

    def _call_via_http(
        self,
        agent: RemoteAgent,
        task: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """通过 HTTP 直连调用远程 Agent（降级方案）"""
        url = f"http://{agent.host}:{agent.port}/agents/{agent.agent_id}/invoke"
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=task)
                resp.raise_for_status()
                result = resp.json()

            self._logger.info(
                "remote_agent_called_via_http",
                agent_id=agent.agent_id,
                node_id=agent.node_id,
                success=result.get("success", False),
            )
            return result
        except httpx.HTTPError as exc:
            self._logger.error(
                "remote_agent_http_call_failed",
                agent_id=agent.agent_id,
                url=url,
                error=str(exc),
            )
            return {
                "success": False,
                "error": f"HTTP 调用失败: {exc}",
            }

    # ── 缓存管理 ────────────────────────────────────────────

    def clear_cache(self) -> None:
        """清除发现缓存"""
        self._cache.clear()
        self._cache_updated_at = 0.0
        self._logger.debug("discovery_cache_cleared")

    def get_cached_agents(self) -> list[RemoteAgent]:
        """获取当前缓存的远程 Agent 列表（不触发发现）"""
        return list(self._cache.values())

    @property
    def cache_age(self) -> float:
        """缓存年龄（秒），0 表示无缓存"""
        if not self._cache:
            return 0.0
        return time.time() - self._cache_updated_at