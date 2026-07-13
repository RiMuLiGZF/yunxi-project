"""
云汐内核 V5 - 向量语义记忆系统

⚠️ [V10.0-R01 DEPRECATED] 本模块属于模块5（潮汐记忆）职责范围，
将在模块5就绪后迁移。当前保留作为向后兼容的临时实现。

M1应通过 MemoryInterface 调用模块5的向量查询能力，
不直接操作向量存储。

灵感来源：FAISS / Chroma / Weaviate 向量数据库

将长期记忆（LTM）从关键词匹配升级为语义向量检索：
- 文本 → Embedding → 向量存储
- 查询 → Embedding → 余弦相似度 Top-K 检索

优势：
- "用户喜欢咖啡" 和 "他爱喝拿铁" 语义相近，可被召回
- 支持跨语言语义匹配
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger(__name__)


Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]
"""嵌入函数签名：输入文本列表，输出向量列表"""


@dataclass
class VectorEntry:
    """向量记忆条目"""

    entry_id: str = ""
    content: str = ""
    vector: list[float] = field(default_factory=list)
    memory_type: str = "generic"
    source: str = ""
    importance: float = 0.5
    created_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "content": self.content,
            "vector": self.vector,
            "memory_type": self.memory_type,
            "source": self.source,
            "importance": self.importance,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class SimpleEmbedder:
    """简单本地嵌入器（无需外部模型）

    基于词频统计 + 哈希的轻量级嵌入方案。
    生产环境应替换为 sentence-transformers 或 LLM embed。
    """

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """生成文本嵌入向量"""
        results = []
        for text in texts:
            vector = self._text_to_vector(text)
            results.append(vector)
        return results

    def _text_to_vector(self, text: str) -> list[float]:
        """将文本转换为固定维度的向量"""
        # 基于字符级别 n-gram 频率统计
        vec = [0.0] * self.dimension
        text_lower = text.lower().strip()

        if not text_lower:
            return vec

        # 字符级 2-gram + 3-gram 哈希
        for i in range(len(text_lower) - 1):
            bigram = text_lower[i:i + 2]
            idx = hash(bigram) % self.dimension
            vec[idx] += 1.0

        for i in range(len(text_lower) - 2):
            trigram = text_lower[i:i + 3]
            idx = hash(trigram) % self.dimension
            vec[idx] += 1.5

        # 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class VectorMemory:
    """向量记忆存储

    内存中的向量数据库，支持语义相似度检索。
    """

    def __init__(
        self,
        dimension: int = 128,
        embedder: SimpleEmbedder | None = None,
    ) -> None:
        self.dimension = dimension
        self.embedder = embedder or SimpleEmbedder(dimension)
        self._entries: dict[str, VectorEntry] = {}
        self._logger = logger.bind(service="vector_memory")

    # ── 写入 ────────────────────────────────────────────

    async def add(
        self,
        content: str,
        memory_type: str = "generic",
        source: str = "",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> VectorEntry:
        """添加记忆条目"""
        vectors = await self.embedder.embed([content])
        entry = VectorEntry(
            entry_id=f"vec_{uuid.uuid4().hex[:12]}",
            content=content,
            vector=vectors[0],
            memory_type=memory_type,
            source=source,
            importance=importance,
            created_at=time.time(),
            metadata=metadata or {},
        )
        self._entries[entry.entry_id] = entry
        self._logger.debug("vector_entry_added", entry_id=entry.entry_id, content=content[:30])
        return entry

    async def add_many(self, items: list[dict[str, Any]]) -> list[VectorEntry]:
        """批量添加"""
        entries = []
        for item in items:
            entry = await self.add(
                content=item["content"],
                memory_type=item.get("memory_type", "generic"),
                source=item.get("source", ""),
                importance=item.get("importance", 0.5),
                metadata=item.get("metadata", {}),
            )
            entries.append(entry)
        return entries

    # ── 检索 ────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.0,
        memory_type: str | None = None,
    ) -> list[tuple[VectorEntry, float]]:
        """语义相似度检索

        Args:
            query: 查询文本
            top_k: 返回 Top-K 结果
            threshold: 相似度阈值（余弦相似度，-1~1）
            memory_type: 可选的内存类型过滤

        Returns:
            [(entry, similarity), ...]，按相似度降序
        """
        if not self._entries:
            return []

        query_vectors = await self.embedder.embed([query])
        query_vector = query_vectors[0]

        results: list[tuple[VectorEntry, float]] = []
        for entry in self._entries.values():
            if memory_type and entry.memory_type != memory_type:
                continue
            sim = self._cosine_similarity(query_vector, entry.vector)
            if sim >= threshold:
                results.append((entry, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── 管理 ────────────────────────────────────────────

    def get(self, entry_id: str) -> VectorEntry | None:
        """按 ID 获取条目"""
        return self._entries.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        """删除条目"""
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    def clear(self) -> None:
        """清空所有条目"""
        self._entries.clear()

    def list_all(self) -> list[VectorEntry]:
        """列出所有条目"""
        return list(self._entries.values())

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "total_entries": len(self._entries),
            "dimension": self.dimension,
            "memory_types": list(set(e.memory_type for e in self._entries.values())),
        }

    # ── 与现有 LTM 集成 ─────────────────────────────────

    async def search_similar(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """搜索并返回字典格式结果（便于与现有 LTM 集成）"""
        results = await self.search(query, top_k=top_k, threshold=threshold)
        return [
            {
                "entry_id": entry.entry_id,
                "content": entry.content,
                "similarity": round(sim, 4),
                "memory_type": entry.memory_type,
                "source": entry.source,
                "importance": entry.importance,
                "metadata": entry.metadata,
            }
            for entry, sim in results
        ]
