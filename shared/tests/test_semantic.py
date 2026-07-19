"""shared.semantic 模块单元测试.

覆盖：
- 向量索引基本操作（add/search/delete）
- cosine similarity 正确性
- fallback 关键词匹配
- 边界情况（空索引、空查询等）
- EmbeddingProvider 抽象基类
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# 确保项目根目录在 path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared.semantic import (
    EmbeddingProvider,
    EmbeddingResult,
    FallbackKeywordProvider,
    VectorIndex,
    SearchResult,
    has_sentence_transformers,
)


# ============================================================================
# FallbackKeywordProvider 测试
# ============================================================================

class TestFallbackKeywordProvider:
    """Fallback 关键词 Embedding 提供者测试."""

    def test_provider_name(self) -> None:
        """提供者名称应包含 fallback_keyword."""
        provider = FallbackKeywordProvider(dimension=128)
        assert "fallback" in provider.name.lower()
        assert "128" in provider.name

    def test_dimension(self) -> None:
        """维度应正确设置."""
        provider = FallbackKeywordProvider(dimension=256)
        assert provider.dimension == 256

    def test_embed_empty_text(self) -> None:
        """空文本应返回零向量."""
        provider = FallbackKeywordProvider(dimension=64)
        result = provider.embed("")
        assert isinstance(result, EmbeddingResult)
        assert result.dimension == 64
        assert len(result.vector) == 64
        assert all(v == 0.0 for v in result.vector)

    def test_embed_whitespace_text(self) -> None:
        """空白文本应返回零向量."""
        provider = FallbackKeywordProvider(dimension=64)
        result = provider.embed("   \n\t  ")
        assert all(v == 0.0 for v in result.vector)

    def test_embed_returns_normalized_vector(self) -> None:
        """返回的向量应是 L2 归一化的."""
        provider = FallbackKeywordProvider(dimension=128)
        result = provider.embed("hello world")
        norm = math.sqrt(sum(v * v for v in result.vector))
        assert abs(norm - 1.0) < 0.01

    def test_embed_batch(self) -> None:
        """批量嵌入应返回相同数量的结果."""
        provider = FallbackKeywordProvider(dimension=64)
        texts = ["hello", "world", "test"]
        results = provider.embed_batch(texts)
        assert len(results) == 3
        for r in results:
            assert r.dimension == 64
            assert len(r.vector) == 64

    def test_similar_texts_higher_similarity(self) -> None:
        """相似文本的相似度应高于不相似文本."""
        provider = FallbackKeywordProvider(dimension=256)
        v1 = provider.embed("python programming language").vector
        v2 = provider.embed("python coding tutorial").vector
        v3 = provider.embed("cooking recipe food").vector

        sim_same = provider.similarity(v1, v2)
        sim_diff = provider.similarity(v1, v3)

        # 相似文本的相似度应更高
        assert sim_same > sim_diff

    def test_keyword_match_score(self) -> None:
        """关键词匹配得分应在 0-1 范围内."""
        provider = FallbackKeywordProvider()
        score = provider.keyword_match_score(
            "python programming",
            "python coding language programming",
        )
        assert 0.0 <= score <= 1.0

    def test_keyword_match_score_no_match(self) -> None:
        """完全不匹配时得分为 0."""
        provider = FallbackKeywordProvider()
        score = provider.keyword_match_score(
            "python programming",
            "cooking recipe food",
        )
        # 可能有微小的 n-gram 重叠，但应该很低
        assert score < 0.3

    def test_chinese_text_embedding(self) -> None:
        """中文文本应能正常嵌入."""
        provider = FallbackKeywordProvider(dimension=128)
        result = provider.embed("学习编程开发")
        assert len(result.vector) == 128
        # 中文文本应该有非零向量
        assert any(v > 0 for v in result.vector)


# ============================================================================
# VectorIndex 测试
# ============================================================================

class TestVectorIndexBasic:
    """向量索引基本操作测试."""

    def test_create_index(self) -> None:
        """创建向量索引."""
        index = VectorIndex(dimension=64)
        assert index.dimension == 64
        assert index.size == 0
        assert len(index) == 0

    def test_add_vector(self) -> None:
        """添加单个向量."""
        index = VectorIndex(dimension=4)
        vec = [1.0, 0.0, 0.0, 0.0]
        index.add("vec1", vec, {"type": "test"})
        assert index.size == 1
        assert "vec1" in index

    def test_add_vector_normalizes(self) -> None:
        """添加向量时应自动归一化."""
        index = VectorIndex(dimension=2)
        # 未归一化向量
        index.add("vec1", [3.0, 4.0])
        result = index.get("vec1")
        assert result is not None
        stored_vec, _ = result
        # L2 范数应为 1
        norm = math.sqrt(sum(v * v for v in stored_vec))
        assert abs(norm - 1.0) < 0.01

    def test_add_duplicate_updates(self) -> None:
        """添加重复 ID 应更新向量."""
        index = VectorIndex(dimension=4)
        index.add("vec1", [1.0, 0.0, 0.0, 0.0])
        index.add("vec1", [0.0, 1.0, 0.0, 0.0])
        assert index.size == 1  # 不增加数量
        result = index.get("vec1")
        assert result is not None
        stored_vec, _ = result
        # 第二个元素应该接近 1.0（归一化后）
        assert stored_vec[1] > 0.9

    def test_add_batch(self) -> None:
        """批量添加向量."""
        index = VectorIndex(dimension=4)
        items = [
            ("a", [1.0, 0.0, 0.0, 0.0], {"name": "a"}),
            ("b", [0.0, 1.0, 0.0, 0.0], {"name": "b"}),
            ("c", [0.0, 0.0, 1.0, 0.0], {"name": "c"}),
        ]
        index.add_batch(items)
        assert index.size == 3

    def test_delete_vector(self) -> None:
        """删除向量."""
        index = VectorIndex(dimension=4)
        index.add("vec1", [1.0, 0.0, 0.0, 0.0])
        result = index.delete("vec1")
        assert result is True
        assert index.size == 0
        assert "vec1" not in index

    def test_delete_nonexistent(self) -> None:
        """删除不存在的向量应返回 False."""
        index = VectorIndex(dimension=4)
        result = index.delete("nonexistent")
        assert result is False

    def test_delete_maintains_integrity(self) -> None:
        """删除后索引应保持完整."""
        index = VectorIndex(dimension=2)
        index.add("a", [1.0, 0.0])
        index.add("b", [0.0, 1.0])
        index.add("c", [1.0, 1.0])

        index.delete("b")
        assert index.size == 2
        assert "a" in index
        assert "c" in index

        # 搜索应仍正常工作
        results = index.search([1.0, 0.0], top_k=2)
        assert len(results) == 2

    def test_clear_index(self) -> None:
        """清空索引."""
        index = VectorIndex(dimension=4)
        index.add("a", [1.0, 0.0, 0.0, 0.0])
        index.add("b", [0.0, 1.0, 0.0, 0.0])
        index.clear()
        assert index.size == 0
        assert len(index.ids()) == 0

    def test_get_vector(self) -> None:
        """获取向量和元数据."""
        index = VectorIndex(dimension=4)
        index.add("vec1", [1.0, 0.0, 0.0, 0.0], {"category": "test"})
        result = index.get("vec1")
        assert result is not None
        vec, meta = result
        assert len(vec) == 4
        assert meta["category"] == "test"

    def test_get_nonexistent(self) -> None:
        """获取不存在的向量返回 None."""
        index = VectorIndex(dimension=4)
        result = index.get("nonexistent")
        assert result is None

    def test_ids(self) -> None:
        """获取所有 ID 列表."""
        index = VectorIndex(dimension=4)
        index.add("a", [1.0, 0.0, 0.0, 0.0])
        index.add("b", [0.0, 1.0, 0.0, 0.0])
        ids = index.ids()
        assert set(ids) == {"a", "b"}


class TestVectorIndexSearch:
    """向量索引搜索测试."""

    def test_search_empty_index(self) -> None:
        """空索引搜索应返回空列表."""
        index = VectorIndex(dimension=4)
        results = index.search([1.0, 0.0, 0.0, 0.0])
        assert results == []

    def test_search_returns_sorted(self) -> None:
        """搜索结果应按相似度降序排列."""
        index = VectorIndex(dimension=3)
        index.add("a", [1.0, 0.0, 0.0])
        index.add("b", [0.0, 1.0, 0.0])
        index.add("c", [0.5, 0.5, 0.0])

        results = index.search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) == 3
        # 按分数降序
        assert results[0].score >= results[1].score >= results[2].score

    def test_search_top_k(self) -> None:
        """搜索应返回 top_k 个结果."""
        index = VectorIndex(dimension=3)
        for i in range(10):
            vec = [0.0] * 3
            vec[i % 3] = 1.0
            index.add(f"vec_{i}", vec)

        results = index.search([1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 5

    def test_search_cosine_similarity(self) -> None:
        """相同向量的余弦相似度应为 1."""
        index = VectorIndex(dimension=4)
        vec = [1.0, 0.0, 0.0, 0.0]
        index.add("same", vec)

        results = index.search(vec, top_k=1)
        assert len(results) == 1
        assert results[0].id == "same"
        assert abs(results[0].score - 1.0) < 0.01

    def test_search_orthogonal_vectors(self) -> None:
        """正交向量的余弦相似度应为 0."""
        index = VectorIndex(dimension=4)
        index.add("orthogonal", [0.0, 1.0, 0.0, 0.0])

        results = index.search([1.0, 0.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert abs(results[0].score - 0.0) < 0.01

    def test_search_with_metadata_filter(self) -> None:
        """元数据过滤应正常工作."""
        index = VectorIndex(dimension=3)
        index.add("a", [1.0, 0.0, 0.0], {"category": "fruit"})
        index.add("b", [0.0, 1.0, 0.0], {"category": "vegetable"})
        index.add("c", [0.0, 0.0, 1.0], {"category": "fruit"})

        results = index.search(
            [1.0, 0.0, 0.0],
            top_k=10,
            filter_metadata={"category": "fruit"},
        )
        assert len(results) == 2
        assert all(r.metadata.get("category") == "fruit" for r in results)

    def test_search_result_type(self) -> None:
        """搜索结果应为 SearchResult 类型."""
        index = VectorIndex(dimension=3)
        index.add("a", [1.0, 0.0, 0.0], {"name": "test"})
        results = index.search([1.0, 0.0, 0.0], top_k=1)
        assert isinstance(results[0], SearchResult)
        assert results[0].id == "a"
        assert isinstance(results[0].score, float)
        assert isinstance(results[0].metadata, dict)

    def test_search_score_range(self) -> None:
        """搜索得分应在 0-1 范围内."""
        index = VectorIndex(dimension=3)
        index.add("a", [1.0, 0.0, 0.0])
        index.add("b", [0.0, 1.0, 0.0])
        index.add("c", [0.5, 0.5, 0.5])

        results = index.search([1.0, 0.0, 0.0], top_k=3)
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_search_wrong_dimension_raises(self) -> None:
        """维度不匹配应抛出 ValueError."""
        index = VectorIndex(dimension=4)
        with pytest.raises(ValueError, match="维度不匹配"):
            index.search([1.0, 0.0, 0.0])  # 3 维 vs 4 维


class TestVectorIndexEdgeCases:
    """向量索引边界情况测试."""

    def test_add_zero_vector(self) -> None:
        """添加零向量不应报错."""
        index = VectorIndex(dimension=4)
        index.add("zero", [0.0, 0.0, 0.0, 0.0])
        assert index.size == 1

    def test_search_zero_vector(self) -> None:
        """查询零向量不应报错."""
        index = VectorIndex(dimension=4)
        index.add("a", [1.0, 0.0, 0.0, 0.0])
        results = index.search([0.0, 0.0, 0.0, 0.0])
        assert len(results) == 1
        # 零向量与任何向量的点积为 0
        assert results[0].score == 0.0

    def test_add_wrong_dimension_raises(self) -> None:
        """添加维度不匹配的向量应抛出 ValueError."""
        index = VectorIndex(dimension=4)
        with pytest.raises(ValueError, match="维度不匹配"):
            index.add("bad", [1.0, 2.0, 3.0])  # 3 维

    def test_large_index_search(self) -> None:
        """较大索引的搜索应正常工作."""
        index = VectorIndex(dimension=16)
        import random
        random.seed(42)

        for i in range(100):
            vec = [random.random() for _ in range(16)]
            index.add(f"vec_{i}", vec)

        assert index.size == 100
        query = [random.random() for _ in range(16)]
        results = index.search(query, top_k=10)
        assert len(results) == 10
        assert results[0].score >= results[-1].score

    def test_delete_then_add(self) -> None:
        """删除后添加应正常工作."""
        index = VectorIndex(dimension=3)
        index.add("a", [1.0, 0.0, 0.0])
        index.delete("a")
        index.add("a", [0.0, 1.0, 0.0])
        assert index.size == 1
        result = index.get("a")
        assert result is not None


class TestEmbeddingProvider:
    """EmbeddingProvider 抽象基类测试."""

    def test_fallback_is_provider_subclass(self) -> None:
        """FallbackKeywordProvider 应是 EmbeddingProvider 的子类."""
        provider = FallbackKeywordProvider()
        assert isinstance(provider, EmbeddingProvider)

    def test_provider_similarity_method(self) -> None:
        """similarity 方法应正确计算余弦相似度."""
        provider = FallbackKeywordProvider()
        # 相同向量
        v = [1.0, 0.0, 0.0]
        sim = provider.similarity(v, v)
        assert abs(sim - 1.0) < 0.01

    def test_provider_similarity_orthogonal(self) -> None:
        """正交向量相似度应为 0."""
        provider = FallbackKeywordProvider()
        sim = provider.similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim - 0.0) < 0.01

    def test_provider_similarity_mismatched_dimension(self) -> None:
        """维度不匹配应抛出 ValueError."""
        provider = FallbackKeywordProvider()
        with pytest.raises(ValueError, match="维度不匹配"):
            provider.similarity([1.0, 0.0], [1.0, 0.0, 0.0])

    def test_embed_documents_returns_vectors(self) -> None:
        """embed_documents 应返回向量列表."""
        provider = FallbackKeywordProvider(dimension=64)
        vectors = provider.embed_documents(["hello", "world"])
        assert len(vectors) == 2
        assert all(len(v) == 64 for v in vectors)

    def test_has_sentence_transformers_returns_bool(self) -> None:
        """has_sentence_transformers 应返回布尔值."""
        result = has_sentence_transformers()
        assert isinstance(result, bool)
