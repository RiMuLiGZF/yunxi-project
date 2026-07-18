"""
检索后处理模块 (Post Processor)

实现检索结果的后处理能力：
1. 结果去重（基于内容相似度）
2. MMR 多样性排序（Maximal Marginal Relevance）
3. 上下文窗口扩展
4. 引用追溯（保留完整的文档来源信息）

纯 Python 实现，不依赖外部服务。
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from .hybrid_search import RetrievalResultItem, cosine_similarity


# ============================================================
# 1. 结果去重
# ============================================================

def _text_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度（基于 n-gram 重叠）

    使用 Jaccard 相似度 + 字符 n-gram。
    """
    if not text1 or not text2:
        return 0.0

    text1 = text1.lower()
    text2 = text2.lower()

    # 完全相同
    if text1 == text2:
        return 1.0

    # 使用 3-gram 计算相似度
    n = 3

    def get_ngrams(text: str) -> set:
        ngrams = set()
        for i in range(len(text) - n + 1):
            ngrams.add(text[i:i + n])
        return ngrams

    ngrams1 = get_ngrams(text1)
    ngrams2 = get_ngrams(text2)

    if not ngrams1 or not ngrams2:
        return 0.0

    # Jaccard 相似度
    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)

    return intersection / union if union > 0 else 0.0


def deduplicate_results(results: List[RetrievalResultItem],
                        threshold: float = 0.9) -> List[RetrievalResultItem]:
    """
    基于内容相似度去重

    保留分数较高的结果，移除相似度超过阈值的重复结果。

    Args:
        results: 检索结果列表
        threshold: 相似度阈值（0-1）

    Returns:
        去重后的结果列表
    """
    if len(results) <= 1:
        return results

    # 按分数降序排列
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)

    unique_results = []
    unique_texts = []

    for result in sorted_results:
        is_dup = False
        for ut in unique_texts:
            sim = _text_similarity(result.text, ut)
            if sim >= threshold:
                is_dup = True
                break

        if not is_dup:
            unique_results.append(result)
            unique_texts.append(result.text)

    # 更新排名
    for i, r in enumerate(unique_results):
        r.rank = i + 1

    return unique_results


# ============================================================
# 2. MMR 多样性排序
# ============================================================

def mmr_rerank(results: List[RetrievalResultItem],
               lambda_param: float = 0.5,
               top_k: Optional[int] = None,
               embedding_fn: Optional = None) -> List[RetrievalResultItem]:
    r"""
    MMR（Maximal Marginal Relevance）多样性排序

    在相关性和多样性之间取得平衡。

    公式：
    MMR = argmax_{d in R \ S} [ λ * Sim1(d, q) - (1 - λ) * max_{d_i in S} Sim2(d, d_i) ]

    其中：
    - Sim1(d, q) 是文档与查询的相关性（已有的 score）
    - Sim2(d, d_i) 是文档之间的相似度
    - λ 控制相关性和多样性的平衡（越大越看重相关性）

    Args:
        results: 检索结果列表
        lambda_param: MMR 平衡参数（0-1）
        top_k: 返回数量（None 则返回全部去重后结果）
        embedding_fn: 嵌入函数（用于计算文档相似度，不提供则使用文本相似度）

    Returns:
        MMR 重排序后的结果列表
    """
    if len(results) <= 1:
        return results

    k = top_k or len(results)
    k = min(k, len(results))

    # 按原始分数排序
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)

    # 已选择的结果
    selected: List[RetrievalResultItem] = []
    # 候选结果（用索引表示）
    remaining = list(range(len(sorted_results)))

    # 第一个直接选分数最高的
    if remaining:
        first_idx = remaining.pop(0)
        selected.append(sorted_results[first_idx])

    # 迭代选择
    while len(selected) < k and remaining:
        best_mmr_score = -float('inf')
        best_idx = -1

        for idx in remaining:
            candidate = sorted_results[idx]

            # 相关性分数（已归一化到 0-1）
            relevance = candidate.score

            # 与已选结果的最大相似度
            max_sim = 0.0
            for sel in selected:
                if embedding_fn:
                    # 使用向量相似度
                    emb1 = embedding_fn(candidate.text)
                    emb2 = embedding_fn(sel.text)
                    if emb1 and emb2:
                        sim = cosine_similarity(emb1, emb2)
                    else:
                        sim = _text_similarity(candidate.text, sel.text)
                else:
                    sim = _text_similarity(candidate.text, sel.text)
                max_sim = max(max_sim, sim)

            # MMR 分数
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_mmr_score:
                best_mmr_score = mmr_score
                best_idx = idx

        if best_idx >= 0:
            remaining.remove(best_idx)
            selected.append(sorted_results[best_idx])
        else:
            break

    # 更新排名和分数（保留原始 score，在 metadata 中记录 mmr 相关信息）
    for i, r in enumerate(selected):
        r.rank = i + 1
        r.metadata["mmr_rank"] = i + 1

    return selected


