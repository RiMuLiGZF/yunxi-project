"""
shared.semantic - 轻量级语义匹配工具包
======================================

为 M2 技能集群和 M4 场景引擎提供统一的语义匹配能力。

核心组件：
- EmbeddingProvider: 向量嵌入提供者抽象基类
- FallbackKeywordProvider: 纯关键词兜底实现（无 sentence-transformers 时使用）
- SentenceTransformerProvider: 基于 sentence-transformers 的嵌入实现（可选）
- VectorIndex: 基于 numpy + cosine similarity 的轻量向量索引

设计原则：
- 可选依赖：sentence-transformers 为可选依赖，缺失时自动降级
- 向后兼容：语义匹配作为关键词匹配的补充，不替换现有机制
- 性能优先：使用 numpy 实现向量运算，足够轻量
- 测试友好：所有测试用 fallback 就能通过
"""

from .embedding_base import (
    EmbeddingProvider,
    EmbeddingResult,
    get_default_provider,
    has_sentence_transformers,
)
from .vector_index import VectorIndex, SearchResult
from .fallback import FallbackKeywordProvider

__all__ = [
    "EmbeddingProvider",
    "EmbeddingResult",
    "FallbackKeywordProvider",
    "VectorIndex",
    "SearchResult",
    "get_default_provider",
    "has_sentence_transformers",
]

__version__ = "1.0.0"
