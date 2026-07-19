"""Embedding 提供者抽象基类.

定义统一的文本嵌入接口，支持多种后端实现：
- SentenceTransformerProvider: 使用 sentence-transformers（可选依赖）
- FallbackKeywordProvider: 纯关键词 TF-IDF 风格向量（兜底实现）

自动检测可用的 embedding 后端，优雅降级。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 全局标志：是否安装了 sentence-transformers
_has_sentence_transformers: bool | None = None


def has_sentence_transformers() -> bool:
    """检测是否安装了 sentence-transformers.

    Returns:
        True 表示已安装且可用
    """
    global _has_sentence_transformers
    if _has_sentence_transformers is not None:
        return _has_sentence_transformers

    try:
        import sentence_transformers  # noqa: F401

        _has_sentence_transformers = True
        logger.info("semantic.embedding.sentence_transformers_available")
    except ImportError:
        _has_sentence_transformers = False
        logger.info("semantic.embedding.sentence_transformers_not_available_using_fallback")

    return _has_sentence_transformers


@dataclass
class EmbeddingResult:
    """嵌入结果."""

    vector: list[float]
    dimension: int
    provider: str
    normalized: bool = False

    def __len__(self) -> int:
        return len(self.vector)


class EmbeddingProvider(ABC):
    """Embedding 提供者抽象基类.

    所有 embedding 后端都需要实现此接口，
    保证上层调用（VectorIndex、SemanticRouter 等）与具体实现解耦。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """提供者名称."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """嵌入向量维度."""
        ...

    @abstractmethod
    def embed(self, text: str) -> EmbeddingResult:
        """将单个文本转换为向量.

        Args:
            text: 输入文本

        Returns:
            EmbeddingResult 嵌入结果
        """
        ...

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """批量嵌入文本.

        默认实现逐次调用 embed()，子类可覆盖以优化批量性能。

        Args:
            texts: 输入文本列表

        Returns:
            嵌入结果列表，顺序与输入一致
        """
        return [self.embed(text) for text in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入，仅返回向量列表（便捷方法）.

        Args:
            texts: 输入文本列表

        Returns:
            向量列表
        """
        results = self.embed_batch(texts)
        return [r.vector for r in results]

    def similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """计算两个向量的余弦相似度.

        Args:
            vec_a: 向量 A
            vec_b: 向量 B

        Returns:
            余弦相似度 (0-1)
        """
        import math

        if len(vec_a) != len(vec_b):
            raise ValueError(
                f"向量维度不匹配: {len(vec_a)} vs {len(vec_b)}"
            )

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return max(0.0, min(1.0, dot_product / (norm_a * norm_b)))


# ============================================================================
# SentenceTransformer 实现（可选依赖）
# ============================================================================

class SentenceTransformerProvider(EmbeddingProvider):
    """基于 sentence-transformers 的嵌入提供者.

    这是高质量的语义嵌入实现，但需要额外安装依赖：
        pip install sentence-transformers

    当 sentence-transformers 不可用时，会抛出 ImportError。
    建议使用 get_default_provider() 自动检测并降级。
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
    ) -> None:
        """初始化 SentenceTransformer 提供者.

        Args:
            model_name: 模型名称
            device: 运行设备 (cpu/cuda)

        Raises:
            ImportError: sentence-transformers 未安装
        """
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            raise ImportError(
                "sentence-transformers 未安装。"
                "请运行: pip install sentence-transformers"
            ) from e

        self._model_name = model_name
        self._device = device
        self._model = SentenceTransformer(model_name, device=device)
        self._dimension: int = self._model.get_sentence_embedding_dimension() or 384

    @property
    def name(self) -> str:
        return f"sentence_transformers:{self._model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> EmbeddingResult:
        vector = self._model.encode(text, normalize_embeddings=True).tolist()
        return EmbeddingResult(
            vector=vector,
            dimension=self._dimension,
            provider=self.name,
            normalized=True,
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        vectors = self._model.encode(texts, normalize_embeddings=True).tolist()
        return [
            EmbeddingResult(
                vector=v,
                dimension=self._dimension,
                provider=self.name,
                normalized=True,
            )
            for v in vectors
        ]


# ============================================================================
# 默认提供者工厂函数
# ============================================================================

_default_provider: EmbeddingProvider | None = None


def get_default_provider() -> EmbeddingProvider:
    """获取默认的 embedding 提供者.

    自动检测可用的后端：
    1. 优先使用 sentence-transformers（如果已安装）
    2. 否则降级到 FallbackKeywordProvider

    结果会被缓存，多次调用返回同一实例。

    Returns:
        EmbeddingProvider 实例
    """
    global _default_provider
    if _default_provider is not None:
        return _default_provider

    if has_sentence_transformers():
        try:
            _default_provider = SentenceTransformerProvider()
            return _default_provider
        except Exception as e:
            logger.warning(
                "semantic.embedding.sentence_transformers_init_failed",
                error=str(e),
            )

    # 兜底：使用关键词 TF-IDF 风格实现
    from .fallback import FallbackKeywordProvider

    _default_provider = FallbackKeywordProvider()
    return _default_provider


def reset_default_provider() -> None:
    """重置默认提供者（主要用于测试）."""
    global _default_provider
    _default_provider = None
