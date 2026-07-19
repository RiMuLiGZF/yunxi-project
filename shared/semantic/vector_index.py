"""轻量级向量索引.

基于 numpy + cosine similarity 的内存向量索引。
支持增量添加、批量搜索、删除操作。

设计目标：
- 轻量：仅依赖 numpy（如果可用），否则回退到纯 Python
- 高效：使用矩阵运算加速批量搜索
- 易用：简洁的 API，支持按 ID 管理向量
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchResult:
    """向量搜索结果."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: "SearchResult") -> bool:
        return self.score < other.score

    def __gt__(self, other: "SearchResult") -> bool:
        return self.score > other.score


class VectorIndex:
    """基于余弦相似度的轻量向量索引.

    支持 numpy 加速（如果可用），否则回退到纯 Python 实现。
    所有向量在添加时自动进行 L2 归一化，确保 cosine similarity
    可以通过点积快速计算。

    使用示例::

        index = VectorIndex(dimension=256)
        index.add("doc1", [0.1, 0.2, ...], {"type": "skill"})
        results = index.search([0.15, 0.18, ...], top_k=5)
    """

    def __init__(self, dimension: int) -> None:
        """初始化向量索引.

        Args:
            dimension: 向量维度
        """
        self._dimension = dimension
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []
        self._metadatas: list[dict[str, Any]] = []
        self._id_to_index: dict[str, int] = {}

        # 检测 numpy 是否可用
        self._use_numpy = False
        self._np_array = None
        try:
            import numpy as np  # type: ignore

            self._np = np
            self._use_numpy = True
        except ImportError:
            self._np = None  # type: ignore

    @property
    def dimension(self) -> int:
        """向量维度."""
        return self._dimension

    @property
    def size(self) -> int:
        """索引中的向量数量."""
        return len(self._ids)

    def add(
        self,
        vector_id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """添加向量到索引.

        如果 ID 已存在，则更新对应向量。

        Args:
            vector_id: 向量唯一标识
            vector: 向量数据
            metadata: 附加元数据
        """
        if len(vector) != self._dimension:
            raise ValueError(
                f"向量维度不匹配: 期望 {self._dimension}, 实际 {len(vector)}"
            )

        # L2 归一化
        normalized = self._normalize(vector)

        if vector_id in self._id_to_index:
            # 更新已有向量
            idx = self._id_to_index[vector_id]
            self._vectors[idx] = normalized
            self._metadatas[idx] = metadata or {}
        else:
            # 添加新向量
            idx = len(self._ids)
            self._ids.append(vector_id)
            self._vectors.append(normalized)
            self._metadatas.append(metadata or {})
            self._id_to_index[vector_id] = idx

        # 清除 numpy 缓存
        self._np_array = None

    def add_batch(
        self,
        items: list[tuple[str, list[float], dict[str, Any] | None]],
    ) -> None:
        """批量添加向量.

        Args:
            items: [(id, vector, metadata), ...] 列表
        """
        for vector_id, vector, metadata in items:
            self.add(vector_id, vector, metadata)

    def delete(self, vector_id: str) -> bool:
        """删除指定 ID 的向量.

        Args:
            vector_id: 向量 ID

        Returns:
            True 表示删除成功，False 表示 ID 不存在
        """
        if vector_id not in self._id_to_index:
            return False

        idx = self._id_to_index[vector_id]
        # 用最后一个元素替换被删除的位置（O(1) 删除）
        last_idx = len(self._ids) - 1

        if idx != last_idx:
            # 移动最后一个元素到被删除位置
            last_id = self._ids[last_idx]
            self._ids[idx] = last_id
            self._vectors[idx] = self._vectors[last_idx]
            self._metadatas[idx] = self._metadatas[last_idx]
            self._id_to_index[last_id] = idx

        # 移除最后一个元素
        self._ids.pop()
        self._vectors.pop()
        self._metadatas.pop()
        del self._id_to_index[vector_id]

        # 清除 numpy 缓存
        self._np_array = None

        return True

    def get(self, vector_id: str) -> tuple[list[float], dict[str, Any]] | None:
        """获取指定 ID 的向量和元数据.

        Args:
            vector_id: 向量 ID

        Returns:
            (vector, metadata) 或 None（不存在时）
        """
        if vector_id not in self._id_to_index:
            return None
        idx = self._id_to_index[vector_id]
        return (list(self._vectors[idx]), dict(self._metadatas[idx]))

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """搜索最相似的向量.

        Args:
            query_vector: 查询向量
            top_k: 返回前 K 个结果
            filter_metadata: 元数据过滤条件（仅返回匹配的结果）

        Returns:
            SearchResult 列表，按相似度降序排列
        """
        if len(query_vector) != self._dimension:
            raise ValueError(
                f"查询向量维度不匹配: 期望 {self._dimension}, 实际 {len(query_vector)}"
            )

        if self.size == 0:
            return []

        # 归一化查询向量
        query_norm = self._normalize(query_vector)

        # 计算相似度
        scores: list[tuple[int, float]] = []

        if self._use_numpy:
            scores = self._search_numpy(query_norm)
        else:
            scores = self._search_python(query_norm)

        # 元数据过滤
        if filter_metadata:
            scores = [
                (idx, score) for idx, score in scores
                if self._metadata_matches(idx, filter_metadata)
            ]

        # 排序并取 top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        top_scores = scores[:top_k]

        return [
            SearchResult(
                id=self._ids[idx],
                score=max(0.0, min(1.0, score)),
                metadata=dict(self._metadatas[idx]),
            )
            for idx, score in top_scores
        ]

    def _search_numpy(
        self, query_vector: list[float]
    ) -> list[tuple[int, float]]:
        """使用 numpy 进行批量相似度计算."""
        assert self._np is not None

        # 延迟构建 numpy 数组
        if self._np_array is None:
            self._np_array = self._np.array(self._vectors, dtype=self._np.float32)

        query_arr = self._np.array(query_vector, dtype=self._np.float32)
        # 因为向量已归一化，cosine similarity = dot product
        similarities = self._np_array @ query_arr

        return list(enumerate(similarities.tolist()))

    def _search_python(
        self, query_vector: list[float]
    ) -> list[tuple[int, float]]:
        """纯 Python 实现相似度计算."""
        results: list[tuple[int, float]] = []
        for i, vec in enumerate(self._vectors):
            # 点积（向量已归一化）
            sim = sum(a * b for a, b in zip(query_vector, vec))
            results.append((i, sim))
        return results

    def _metadata_matches(
        self, idx: int, filter_dict: dict[str, Any]
    ) -> bool:
        """检查指定索引的元数据是否匹配过滤条件."""
        meta = self._metadatas[idx]
        for key, value in filter_dict.items():
            if meta.get(key) != value:
                return False
        return True

    def _normalize(self, vector: list[float]) -> list[float]:
        """L2 归一化向量."""
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return [0.0] * len(vector)
        return [v / norm for v in vector]

    def clear(self) -> None:
        """清空索引."""
        self._ids.clear()
        self._vectors.clear()
        self._metadatas.clear()
        self._id_to_index.clear()
        self._np_array = None

    def ids(self) -> list[str]:
        """获取所有向量 ID 列表."""
        return list(self._ids)

    def __contains__(self, vector_id: str) -> bool:
        """检查 ID 是否存在."""
        return vector_id in self._id_to_index

    def __len__(self) -> int:
        return self.size
