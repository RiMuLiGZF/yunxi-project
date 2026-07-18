"""
检索后处理测试

覆盖：
1. 结果去重（deduplicate_results）
2. MMR 多样性排序（mmr_rerank）
3. 上下文窗口扩展（expand_context_window）
4. 引用追溯（build_citations）
5. PostProcessor 综合测试
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_services.hybrid_search import RetrievalResultItem
from shared.business.rag_services.post_processor import (
    deduplicate_results,
    mmr_rerank,
    expand_context_window,
    build_citations,
    format_citations_markdown,
    PostProcessor,
    ChunkWithContext,
    CitationInfo,
)


# ==================== 结果去重测试 ====================

class TestDeduplication:
    """结果去重测试"""

    def test_no_duplicates(self):
        """无重复结果测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能是计算机科学的分支", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="数据库管理系统用于存储数据", score=0.8, rank=2),
            RetrievalResultItem(chunk_id="c3", doc_id="d2", text="Python是一种编程语言", score=0.7, rank=3),
        ]
        deduped = deduplicate_results(results, threshold=0.9)
        assert len(deduped) == 3

    def test_exact_duplicates(self):
        """完全重复结果去重"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能是计算机科学的分支", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="人工智能是计算机科学的分支", score=0.8, rank=2),
        ]
        deduped = deduplicate_results(results, threshold=0.9)
        # 完全相同的文本应该被去重
        assert len(deduped) == 1
        assert deduped[0].score == 0.9  # 保留分数高的

    def test_high_similarity_duplicates(self):
        """高度相似结果去重"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能是计算机科学的一个重要分支领域", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="人工智能是计算机科学的一个重要分支", score=0.85, rank=2),
        ]
        deduped = deduplicate_results(results, threshold=0.8)
        # 高度相似应该被去重
        assert len(deduped) == 1

    def test_threshold_adjustment(self):
        """阈值调整测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能机器学习深度学习", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="数据库SQL查询优化索引", score=0.8, rank=2),
        ]
        # 低阈值：容易判定为重复
        deduped_low = deduplicate_results(results, threshold=0.1)
        # 高阈值：不容易判定为重复
        deduped_high = deduplicate_results(results, threshold=0.9)
        # 低阈值下可能去重更多
        assert len(deduped_low) <= len(deduped_high)

    def test_empty_results(self):
        """空结果去重"""
        assert deduplicate_results([]) == []

    def test_single_result(self):
        """单个结果去重"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="测试", score=0.9, rank=1),
        ]
        deduped = deduplicate_results(results)
        assert len(deduped) == 1

    def test_preserves_rank_order(self):
        """去重后保持排名顺序"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="完全不同的文本一", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="完全不同的文本二", score=0.8, rank=2),
            RetrievalResultItem(chunk_id="c3", doc_id="d1", text="完全不同的文本三", score=0.7, rank=3),
        ]
        deduped = deduplicate_results(results, threshold=0.9)
        assert len(deduped) == 3
        assert deduped[0].rank == 1
        assert deduped[1].rank == 2
        assert deduped[2].rank == 3


# ==================== MMR 多样性排序测试 ====================

class TestMMR:
    """MMR 多样性排序测试"""

    def test_mmr_basic(self):
        """基础 MMR 排序测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能机器学习深度学习", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="人工智能神经网络模型", score=0.85, rank=2),
            RetrievalResultItem(chunk_id="c3", doc_id="d2", text="数据库SQL查询优化", score=0.8, rank=3),
            RetrievalResultItem(chunk_id="c4", doc_id="d2", text="数据库索引性能调优", score=0.75, rank=4),
        ]
        mmr_results = mmr_rerank(results, lambda_param=0.5, top_k=3)
        assert len(mmr_results) == 3
        # 第一个应该是分数最高的
        assert mmr_results[0].chunk_id == "c1"

    def test_mmr_lambda_high(self):
        """高 lambda 值（更看重相关性）"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能机器学习", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="人工智能深度学习", score=0.85, rank=2),
            RetrievalResultItem(chunk_id="c3", doc_id="d2", text="数据库查询优化", score=0.5, rank=3),
        ]
        # lambda=1 应该完全按相关性排序
        mmr_high = mmr_rerank(results, lambda_param=1.0, top_k=3)
        assert mmr_high[0].chunk_id == "c1"
        assert mmr_high[1].chunk_id == "c2"

    def test_mmr_lambda_low(self):
        """低 lambda 值（更看重多样性）"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能机器学习", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="人工智能深度学习", score=0.85, rank=2),
            RetrievalResultItem(chunk_id="c3", doc_id="d2", text="数据库查询优化", score=0.5, rank=3),
        ]
        # lambda=0 应该更看重多样性
        mmr_low = mmr_rerank(results, lambda_param=0.0, top_k=3)
        # 第二个结果可能是 c3（更不相似）
        assert mmr_low[0].chunk_id == "c1"

    def test_mmr_top_k(self):
        """MMR Top K 限制"""
        results = [
            RetrievalResultItem(chunk_id=f"c{i}", doc_id="d1", text=f"不同的文本内容{i}" * 5, score=0.9 - i * 0.1, rank=i + 1)
            for i in range(10)
        ]
        mmr_results = mmr_rerank(results, lambda_param=0.5, top_k=5)
        assert len(mmr_results) == 5

    def test_mmr_empty_results(self):
        """空结果 MMR"""
        assert mmr_rerank([]) == []

    def test_mmr_single_result(self):
        """单个结果 MMR"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="测试", score=0.9, rank=1),
        ]
        mmr_results = mmr_rerank(results)
        assert len(mmr_results) == 1

    def test_mmr_metadata_has_rank(self):
        """MMR 结果包含排名元数据"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="测试文本一", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d2", text="测试文本二", score=0.8, rank=2),
        ]
        mmr_results = mmr_rerank(results, lambda_param=0.5)
        assert "mmr_rank" in mmr_results[0].metadata


