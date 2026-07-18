"""
RAG 检索增强配置模块

提供完整的 RAG 相关配置项，支持动态更新。
所有配置均有合理默认值，确保默认行为与现有系统一致。
"""

from __future__ import annotations

import os
import threading
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any


class ChunkingStrategyType(str, Enum):
    """分块策略类型"""
    FIXED = "fixed"           # 固定大小分块
    SEMANTIC = "semantic"     # 语义分块
    STRUCTURED = "structured"  # 结构化分块
    RECURSIVE = "recursive"   # 递归分块


class RewriteStrategyType(str, Enum):
    """查询改写策略类型"""
    EXPANSION = "expansion"       # 查询扩展
    DECOMPOSITION = "decomposition"  # 查询分解
    CONVERSATIONAL = "conversational"  # 多轮改写
    HYDE = "hyde"                 # 假设性文档生成


class FusionMethod(str, Enum):
    """混合检索融合方法"""
    WEIGHTED = "weighted"      # 加权融合
    RRF = "rrf"                # 倒数排名融合


@dataclass
class RAGConfig:
    """
    RAG 检索增强完整配置

    默认值设计原则：
    - 保持与现有 RAGKnowledgeBase 行为一致
    - 高级功能默认关闭，按需开启
    - 所有参数均可动态调整
    """

    # ---------- 分块配置 ----------
    default_chunk_size: int = 512
    """默认分块大小（字符数）"""

    default_chunk_overlap: int = 50
    """默认重叠大小（字符数）"""

    chunking_strategy: str = ChunkingStrategyType.FIXED.value
    """分块策略：fixed/semantic/structured/recursive"""

    chunk_by_tokens: bool = False
    """是否按 token 数分块（否则按字符数）"""

    min_chunk_size: int = 50
    """最小分块大小（小于此值的块会被合并）"""

    # ---------- 检索配置 ----------
    retrieval_top_k: int = 10
    """检索返回的 Top K 结果数"""

    min_similarity_score: float = 0.3
    """最低相似度阈值"""

    # ---------- 混合检索 ----------
    enable_hybrid_search: bool = True
    """是否启用混合检索"""

    hybrid_search_weight: float = 0.7
    """向量检索权重（关键词检索权重为 1 - weight）"""

    fusion_method: str = FusionMethod.RRF.value
    """融合方法：weighted / rrf"""

    rrf_k: int = 60
    """RRF 算法的 K 参数"""

    sparse_top_k: int = 20
    """关键词检索 Top K"""

    dense_top_k: int = 20
    """向量检索 Top K"""

    # ---------- 重排序 ----------
    enable_rerank: bool = True
    """是否启用重排序"""

    rerank_top_n: int = 20
    """重排序的候选数量（从检索结果中取前 N 个重排）"""

    rerank_method: str = "keyword"
    """重排序方法：keyword（关键词匹配度）/ semantic（语义相似度）/ hybrid"""

    # ---------- 查询改写 ----------
    enable_query_rewrite: bool = False
    """是否启用查询改写（默认关闭）"""

    rewrite_strategy: str = RewriteStrategyType.EXPANSION.value
    """查询改写策略"""

    max_rewrite_queries: int = 3
    """最多生成的改写查询数量"""

    # ---------- MMR 多样性 ----------
    enable_mmr: bool = False
    """是否启用 MMR 多样性排序（默认关闭）"""

    mmr_lambda: float = 0.5
    """MMR 平衡参数（0-1，越大越看重相关性，越小越看重多样性）"""

    # ---------- 上下文窗口扩展 ----------
    context_window_expansion: bool = True
    """是否启用上下文窗口扩展"""

    expansion_chars_before: int = 100
    """向前扩展字符数"""

    expansion_chars_after: int = 100
    """向后扩展字符数"""

    # ---------- 结果去重 ----------
    enable_dedup: bool = True
    """是否启用结果去重"""

    dedup_threshold: float = 0.9
    """去重相似度阈值（高于此值视为重复）"""

    # ---------- 嵌入模型 ----------
    embedding_model: str = "nomic-embed-text"
    """嵌入模型名称"""

    embedding_dim: int = 768
    """嵌入向量维度"""

    # ---------- 内部状态 ----------
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """导出配置字典（排除内部字段）"""
        # 手动构建字典，避免 asdict  deepcopy RLock 对象的问题
        d = {}
        for f in RAGConfig.__dataclass_fields__:
            if f.startswith("_"):
                continue
            d[f] = getattr(self, f)
        return d

    def update(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        批量更新配置（动态生效）

        Args:
            updates: 配置更新字典

        Returns:
            实际更新的配置项（键为旧值，值为新值）

        Raises:
            ValueError: 配置项不存在或值非法
        """
        changed = {}
        valid_fields = {f.name for f in RAGConfig.__dataclass_fields__.values()}

        with self._lock:
            for key, value in updates.items():
                if key.startswith("_"):
                    continue
                if key not in valid_fields:
                    raise ValueError(f"未知配置项: {key}")

                old_value = getattr(self, key)
                # 类型转换和校验
                try:
                    if isinstance(old_value, bool):
                        value = bool(value) if not isinstance(value, bool) else value
                    elif isinstance(old_value, int):
                        value = int(value)
                    elif isinstance(old_value, float):
                        value = float(value)
                    elif isinstance(old_value, str):
                        value = str(value)
                except (TypeError, ValueError):
                    raise ValueError(f"配置项 {key} 的值非法: {value}")

                # 范围校验
                if key in ("default_chunk_size", "retrieval_top_k", "rerank_top_n",
                           "sparse_top_k", "dense_top_k", "max_rewrite_queries",
                           "expansion_chars_before", "expansion_chars_after"):
                    if value <= 0:
                        raise ValueError(f"{key} 必须大于 0")

                if key in ("default_chunk_overlap", "min_chunk_size"):
                    if value < 0:
                        raise ValueError(f"{key} 不能为负数")

                if key in ("mmr_lambda", "hybrid_search_weight", "dedup_threshold",
                           "min_similarity_score"):
                    if not (0 <= value <= 1):
                        raise ValueError(f"{key} 必须在 0-1 之间")

                if key == "chunking_strategy":
                    valid = [s.value for s in ChunkingStrategyType]
                    if value not in valid:
                        raise ValueError(f"chunking_strategy 必须是 {valid} 之一")

                if key == "fusion_method":
                    valid = [m.value for m in FusionMethod]
                    if value not in valid:
                        raise ValueError(f"fusion_method 必须是 {valid} 之一")

                if old_value != value:
                    setattr(self, key, value)
                    changed[key] = {"old": old_value, "new": value}

        return changed

    def get(self, key: str, default: Any = None) -> Any:
        """获取单个配置项"""
        with self._lock:
            return getattr(self, key, default)


# 全局配置单例
_config_instance: Optional[RAGConfig] = None
_config_lock = threading.Lock()


def get_rag_config() -> RAGConfig:
    """
    获取 RAG 配置单例

    配置加载优先级：
    1. 环境变量（RAG_ 前缀）
    2. 默认值
    """
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = _load_config_from_env()
    return _config_instance


def _load_config_from_env() -> RAGConfig:
    """从环境变量加载配置"""
    config = RAGConfig()

    env_mapping = {
        "RAG_CHUNK_SIZE": ("default_chunk_size", int),
        "RAG_CHUNK_OVERLAP": ("default_chunk_overlap", int),
        "RAG_CHUNKING_STRATEGY": ("chunking_strategy", str),
        "RAG_CHUNK_BY_TOKENS": ("chunk_by_tokens", lambda v: v.lower() == "true"),
        "RAG_RETRIEVAL_TOP_K": ("retrieval_top_k", int),
        "RAG_MIN_SIMILARITY": ("min_similarity_score", float),
        "RAG_ENABLE_HYBRID": ("enable_hybrid_search", lambda v: v.lower() == "true"),
        "RAG_HYBRID_WEIGHT": ("hybrid_search_weight", float),
        "RAG_FUSION_METHOD": ("fusion_method", str),
        "RAG_RRF_K": ("rrf_k", int),
        "RAG_SPARSE_TOP_K": ("sparse_top_k", int),
        "RAG_DENSE_TOP_K": ("dense_top_k", int),
        "RAG_ENABLE_RERANK": ("enable_rerank", lambda v: v.lower() == "true"),
        "RAG_RERANK_TOP_N": ("rerank_top_n", int),
        "RAG_RERANK_METHOD": ("rerank_method", str),
        "RAG_ENABLE_QUERY_REWRITE": ("enable_query_rewrite", lambda v: v.lower() == "true"),
        "RAG_REWRITE_STRATEGY": ("rewrite_strategy", str),
        "RAG_MAX_REWRITE_QUERIES": ("max_rewrite_queries", int),
        "RAG_ENABLE_MMR": ("enable_mmr", lambda v: v.lower() == "true"),
        "RAG_MMR_LAMBDA": ("mmr_lambda", float),
        "RAG_CONTEXT_EXPANSION": ("context_window_expansion", lambda v: v.lower() == "true"),
        "RAG_EXPANSION_BEFORE": ("expansion_chars_before", int),
        "RAG_EXPANSION_AFTER": ("expansion_chars_after", int),
        "RAG_ENABLE_DEDUP": ("enable_dedup", lambda v: v.lower() == "true"),
        "RAG_DEDUP_THRESHOLD": ("dedup_threshold", float),
        "RAG_EMBEDDING_MODEL": ("embedding_model", str),
        "RAG_EMBEDDING_DIM": ("embedding_dim", int),
    }

    for env_key, (attr, converter) in env_mapping.items():
        env_val = os.environ.get(env_key)
        if env_val is not None:
            try:
                setattr(config, attr, converter(env_val))
            except (ValueError, TypeError):
                # 环境变量格式错误时忽略，使用默认值
                pass

    return config


def reset_rag_config() -> None:
    """重置配置单例（测试用）"""
    global _config_instance
    with _config_lock:
        _config_instance = None
