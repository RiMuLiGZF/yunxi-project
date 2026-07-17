"""
云汐内核 V9 - GroupChat 对话引擎

灵感来源：AutoGen v0.4 GroupChat / SelectorGroupChat
https://microsoft.github.io/autogen/0.4.8/user-guide/core-user-guide/design-patterns/group-chat.html

解决 V8 短板：
- 仅有任务驱动模式，缺少开放域多Agent对话
- Agent间不直接通信，所有消息经编排器中转

核心设计：
- GroupChat：多Agent共享对话上下文
- 发言选择策略：RoundRobin / Selector / Custom
- 终止条件：max_round / keyword / custom
- Agent 直接互发消息，无需中央编排器
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.core.semantic_intent_v3 import SemanticIntentClassifierV3

import structlog

# [P3-003] 导入 AgentIdentity（延迟导入以避免循环依赖）
# [P0-5-1] 扩展导入 RBAC 相关类型
try:
    from src.memory.rbac_memory import AgentIdentity, AgentRole, MemoryAccessPolicy
except ImportError:
    AgentIdentity = None  # type: ignore[assignment,misc]
    AgentRole = None  # type: ignore[assignment,misc]
    MemoryAccessPolicy = None  # type: ignore[assignment,misc]

logger = structlog.get_logger(__name__)


@dataclass
class ChatMessage:
    """GroupChat 消息"""

    agent_id: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class SpeakerStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    SELECTOR = "selector"  # 基于描述的Agent选择
    RANDOM = "random"
    CUSTOM = "custom"


class TerminationCondition(ABC):
    """终止条件基类"""

    @abstractmethod
    def should_terminate(self, messages: list[ChatMessage]) -> tuple[bool, str]:
        ...


class MaxRoundTermination(TerminationCondition):
    """最大轮数终止"""

    def __init__(self, max_round: int = 10) -> None:
        self.max_round = max_round

    def should_terminate(self, messages: list[ChatMessage]) -> tuple[bool, str]:
        agent_msgs = [m for m in messages if m.agent_id != "user"]
        if len(agent_msgs) >= self.max_round:
            return True, f"max_round_reached ({self.max_round})"
        return False, ""


class KeywordTermination(TerminationCondition):
    """关键词终止"""

    def __init__(self, keyword: str = "TERMINATE") -> None:
        self.keyword = keyword

    def should_terminate(self, messages: list[ChatMessage]) -> tuple[bool, str]:
        if messages and self.keyword in messages[-1].content:
            return True, f"keyword_triggered ({self.keyword})"
        return False, ""


class CompositeTermination(TerminationCondition):
    """组合终止条件（OR逻辑）"""

    def __init__(
        self, *conditions: TerminationCondition
    ) -> None:
        # 兼容 list 传入：CompositeTermination([a, b]) 或 CompositeTermination(a, b)
        if (
            len(conditions) == 1
            and isinstance(conditions[0], list)
        ):
            self.conditions = tuple(conditions[0])
        else:
            self.conditions = conditions

    def should_terminate(self, messages: list[ChatMessage]) -> tuple[bool, str]:
        for cond in self.conditions:
            should, reason = cond.should_terminate(messages)
            if should:
                return True, reason
        return False, ""


class ConvergenceTermination(TerminationCondition):
    """对话收敛检测终止条件

    基于 TF-IDF 余弦相似度，检测最近 N 轮 Agent 消息的内容相似度。
    当连续多轮相似度超过阈值时，判定对话已收敛，触发终止。

    解决评审 P1-018：GroupChat 缺少对话收敛检测。
    解决评审 P2-023：支持注入已有 SemanticIntentClassifierV3 实例，
        避免每次实例化创建独立的分类器。
    """

    def __init__(
        self,
        window_size: int = 3,
        similarity_threshold: float = 0.85,
        min_agent_messages: int = 4,
        classifier: SemanticIntentClassifierV3 | None = None,
    ) -> None:
        self.window_size = window_size
        self.similarity_threshold = similarity_threshold
        self.min_agent_messages = min_agent_messages
        # [P2-023] 支持注入已有分类器实例，避免重复创建
        self._classifier = classifier or SemanticIntentClassifierV3()

    def _tokenize(self, text: str) -> list[str]:
        """复用语义分类器的分词逻辑"""
        return self._classifier._tokenize(text)

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        """构建词频向量（无IDF，仅term frequency）"""
        vec: dict[str, float] = {}
        for t in tokens:
            vec[t] = vec.get(t, 0.0) + 1.0
        return vec

    def _cosine_similarity(
        self, vec1: dict[str, float], vec2: dict[str, float]
    ) -> float:
        """计算两个稀疏向量的余弦相似度"""
        dot = 0.0
        norm1 = 0.0
        for k, v in vec1.items():
            norm1 += v * v
            if k in vec2:
                dot += v * vec2[k]
        norm2 = sum(v * v for v in vec2.values())
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1**0.5 * norm2**0.5)

    def should_terminate(self, messages: list[ChatMessage]) -> tuple[bool, str]:
        # 只考虑Agent消息（排除user消息）
        agent_msgs = [m for m in messages if m.agent_id != "user"]
        if len(agent_msgs) < self.min_agent_messages:
            return False, ""

        # 取最近 window_size 轮
        recent = agent_msgs[-self.window_size:]
        if len(recent) < 2:
            return False, ""

        # 计算两两相似度
        vectors = [self._vectorize(self._tokenize(m.content)) for m in recent]
        similarities: list[float] = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                similarities.append(self._cosine_similarity(vectors[i], vectors[j]))

        if not similarities:
            return False, ""

        avg_sim = sum(similarities) / len(similarities)
        if avg_sim >= self.similarity_threshold:
            return True, f"conversation_converged (avg_similarity={avg_sim:.2f})"
        return False, ""


# ── Agent 参与者 ────────────────────────────────────────────


class GroupChatAgent(ABC):
    """GroupChat Agent 抽象

    [P3-003] 新增 agent_identity 参数支持 RBAC 身份绑定，
    以及 content_filter 可选回调用于内容过滤。
    [P0-5-1] 新增 role 参数支持 RBAC 角色约束。
    """

    def __init__(
        self,
        agent_id: str,
        description: str = "",
        agent_identity: Any | None = None,
        content_filter: Callable[[str, Any], str] | None = None,
        role: str = "guest",
    ) -> None:
        self.agent_id = agent_id
        self.description = description
        self.agent_identity = agent_identity
        self.content_filter = content_filter
        self.role = role

    @abstractmethod
    async def respond(self, context: list[ChatMessage], task: str = "") -> str:
        """根据对话上下文生成回复"""
        ...

    def _apply_content_filter(self, response: str) -> str:
        """[P3-003] 在返回前应用可选的内容过滤

        如果 content_filter 已设置，对响应内容进行过滤。
        content_filter 签名: (content: str, agent_identity) -> str
        """
        if self.content_filter is not None:
            return self.content_filter(response, self.agent_identity)
        return response


# ── 发言选择器 ────────────────────────────────────────


class SpeakerSelector(ABC):
    """发言选择器"""

    @abstractmethod
    def select_next(
        self,
        agents: list[GroupChatAgent],
        messages: list[ChatMessage],
        last_speaker: GroupChatAgent | None,
    ) -> GroupChatAgent:
        ...


class RoundRobinSelector(SpeakerSelector):
    """轮询选择器"""

    def __init__(self) -> None:
        self._index = 0

    def select_next(
        self,
        agents: list[GroupChatAgent],
        messages: list[ChatMessage],
        last_speaker: GroupChatAgent | None,
    ) -> GroupChatAgent:
        agent = agents[self._index % len(agents)]
        self._index += 1
        return agent


class RandomSelector(SpeakerSelector):
    """随机选择器"""

    def select_next(
        self,
        agents: list[GroupChatAgent],
        messages: list[ChatMessage],
        last_speaker: GroupChatAgent | None,
    ) -> GroupChatAgent:
        import random
        return random.choice(agents)


class DescriptionSelector(SpeakerSelector):
    """基于描述的智能选择器

    简单实现：根据上一条消息内容和各Agent的description匹配度选择。
    生产环境应使用LLM进行决策。
    """

    def select_next(
        self,
        agents: list[GroupChatAgent],
        messages: list[ChatMessage],
        last_speaker: GroupChatAgent | None,
    ) -> GroupChatAgent:
        if not messages:
            return agents[0]

        last_content = messages[-1].content.lower()
        # 简单关键词匹配
        best_agent = agents[0]
        best_score = 0
        for agent in agents:
            desc = agent.description.lower()
            score = sum(1 for word in desc.split() if word in last_content)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent


class CustomSelector(SpeakerSelector):
    """自定义选择器"""

    def __init__(
        self,
        selector_func: Callable[
            [list[GroupChatAgent], list[ChatMessage], GroupChatAgent | None],
            GroupChatAgent,
        ],
    ) -> None:
        self._selector_func = selector_func

    def select_next(
        self,
        agents: list[GroupChatAgent],
        messages: list[ChatMessage],
        last_speaker: GroupChatAgent | None,
    ) -> GroupChatAgent:
        return self._selector_func(agents, messages, last_speaker)


# ── GroupChat 引擎 ────────────────────────────────────


class GroupChatEngine:
    """GroupChat 对话引擎

    管理多Agent的对话循环：
    1. 选择下一个发言Agent
    2. 该Agent根据上下文生成回复
    3. 将回复广播给所有Agent
    4. 检查终止条件
    """

    def __init__(
        self,
        agents: list[GroupChatAgent],
        selector: SpeakerSelector | None = None,
        termination: TerminationCondition | None = None,
        allow_repeat_speaker: bool = True,
        content_filter: Callable[[str, GroupChatAgent], str] | None = None,
        rbac_guard: Any | None = None,
    ) -> None:
        self.agents = {a.agent_id: a for a in agents}
        self.agent_list = list(agents)
        self.selector = selector or RoundRobinSelector()
        self.termination = termination or MaxRoundTermination(10)
        self.allow_repeat_speaker = allow_repeat_speaker
        self.content_filter = content_filter
        self._rbac_guard = rbac_guard
        self._messages: list[ChatMessage] = []
        self._round = 0
        self._logger = logger.bind(service="group_chat")

    async def run(self, task: str = "", max_round: int | None = None) -> dict[str, Any]:
        """运行对话循环

        Args:
            task: 初始任务/话题
            max_round: 覆盖默认的最大轮数
        """
        # 初始任务消息
        if task:
            self._messages.append(ChatMessage(agent_id="user", content=task))

        last_speaker: GroupChatAgent | None = None
        effective_max = max_round or (
            self.termination.max_round
            if isinstance(self.termination, MaxRoundTermination)
            else 20
        )

        while self._round < effective_max:
            # 选择下一个发言者
            next_agent = self.selector.select_next(
                self.agent_list, self._messages, last_speaker
            )

            # 如果不允许连续同一Agent发言，跳过
            if not self.allow_repeat_speaker and last_speaker == next_agent:
                # 尝试下一个
                idx = self.agent_list.index(next_agent)
                next_agent = self.agent_list[(idx + 1) % len(self.agent_list)]

            # [V9.5] RBAC 三层可见性模型（对标 CA-RBAC）
            context_messages = self._messages
            if self._rbac_guard is not None and hasattr(next_agent, "role"):
                if next_agent.role == "guest":
                    # [V9.5] Guest 三层可见性：user消息完整 + agent消息摘要
                    user_msgs = [m for m in self._messages if m.agent_id == "user"]
                    # 收集每个 Agent 的最后一条消息摘要
                    agent_last: dict[str, str] = {}
                    for m in self._messages:
                        if m.agent_id != "user" and m.agent_id not in agent_last:
                            excerpt = m.content[:80] + "..." if len(m.content) > 80 else m.content
                            agent_last[m.agent_id] = f"[{m.agent_id}]: {excerpt}"
                    # 构建摘要消息
                    if agent_last:
                        # [V9.5-R2] 增强摘要：附带关键动作词标记
                        summary_parts = []
                        for aid, excerpt in agent_last.items():
                            # 标记动作类型
                            action_markers = []
                            lower_excerpt = excerpt.lower()
                            if any(w in lower_excerpt for w in ["同意", "agree", "确认", "confirm"]):
                                action_markers.append("✓共识")
                            if any(w in lower_excerpt for w in ["反对", "disagree", "不同意", "异议"]):
                                action_markers.append("✗异议")
                            if any(w in lower_excerpt for w in ["建议", "suggest", "提议", "推荐"]):
                                action_markers.append("💡建议")
                            if any(w in lower_excerpt for w in ["问题", "question", "疑问", "不解"]):
                                action_markers.append("?疑问")
                            
                            marker_str = f" [{','.join(action_markers)}]" if action_markers else ""
                            summary_parts.append(f"{excerpt}{marker_str}")
                        
                        summary_text = "Agent讨论摘要: " + "; ".join(summary_parts)
                        summary_msg = ChatMessage(
                            agent_id="_system",
                            content=summary_text,
                            metadata={"visibility": "summary"},
                        )
                        context_messages = user_msgs + [summary_msg]
                    else:
                        context_messages = user_msgs
                elif AgentIdentity is not None and MemoryAccessPolicy is not None:
                    try:
                        agent_role_enum = AgentRole(next_agent.role) if AgentRole is not None else None
                    except (ValueError, TypeError):
                        agent_role_enum = AgentRole.GENERAL if AgentRole is not None else None
                    identity = AgentIdentity(
                        agent_id=next_agent.agent_id,
                        role=agent_role_enum,
                    )
                    context_messages = [
                        m for m in self._messages
                        if m.agent_id == "user" or self._rbac_guard.can_read(
                            identity,
                            MemoryAccessPolicy(visibility="team", owner=""),
                        )
                    ]

            # 生成回复
            try:
                response = await next_agent.respond(context_messages, task)
            except Exception as exc:
                self._logger.error(
                    "agent_respond_failed",
                    agent_id=next_agent.agent_id,
                    error=str(exc),
                )
                response = f"[ERROR] {exc}"

            # [P3-003] 应用引擎级 content_filter（如果提供）
            if self.content_filter is not None:
                response = self.content_filter(response, next_agent)

            msg = ChatMessage(
                agent_id=next_agent.agent_id,
                content=response,
            )
            self._messages.append(msg)
            last_speaker = next_agent
            self._round += 1

            # 检查终止条件
            should_stop, reason = self.termination.should_terminate(self._messages)
            if should_stop:
                self._logger.info("group_chat_terminated", reason=reason, rounds=self._round)
                break

        return {
            "messages": [
                {"agent_id": m.agent_id, "content": m.content, "timestamp": m.timestamp}
                for m in self._messages
            ],
            "rounds": self._round,
            "participants": list(self.agents.keys()),
            "final_answer": self._messages[-1].content if self._messages else "",
        }

    def get_history(self) -> list[ChatMessage]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()
        self._round = 0

    def stats(self) -> dict[str, Any]:
        return {
            "participants": len(self.agents),
            "total_messages": len(self._messages),
            "rounds": self._round,
            "selector_type": type(self.selector).__name__,
            "termination_type": type(self.termination).__name__,
        }
