"""
RAG 知识库集成测试

测试 RAGKnowledgeBase 与 rag_services 的集成：
1. 向后兼容测试（原有 API 不变）
2. 增强功能测试（混合检索、分块策略、查询改写等）
3. 配置动态更新测试
4. 完整检索流程测试
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_knowledge import (
    RAGKnowledgeBase,
    Document,
    Chunk,
    RetrievalResult,
    KnowledgeStatus,
    get_rag_knowledge_base,
    _RAG_SERVICES_AVAILABLE,
)


@pytest.fixture
def temp_rag():
    """创建临时 RAG 知识库实例（使用临时目录）"""
    # 重置单例（测试用）
    RAGKnowledgeBase._instance = None

    temp_dir = tempfile.mkdtemp(prefix="rag_test_")
    rag = RAGKnowledgeBase(data_dir=temp_dir)

    yield rag

    # 清理
    RAGKnowledgeBase._instance = None
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==================== 向后兼容测试 ====================

class TestBackwardCompatibility:
    """向后兼容性测试 - 确保原有 API 行为不变"""

    def test_add_document_returns_document(self, temp_rag):
        """add_document 返回 Document 对象"""
        doc = temp_rag.add_document(
            title="测试文档",
            content="这是测试文档的内容。",
        )
        assert isinstance(doc, Document)
        assert doc.doc_id.startswith("doc_")
        assert doc.title == "测试文档"
        assert doc.status == KnowledgeStatus.READY.value

    def test_search_returns_retrieval_results(self, temp_rag):
        """search 返回 RetrievalResult 列表"""
        temp_rag.add_document("测试", "人工智能机器学习深度学习")
        results = temp_rag.search("人工智能")
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], RetrievalResult)
            assert isinstance(results[0].chunk, Chunk)
            assert isinstance(results[0].score, float)

    def test_search_with_category_filter(self, temp_rag):
        """分类过滤搜索"""
        temp_rag.add_document("文档1", "人工智能内容", category="ai")
        temp_rag.add_document("文档2", "数据库内容", category="db")

        results = temp_rag.search("人工智能", category="ai")
        assert all(r.chunk.doc_id for r in results)  # 都有 doc_id

    def test_list_documents(self, temp_rag):
        """列出文档"""
        temp_rag.add_document("文档1", "内容1")
        temp_rag.add_document("文档2", "内容2")

        docs = temp_rag.list_documents()
        assert len(docs) == 2
        assert all(isinstance(d, Document) for d in docs)

    def test_get_document(self, temp_rag):
        """获取单个文档"""
        doc = temp_rag.add_document("测试", "内容")
        retrieved = temp_rag.get_document(doc.doc_id)
        assert retrieved is not None
        assert retrieved.doc_id == doc.doc_id

    def test_delete_document(self, temp_rag):
        """删除文档"""
        doc = temp_rag.add_document("测试", "内容")
        success = temp_rag.delete_document(doc.doc_id)
        assert success == True

        # 验证已删除
        assert temp_rag.get_document(doc.doc_id) is None

    def test_get_stats(self, temp_rag):
        """获取统计信息"""
        temp_rag.add_document("文档1", "内容1")
        temp_rag.add_document("文档2", "内容2")

        stats = temp_rag.get_stats()
        assert "total_documents" in stats
        assert "total_chunks" in stats
        assert stats["total_documents"] == 2

    def test_build_context(self, temp_rag):
        """构建 RAG 上下文"""
        temp_rag.add_document("测试", "人工智能是计算机科学的分支。")
        context, results = temp_rag.build_context("人工智能")
        assert isinstance(context, str)
        assert isinstance(results, list)

    def test_build_rag_prompt(self, temp_rag):
        """构建 RAG prompt"""
        temp_rag.add_document("测试", "人工智能是计算机科学的分支。")
        prompt, used_rag = temp_rag.build_rag_prompt("什么是人工智能？")
        assert isinstance(prompt, str)
        assert isinstance(used_rag, bool)

    def test_chunk_structure(self, temp_rag):
        """Chunk 数据结构不变"""
        doc = temp_rag.add_document("测试", "内容" * 100)

        # 获取 chunks
        chunks = temp_rag._chunks.get(doc.doc_id, [])
        assert len(chunks) > 0
        chunk = chunks[0]

        # 验证原有字段都存在
        assert hasattr(chunk, "chunk_id")
        assert hasattr(chunk, "doc_id")
        assert hasattr(chunk, "text")
        assert hasattr(chunk, "chunk_index")
        assert hasattr(chunk, "token_count")
        assert hasattr(chunk, "embedding")
        assert hasattr(chunk, "section")
        assert hasattr(chunk, "keywords")

    def test_retrieval_result_properties(self, temp_rag):
        """RetrievalResult 属性不变"""
        temp_rag.add_document("测试", "内容")
        results = temp_rag.search("内容")
        if results:
            r = results[0]
            assert r.text == r.chunk.text
            assert r.doc_id == r.chunk.doc_id

    def test_document_to_dict(self, temp_rag):
        """Document.to_dict 方法不变"""
        doc = temp_rag.add_document("测试", "内容")
        d = doc.to_dict()
        assert isinstance(d, dict)
        assert "doc_id" in d
        assert "title" in d
        assert "status" in d


# ==================== 增强功能测试 ====================

@pytest.mark.skipif(not _RAG_SERVICES_AVAILABLE, reason="RAG 增强服务不可用")
class TestEnhancedFeatures:
    """增强功能测试"""

    def test_hybrid_search_available(self, temp_rag):
        """混合检索方法可用"""
        assert hasattr(temp_rag, 'hybrid_search')

    def test_hybrid_search_basic(self, temp_rag):
        """混合检索基础测试"""
        temp_rag.add_document("AI文档", "人工智能机器学习深度学习神经网络")
        temp_rag.add_document("DB文档", "数据库SQL查询优化索引")

        results = temp_rag.hybrid_search("人工智能", top_k=5)
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], RetrievalResult)

    def test_hybrid_search_with_category(self, temp_rag):
        """带分类过滤的混合检索"""
        temp_rag.add_document("AI", "人工智能内容", category="ai")
        temp_rag.add_document("DB", "数据库内容", category="db")

        results = temp_rag.hybrid_search("内容", category="ai", top_k=5)
        assert isinstance(results, list)

    def test_chunk_with_strategy_fixed(self, temp_rag):
        """固定大小分块策略测试"""
        text = "测试文本。" * 50
        results = temp_rag.chunk_with_strategy(text, strategy="fixed", chunk_size=100)
        assert isinstance(results, list)
        assert len(results) > 1
        assert all("chunk_id" in r for r in results)
        assert all("metadata" in r for r in results)

    def test_chunk_with_strategy_semantic(self, temp_rag):
        """语义分块策略测试"""
        text = "第一段内容。这是第一个段落。\n\n第二段内容。这是第二个段落。\n\n第三段内容。"
        results = temp_rag.chunk_with_strategy(text, strategy="semantic", chunk_size=200)
        assert isinstance(results, list)

    def test_chunk_with_strategy_structured(self, temp_rag):
        """结构化分块策略测试"""
        text = "# 第一章\n\n内容。\n\n## 第一节\n\n内容。"
        results = temp_rag.chunk_with_strategy(text, strategy="structured")
        assert isinstance(results, list)

    def test_chunk_with_strategy_recursive(self, temp_rag):
        """递归分块策略测试"""
        text = "测试文本内容。" * 30
        results = temp_rag.chunk_with_strategy(text, strategy="recursive", chunk_size=100)
        assert isinstance(results, list)
        assert len(results) > 1

    def test_chunk_with_invalid_strategy(self, temp_rag):
        """无效分块策略测试"""
        with pytest.raises(ValueError):
            temp_rag.chunk_with_strategy("测试", strategy="invalid")

    def test_chunk_metadata_enhanced(self, temp_rag):
        """增强版分块元数据测试"""
        text = "测试文本。" * 10
        results = temp_rag.chunk_with_strategy(text, strategy="fixed", doc_id="test001", doc_title="测试文档")
        assert len(results) > 0
        meta = results[0]["metadata"]
        assert "chunk_index" in meta
        assert "total_chunks" in meta
        assert "document_id" in meta
        assert "document_title" in meta
        assert "token_count" in meta
        assert "char_count" in meta
        assert "content_type" in meta
        assert "keywords" in meta
        assert "entities" in meta

    def test_rewrite_query_expansion(self, temp_rag):
        """查询扩展改写测试"""
        result = temp_rag.rewrite_query("人工智能优化", strategy="expansion")
        assert "original_query" in result
        assert "rewritten_queries" in result
        assert result["strategy"] == "expansion"
        assert result["enhanced"] == True

    def test_rewrite_query_decomposition(self, temp_rag):
        """查询分解改写测试"""
        result = temp_rag.rewrite_query("人工智能和机器学习的区别", strategy="decomposition")
        assert "rewritten_queries" in result
        assert result["strategy"] == "decomposition"

    def test_rewrite_query_conversational(self, temp_rag):
        """多轮改写测试"""
        history = [
            {"role": "user", "content": "什么是人工智能？"},
        ]
        result = temp_rag.rewrite_query("它有什么用？", strategy="conversational", history=history)
        assert "rewritten_queries" in result
        assert result["strategy"] == "conversational"

    def test_rewrite_query_hyde(self, temp_rag):
        """HyDE 改写测试"""
        result = temp_rag.rewrite_query("人工智能应用", strategy="hyde")
        assert "rewritten_queries" in result
        assert len(result["rewritten_queries"]) > 0

    def test_get_chunk_detail(self, temp_rag):
        """获取 chunk 详情测试"""
        doc = temp_rag.add_document("测试", "内容" * 20)
        chunks = temp_rag._chunks.get(doc.doc_id, [])
        if chunks:
            chunk_id = chunks[0].chunk_id
            detail = temp_rag.get_chunk_detail(chunk_id)
            assert detail is not None
            assert "chunk_id" in detail
            assert "document" in detail
            assert "has_embedding" in detail

    def test_get_chunk_detail_not_found(self, temp_rag):
        """获取不存在的 chunk"""
        assert temp_rag.get_chunk_detail("nonexistent") is None

    def test_get_context_expanded(self, temp_rag):
        """上下文扩展测试"""
        doc = temp_rag.add_document("测试", "开头内容。" + "中间内容。" * 10 + "结尾内容。")
        chunks = temp_rag._chunks.get(doc.doc_id, [])
        if len(chunks) >= 2:
            # 获取中间 chunk 的上下文
            middle_chunk = chunks[len(chunks) // 2]
            result = temp_rag.get_context_expanded(middle_chunk.chunk_id, chars_before=50, chars_after=50)
            assert result is not None
            assert "expanded_text" in result
            assert len(result["expanded_text"]) >= len(middle_chunk.text)

    def test_reindex_single_doc(self, temp_rag):
        """重建单个文档索引"""
        doc = temp_rag.add_document("测试", "内容")
        result = temp_rag.reindex(doc_id=doc.doc_id)
        assert "reindexed_docs" in result
        assert result["reindexed_docs"] == 1

    def test_reindex_all(self, temp_rag):
        """重建全部索引"""
        temp_rag.add_document("文档1", "内容1")
        temp_rag.add_document("文档2", "内容2")
        result = temp_rag.reindex()
        assert "reindexed_docs" in result
        assert result["reindexed_docs"] == 2

    def test_get_detailed_stats(self, temp_rag):
        """详细统计信息测试"""
        temp_rag.add_document("测试", "内容")
        stats = temp_rag.get_detailed_stats()
        assert "vector_count" in stats
        assert "vector_coverage" in stats
        assert "bm25_index_built" in stats
        assert "enhanced_services" in stats

    def test_search_with_debug(self, temp_rag):
        """调试模式检索测试"""
        temp_rag.add_document("测试", "人工智能内容")
        debug_info = temp_rag.search_with_debug("人工智能")
        assert "enhanced" in debug_info
        assert debug_info["enhanced"] == True

    def test_process_with_post(self, temp_rag):
        """完整后处理流程测试"""
        temp_rag.add_document("AI", "人工智能机器学习深度学习")
        temp_rag.add_document("DB", "数据库SQL查询优化")
        result = temp_rag.process_with_post("人工智能", top_k=3)
        assert "results" in result
        assert "expanded_results" in result
        assert "citations" in result
        assert "stats" in result
        assert result["enhanced"] == True


# ==================== 配置动态更新测试 ====================

@pytest.mark.skipif(not _RAG_SERVICES_AVAILABLE, reason="RAG 增强服务不可用")
class TestConfigDynamicUpdate:
    """配置动态更新测试"""

    def test_get_retrieval_config(self, temp_rag):
        """获取检索配置"""
        config = temp_rag.get_retrieval_config()
        assert "enhanced" in config
        assert config["enhanced"] == True
        assert "default_chunk_size" in config
        assert "chunking_strategy" in config

    def test_update_retrieval_config(self, temp_rag):
        """更新检索配置"""
        changed = temp_rag.update_retrieval_config({
            "default_chunk_size": 1024,
            "retrieval_top_k": 20,
        })
        assert len(changed) == 2
        assert "default_chunk_size" in changed
        assert "retrieval_top_k" in changed

    def test_update_config_invalid_key(self, temp_rag):
        """更新无效配置键"""
        with pytest.raises(ValueError):
            temp_rag.update_retrieval_config({"invalid_key": "value"})

    def test_update_config_invalid_value(self, temp_rag):
        """更新无效配置值"""
        with pytest.raises(ValueError):
            temp_rag.update_retrieval_config({"default_chunk_size": -1})

    def test_update_config_applied_immediately(self, temp_rag):
        """配置更新立即生效"""
        # 更新 chunk_size
        temp_rag.update_retrieval_config({"default_chunk_size": 100})

        # 验证新配置生效
        config = temp_rag.get_retrieval_config()
        assert config["default_chunk_size"] == 100

    def test_update_hybrid_weight(self, temp_rag):
        """更新混合检索权重"""
        changed = temp_rag.update_retrieval_config({"hybrid_search_weight": 0.8})
        assert "hybrid_search_weight" in changed
        assert changed["hybrid_search_weight"]["new"] == 0.8

    def test_update_mmr_lambda(self, temp_rag):
        """更新 MMR lambda"""
        changed = temp_rag.update_retrieval_config({"mmr_lambda": 0.7})
        assert "mmr_lambda" in changed

    def test_toggle_features(self, temp_rag):
        """切换功能开关"""
        changed = temp_rag.update_retrieval_config({
            "enable_query_rewrite": True,
            "enable_mmr": True,
        })
        assert "enable_query_rewrite" in changed
        assert "enable_mmr" in changed

    def test_update_chunking_strategy(self, temp_rag):
        """更新分块策略"""
        changed = temp_rag.update_retrieval_config({"chunking_strategy": "semantic"})
        assert "chunking_strategy" in changed
        assert changed["chunking_strategy"]["new"] == "semantic"


# ==================== 完整流程测试 ====================

@pytest.mark.skipif(not _RAG_SERVICES_AVAILABLE, reason="RAG 增强服务不可用")
class TestFullPipeline:
    """完整检索流程测试"""

    def test_document_lifecycle(self, temp_rag):
        """文档完整生命周期测试"""
        # 1. 添加文档
        doc = temp_rag.add_document(
            title="人工智能入门",
            content="人工智能是计算机科学的一个分支。机器学习是人工智能的子集。深度学习是机器学习的方法。",
            category="ai",
        )
        assert doc.status == KnowledgeStatus.READY.value

        # 2. 检索
        results = temp_rag.hybrid_search("人工智能", top_k=5)
        assert len(results) > 0

        # 3. 查看 chunk 详情
        chunk_id = results[0].chunk.chunk_id
        detail = temp_rag.get_chunk_detail(chunk_id)
        assert detail is not None

        # 4. 上下文扩展
        expanded = temp_rag.get_context_expanded(chunk_id)
        assert expanded is not None

        # 5. 统计信息
        stats = temp_rag.get_detailed_stats()
        assert stats["total_documents"] == 1

        # 6. 删除文档
        success = temp_rag.delete_document(doc.doc_id)
        assert success

        # 7. 验证删除
        stats_after = temp_rag.get_detailed_stats()
        assert stats_after["total_documents"] == 0

    def test_multiple_categories(self, temp_rag):
        """多分类知识库测试"""
        temp_rag.add_document("AI文档", "人工智能机器学习", category="ai")
        temp_rag.add_document("DB文档", "数据库SQL查询", category="db")
        temp_rag.add_document("Web文档", "JavaScript React前端", category="web")

        # 全量检索
        all_results = temp_rag.hybrid_search("学习", top_k=10)
        assert len(all_results) > 0

        # 分类检索
        ai_results = temp_rag.hybrid_search("学习", category="ai", top_k=10)
        assert isinstance(ai_results, list)

    def test_query_rewrite_and_search(self, temp_rag):
        """查询改写 + 检索组合测试"""
        temp_rag.add_document("AI", "人工智能机器学习深度学习")
        temp_rag.add_document("DB", "数据库优化索引")

        # 使用改写后检索
        results = temp_rag.search_with_rewrite("AI性能", strategy="expansion", top_k=5)
        assert isinstance(results, list)

    def test_rebuild_index_after_changes(self, temp_rag):
        """修改后重建索引测试"""
        temp_rag.add_document("文档1", "内容1")
        temp_rag.add_document("文档2", "内容2")

        # 重建前统计
        stats_before = temp_rag.get_detailed_stats()

        # 重建索引
        result = temp_rag.reindex()

        # 重建后统计
        stats_after = temp_rag.get_detailed_stats()

        assert result["reindexed_docs"] == 2
        assert stats_after["total_documents"] == stats_before["total_documents"]
