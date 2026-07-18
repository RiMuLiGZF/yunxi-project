"""
混合检索测试

覆盖：
1. BM25 关键词检索
2. 向量检索（模拟）
3. 加权融合
4. RRF 融合
5. 重排序
6. HybridSearcher 综合测试
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_services.hybrid_search import (
    DenseRetriever,
    BM25Retriever,
    Reranker,
    HybridSearcher,
    RetrievalResultItem,
    cosine_similarity,
    weighted_fusion,
    rrf_fusion,
)


# ==================== 工具函数测试 ====================

class TestCosineSimilarity:
    """余弦相似度测试"""

    def test_identical_vectors(self):
        """相同向量相似度为 1"""
        v = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        """正交向量相似度为 0"""
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert abs(cosine_similarity(v1, v2)) < 0.001

    def test_opposite_vectors(self):
        """相反向量相似度为 -1"""
        v1 = [1.0, 0.0]
        v2 = [-1.0, 0.0]
        assert abs(cosine_similarity(v1, v2) + 1.0) < 0.001

    def test_zero_vector(self):
        """零向量相似度为 0"""
        v1 = [0.0, 0.0]
        v2 = [1.0, 2.0]
        assert cosine_similarity(v1, v2) == 0.0

    def test_different_lengths(self):
        """不同长度向量相似度为 0"""
        v1 = [1.0, 2.0]
        v2 = [1.0, 2.0, 3.0]
        assert cosine_similarity(v1, v2) == 0.0


# ==================== BM25 检索测试 ====================

class TestBM25Retriever:
    """BM25 关键词检索测试"""

    def setup_method(self):
        """初始化测试数据"""
        self.retriever = BM25Retriever(top_k=10)
        self.docs = [
            {"chunk_id": "c1", "text": "人工智能是计算机科学的一个分支，它企图了解智能的实质。", "doc_id": "d1"},
            {"chunk_id": "c2", "text": "机器学习是人工智能的一个子集，使用算法从数据中学习。", "doc_id": "d1"},
            {"chunk_id": "c3", "text": "深度学习是机器学习的一种方法，基于神经网络。", "doc_id": "d2"},
            {"chunk_id": "c4", "text": "数据库管理系统用于存储和检索大量数据。", "doc_id": "d2"},
            {"chunk_id": "c5", "text": "Python 是一种流行的编程语言，广泛用于人工智能领域。", "doc_id": "d3"},
        ]
        for doc in self.docs:
            self.retriever.add_document(**doc)

    def test_basic_search(self):
        """基础检索测试"""
        results = self.retriever.search("人工智能")
        assert len(results) > 0
        # 第一个结果应该最相关
        assert results[0].score > 0

    def test_search_returns_top_k(self):
        """返回数量不超过 top_k"""
        retriever = BM25Retriever(top_k=2)
        for doc in self.docs:
            retriever.add_document(**doc)
        results = retriever.search("学习")
        assert len(results) <= 2

    def test_search_score_range(self):
        """分数在 0-1 之间"""
        results = self.retriever.search("人工智能")
        for r in results:
            assert 0 <= r.score <= 1

    def test_no_match(self):
        """无匹配结果"""
        results = self.retriever.search("完全不相关的词汇量子物理弦理论")
        # 可能有部分匹配，分数应该很低
        if results:
            assert all(r.score < 0.5 for r in results)

    def test_empty_query(self):
        """空查询返回空"""
        results = self.retriever.search("")
        assert len(results) == 0

    def test_add_remove(self):
        """添加和移除文档"""
        retriever = BM25Retriever()
        retriever.add_document("c1", "测试文档内容", "d1")
        assert retriever.is_available

        results_before = retriever.search("测试")
        assert len(results_before) > 0

        retriever.remove("c1")
        results_after = retriever.search("测试")
        # 移除后应该没有结果
        assert len(results_after) == 0 or all(r.chunk_id != "c1" for r in results_after)

    def test_clear(self):
        """清空索引"""
        retriever = BM25Retriever()
        retriever.add_document("c1", "测试文档", "d1")
        retriever.clear()
        assert not retriever.is_available

    def test_batch_add(self):
        """批量添加"""
        retriever = BM25Retriever()
        items = [
            {"chunk_id": "c1", "text": "文档一", "doc_id": "d1"},
            {"chunk_id": "c2", "text": "文档二", "doc_id": "d2"},
        ]
        retriever.add_batch(items)
        assert retriever.is_available
        assert retriever._total_docs == 2

    def test_result_structure(self):
        """结果结构测试"""
        results = self.retriever.search("人工智能")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r.chunk_id, str)
        assert isinstance(r.doc_id, str)
        assert isinstance(r.text, str)
        assert isinstance(r.score, float)
        assert r.sparse_score > 0
        assert r.source == "sparse"

    def test_chinese_search(self):
        """中文检索测试"""
        results = self.retriever.search("神经网络深度学习")
        assert len(results) > 0
        # 包含"深度学习"的文档应该排在前面
        assert "深度" in results[0].text or "神经" in results[0].text


# ==================== 向量检索测试 ====================

class TestDenseRetriever:
    """向量检索测试"""

    def _mock_embedding(self, text: str):
        """模拟嵌入函数（简单的基于字符哈希的伪向量）"""
        # 生成一个确定性的伪向量
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        # 将 hash 转换为 16 维向量
        vector = []
        for i in range(0, len(h), 2):
            vector.append(int(h[i:i + 2], 16) / 255.0)
        # 补全到 16 维
        while len(vector) < 16:
            vector.append(0.0)
        return vector

    def setup_method(self):
        """初始化测试数据"""
        self.retriever = DenseRetriever(
            embedding_fn=self._mock_embedding,
            top_k=10,
        )
        self.docs = [
            {"chunk_id": "c1", "text": "人工智能机器学习深度学习"},
            {"chunk_id": "c2", "text": "数据库SQL查询优化索引"},
            {"chunk_id": "c3", "text": "Python编程代码开发"},
            {"chunk_id": "c4", "text": "前端JavaScript React Vue"},
        ]
        for doc in self.docs:
            self.retriever.add_document(**doc)

    def test_basic_search(self):
        """基础向量检索测试"""
        results = self.retriever.search("人工智能深度学习")
        assert len(results) > 0
        assert results[0].dense_score > 0

    def test_no_embedding_fn(self):
        """无嵌入函数时返回空"""
        retriever = DenseRetriever(embedding_fn=None)
        retriever.add_document("c1", "测试")
        results = retriever.search("测试")
        assert len(results) == 0

    def test_embedding_passthrough(self):
        """直接传入向量"""
        retriever = DenseRetriever(embedding_fn=None, top_k=5)
        retriever.add_document(
            chunk_id="c1",
            text="测试",
            doc_id="d1",
            embedding=[1.0, 0.0, 0.0],
        )
        # 即使没有 embedding_fn，有预计算向量也能检索
        # 注意：实际检索需要查询向量，这里需要 embedding_fn
        # 所以测试的是存储功能
        assert "c1" in retriever._embeddings

    def test_top_k(self):
        """Top K 限制"""
        retriever = DenseRetriever(
            embedding_fn=self._mock_embedding,
            top_k=2,
        )
        for doc in self.docs:
            retriever.add_document(**doc)
        results = retriever.search("测试")
        assert len(results) <= 2

    def test_remove(self):
        """移除文档"""
        self.retriever.remove("c1")
        results = self.retriever.search("人工智能")
        assert all(r.chunk_id != "c1" for r in results)

    def test_clear(self):
        """清空索引"""
        self.retriever.clear()
        assert not self.retriever.is_available


# ==================== 融合算法测试 ====================

class TestFusionAlgorithms:
    """融合算法测试"""

    def _make_results(self, n: int, prefix: str, source: str):
        """生成测试结果"""
        results = []
        for i in range(n):
            results.append(RetrievalResultItem(
                chunk_id=f"{prefix}_{i}",
                doc_id="d1",
                text=f"文档 {i}",
                score=1.0 - i * 0.1,
                rank=i + 1,
                source=source,
                dense_score=1.0 - i * 0.1 if source == "dense" else 0.0,
                sparse_score=1.0 - i * 0.1 if source == "sparse" else 0.0,
            ))
        return results

    def test_weighted_fusion_basic(self):
        """加权融合基础测试"""
        dense = self._make_results(5, "d", "dense")
        sparse = self._make_results(5, "s", "sparse")

        results = weighted_fusion(dense, sparse, dense_weight=0.7, top_k=10)
        assert len(results) > 0
        assert all(0 <= r.score <= 1 for r in results)

    def test_weighted_fusion_top_k(self):
        """加权融合 Top K 限制"""
        dense = self._make_results(10, "d", "dense")
        sparse = self._make_results(10, "s", "sparse")

        results = weighted_fusion(dense, sparse, top_k=5)
        assert len(results) <= 5

    def test_weighted_fusion_overlap(self):
        """加权融合 - 有重叠结果"""
        dense = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="", score=0.9, rank=1, source="dense", dense_score=0.9),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="", score=0.8, rank=2, source="dense", dense_score=0.8),
            RetrievalResultItem(chunk_id="c3", doc_id="d1", text="", score=0.7, rank=3, source="dense", dense_score=0.7),
        ]
        sparse = [
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="", score=0.9, rank=1, source="sparse", sparse_score=0.9),
            RetrievalResultItem(chunk_id="c3", doc_id="d1", text="", score=0.8, rank=2, source="sparse", sparse_score=0.8),
            RetrievalResultItem(chunk_id="c4", doc_id="d1", text="", score=0.7, rank=3, source="sparse", sparse_score=0.7),
        ]

        results = weighted_fusion(dense, sparse, dense_weight=0.5, top_k=10)
        # c2 和 c3 在两个列表中都有，分数应该更高
        assert len(results) == 4  # c1, c2, c3, c4

    def test_rrf_fusion_basic(self):
        """RRF 融合基础测试"""
        dense = self._make_results(5, "d", "dense")
        sparse = self._make_results(5, "s", "sparse")

        results = rrf_fusion(dense, sparse, k=60, top_k=10)
        assert len(results) > 0
        assert all(r.source == "hybrid" for r in results)

    def test_rrf_fusion_rank_order(self):
        """RRF 融合 - 排名顺序"""
        dense = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="", score=0.9, rank=1, source="dense"),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="", score=0.8, rank=2, source="dense"),
        ]
        sparse = [
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="", score=0.9, rank=1, source="sparse"),
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="", score=0.8, rank=2, source="sparse"),
        ]

        results = rrf_fusion(dense, sparse, k=60, top_k=10)
        # c1 和 c2 都在两个列表中，c1 排名 1+2，c2 排名 2+1
        # RRF 分数应该相同或接近
        assert len(results) == 2
        # 分数应该接近（排名和相同）
        assert abs(results[0].score - results[1].score) < 0.1

    def test_rrf_fusion_k_parameter(self):
        """RRF K 参数影响"""
        dense = self._make_results(5, "d", "dense")
        sparse = self._make_results(5, "s", "sparse")

        results_k10 = rrf_fusion(dense, sparse, k=10, top_k=10)
        results_k60 = rrf_fusion(dense, sparse, k=60, top_k=10)

        # K 值不同，分数分布应该不同
        # 但这里都是完全不同的 ID，顺序可能一样
        assert len(results_k10) == len(results_k60)

    def test_weighted_fusion_empty_input(self):
        """加权融合 - 空输入"""
        results = weighted_fusion([], [], top_k=10)
        assert results == []

    def test_rrf_fusion_empty_input(self):
        """RRF 融合 - 空输入"""
        results = rrf_fusion([], [], top_k=10)
        assert results == []


# ==================== 重排序测试 ====================

class TestReranker:
    """重排序测试"""

    def setup_method(self):
        self.reranker = Reranker(method="hybrid")

    def test_basic_rerank(self):
        """基础重排序测试"""
        results = [
            RetrievalResultItem(
                chunk_id="c1", doc_id="d1",
                text="人工智能机器学习深度学习神经网络",
                score=0.8, rank=1, source="hybrid",
            ),
            RetrievalResultItem(
                chunk_id="c2", doc_id="d1",
                text="数据库管理系统SQL查询优化",
                score=0.7, rank=2, source="hybrid",
            ),
            RetrievalResultItem(
                chunk_id="c3", doc_id="d1",
                text="深度学习神经网络模型训练",
                score=0.6, rank=3, source="hybrid",
            ),
        ]

        reranked = self.reranker.rerank("深度学习神经网络", results)
        assert len(reranked) == 3
        # 包含"深度学习"和"神经网络"的应该排前面
        assert "深度" in reranked[0].text and "神经" in reranked[0].text

    def test_rerank_top_n(self):
        """重排序 Top N 限制"""
        results = [
            RetrievalResultItem(chunk_id=f"c{i}", doc_id="d1", text=f"文档{i}", score=0.9 - i * 0.1, rank=i + 1)
            for i in range(10)
        ]

        reranked = self.reranker.rerank("测试", results, top_n=5)
        assert len(reranked) == 5

    def test_rerank_preserves_items(self):
        """重排序保留所有结果信息"""
        results = [
            RetrievalResultItem(
                chunk_id="c1", doc_id="d1", text="测试文档",
                score=0.8, rank=1, dense_score=0.8, sparse_score=0.6,
            ),
        ]

        reranked = self.reranker.rerank("测试", results)
        assert len(reranked) == 1
        assert reranked[0].chunk_id == "c1"
        assert "rerank_score" in reranked[0].metadata

    def test_rerank_methods(self):
        """不同重排序方法"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能深度学习", score=0.8, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="数据库SQL查询", score=0.7, rank=2),
        ]

        for method in ["keyword", "semantic", "hybrid"]:
            reranker = Reranker(method=method)
            reranked = reranker.rerank("人工智能", results)
            assert len(reranked) == 2

    def test_empty_results(self):
        """空结果重排序"""
        assert self.reranker.rerank("测试", []) == []

    def test_score_range(self):
        """重排序分数范围"""
        results = [
            RetrievalResultItem(chunk_id=f"c{i}", doc_id="d1",
                               text=f"测试文档内容{i}" * 10, score=0.5, rank=i + 1)
            for i in range(5)
        ]

        reranked = self.reranker.rerank("测试文档", results)
        for r in reranked:
            assert 0 <= r.score <= 1


