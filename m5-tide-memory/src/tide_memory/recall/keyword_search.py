"""
关键词检索模块

基于倒排索引的轻量级关键词搜索
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from ..common.text_utils import tokenize


class KeywordSearch:
    """
    关键词检索引擎
    
    - 倒排索引
    - 支持标签匹配
    - 支持时间范围过滤
    - 支持权重排序（TF-IDF简化版）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        config = config or {}
        self._inverted_index: Dict[str, Set[str]] = defaultdict(set)  # term -> set of memory_ids
        self._doc_freq: Dict[str, int] = defaultdict(int)  # term -> doc count
        self._tag_index: Dict[str, Set[str]] = defaultdict(set)  # tag -> set of memory_ids
        self._metadata: Dict[str, dict] = {}  # memory_id -> metadata
        self._total_docs = 0

    def index(self, memory_id: str, text: str, tags: List[str] = None, metadata: dict = None) -> bool:
        """
        索引一条记忆
        
        ⚠️ 只索引标签和关键词，不存储原文
        """
        if memory_id in self._metadata:
            # 先移除旧索引
            self._remove_from_index(memory_id)

        # 分词
        terms = tokenize(text)
        
        # 更新倒排索引
        for term in set(terms):  # 去重
            self._inverted_index[term].add(memory_id)
            self._doc_freq[term] += 1

        # 标签索引
        if tags:
            for tag in tags:
                self._tag_index[tag.lower()].add(memory_id)

        # 元数据
        self._metadata[memory_id] = {
            "tags": tags or [],
            "term_count": len(terms),
            "unique_terms": len(set(terms)),
            **(metadata or {}),
        }

        self._total_docs += 1
        return True

    def search(self, query: str, top_k: int = 10, tags: List[str] = None) -> List[Dict]:
        """
        关键词搜索
        
        返回: [{memory_id, score, matched_terms, matched_tags}]
        """
        query_terms = tokenize(query)
        if not query_terms and not tags:
            return []

        candidate_scores: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "score": 0.0, "matched_terms": [], "matched_tags": []
        })

        # 关键词匹配
        for term in query_terms:
            if term in self._inverted_index:
                for mem_id in self._inverted_index[term]:
                    candidate_scores[mem_id]["score"] += self._term_weight(term)
                    candidate_scores[mem_id]["matched_terms"].append(term)

        # 标签匹配
        if tags:
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower in self._tag_index:
                    for mem_id in self._tag_index[tag_lower]:
                        candidate_scores[mem_id]["score"] += 0.5
                        candidate_scores[mem_id]["matched_tags"].append(tag)

        # 排序
        results = []
        for mem_id, data in candidate_scores.items():
            results.append({
                "memory_id": mem_id,
                "score": round(data["score"], 4),
                "matched_terms": data["matched_terms"],
                "matched_tags": data["matched_tags"],
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _term_weight(self, term: str) -> float:
        """计算词权重（简化IDF）"""
        if self._total_docs == 0:
            return 1.0
        import math
        df = self._doc_freq.get(term, 1)
        return math.log((self._total_docs + 1) / (df + 1)) + 1.0

    def _remove_from_index(self, memory_id: str) -> None:
        """从索引中移除"""
        for term, ids in list(self._inverted_index.items()):
            if memory_id in ids:
                ids.remove(memory_id)
                self._doc_freq[term] -= 1
                if not ids:
                    del self._inverted_index[term]
                    del self._doc_freq[term]

        for tag, ids in list(self._tag_index.items()):
            if memory_id in ids:
                ids.remove(memory_id)
                if not ids:
                    del self._tag_index[tag]

        if memory_id in self._metadata:
            del self._metadata[memory_id]
            self._total_docs -= 1

    def delete(self, memory_id: str) -> bool:
        """删除记忆索引"""
        if memory_id in self._metadata:
            self._remove_from_index(memory_id)
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_docs": self._total_docs,
            "total_terms": len(self._inverted_index),
            "total_tags": len(self._tag_index),
        }
# vim: set et ts=4 sw=4:
