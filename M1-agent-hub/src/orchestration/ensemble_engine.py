"""
云汐内核 V7 - 多 Agent 集成引擎

灵感来源：
- ACL 2025 "Voting or Consensus? Decision-Making in Multi-Agent Debate"
- Meta Council: Weighted Multi-Expert Synthesis with Dissent Preservation
- ART: Adaptive Response Tuning Framework

核心创新：
1. 投票机制（Voting）- 在推理任务上比单 Agent 提升 10.4%
2. 共识机制（Consensus）- 在知识任务上比投票提升 2.8%
3. 保留异议的加权合成（Dissent-Preserving Weighted Synthesis）- 不丢弃少数派观点
4. 辩论轮次（Debate Rounds）- 多轮迭代改进

集成策略：
- voting: 多数表决，适合推理任务
- consensus: 达成一致，适合知识任务
- weighted_synthesis: 加权合成，保留异议，适合高风险决策
- best_of_n: 选最优，适合创造性任务
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


class EnsembleStrategy(str, Enum):
    """集成策略"""

    VOTING = "voting"                    # 多数表决
    CONSENSUS = "consensus"              # 共识达成
    WEIGHTED_SYNTHESIS = "weighted_synthesis"  # 加权合成（保留异议）
    BEST_OF_N = "best_of_n"              # 最优选择


@dataclass
class AgentVote:
    """Agent 投票/回答"""

    agent_id: str = ""
    response: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleResult:
    """集成结果"""

    final_answer: str = ""
    strategy: EnsembleStrategy = EnsembleStrategy.VOTING
    votes: list[AgentVote] = field(default_factory=list)
    dissenting_views: list[AgentVote] = field(default_factory=list)
    consensus_reached: bool = False
    rounds: int = 1
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_answer": self.final_answer,
            "strategy": self.strategy.value,
            "votes": [
                {
                    "agent_id": v.agent_id,
                    "response": v.response,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                }
                for v in self.votes
            ],
            "dissenting_views": [
                {
                    "agent_id": v.agent_id,
                    "response": v.response,
                    "confidence": v.confidence,
                }
                for v in self.dissenting_views
            ],
            "consensus_reached": self.consensus_reached,
            "rounds": self.rounds,
            "latency_ms": round(self.latency_ms, 2),
        }


AgentCaller = Callable[[str, str], Awaitable[AgentVote]]
"""Agent 调用函数签名：(agent_id, query) -> AgentVote"""


class EnsembleEngine:
    """多 Agent 集成引擎

    对同一问题并行调用多个 Agent，通过不同策略合成最终答案。
    """

    def __init__(
        self,
        default_strategy: EnsembleStrategy = EnsembleStrategy.VOTING,
        consensus_threshold: float = 0.6,
        max_debate_rounds: int = 3,
    ) -> None:
        self.default_strategy = default_strategy
        self.consensus_threshold = consensus_threshold
        self.max_debate_rounds = max_debate_rounds
        self._logger = logger.bind(service="ensemble_engine")

    # ── 核心入口 ────────────────────────────────────────

    async def run(
        self,
        query: str,
        agent_ids: list[str],
        caller: AgentCaller,
        strategy: EnsembleStrategy | None = None,
    ) -> EnsembleResult:
        """执行集成

        Args:
            query: 用户查询
            agent_ids: 参与集成的 Agent ID 列表
            caller: 调用单个 Agent 的函数
            strategy: 集成策略，None 则使用默认策略

        Returns:
            EnsembleResult: 集成结果
        """
        strategy = strategy or self.default_strategy
        start = time.time()

        self._logger.info(
            "ensemble_start",
            query=query[:50],
            agent_count=len(agent_ids),
            strategy=strategy.value,
        )

        # 并行收集所有 Agent 的回答
        votes = await self._collect_votes(agent_ids, query, caller)

        if strategy == EnsembleStrategy.VOTING:
            result = self._voting(votes)
        elif strategy == EnsembleStrategy.CONSENSUS:
            result = await self._consensus(votes, query, caller)
        elif strategy == EnsembleStrategy.WEIGHTED_SYNTHESIS:
            result = self._weighted_synthesis(votes)
        elif strategy == EnsembleStrategy.BEST_OF_N:
            result = self._best_of_n(votes)
        else:
            result = self._voting(votes)

        result.strategy = strategy
        result.votes = votes
        result.latency_ms = (time.time() - start) * 1000

        self._logger.info(
            "ensemble_complete",
            strategy=strategy.value,
            consensus=result.consensus_reached,
            rounds=result.rounds,
            latency_ms=round(result.latency_ms, 2),
        )

        return result

    # ── 投票收集 ────────────────────────────────────────

    async def _collect_votes(
        self,
        agent_ids: list[str],
        query: str,
        caller: AgentCaller,
    ) -> list[AgentVote]:
        """并行收集所有 Agent 的投票"""
        import asyncio

        tasks = [caller(aid, query) for aid in agent_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        votes = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._logger.warning("ensemble_agent_failed", agent_id=agent_ids[i], error=str(result))
                votes.append(AgentVote(agent_id=agent_ids[i], response="", confidence=0.0))
            else:
                votes.append(result)

        return votes

    # ── 策略实现 ────────────────────────────────────────

    def _voting(self, votes: list[AgentVote]) -> EnsembleResult:
        """多数表决策略

        在推理任务上表现最佳（ACL 2025：比单 Agent 提升 10.4%）。
        """
        from collections import Counter

        # 按回答内容分组，统计票数
        responses = [v.response.strip() for v in votes if v.response.strip()]
        if not responses:
            return EnsembleResult(final_answer="", consensus_reached=False)

        counter = Counter(responses)
        most_common, count = counter.most_common(1)[0]
        total = len(responses)
        ratio = count / total if total > 0 else 0

        # 找出异议观点
        dissenting = [v for v in votes if v.response.strip() != most_common]

        return EnsembleResult(
            final_answer=most_common,
            consensus_reached=ratio >= self.consensus_threshold,
            dissenting_views=dissenting,
        )

    async def _consensus(
        self,
        votes: list[AgentVote],
        query: str,
        caller: AgentCaller,
    ) -> EnsembleResult:
        """共识达成策略

        多轮辩论，直到达成一致或达到最大轮次。
        在知识任务上表现最佳（ACL 2025：比投票提升 2.8%）。
        """
        current_votes = list(votes)
        round_num = 1

        while round_num <= self.max_debate_rounds:
            # 检查是否已达成共识
            result = self._voting(current_votes)
            if result.consensus_reached:
                result.rounds = round_num
                return result

            if round_num >= self.max_debate_rounds:
                break

            # 辩论轮：让 Agent 看到其他 Agent 的观点并重新回答
            # 简化实现：取前一轮的答案作为新查询
            import asyncio

            debate_prompt = self._build_debate_prompt(query, current_votes)
            tasks = [caller(v.agent_id, debate_prompt) for v in current_votes]
            new_results = await asyncio.gather(*tasks, return_exceptions=True)

            current_votes = []
            for i, result in enumerate(new_results):
                if isinstance(result, Exception):
                    current_votes.append(
                        AgentVote(agent_id=votes[i].agent_id, response="", confidence=0.0)
                    )
                else:
                    current_votes.append(result)

            round_num += 1

        # 未达成共识，返回最后一轮的多数答案
        final = self._voting(current_votes)
        final.rounds = round_num
        return final

    def _weighted_synthesis(self, votes: list[AgentVote]) -> EnsembleResult:
        """加权合成策略（保留异议）

        Meta Council 框架核心：不丢弃少数派观点，
        而是按置信度加权合成，并在结果中标注异议。
        """
        valid_votes = [v for v in votes if v.response.strip()]
        if not valid_votes:
            return EnsembleResult(final_answer="", consensus_reached=False)

        # 按置信度加权
        total_confidence = sum(v.confidence for v in valid_votes)
        if total_confidence == 0:
            # 无置信度时退化为投票
            return self._voting(votes)

        # 选择加权后最可信的回答（简化实现：选置信度最高的）
        best = max(valid_votes, key=lambda v: v.confidence)

        # 异议：置信度低于平均值的视为异议
        avg_confidence = total_confidence / len(valid_votes)
        dissenting = [v for v in valid_votes if v.confidence < avg_confidence * 0.8]

        # 合成说明
        synthesis = best.response
        if dissenting:
            synthesis += f"\n\n[注意：{len(dissenting)} 个 Agent 持不同意见]"

        return EnsembleResult(
            final_answer=synthesis,
            consensus_reached=len(dissenting) == 0,
            dissenting_views=dissenting,
        )

    def _best_of_n(self, votes: list[AgentVote]) -> EnsembleResult:
        """最优选择策略

        选择置信度最高的单个回答，适合创造性任务。
        """
        valid_votes = [v for v in votes if v.response.strip()]
        if not valid_votes:
            return EnsembleResult(final_answer="", consensus_reached=False)

        best = max(valid_votes, key=lambda v: v.confidence)
        dissenting = [v for v in valid_votes if v is not best]

        return EnsembleResult(
            final_answer=best.response,
            consensus_reached=best.confidence >= self.consensus_threshold,
            dissenting_views=dissenting,
        )

    # ── 工具方法 ────────────────────────────────────────

    def _build_debate_prompt(self, original_query: str, votes: list[AgentVote]) -> str:
        """构建辩论提示"""
        lines = [f"原始问题：{original_query}", "", "其他专家的观点："]
        for v in votes:
            if v.response.strip():
                lines.append(f"- {v.agent_id}: {v.response[:100]}")
        lines.append("")
        lines.append("基于以上观点，请重新思考并给出你的最终回答：")
        return "\n".join(lines)

    def recommend_strategy(self, query: str, task_type: str = "") -> EnsembleStrategy:
        """根据查询特征推荐最佳策略"""
        if task_type == "reasoning":
            return EnsembleStrategy.VOTING
        elif task_type == "knowledge":
            return EnsembleStrategy.CONSENSUS
        elif task_type == "creative":
            return EnsembleStrategy.BEST_OF_N
        elif task_type == "high_stakes":
            return EnsembleStrategy.WEIGHTED_SYNTHESIS

        # 启发式判断
        reasoning_keywords = ["为什么", "如何", "推理", "证明", "计算", "分析"]
        knowledge_keywords = ["是什么", "定义", "事实", "历史", "数据"]
        creative_keywords = ["写", "创作", "设计", "故事", " poem"]

        if any(kw in query for kw in reasoning_keywords):
            return EnsembleStrategy.VOTING
        elif any(kw in query for kw in knowledge_keywords):
            return EnsembleStrategy.CONSENSUS
        elif any(kw in query for kw in creative_keywords):
            return EnsembleStrategy.BEST_OF_N

        return self.default_strategy