# ==================== HybridSearcher 综合测试 ====================

class TestHybridSearcher:
    """混合检索器综合测试"""

    def _mock_embedding(self, text: str):
        """模拟嵌入函数"""
        import hashlib
        h = hashlib.md5(text.encode()).hexdigest()
        vector = []
        for i in range(0, len(h), 2):
            vector.append(int(h[i:i + 2], 16) / 255.0)
        while len(vector) < 16:
            vector.append(0.0)
        return vector

    def setup_method(self):
        self.searcher = HybridSearcher(
            embedding_fn=self._mock_embedding,
            dense_top_k=10,
            sparse_top_k=10,
            final_top_k=5,
            enable_hybrid=True,
            hybrid_weight=0.7,
            fusion_method="rrf",
            enable_rerank=True,
            rerank_top_n=10,
        )
        # 添加测试文档
        docs = [
            {"chunk_id": "c1", "text": "人工智能是计算机科学的重要分支，研究如何使计算机具有智能。", "doc_id": "d1"},
            {"chunk_id": "c2", "text": "机器学习是实现人工智能的一种方法，通过数据训练模型。", "doc_id": "d1"},
            {"chunk_id": "c3", "text": "深度学习使用多层神经网络进行特征学习和模式识别。", "doc_id": "d1"},
            {"chunk_id": "c4", "text": "数据库是存储和管理数据的系统，支持SQL查询语言。", "doc_id": "d2"},
            {"chunk_id": "c5", "text": "Python是一种高级编程语言，广泛用于数据科学和AI开发。", "doc_id": "d2"},
        ]
        for doc in docs:
            self.searcher.add_document(**doc)

    def test_basic_search(self):
        """基础混合检索测试"""
        results = self.searcher.search("人工智能机器学习")
        assert len(results) > 0
        assert all(r.source == "hybrid" for r in results)

    def test_search_top_k(self):
        """检索结果数量限制"""
        results = self.searcher.search("测试", top_k=3)
        assert len(results) <= 3

    def test_disable_hybrid(self):
        """禁用混合检索"""
        results = self.searcher.search("人工智能", enable_hybrid=False)
        assert len(results) > 0

    def test_disable_rerank(self):
        """禁用重排序"""
        results = self.searcher.search("人工智能", enable_rerank=False)
        assert len(results) > 0

    def test_add_document(self):
        """添加文档"""
        before_count = len(self.searcher.sparse._docs)
        self.searcher.add_document("c_new", "新文档内容", "d3")
        after_count = len(self.searcher.sparse._docs)
        assert after_count == before_count + 1

    def test_remove_document(self):
        """移除文档"""
        self.searcher.remove("c1")
        results = self.searcher.search("计算机科学")
        assert all(r.chunk_id != "c1" for r in results)

    def test_search_debug(self):
        """调试模式检索"""
        debug_info = self.searcher.search_debug("人工智能")
        assert "query" in debug_info
        assert "dense_results" in debug_info
        assert "sparse_results" in debug_info
        assert "fused_results" in debug_info
        assert "reranked_results" in debug_info
        assert "stats" in debug_info

    def test_weighted_fusion_method(self):
        """加权融合方法"""
        searcher = HybridSearcher(
            embedding_fn=self._mock_embedding,
            fusion_method="weighted",
            enable_hybrid=True,
            enable_rerank=False,
        )
        docs = [
            {"chunk_id": "c1", "text": "人工智能机器学习", "doc_id": "d1"},
            {"chunk_id": "c2", "text": "数据库SQL查询", "doc_id": "d2"},
        ]
        for doc in docs:
            searcher.add_document(**doc)

        results = searcher.search("人工智能")
        assert len(results) > 0

    def test_clear(self):
        """清空索引"""
        self.searcher.clear()
        assert not self.searcher.sparse.is_available
        assert not self.searcher.dense.is_available

    def test_result_ranking(self):
        """结果排名正确"""
        results = self.searcher.search("深度学习神经网络")
        for i, r in enumerate(results):
            assert r.rank == i + 1
