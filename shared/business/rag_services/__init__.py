"""
RAG 检索增强服务包 (P3 级优化)

提供完整的 RAG 检索增强能力：
- 多种分块策略（fixed/semantic/structured/recursive）
- 混合检索（向量 + 关键词 + RRF 融合）
- 重排序（Cross-Encoder 风格评分）
- 查询改写（扩展/分解/多轮/HyDE）
- 检索后处理（去重/MMR/上下文扩展/引用追溯）

所有模块均为纯 Python 实现，不依赖外部服务，
在向量模型不可用时自动降级，确保向后兼容。
"""

from .config import RAGConfig, get_rag_config
from .chunker import (
    ChunkingStrategy,
    BaseChunker,
    FixedSizeChunker,
    SemanticChunker,
    StructuredChunker,
    RecursiveChunker,
    ChunkMetadata,
    create_chunker,
)
from .hybrid_search import (
    HybridSearcher,
    RetrievalResultItem,
    rrf_fusion,
    weighted_fusion,
)
from .query_rewriter import (
    QueryRewriter,
    RewriteStrategy,
)
from .post_processor import (
    PostProcessor,
    deduplicate_results,
    mmr_rerank,
    expand_context_window,
)

__version__ = "1.0.0"

__all__ = [
    # 配置
    "RAGConfig",
    "get_rag_config",
    # 分块
    "ChunkingStrategy",
    "BaseChunker",
    "FixedSizeChunker",
    "SemanticChunker",
    "StructuredChunker",
    "RecursiveChunker",
    "ChunkMetadata",
    "create_chunker",
    # 混合检索
    "HybridSearcher",
    "RetrievalResultItem",
    "rrf_fusion",
    "weighted_fusion",
    # 查询改写
    "QueryRewriter",
    "RewriteStrategy",
    # 后处理
    "PostProcessor",
    "deduplicate_results",
    "mmr_rerank",
    "expand_context_window",
]