# ==================== 上下文窗口扩展测试 ====================

class TestContextExpansion:
    """上下文窗口扩展测试"""

    def test_expand_basic(self):
        """基础上下文扩展测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="中间内容。", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "前面的内容。", "chunk_index": 0},
                {"chunk_id": "c1", "text": "中间内容。", "chunk_index": 1},
                {"chunk_id": "c2", "text": "后面的内容。", "chunk_index": 2},
            ]
        }
        expanded = expand_context_window(results, all_chunks, chars_before=10, chars_after=10)
        assert len(expanded) == 1
        assert len(expanded[0].expanded_text) > len(expanded[0].text)
        assert "前面" in expanded[0].expanded_text
        assert "后面" in expanded[0].expanded_text

    def test_expand_first_chunk(self):
        """第一个 chunk 向前扩展（无前置内容）"""
        results = [
            RetrievalResultItem(chunk_id="c0", doc_id="d1", text="开头内容。", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "开头内容。", "chunk_index": 0},
                {"chunk_id": "c1", "text": "后面内容。", "chunk_index": 1},
            ]
        }
        expanded = expand_context_window(results, all_chunks, chars_before=10, chars_after=10)
        assert len(expanded) == 1
        # 向前扩展应该为空或很少
        assert len(expanded[0].context_before) < 10
        # 向后扩展应该有内容
        assert len(expanded[0].context_after) > 0

    def test_expand_last_chunk(self):
        """最后一个 chunk 向后扩展（无后置内容）"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="结尾内容。", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "前面内容。", "chunk_index": 0},
                {"chunk_id": "c1", "text": "结尾内容。", "chunk_index": 1},
            ]
        }
        expanded = expand_context_window(results, all_chunks, chars_before=10, chars_after=10)
        assert len(expanded) == 1
        assert len(expanded[0].context_before) > 0
        assert len(expanded[0].context_after) < 10

    def test_expand_chars_count(self):
        """扩展字符数控制"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="中间内容。", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "a" * 100, "chunk_index": 0},
                {"chunk_id": "c1", "text": "中间内容。", "chunk_index": 1},
                {"chunk_id": "c2", "text": "b" * 100, "chunk_index": 2},
            ]
        }
        expanded = expand_context_window(results, all_chunks, chars_before=30, chars_after=20)
        assert len(expanded[0].context_before) <= 30
        assert len(expanded[0].context_after) <= 20

    def test_expand_no_context(self):
        """无上下文时扩展"""
        results = [
            RetrievalResultItem(chunk_id="c0", doc_id="d1", text="唯一内容。", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "唯一内容。", "chunk_index": 0},
            ]
        }
        expanded = expand_context_window(results, all_chunks, chars_before=10, chars_after=10)
        assert len(expanded) == 1
        assert expanded[0].expanded_text == expanded[0].text

    def test_expand_result_structure(self):
        """扩展结果结构测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="内容", score=0.9, rank=1),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "前置", "chunk_index": 0},
                {"chunk_id": "c1", "text": "内容", "chunk_index": 1},
            ]
        }
        expanded = expand_context_window(results, all_chunks)
        assert isinstance(expanded[0], ChunkWithContext)
        assert expanded[0].chunk_id == "c1"
        assert expanded[0].doc_id == "d1"
        assert isinstance(expanded[0].metadata, dict)

    def test_expand_multiple_results(self):
        """多个结果的上下文扩展"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="内容一", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="内容二", score=0.8, rank=2),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "开头", "chunk_index": 0},
                {"chunk_id": "c1", "text": "内容一", "chunk_index": 1},
                {"chunk_id": "c2", "text": "内容二", "chunk_index": 2},
                {"chunk_id": "c3", "text": "结尾", "chunk_index": 3},
            ]
        }
        expanded = expand_context_window(results, all_chunks)
        assert len(expanded) == 2


# ==================== 引用追溯测试 ====================

class TestCitations:
    """引用追溯测试"""

    def test_build_citations_basic(self):
        """基础引用构建测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="人工智能是计算机科学的分支。", score=0.9, rank=1),
        ]
        documents = {
            "d1": {"title": "AI入门", "source": "book.pdf"},
        }
        citations = build_citations(results, documents)
        assert len(citations) == 1
        assert citations[0].doc_title == "AI入门"
        assert citations[0].source == "book.pdf"
        assert citations[0].confidence == 0.9

    def test_citation_text_snippet(self):
        """引用文本片段测试"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="a" * 300, score=0.9, rank=1),
        ]
        documents = {"d1": {"title": "文档", "source": ""}}
        citations = build_citations(results, documents, max_snippet_length=100)
        assert len(citations[0].text_snippet) <= 103  # 100 + "..."

    def test_citation_unknown_doc(self):
        """未知文档的引用"""
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="unknown", text="内容", score=0.9, rank=1),
        ]
        documents = {}
        citations = build_citations(results, documents)
        assert citations[0].doc_title == "未知文档"

    def test_format_citations_markdown(self):
        """Markdown 格式引用"""
        citations = [
            CitationInfo(
                chunk_id="c1",
                doc_id="d1",
                doc_title="AI入门",
                source="book.pdf",
                section_path="第一章/第一节",
                confidence=0.9,
                text_snippet="人工智能是...",
            ),
        ]
        md = format_citations_markdown(citations)
        assert "AI入门" in md
        assert "第一章/第一节" in md
        assert "人工智能是..." in md

    def test_format_empty_citations(self):
        """空引用格式化"""
        assert format_citations_markdown([]) == ""

    def test_citation_to_dict(self):
        """引用信息序列化"""
        citation = CitationInfo(
            chunk_id="c1",
            doc_id="d1",
            doc_title="测试",
            source="test.txt",
            section_path="",
            confidence=0.85,
            text_snippet="内容",
        )
        d = citation.to_dict()
        assert d["chunk_id"] == "c1"
        assert d["doc_title"] == "测试"
        assert "confidence" in d


# ==================== PostProcessor 综合测试 ====================

class TestPostProcessor:
    """后处理器综合测试"""

    def test_process_full_pipeline(self):
        """完整处理流程测试"""
        processor = PostProcessor(
            enable_dedup=True,
            dedup_threshold=0.9,
            enable_mmr=False,
            enable_context_expansion=True,
            context_chars_before=20,
            context_chars_after=20,
        )
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="中间内容。", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d2", text="其他内容。", score=0.8, rank=2),
        ]
        all_chunks = {
            "d1": [
                {"chunk_id": "c0", "text": "前面内容。", "chunk_index": 0},
                {"chunk_id": "c1", "text": "中间内容。", "chunk_index": 1},
                {"chunk_id": "c2", "text": "后面内容。", "chunk_index": 2},
            ],
            "d2": [
                {"chunk_id": "c2", "text": "其他内容。", "chunk_index": 0},
            ],
        }
        documents = {
            "d1": {"title": "文档一", "source": "d1.txt"},
            "d2": {"title": "文档二", "source": "d2.txt"},
        }

        processed = processor.process(
            results,
            all_chunks=all_chunks,
            documents=documents,
            top_k=5,
        )

        assert "results" in processed
        assert "expanded_results" in processed
        assert "citations" in processed
        assert "stats" in processed
        assert processed["stats"]["input_count"] == 2
        assert processed["stats"]["context_expanded"] == True

    def test_process_with_mmr(self):
        """启用 MMR 的处理流程"""
        processor = PostProcessor(
            enable_dedup=True,
            enable_mmr=True,
            mmr_lambda=0.5,
            enable_context_expansion=False,
        )
        results = [
            RetrievalResultItem(chunk_id=f"c{i}", doc_id=f"d{i%2}",
                               text=f"不同的文本{i}" * 3, score=0.9 - i * 0.1, rank=i + 1)
            for i in range(5)
        ]
        all_chunks = {}
        documents = {}

        processed = processor.process(results, all_chunks=all_chunks, top_k=3)
        assert processed["stats"]["mmr_applied"] == True
        assert len(processed["results"]) <= 3

    def test_process_no_enhancement(self):
        """无增强的处理流程"""
        processor = PostProcessor(
            enable_dedup=False,
            enable_mmr=False,
            enable_context_expansion=False,
        )
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="内容", score=0.9, rank=1),
        ]
        processed = processor.process(results, top_k=5)
        assert processed["stats"]["dedup_count"] == 0
        assert processed["stats"]["mmr_applied"] == False
        assert processed["stats"]["context_expanded"] == False

    def test_process_dedup_count(self):
        """去重数量统计"""
        processor = PostProcessor(
            enable_dedup=True,
            dedup_threshold=0.9,
            enable_mmr=False,
            enable_context_expansion=False,
        )
        results = [
            RetrievalResultItem(chunk_id="c1", doc_id="d1", text="完全相同的内容", score=0.9, rank=1),
            RetrievalResultItem(chunk_id="c2", doc_id="d1", text="完全相同的内容", score=0.8, rank=2),
        ]
        processed = processor.process(results)
        assert processed["stats"]["dedup_count"] == 1