# ============================================================
# 3. 上下文窗口扩展
# ============================================================

@dataclass
class ChunkWithContext:
    """带上下文的 chunk"""
    chunk_id: str
    text: str
    expanded_text: str
    doc_id: str
    score: float
    rank: int
    context_before: str = ""
    context_after: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "expanded_text": self.expanded_text,
            "doc_id": self.doc_id,
            "score": self.score,
            "rank": self.rank,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "metadata": self.metadata,
        }


def expand_context_window(results: List[RetrievalResultItem],
                          all_chunks: Dict[str, List[Dict[str, Any]]],
                          chars_before: int = 100,
                          chars_after: int = 100) -> List[ChunkWithContext]:
    """
    上下文窗口扩展

    检索到 chunk 后，自动扩展前后文，提供更完整的上下文。

    Args:
        results: 检索结果列表
        all_chunks: 所有 chunk 的数据，格式为 {doc_id: [{chunk_id, text, chunk_index, ...}, ...]}
        chars_before: 向前扩展字符数
        chars_after: 向后扩展字符数

    Returns:
        带上下文的结果列表
    """
    expanded_results = []

    # 建立 chunk_id -> chunk_info 的映射
    chunk_map: Dict[str, Dict[str, Any]] = {}
    doc_chunk_lists: Dict[str, List[Dict[str, Any]]] = {}

    for doc_id, chunks in all_chunks.items():
        # 按 chunk_index 排序
        sorted_chunks = sorted(chunks, key=lambda c: c.get("chunk_index", 0))
        doc_chunk_lists[doc_id] = sorted_chunks
        for c in sorted_chunks:
            chunk_map[c["chunk_id"]] = c

    for result in results:
        chunk_info = chunk_map.get(result.chunk_id, {})
        doc_id = result.doc_id
        chunk_index = chunk_info.get("chunk_index", 0)
        doc_chunks = doc_chunk_lists.get(doc_id, [])

        context_before = ""
        context_after = ""

        # 向前扩展：从前面的 chunk 中取尾部
        chars_needed_before = chars_before
        prev_idx = chunk_index - 1
        while chars_needed_before > 0 and prev_idx >= 0 and prev_idx < len(doc_chunks):
            prev_chunk = doc_chunks[prev_idx]
            prev_text = prev_chunk.get("text", "")
            if prev_text:
                # 取尾部
                take = min(chars_needed_before, len(prev_text))
                context_before = prev_text[-take:] + context_before
                chars_needed_before -= take
            prev_idx -= 1

        # 向后扩展：从后面的 chunk 中取头部
        chars_needed_after = chars_after
        next_idx = chunk_index + 1
        while chars_needed_after > 0 and next_idx < len(doc_chunks):
            next_chunk = doc_chunks[next_idx]
            next_text = next_chunk.get("text", "")
            if next_text:
                # 取头部
                take = min(chars_needed_after, len(next_text))
                context_after += next_text[:take]
                chars_needed_after -= take
            next_idx += 1

        # 组装扩展后的文本
        expanded_text = result.text
        if context_before:
            expanded_text = context_before + expanded_text
        if context_after:
            expanded_text = expanded_text + context_after

        expanded_results.append(ChunkWithContext(
            chunk_id=result.chunk_id,
            text=result.text,
            expanded_text=expanded_text,
            doc_id=doc_id,
            score=result.score,
            rank=result.rank,
            context_before=context_before,
            context_after=context_after,
            metadata={
                **result.metadata,
                "original_length": len(result.text),
                "expanded_length": len(expanded_text),
                "context_before_chars": len(context_before),
                "context_after_chars": len(context_after),
            },
        ))

    return expanded_results


# ============================================================
# 4. 引用追溯
# ============================================================

@dataclass
class CitationInfo:
    """引用信息"""
    chunk_id: str
    doc_id: str
    doc_title: str
    source: str
    section_path: str
    page_number: Optional[int] = None
    confidence: float = 0.0
    text_snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "source": self.source,
            "section_path": self.section_path,
            "page_number": self.page_number,
            "confidence": round(self.confidence, 4),
            "text_snippet": self.text_snippet,
        }


