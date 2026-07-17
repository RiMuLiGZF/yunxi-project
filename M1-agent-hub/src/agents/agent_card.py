"""
云汐内核 V2 - AgentCard 能力发现系统

灵感来源：Google A2A AgentCard 协议
https://codelabs.developers.google.cn/adk-a2a-agent-runtime

每个 Agent 通过 AgentCard 自描述其能力、接口、认证方式，
实现异构 Agent 之间的动态发现与互操作。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class AgentCapability:
    """Agent 能力描述"""

    id: str = ""
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    return_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEndpoint:
    """Agent 接入端点"""

    protocol: str = "internal"  # internal | http | grpc | websocket
    url: str = ""
    auth_type: str = "none"  # none | token | oauth | mtls
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCard:
    """Agent 能力卡片

    机器可读的结构化元数据，描述 Agent 的身份、能力、接口。
    类似 Google A2A 的 AgentCard，但适配云汐内核内部架构。
    """

    agent_id: str = ""
    agent_name: str = ""
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[AgentCapability] = field(default_factory=list)
    endpoints: list[AgentEndpoint] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    owner: str = ""
    health_endpoint: str = ""
    rate_limits: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return asdict(self)

    def has_capability(self, capability_id: str) -> bool:
        """是否支持指定能力"""
        return any(c.id == capability_id for c in self.capabilities)

    def find_capability(self, keyword: str) -> list[AgentCapability]:
        """按关键词搜索能力"""
        results = []
        kw_lower = keyword.lower()
        for cap in self.capabilities:
            if (
                kw_lower in cap.id.lower()
                or kw_lower in cap.name.lower()
                or kw_lower in cap.description.lower()
            ):
                results.append(cap)
        return results

    def match_score(self, query: str) -> float:
        """计算与查询的匹配分数"""
        query_lower = query.lower()
        score = 0.0

        # 名称匹配
        if query_lower in self.agent_name.lower():
            score += 0.5
        if query_lower in self.agent_id.lower():
            score += 0.3

        # 能力匹配
        for cap in self.capabilities:
            if query_lower in cap.id.lower():
                score += 0.3
            if query_lower in cap.name.lower():
                score += 0.2
            if query_lower in cap.description.lower():
                score += 0.1

        # 标签匹配
        for tag in self.tags:
            if query_lower in tag.lower():
                score += 0.15

        return min(score, 1.0)


# ── AgentCard 注册中心 ──────────────────────────────────────


class AgentCardRegistry:
    """AgentCard 注册中心

    集中管理所有 Agent 的能力卡片，支持动态发现与语义搜索。
    """

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}
        self._logger = logger.bind(service="agent_card_registry")

    def register(self, card: AgentCard) -> None:
        """注册 AgentCard"""
        self._cards[card.agent_id] = card
        self._logger.info(
            "agent_card_registered",
            agent_id=card.agent_id,
            capabilities_count=len(card.capabilities),
        )

    def unregister(self, agent_id: str) -> None:
        """注销 AgentCard"""
        if agent_id in self._cards:
            del self._cards[agent_id]
            self._logger.info("agent_card_unregistered", agent_id=agent_id)

    def get(self, agent_id: str) -> AgentCard | None:
        """获取指定 Agent 的卡片"""
        return self._cards.get(agent_id)

    def list_all(self) -> list[AgentCard]:
        """列出所有卡片"""
        return list(self._cards.values())

    def discover(
        self,
        capability_id: str | None = None,
        keyword: str | None = None,
        tag: str | None = None,
    ) -> list[tuple[AgentCard, float]]:
        """发现 Agent

        按能力、关键词或标签搜索匹配的 Agent，返回按匹配分数排序的结果。

        Args:
            capability_id: 精确匹配的能力 ID
            keyword: 语义搜索关键词
            tag: 标签过滤

        Returns:
            [(AgentCard, match_score), ...]
        """
        candidates = list(self._cards.values())
        results: list[tuple[AgentCard, float]] = []

        for card in candidates:
            score = 0.0
            matched = False

            if capability_id:
                if card.has_capability(capability_id):
                    score += 1.0
                    matched = True
                else:
                    continue

            if keyword:
                kw_score = card.match_score(keyword)
                if kw_score > 0:
                    score += kw_score
                    matched = True
                elif capability_id:
                    pass  # capability 已匹配
                else:
                    continue

            if tag:
                if tag in card.tags:
                    score += 0.5
                    matched = True
                else:
                    continue

            if matched or (not capability_id and not keyword and not tag):
                results.append((card, min(score, 1.0)))

        # 按匹配分数降序
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def semantic_search(self, query: str, top_k: int = 5) -> list[tuple[AgentCard, float]]:
        """语义搜索 Agent

        基于关键词匹配分数返回 Top-K 结果。
        生产环境可接入向量检索（embedding similarity）。
        """
        all_results = [(card, card.match_score(query)) for card in self._cards.values()]
        all_results = [(c, s) for c, s in all_results if s > 0]
        all_results.sort(key=lambda x: x[1], reverse=True)
        return all_results[:top_k]


# ── 从 IAgentPlugin 自动生成 AgentCard ──────────────────────


def build_agent_card(
    agent_id: str,
    name: str,
    version: str,
    capabilities: list[str],
    description: str = "",
    skills: list[str] | None = None,
    tags: list[str] | None = None,
) -> AgentCard:
    """从 Agent 元信息生成 AgentCard"""
    cap_objs = []
    for cap_id in capabilities:
        cap_objs.append(
            AgentCapability(
                id=cap_id,
                name=cap_id.replace(".", " ").title(),
                description=f"Capability: {cap_id}",
            )
        )

    return AgentCard(
        agent_id=agent_id,
        agent_name=name,
        version=version,
        description=description,
        capabilities=cap_objs,
        skills=skills or [],
        tags=tags or [],
    )
