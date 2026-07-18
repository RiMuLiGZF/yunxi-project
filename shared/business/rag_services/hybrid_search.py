"""
混合检索模块 (Hybrid Search)

实现多路召回与融合：
1. 向量检索（Dense Retrieval）- 语义相似度
2. 关键词检索（Sparse Retrieval）- BM25 / TF-IDF
3. 混合检索 - 加权融合 / RRF 融合
4. 重排序（Rerank）- 交叉编码器风格评分

纯 Python 实现，不依赖外部服务。
向量检索在 embedding 不可用时自动降级。
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Callable
from collections import defaultdict


# ============================================================
# 数据结构
# ============================================================

@dataclass
class RetrievalResultItem:
    """
    检索结果项（统一格式）

    用于混合检索的中间和最终结果表示。
    """
    chunk_id: str
    doc_id: str
    text: str
    score: float = 0.0
    rank: int = 0
    source: str = ""  # dense / sparse / hybrid
    dense_score: float = 0.0
    sparse_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "text": self.text,
            "score": round(self.score, 4),
            "rank": self.rank,
            "source": self.source,
            "dense_score": round(self.dense_score, 4),
            "sparse_score": round(self.sparse_score, 4),
            "metadata": self.metadata,
        }


# ============================================================
# 向量检索（Dense Retrieval）
# ============================================================

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    if len(a) != len(b) or not a:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


class DenseRetriever:
    """
    向量检索器

    基于余弦相似度的向量检索。
    支持传入 embedding 函数，不传入时使用纯关键词降级。
    """

    def __init__(self,
                 embedding_fn: Optional[Callable[[str], Optional[List[float]]]] = None,
                 top_k: int = 20,
                 min_score: float = 0.0):
        """
        Args:
            embedding_fn: 嵌入函数，输入文本输出向量
            top_k: 返回 Top K 结果
            min_score: 最低相似度阈值
        """
        self.embedding_fn = embedding_fn
        self.top_k = top_k
        self.min_score = min_score
        self._embeddings: Dict[str, List[float]] = {}  # chunk_id -> vector
        self._texts: Dict[str, str] = {}  # chunk_id -> text
        self._doc_ids: Dict[str, str] = {}  # chunk_id -> doc_id

    def add_document(self, chunk_id: str, text: str, doc_id: str = "",
                     embedding: Optional[List[float]] = None):
        """添加文档到索引"""
        self._texts[chunk_id] = text
        self._doc_ids[chunk_id] = doc_id

        if embedding is not None:
            self._embeddings[chunk_id] = embedding
        elif self.embedding_fn:
            emb = self.embedding_fn(text)
            if emb is not None:
                self._embeddings[chunk_id] = emb

    def add_batch(self, items: List[Dict[str, Any]]):
        """批量添加文档"""
        for item in items:
            self.add_document(
                chunk_id=item["chunk_id"],
                text=item["text"],
                doc_id=item.get("doc_id", ""),
                embedding=item.get("embedding"),
            )

    def remove(self, chunk_id: str):
        """移除文档"""
        self._embeddings.pop(chunk_id, None)
        self._texts.pop(chunk_id, None)
        self._doc_ids.pop(chunk_id, None)

    def search(self, query: str, top_k: Optional[int] = None) -> List[RetrievalResultItem]:
        """
        向量检索

        Args:
            query: 查询文本
            top_k: 返回数量（覆盖默认值）

        Returns:
            检索结果列表（按相似度降序）
        """
        k = top_k or self.top_k

        # 如果没有 embedding 函数或没有向量，返回空
        if not self.embedding_fn or not self._embeddings:
            return []

        query_emb = self.embedding_fn(query)
        if query_emb is None:
            return []

        results = []
        for chunk_id, emb in self._embeddings.items():
            score = cosine_similarity(query_emb, emb)
            if score >= self.min_score:
                results.append(RetrievalResultItem(
                    chunk_id=chunk_id,
                    doc_id=self._doc_ids.get(chunk_id, ""),
                    text=self._texts.get(chunk_id, ""),
                    score=score,
                    dense_score=score,
                    source="dense",
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:k]

        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    @property
    def is_available(self) -> bool:
        """向量检索是否可用"""
        return self.embedding_fn is not None and len(self._embeddings) > 0

    def clear(self):
        """清空索引"""
        self._embeddings.clear()
        self._texts.clear()
        self._doc_ids.clear()


# ============================================================
# 关键词检索（Sparse Retrieval - BM25）
# ============================================================

class BM25Retriever:
    """
    BM25 关键词检索器

    实现经典的 BM25 算法，支持中英文混合文本。
    中文采用 2-gram 分词，英文采用空格分词。

    BM25 公式：
    score(Q, D) = sum( IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D| / avgdl)) )
    """

    def __init__(self,
                 k1: float = 1.5,
                 b: float = 0.75,
                 top_k: int = 20,
                 min_score: float = 0.0):
        """
        Args:
            k1: BM25 k1 参数（饱和度参数）
            b: BM25 b 参数（长度归一化参数）
            top_k: 返回 Top K 结果
            min_score: 最低分数阈值
        """
        self.k1 = k1
        self.b = b
        self.top_k = top_k
        self.min_score = min_score

        self._docs: Dict[str, str] = {}  # chunk_id -> text
        self._doc_ids: Dict[str, str] = {}  # chunk_id -> doc_id
        self._doc_lens: Dict[str, int] = {}  # chunk_id -> doc length (terms)
        self._df: Dict[str, int] = defaultdict(int)  # term -> doc frequency
        self._tf: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # chunk_id -> {term: freq}
        self._avgdl: float = 0.0
        self._total_docs: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """
        分词（中英文混合）

        策略：
        - 英文：按空格和标点分割，转小写
        - 中文：2-gram 切分
        """
        tokens = []

        # 统一处理
        text_lower = text.lower()

        # 提取英文单词
        english_words = re.findall(r'[a-zA-Z]{2,}', text_lower)
        tokens.extend(english_words)

        # 提取中文 2-gram
        chinese_segments = re.findall(r'[\u4e00-\u9fff]+', text_lower)
        for seg in chinese_segments:
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i + 2])

        # 提取数字
        numbers = re.findall(r'\d+', text_lower)
        tokens.extend(numbers)

        return tokens

    def add_document(self, chunk_id: str, text: str, doc_id: str = ""):
        """添加文档到索引"""
        if chunk_id in self._docs:
            # 已存在，先移除再添加
            self.remove(chunk_id)

        tokens = self._tokenize(text)
        self._docs[chunk_id] = text
        self._doc_ids[chunk_id] = doc_id
        self._doc_lens[chunk_id] = len(tokens)

        # 统计词频
        tf_dict: Dict[str, int] = defaultdict(int)
        for token in tokens:
            tf_dict[token] += 1

        self._tf[chunk_id] = dict(tf_dict)

        # 更新文档频率
        for term in tf_dict:
            self._df[term] += 1

        self._total_docs += 1
        self._update_avgdl()

    def add_batch(self, items: List[Dict[str, Any]]):
        """批量添加文档"""
        for item in items:
            self.add_document(
                chunk_id=item["chunk_id"],
                text=item["text"],
                doc_id=item.get("doc_id", ""),
            )

    def remove(self, chunk_id: str):
        """移除文档"""
        if chunk_id not in self._docs:
            return

        # 从文档频率中减去
        tf_dict = self._tf.pop(chunk_id, {})
        for term in tf_dict:
            if term in self._df:
                self._df[term] -= 1
                if self._df[term] <= 0:
                    del self._df[term]

        self._docs.pop(chunk_id, None)
        self._doc_ids.pop(chunk_id, None)
        self._doc_lens.pop(chunk_id, None)

        self._total_docs -= 1
        self._update_avgdl()

    def _update_avgdl(self):
        """更新平均文档长度"""
        if self._total_docs == 0:
            self._avgdl = 0.0
            return
        self._avgdl = sum(self._doc_lens.values()) / self._total_docs

    def _idf(self, term: str) -> float:
        """计算 IDF"""
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        # BM25 IDF 公式
        return math.log(1 + (self._total_docs - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: Optional[int] = None) -> List[RetrievalResultItem]:
        """
        BM25 检索

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            检索结果列表（按 BM25 分数降序）
        """
        k = top_k or self.top_k

        if self._total_docs == 0:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores: Dict[str, float] = defaultdict(float)

        for term in query_tokens:
            idf = self._idf(term)
            if idf == 0:
                continue

            for doc_id, tf_dict in self._tf.items():
                tf = tf_dict.get(term, 0)
                if tf == 0:
                    continue

                dl = self._doc_lens.get(doc_id, 0)
                avgdl = self._avgdl or 1.0

                # BM25 核心公式
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / avgdl)
                scores[doc_id] += idf * numerator / denominator

        # 归一化分数到 0-1 区间
        if scores:
            max_score = max(scores.values())
            if max_score > 0:
                for doc_id in scores:
                    scores[doc_id] = scores[doc_id] / max_score

        results = []
        for chunk_id, score in scores.items():
            if score >= self.min_score:
                results.append(RetrievalResultItem(
                    chunk_id=chunk_id,
                    doc_id=self._doc_ids.get(chunk_id, ""),
                    text=self._docs.get(chunk_id, ""),
                    score=score,
                    sparse_score=score,
                    source="sparse",
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:k]

        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    @property
    def is_available(self) -> bool:
        """BM25 检索是否可用"""
        return self._total_docs > 0

    def clear(self):
        """清空索引"""
        self._docs.clear()
        self._doc_ids.clear()
        self._doc_lens.clear()
        self._df.clear()
        self._tf.clear()
        self._avgdl = 0.0
        self._total_docs = 0


# ============================================================
# 融合算法
# ============================================================

def weighted_fusion(dense_results: List[RetrievalResultItem],
                    sparse_results: List[RetrievalResultItem],
                    dense_weight: float = 0.7,
                    top_k: int = 10) -> List[RetrievalResultItem]:
    """
    加权融合 (Weighted Fusion)

    对向量检索和关键词检索的分数进行加权平均。
    分数需要先归一化到 0-1 区间。

    Args:
        dense_results: 向量检索结果
        sparse_results: 关键词检索结果
        dense_weight: 向量检索权重（0-1）
        top_k: 返回数量

    Returns:
        融合后的结果列表
    """
    sparse_weight = 1.0 - dense_weight

    # 建立结果映射
    result_map: Dict[str, RetrievalResultItem] = {}

    for r in dense_results:
        item = RetrievalResultItem(
            chunk_id=r.chunk_id,
            doc_id=r.doc_id,
            text=r.text,
            dense_score=r.score,
            sparse_score=0.0,
            score=r.score * dense_weight,
            source="hybrid",
            metadata=r.metadata.copy(),
        )
        result_map[r.chunk_id] = item

    for r in sparse_results:
        if r.chunk_id in result_map:
            item = result_map[r.chunk_id]
            item.sparse_score = r.score
            item.score += r.score * sparse_weight
        else:
            item = RetrievalResultItem(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                dense_score=0.0,
                sparse_score=r.score,
                score=r.score * sparse_weight,
                source="hybrid",
                metadata=r.metadata.copy(),
            )
            result_map[r.chunk_id] = item

    results = list(result_map.values())
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top_k]

    for i, r in enumerate(results):
        r.rank = i + 1

    return results


def rrf_fusion(dense_results: List[RetrievalResultItem],
               sparse_results: List[RetrievalResultItem],
               k: int = 60,
               top_k: int = 10) -> List[RetrievalResultItem]:
    """
    倒数排名融合 (Reciprocal Rank Fusion, RRF)

    公式：score(d) = sum(1 / (k + rank_i(d)))
    其中 rank_i(d) 是文档 d 在第 i 个排序列表中的排名。

    RRF 不需要归一化分数，对不同来源的排名直接融合，效果更稳定。

    Args:
        dense_results: 向量检索结果
        sparse_results: 关键词检索结果
        k: RRF 的 K 参数（通常取 60）
        top_k: 返回数量

    Returns:
        融合后的结果列表
    """
    rrf_scores: Dict[str, float] = defaultdict(float)
    result_info: Dict[str, RetrievalResultItem] = {}

    # 处理向量检索结果
    for r in dense_results:
        rank = r.rank or 0
        if rank > 0:
            rrf_scores[r.chunk_id] += 1.0 / (k + rank)
        if r.chunk_id not in result_info:
            result_info[r.chunk_id] = RetrievalResultItem(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                dense_score=r.score,
                sparse_score=0.0,
                source="hybrid",
                metadata=r.metadata.copy(),
            )
        else:
            result_info[r.chunk_id].dense_score = r.score

    # 处理关键词检索结果
    for r in sparse_results:
        rank = r.rank or 0
        if rank > 0:
            rrf_scores[r.chunk_id] += 1.0 / (k + rank)
        if r.chunk_id not in result_info:
            result_info[r.chunk_id] = RetrievalResultItem(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                dense_score=0.0,
                sparse_score=r.score,
                source="hybrid",
                metadata=r.metadata.copy(),
            )
        else:
            result_info[r.chunk_id].sparse_score = r.score

    # 归一化 RRF 分数到 0-1
    if rrf_scores:
        max_score = max(rrf_scores.values())
        if max_score > 0:
            for cid in rrf_scores:
                rrf_scores[cid] = rrf_scores[cid] / max_score

    # 构建结果列表
    results = []
    for chunk_id, score in rrf_scores.items():
        item = result_info[chunk_id]
        item.score = score
        results.append(item)

    results.sort(key=lambda r: r.score, reverse=True)
    results = results[:top_k]

    for i, r in enumerate(results):
        r.rank = i + 1

    return results


# ============================================================
# 重排序（Rerank）
# ============================================================

class Reranker:
    """
    重排序器

    实现轻量级交叉编码器风格的重排序。
    不依赖外部模型，基于多维度特征计算相关性分数。

    评分维度：
    1. 关键词匹配度（精确匹配、部分匹配）
    2. 词序相似度
    3. 文本覆盖度
    4. 关键词密度
    """

    def __init__(self, method: str = "hybrid"):
        """
        Args:
            method: 重排序方法（keyword / semantic / hybrid）
        """
        self.method = method

    def rerank(self,
               query: str,
               results: List[RetrievalResultItem],
               top_n: Optional[int] = None) -> List[RetrievalResultItem]:
        """
        对检索结果进行重排序

        Args:
            query: 查询文本
            results: 待重排的结果列表
            top_n: 返回前 N 个（None 则返回全部）

        Returns:
            重排序后的结果列表
        """
        if not results:
            return []

        # 计算每个结果的重排序分数
        reranked = []
        for r in results:
            rerank_score = self._compute_rerank_score(query, r.text)

            # 融合原始分数和重排序分数
            if self.method == "keyword":
                final_score = rerank_score
            elif self.method == "semantic":
                # 语义模式下保留原始向量分数
                final_score = r.score * 0.3 + rerank_score * 0.7
            else:  # hybrid
                final_score = r.score * 0.5 + rerank_score * 0.5

            new_item = RetrievalResultItem(
                chunk_id=r.chunk_id,
                doc_id=r.doc_id,
                text=r.text,
                score=final_score,
                source=r.source,
                dense_score=r.dense_score,
                sparse_score=r.sparse_score,
                metadata={**r.metadata, "rerank_score": rerank_score},
            )
            reranked.append(new_item)

        reranked.sort(key=lambda r: r.score, reverse=True)

        if top_n is not None:
            reranked = reranked[:top_n]

        for i, r in enumerate(reranked):
            r.rank = i + 1

        return reranked

    def _compute_rerank_score(self, query: str, text: str) -> float:
        """
        计算重排序分数（0-1）

        综合多维度特征：
        1. 精确短语匹配
        2. 关键词覆盖率
        3. 关键词密度
        4. 位置权重（出现在开头分数更高）
        5. 连续匹配
        """
        if not query or not text:
            return 0.0

        query_lower = query.lower().strip()
        text_lower = text.lower().strip()

        score = 0.0
        weights = {
            "exact_match": 0.30,
            "keyword_coverage": 0.30,
            "keyword_density": 0.15,
            "position": 0.15,
            "consecutive_match": 0.10,
        }

        # 1. 精确短语匹配
        if query_lower in text_lower:
            score += weights["exact_match"] * 1.0
        else:
            # 部分短语匹配
            query_words = query_lower.split()
            if len(query_words) >= 2:
                max_consecutive = self._max_consecutive_match(query_words, text_lower)
                score += weights["exact_match"] * (max_consecutive / len(query_words))

        # 2. 关键词覆盖率
        query_terms = self._extract_terms(query_lower)
        text_terms = set(self._extract_terms(text_lower))
        if query_terms:
            matched = sum(1 for t in query_terms if t in text_terms)
            coverage = matched / len(query_terms)
            score += weights["keyword_coverage"] * coverage

        # 3. 关键词密度
        if query_terms and len(text_lower) > 0:
            total_matches = sum(text_lower.count(t) for t in query_terms)
            density = min(1.0, total_matches / max(1, len(text_terms) if text_terms else 1))
            score += weights["keyword_density"] * density

        # 4. 位置权重
        first_pos = len(text_lower)
        for t in query_terms:
            pos = text_lower.find(t)
            if pos >= 0 and pos < first_pos:
                first_pos = pos
        if first_pos < len(text_lower):
            position_score = 1.0 - (first_pos / len(text_lower))
            score += weights["position"] * position_score

        # 5. 连续匹配（n-gram 重叠）
        n = min(4, len(query_lower))
        if n >= 2:
            query_ngrams = set()
            for i in range(len(query_lower) - n + 1):
                query_ngrams.add(query_lower[i:i + n])

            text_ngrams = set()
            for i in range(len(text_lower) - n + 1):
                text_ngrams.add(text_lower[i:i + n])

            if query_ngrams:
                overlap = len(query_ngrams & text_ngrams) / len(query_ngrams)
                score += weights["consecutive_match"] * overlap

        return min(1.0, max(0.0, score))

    def _extract_terms(self, text: str) -> List[str]:
        """提取关键词项"""
        terms = []

        # 英文单词
        english_words = re.findall(r'[a-zA-Z]{3,}', text)
        terms.extend(english_words)

        # 中文 2-gram
        chinese_segs = re.findall(r'[\u4e00-\u9fff]+', text)
        for seg in chinese_segs:
            if len(seg) >= 2:
                for i in range(len(seg) - 1):
                    terms.append(seg[i:i + 2])

        # 数字
        numbers = re.findall(r'\d+', text)
        terms.extend(numbers)

        return terms

    def _max_consecutive_match(self, query_words: List[str], text: str) -> int:
        """计算查询词在文本中的最大连续匹配数"""
        if not query_words:
            return 0

        max_count = 0
        for i in range(len(query_words)):
            count = 0
            pos = 0
            for j in range(i, len(query_words)):
                idx = text.find(query_words[j], pos)
                if idx >= 0:
                    count += 1
                    pos = idx + len(query_words[j])
                else:
                    break
            max_count = max(max_count, count)

        return max_count


# ============================================================
# 混合检索主类
# ============================================================

class HybridSearcher:
    """
    混合检索器（主入口类）

    整合向量检索、关键词检索、融合算法和重排序。
    提供统一的 search 接口。
    """

    def __init__(self,
                 embedding_fn: Optional[Callable[[str], Optional[List[float]]]] = None,
                 dense_top_k: int = 20,
                 sparse_top_k: int = 20,
                 final_top_k: int = 10,
                 enable_hybrid: bool = True,
                 hybrid_weight: float = 0.7,
                 fusion_method: str = "rrf",
                 rrf_k: int = 60,
                 enable_rerank: bool = True,
                 rerank_top_n: int = 20,
                 rerank_method: str = "hybrid",
                 min_score: float = 0.0):
        """
        Args:
            embedding_fn: 嵌入函数
            dense_top_k: 向量检索 Top K
            sparse_top_k: 关键词检索 Top K
            final_top_k: 最终返回 Top K
            enable_hybrid: 是否启用混合检索
            hybrid_weight: 向量检索权重（加权融合时使用）
            fusion_method: 融合方法（weighted / rrf）
            rrf_k: RRF 的 K 参数
            enable_rerank: 是否启用重排序
            rerank_top_n: 重排序候选数量
            rerank_method: 重排序方法
            min_score: 最低分数阈值
        """
        self.enable_hybrid = enable_hybrid
        self.hybrid_weight = hybrid_weight
        self.fusion_method = fusion_method
        self.rrf_k = rrf_k
        self.final_top_k = final_top_k
        self.enable_rerank = enable_rerank
        self.rerank_top_n = rerank_top_n
        self.min_score = min_score

        self.dense = DenseRetriever(
            embedding_fn=embedding_fn,
            top_k=dense_top_k,
            min_score=min_score,
        )
        self.sparse = BM25Retriever(top_k=sparse_top_k, min_score=0.0)
        self.reranker = Reranker(method=rerank_method)

    def add_document(self, chunk_id: str, text: str, doc_id: str = "",
                     embedding: Optional[List[float]] = None):
        """添加文档到所有索引"""
        self.dense.add_document(chunk_id, text, doc_id, embedding)
        self.sparse.add_document(chunk_id, text, doc_id)

    def add_batch(self, items: List[Dict[str, Any]]):
        """批量添加文档"""
        for item in items:
            self.add_document(
                chunk_id=item["chunk_id"],
                text=item["text"],
                doc_id=item.get("doc_id", ""),
                embedding=item.get("embedding"),
            )

    def remove(self, chunk_id: str):
        """从所有索引中移除文档"""
        self.dense.remove(chunk_id)
        self.sparse.remove(chunk_id)

    def search(self, query: str,
               top_k: Optional[int] = None,
               enable_hybrid: Optional[bool] = None,
               enable_rerank: Optional[bool] = None) -> List[RetrievalResultItem]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回数量（覆盖默认值）
            enable_hybrid: 是否启用混合（覆盖默认值）
            enable_rerank: 是否启用重排序（覆盖默认值）

        Returns:
            检索结果列表
        """
        k = top_k or self.final_top_k
        use_hybrid = enable_hybrid if enable_hybrid is not None else self.enable_hybrid
        use_rerank = enable_rerank if enable_rerank is not None else self.enable_rerank

        # 执行各通道检索
        dense_results = self.dense.search(query)
        sparse_results = self.sparse.search(query)

        # 融合
        if use_hybrid and dense_results and sparse_results:
            if self.fusion_method == "weighted":
                results = weighted_fusion(
                    dense_results, sparse_results,
                    dense_weight=self.hybrid_weight,
                    top_k=max(k, self.rerank_top_n if use_rerank else k),
                )
            else:  # rrf
                results = rrf_fusion(
                    dense_results, sparse_results,
                    k=self.rrf_k,
                    top_k=max(k, self.rerank_top_n if use_rerank else k),
                )
        elif dense_results:
            results = dense_results[:max(k, self.rerank_top_n if use_rerank else k)]
        elif sparse_results:
            results = sparse_results[:max(k, self.rerank_top_n if use_rerank else k)]
        else:
            return []

        # 重排序
        if use_rerank and results:
            results = self.reranker.rerank(query, results, top_n=k)
        else:
            results = results[:k]
            for i, r in enumerate(results):
                r.rank = i + 1

        # 过滤低分结果
        results = [r for r in results if r.score >= self.min_score]

        return results

    def search_debug(self, query: str) -> Dict[str, Any]:
        """
        调试模式检索（返回各阶段的详细信息）

        Returns:
            包含各阶段结果的字典
        """
        dense_results = self.dense.search(query)
        sparse_results = self.sparse.search(query)

        # 混合
        if self.enable_hybrid and dense_results and sparse_results:
            if self.fusion_method == "weighted":
                fused = weighted_fusion(
                    dense_results, sparse_results,
                    dense_weight=self.hybrid_weight,
                    top_k=self.rerank_top_n,
                )
            else:
                fused = rrf_fusion(
                    dense_results, sparse_results,
                    k=self.rrf_k,
                    top_k=self.rerank_top_n,
                )
        else:
            fused = dense_results or sparse_results

        # 重排序
        reranked = []
        if self.enable_rerank and fused:
            reranked = self.reranker.rerank(query, fused, top_n=self.final_top_k)

        return {
            "query": query,
            "dense_results": [r.to_dict() for r in dense_results[:10]],
            "sparse_results": [r.to_dict() for r in sparse_results[:10]],
            "fused_results": [r.to_dict() for r in fused[:10]],
            "reranked_results": [r.to_dict() for r in reranked],
            "stats": {
                "dense_count": len(dense_results),
                "sparse_count": len(sparse_results),
                "fused_count": len(fused),
                "reranked_count": len(reranked),
            },
        }

    def clear(self):
        """清空所有索引"""
        self.dense.clear()
        self.sparse.clear()
