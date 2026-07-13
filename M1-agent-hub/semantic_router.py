"""
云汐内核 V9.8 - 语义路由 Agent 选择器

基于任务描述的语义嵌入相似度，自动选择最合适的 Agent。
无需 LLM 调用，纯本地轻量实现，适配 7B 部署。

核心设计：
1. 为每个 Agent 维护一个能力描述文本
2. 使用简单的字符级 n-gram 特征提取生成嵌入
3. 计算任务描述与各 Agent 能力描述的余弦相似度
4. 选择相似度最高的 Agent
"""

from __future__ import annotations

import math
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SemanticRouter:
    """语义路由：基于 n-gram 嵌入相似度的轻量级 Agent 选择器"""

    def __init__(self, n: int = 2, use_idf: bool = True) -> None:
        self._n = n
        self._use_idf = use_idf
        self._agent_profiles: dict[str, str] = {}  # agent_id -> capability_description
        self._agent_embeddings: dict[str, dict[str, float]] = {}
        # [V9.9] IDF 表：n-gram 在多少 agent 描述中出现
        self._idf: dict[str, float] = {}
        self._logger = logger.bind(service="semantic_router")

    def register_agent(self, agent_id: str, capability_description: str) -> None:
        """注册 Agent 及其能力描述"""
        self._agent_profiles[agent_id] = capability_description
        self._agent_embeddings[agent_id] = self._embed(capability_description)
        # [V9.9] 重新计算 IDF
        if self._use_idf:
            self._rebuild_idf()
        self._logger.info("agent_registered", agent_id=agent_id, desc_len=len(capability_description))

    def unregister_agent(self, agent_id: str) -> None:
        """注销 Agent"""
        self._agent_profiles.pop(agent_id, None)
        self._agent_embeddings.pop(agent_id, None)
        if self._use_idf:
            self._rebuild_idf()

    def _rebuild_idf(self) -> None:
        """[V9.9] 基于所有 Agent 描述重建 IDF 表"""
        import math
        doc_count = len(self._agent_profiles)
        if doc_count == 0:
            self._idf.clear()
            return

        gram_doc_freq: dict[str, int] = {}
        for desc in self._agent_profiles.values():
            unique_grams = set(self._raw_grams(desc).keys())
            for g in unique_grams:
                gram_doc_freq[g] = gram_doc_freq.get(g, 0) + 1

        self._idf = {
            g: math.log((doc_count + 1) / (freq + 1)) + 1.0
            for g, freq in gram_doc_freq.items()
        }

    def _raw_grams(self, text: str) -> dict[str, int]:
        """提取原始 n-gram 频率（不计入 IDF）"""
        text = text.lower().strip()
        grams: dict[str, int] = {}
        for i in range(len(text) - self._n + 1):
            g = text[i : i + self._n]
            grams[g] = grams.get(g, 0) + 1
        return grams

    def route(self, task_description: str, top_k: int = 1) -> list[tuple[str, float]]:
        """为任务选择最合适的 Agent

        Returns:
            [(agent_id, similarity_score), ...] 按相似度降序排列
        """
        if not self._agent_embeddings:
            return []

        task_emb = self._embed(task_description)
        scores: list[tuple[str, float]] = []

        for agent_id, agent_emb in self._agent_embeddings.items():
            sim = self._cosine_similarity(task_emb, agent_emb)
            scores.append((agent_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _embed(self, text: str) -> dict[str, float]:
        """字符级 n-gram 特征提取（轻量，无外部依赖）

        [V9.9] 支持 TF-IDF 加权：稀有 n-gram 获得更高权重
        """
        grams = self._raw_grams(text)
        if not grams:
            return {}

        # [V9.9] 应用 IDF 加权
        if self._use_idf and self._idf:
            weighted = {
                g: freq * self._idf.get(g, 1.0)
                for g, freq in grams.items()
            }
        else:
            weighted = {g: float(freq) for g, freq in grams.items()}

        # L2 归一化
        total = math.sqrt(sum(v * v for v in weighted.values()))
        if total == 0:
            return {}
        return {k: v / total for k, v in weighted.items()}

    def _cosine_similarity(
        self, emb_a: dict[str, float], emb_b: dict[str, float]
    ) -> float:
        """计算两个稀疏嵌入的余弦相似度"""
        common = set(emb_a.keys()) & set(emb_b.keys())
        if not common:
            return 0.0
        dot = sum(emb_a[k] * emb_b[k] for k in common)
        return dot

    def stats(self) -> dict[str, Any]:
        return {
            "registered_agents": len(self._agent_profiles),
            "agent_ids": list(self._agent_profiles.keys()),
        }
