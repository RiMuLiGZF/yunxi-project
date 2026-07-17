"""
云汐内核 V9 - 语义意图分类器 V3

2026年业界主流：Semantic Router（Embedding-based Intent Routing）
https://truto.one/blog/how-to-implement-semantic-routing-for-ai-agents/

解决 V8 短板：
- IntentClassifierV2 仍用字符级 n-gram Jaccard，无法理解深层语义
- 升级到 Embedding-based 余弦相似度路由

本地 7B 友好设计：
- 使用轻量级词袋 + TF-IDF 向量化（无需加载 LLM）
- 支持增量学习：新样本自动更新向量空间
- 分层漏斗：先 Embedding 快速粗筛（<10ms），后 LLM 精筛（可选）
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class IntentVector:
    """意图向量表示"""

    intent: str
    vector: dict[str, float]  # 稀疏向量：词 -> TF-IDF 权重
    sample_count: int = 0
    last_updated: float = field(default_factory=time.time)


class SemanticIntentClassifierV3:
    """语义意图分类器 V3

    基于 TF-IDF 稀疏向量和余弦相似度进行意图匹配。
    无需外部 Embedding 模型，纯 Python 实现，7B 部署零额外开销。
    """

    def __init__(self, min_confidence: float = 0.3, top_k: int = 3) -> None:
        self._intent_vectors: dict[str, IntentVector] = {}
        self._idf: dict[str, float] = {}  # 全局 IDF
        self._doc_count: int = 0
        self.min_confidence = min_confidence
        self.top_k = top_k
        self._logger = logger.bind(service="semantic_intent_v3")

    # ── 文本预处理 ────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词：去标点、小写、保留2字以上词"""
        import re
        text = text.lower()
        # 保留中文字符和英文单词
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-z]+', text)
        # 中文按字分 + 保留完整词
        result = []
        for t in tokens:
            if any('\u4e00' <= c <= '\u9fff' for c in t):
                result.extend(t)  # 中文字符级
                if len(t) >= 2:
                    result.append(t)  # 保留完整中文词
            else:
                result.append(t)
        return [t for t in result if len(t) >= 1]

    def _compute_tf(self, tokens: list[str]) -> dict[str, float]:
        """计算 TF（词频）"""
        counter = Counter(tokens)
        total = len(tokens) or 1
        return {word: count / total for word, count in counter.items()}

    def _compute_idf(self, all_docs: list[list[str]]) -> dict[str, float]:
        """计算 IDF"""
        doc_freq: dict[str, int] = defaultdict(int)
        for doc in all_docs:
            for word in set(doc):
                doc_freq[word] += 1
        n = len(all_docs) or 1
        return {word: math.log(n / (freq + 1)) + 1 for word, freq in doc_freq.items()}

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        """计算 TF-IDF 向量"""
        tf = self._compute_tf(tokens)
        return {word: tf[word] * self._idf.get(word, 1.0) for word in tf}

    def _cosine_similarity(
        self, vec_a: dict[str, float], vec_b: dict[str, float]
    ) -> float:
        """余弦相似度"""
        all_words = set(vec_a.keys()) | set(vec_b.keys())
        dot = sum(vec_a.get(w, 0) * vec_b.get(w, 0) for w in all_words)
        norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── 训练 ──────────────────────────────────────────

    def train(self, samples: dict[str, list[str]]) -> None:
        """训练意图分类器

        Args:
            samples: intent -> [sample_text, ...]
        """
        # 1. 收集所有文档
        all_docs: list[list[str]] = []
        intent_docs: dict[str, list[list[str]]] = {}

        for intent, texts in samples.items():
            docs = [self._tokenize(t) for t in texts]
            intent_docs[intent] = docs
            all_docs.extend(docs)

        # 2. 计算全局 IDF
        self._idf = self._compute_idf(all_docs)
        self._doc_count = len(all_docs)

        # 3. 为每个意图计算平均向量
        for intent, docs in intent_docs.items():
            vectors = [self._vectorize(doc) for doc in docs]
            # 平均向量
            avg_vec: dict[str, float] = defaultdict(float)
            for vec in vectors:
                for word, weight in vec.items():
                    avg_vec[word] += weight
            avg_vec = {
                word: weight / len(vectors)
                for word, weight in avg_vec.items()
            }
            self._intent_vectors[intent] = IntentVector(
                intent=intent,
                vector=avg_vec,
                sample_count=len(docs),
            )

        self._logger.info(
            "classifier_trained",
            intents=list(self._intent_vectors.keys()),
            vocab_size=len(self._idf),
        )

    def add_sample(self, intent: str, text: str) -> None:
        """增量添加训练样本"""
        tokens = self._tokenize(text)
        vec = self._vectorize(tokens)

        existing = self._intent_vectors.get(intent)
        if existing is None:
            self._intent_vectors[intent] = IntentVector(
                intent=intent, vector=vec, sample_count=1
            )
        else:
            # 加权平均更新
            n = existing.sample_count
            new_vec = {}
            all_words = set(existing.vector.keys()) | set(vec.keys())
            for word in all_words:
                old_w = existing.vector.get(word, 0)
                new_w = vec.get(word, 0)
                new_vec[word] = (old_w * n + new_w) / (n + 1)
            existing.vector = new_vec
            existing.sample_count += 1
            existing.last_updated = time.time()

        # 增量更新 IDF（简化：给新词一个基础 IDF）
        for word in set(tokens):
            if word not in self._idf:
                self._idf[word] = math.log(self._doc_count + 1) + 1

    # ── 分类 ──────────────────────────────────────────

    def classify(self, text: str) -> dict[str, Any]:
        """分类意图

        Returns:
            {
                "intent": str,
                "confidence": float,
                "top_k": [(intent, score), ...],
                "latency_ms": float,
            }
        """
        start = time.time()
        tokens = self._tokenize(text)
        query_vec = self._vectorize(tokens)

        scores: list[tuple[str, float]] = []
        for intent, iv in self._intent_vectors.items():
            sim = self._cosine_similarity(query_vec, iv.vector)
            scores.append((intent, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[0] if scores else ("fallback", 0.0)

        latency = (time.time() - start) * 1000

        return {
            "intent": top[0] if top[1] >= self.min_confidence else "fallback",
            "confidence": round(top[1], 4),
            "top_k": [(i, round(s, 4)) for i, s in scores[: self.top_k]],
            "latency_ms": round(latency, 2),
        }

    def batch_classify(self, texts: list[str]) -> list[dict[str, Any]]:
        """批量分类"""
        return [self.classify(t) for t in texts]

    def stats(self) -> dict[str, Any]:
        return {
            "intents_count": len(self._intent_vectors),
            "vocab_size": len(self._idf),
            "total_samples": sum(iv.sample_count for iv in self._intent_vectors.values()),
            "intents": {
                iv.intent: {
                    "samples": iv.sample_count,
                    "last_updated": iv.last_updated,
                }
                for iv in self._intent_vectors.values()
            },
        }
