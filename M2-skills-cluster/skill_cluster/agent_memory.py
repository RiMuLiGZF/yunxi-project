from __future__ import annotations

"""Agent Memory - Agent 向量记忆层.

参考 2026 年 Agent Memory 最佳实践，实现三层记忆架构：
- Working Memory: 当前会话上下文（ ephemeral ）
- Session Memory: 会话摘要与提取事实
- Long-term Memory: 跨会话持久化知识，支持向量语义检索

支持多信号检索融合：语义相似度 + 关键词匹配 + 时间衰减 + 重要性权重。
"""

import math
import re
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class MemoryEntry(BaseModel):
    """记忆条目."""

    entry_id: str = Field(..., description="记忆唯一标识")
    content: str = Field(..., description="文本内容")
    embedding: list[float] | None = Field(
        default=None, description="向量嵌入"
    )
    timestamp: float = Field(default_factory=time.time, description="创建时间")
    tags: list[str] = Field(default_factory=list, description="标签")
    importance: float = Field(
        default=1.0, description="重要性评分 (0-10)"
    )
    source: str = Field(default="unknown", description="来源")
    memory_type: str = Field(
        default="long_term", description="记忆类型: working/session/long_term"
    )


class AgentMemory:
    """Agent 记忆管理器.

    管理三层记忆存储与多信号检索。
    """

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id
        self._working: list[MemoryEntry] = []
        self._session: list[MemoryEntry] = []
        self._long_term: list[MemoryEntry] = []
        self._embedding_dim: int = 64  # 简化维度，生产环境用 768/1536

    # ---- 写入接口 ----

    def add_working(
        self,
        content: str,
        tags: list[str] | None = None,
        importance: float = 1.0,
    ) -> MemoryEntry:
        """添加到工作记忆（当前会话上下文）."""
        entry = MemoryEntry(
            entry_id=self._gen_id("w"),
            content=content,
            tags=tags or [],
            importance=importance,
            source=self._agent_id,
            memory_type="working",
        )
        self._working.append(entry)
        return entry

    def add_session(
        self,
        content: str,
        tags: list[str] | None = None,
        importance: float = 3.0,
    ) -> MemoryEntry:
        """添加到会话记忆（会话级别摘要）."""
        entry = MemoryEntry(
            entry_id=self._gen_id("s"),
            content=content,
            tags=tags or [],
            importance=importance,
            source=self._agent_id,
            memory_type="session",
        )
        self._session.append(entry)
        return entry

    def add_long_term(
        self,
        content: str,
        tags: list[str] | None = None,
        importance: float = 5.0,
    ) -> MemoryEntry:
        """添加到长期记忆（跨会话持久化）.

        自动计算简化向量嵌入（基于字符 n-gram 的哈希嵌入，
        生产环境应替换为真实 Embedding 模型）。
        """
        embedding = self._compute_embedding(content)
        entry = MemoryEntry(
            entry_id=self._gen_id("l"),
            content=content,
            embedding=embedding,
            tags=tags or [],
            importance=importance,
            source=self._agent_id,
            memory_type="long_term",
        )
        self._long_term.append(entry)
        return entry

    # ---- 检索接口 ----

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        memory_types: list[str] | None = None,
        tags: list[str] | None = None,
        time_decay_hours: float = 24.0,
    ) -> list[tuple[MemoryEntry, float]]:
        """多信号检索融合.

        综合评分 = 语义相似度 * 0.5 + 关键词匹配 * 0.3 + 时间衰减 * 0.1 + 重要性 * 0.1

        Args:
            query: 查询文本.
            top_k: 返回条数.
            memory_types: 记忆类型过滤（None 表示全部）.
            tags: 标签过滤.
            time_decay_hours: 时间衰减半衰期（小时）.

        Returns:
            (记忆条目, 融合评分) 列表，按评分降序.
        """
        candidates: list[MemoryEntry] = []
        if memory_types is None:
            candidates = self._working + self._session + self._long_term
        else:
            if "working" in memory_types:
                candidates.extend(self._working)
            if "session" in memory_types:
                candidates.extend(self._session)
            if "long_term" in memory_types:
                candidates.extend(self._long_term)

        if tags:
            candidates = [
                e for e in candidates if any(t in e.tags for t in tags)
            ]

        query_emb = self._compute_embedding(query)
        query_tokens = set(self._tokenize(query))
        now = time.time()

        scored: list[tuple[MemoryEntry, float]] = []
        for entry in candidates:
            # 语义相似度（仅长期记忆有 embedding）
            semantic_score = 0.0
            if entry.embedding and query_emb:
                semantic_score = self._cosine_similarity(
                    entry.embedding, query_emb
                )
            elif entry.memory_type in ("working", "session"):
                # 工作/会话记忆无 embedding，用文本重合度近似
                entry_tokens = set(self._tokenize(entry.content))
                if query_tokens:
                    semantic_score = len(
                        query_tokens & entry_tokens
                    ) / len(query_tokens)

            # 关键词匹配
            keyword_score = self._keyword_match_score(query, entry.content)

            # 时间衰减
            age_hours = (now - entry.timestamp) / 3600.0
            time_score = math.exp(-age_hours / time_decay_hours)

            # 重要性归一化
            importance_score = min(entry.importance / 10.0, 1.0)

            # 融合
            fused = (
                semantic_score * 0.5
                + keyword_score * 0.3
                + time_score * 0.1
                + importance_score * 0.1
            )
            scored.append((entry, fused))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def search_by_tag(
        self, tag: str, memory_type: str | None = None
    ) -> list[MemoryEntry]:
        """按标签搜索."""
        pool: list[MemoryEntry] = []
        if memory_type == "working" or memory_type is None:
            pool.extend(self._working)
        if memory_type == "session" or memory_type is None:
            pool.extend(self._session)
        if memory_type == "long_term" or memory_type is None:
            pool.extend(self._long_term)
        return [e for e in pool if tag in e.tags]

    # ---- 记忆管理 ----

    def summarize_working(self) -> str | None:
        """将工作记忆压缩为会话摘要并移入会话记忆.

        Returns:
            生成的摘要内容，若无工作记忆则返回 None.
        """
        if not self._working:
            return None
        contents = [e.content for e in self._working]
        summary = " | ".join(contents[:10])  # 简化摘要
        self.add_session(summary, tags=["auto_summary"], importance=4.0)
        self._working.clear()
        return summary

    def compress_session(self) -> str | None:
        """将高频/高重要性会话记忆提升为长期记忆.

        Returns:
            提升的记忆内容，若无则返回 None.
        """
        if not self._session:
            return None
        # 选择重要性最高的会话记忆
        top = max(self._session, key=lambda e: e.importance)
        self.add_long_term(
            top.content, tags=top.tags + ["promoted"], importance=top.importance
        )
        self._session.remove(top)
        return top.content

    def forget_old(self, max_age_hours: float = 168.0) -> int:
        """清理超期记忆.

        Args:
            max_age_hours: 最大保留时间（小时），默认 7 天.

        Returns:
            清理的条目数.
        """
        now = time.time()
        threshold = now - max_age_hours * 3600
        removed = 0
        for pool in (self._working, self._session, self._long_term):
            to_remove = [e for e in pool if e.timestamp < threshold]
            for e in to_remove:
                pool.remove(e)
                removed += 1
        return removed

    def clear_working(self) -> None:
        """清空工作记忆."""
        self._working.clear()

    def get_stats(self) -> dict[str, Any]:
        """获取记忆统计."""
        return {
            "working_count": len(self._working),
            "session_count": len(self._session),
            "long_term_count": len(self._long_term),
            "total_count": len(self._working)
            + len(self._session)
            + len(self._long_term),
        }

    # ---- 内部方法 ----

    def _gen_id(self, prefix: str) -> str:
        return f"{prefix}_{self._agent_id}_{int(time.time() * 1000)}"

    def _tokenize(self, text: str) -> list[str]:
        """简单分词."""
        return re.findall(r"\b\w+\b", text.lower())

    def _compute_embedding(self, text: str) -> list[float]:
        """简化嵌入计算（字符 n-gram 哈希）.

        生产环境应替换为 sentence-transformers / OpenAI Embedding API。
        """
        n = 3
        dim = self._embedding_dim
        vec = [0.0] * dim
        text = text.lower()
        for i in range(len(text) - n + 1):
            gram = text[i : i + n]
            idx = hash(gram) % dim
            vec[idx] += 1.0
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _cosine_similarity(
        self, a: list[float], b: list[float]
    ) -> float:
        """计算余弦相似度."""
        dot = sum(x * y for x, y in zip(a, b))
        return max(0.0, min(1.0, dot))  # 裁剪到 [0, 1]

    def _keyword_match_score(self, query: str, content: str) -> float:
        """关键词匹配评分（Jaccard 近似）."""
        q_tokens = set(self._tokenize(query))
        c_tokens = set(self._tokenize(content))
        if not q_tokens:
            return 0.0
        intersection = q_tokens & c_tokens
        union = q_tokens | c_tokens
        if not union:
            return 0.0
        return len(intersection) / len(union)