def build_citations(results: List[RetrievalResultItem],
                    documents: Dict[str, Any],
                    max_snippet_length: int = 200) -> List[CitationInfo]:
    """
    构建引用信息列表

    从检索结果中提取完整的文档来源信息，用于答案引用标注。

    Args:
        results: 检索结果列表
        documents: 文档信息字典 {doc_id: {title, source, ...}}
        max_snippet_length: 引用片段最大长度

    Returns:
        引用信息列表
    """
    citations = []

    for result in results:
        doc_info = documents.get(result.doc_id, {})
        text_snippet = result.text[:max_snippet_length]
        if len(result.text) > max_snippet_length:
            text_snippet += "..."

        citation = CitationInfo(
            chunk_id=result.chunk_id,
            doc_id=result.doc_id,
            doc_title=doc_info.get("title", "未知文档"),
            source=doc_info.get("source", ""),
            section_path=result.metadata.get("section_path", ""),
            page_number=result.metadata.get("page_number"),
            confidence=result.score,
            text_snippet=text_snippet,
        )
        citations.append(citation)

    return citations


def format_citations_markdown(citations: List[CitationInfo]) -> str:
    """
    将引用信息格式化为 Markdown 文本

    Args:
        citations: 引用信息列表

    Returns:
        Markdown 格式的引用列表
    """
    if not citations:
        return ""

    lines = ["**参考资料：**", ""]
    for i, cit in enumerate(citations, 1):
        title = cit.doc_title or "未知文档"
        source_info = f"（来源：{cit.source}）" if cit.source else ""
        section = f" - {cit.section_path}" if cit.section_path else ""

        lines.append(f"{i}. **{title}**{section}{source_info}")
        if cit.text_snippet:
            lines.append(f"   > {cit.text_snippet}")
        lines.append("")

    return "\n".join(lines)


# ============================================================
# 后处理主类
# ============================================================

class PostProcessor:
    """
    检索后处理器（主入口类）

    整合去重、MMR、上下文扩展、引用追溯等后处理能力。
    """

    def __init__(self,
                 enable_dedup: bool = True,
                 dedup_threshold: float = 0.9,
                 enable_mmr: bool = False,
                 mmr_lambda: float = 0.5,
                 enable_context_expansion: bool = True,
                 context_chars_before: int = 100,
                 context_chars_after: int = 100):
        """
        Args:
            enable_dedup: 是否启用去重
            dedup_threshold: 去重相似度阈值
            enable_mmr: 是否启用 MMR 多样性排序
            mmr_lambda: MMR 平衡参数
            enable_context_expansion: 是否启用上下文扩展
            context_chars_before: 向前扩展字符数
            context_chars_after: 向后扩展字符数
        """
        self.enable_dedup = enable_dedup
        self.dedup_threshold = dedup_threshold
        self.enable_mmr = enable_mmr
        self.mmr_lambda = mmr_lambda
        self.enable_context_expansion = enable_context_expansion
        self.context_chars_before = context_chars_before
        self.context_chars_after = context_chars_after

    def process(self,
                results: List[RetrievalResultItem],
                all_chunks: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                documents: Optional[Dict[str, Any]] = None,
                top_k: Optional[int] = None,
                embedding_fn=None) -> Dict[str, Any]:
        """
        执行完整的后处理流程

        Args:
            results: 原始检索结果
            all_chunks: 所有 chunk 数据（用于上下文扩展）
            documents: 文档信息（用于引用追溯）
            top_k: 最终返回数量
            embedding_fn: 嵌入函数（用于 MMR 计算）

        Returns:
            处理结果字典，包含：
            - results: 处理后的结果列表
            - expanded: 带上下文的结果（如果启用了上下文扩展）
            - citations: 引用信息列表
            - stats: 处理统计
        """
        stats = {
            "input_count": len(results),
            "dedup_count": 0,
            "mmr_applied": False,
            "context_expanded": False,
        }

        processed = results

        # 1. 去重
        if self.enable_dedup:
            before = len(processed)
            processed = deduplicate_results(processed, self.dedup_threshold)
            stats["dedup_count"] = before - len(processed)

        # 2. MMR 多样性排序
        if self.enable_mmr and len(processed) > 1:
            processed = mmr_rerank(
                processed,
                lambda_param=self.mmr_lambda,
                top_k=top_k,
                embedding_fn=embedding_fn,
            )
            stats["mmr_applied"] = True

        # 3. 限制数量
        if top_k:
            processed = processed[:top_k]

        # 4. 上下文窗口扩展
        expanded = []
        if self.enable_context_expansion and all_chunks:
            expanded = expand_context_window(
                processed,
                all_chunks,
                chars_before=self.context_chars_before,
                chars_after=self.context_chars_after,
            )
            stats["context_expanded"] = True
            stats["output_count"] = len(expanded)
        else:
            stats["output_count"] = len(processed)

        # 5. 引用追溯
        citations = []
        if documents:
            citations = build_citations(processed, documents)

        return {
            "results": processed,
            "expanded_results": expanded,
            "citations": citations,
            "stats": stats,
        }
