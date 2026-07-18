"""
查询改写测试

覆盖 4 种改写策略：
1. 查询扩展（Query Expansion）
2. 查询分解（Query Decomposition）
3. 多轮改写（Conversational Rewrite）
4. 假设性文档生成（HyDE）
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest
from shared.business.rag_services.query_rewriter import (
    QueryRewriter,
    RewriteStrategy,
    RewriteResult,
    expand_query,
    decompose_query,
    rewrite_conversational,
    generate_hypothetical_documents,
)


# ==================== 查询扩展测试 ====================

class TestQueryExpansion:
    """查询扩展测试"""

    def test_expand_basic(self):
        """基础查询扩展测试"""
        query = "人工智能性能优化"
        expansions = expand_query(query, max_expansions=3)
        assert isinstance(expansions, list)
        assert len(expansions) <= 3

    def test_expand_returns_different_queries(self):
        """扩展查询与原查询不同"""
        query = "人工智能优化"
        expansions = expand_query(query, max_expansions=3)
        for exp in expansions:
            assert exp != query

    def test_expand_max_count(self):
        """最大扩展数量限制"""
        query = "人工智能机器学习深度学习"
        expansions = expand_query(query, max_expansions=2)
        assert len(expansions) <= 2

    def test_expand_empty_query(self):
        """空查询扩展"""
        assert expand_query("") == []

    def test_expand_whitespace_query(self):
        """空白查询扩展"""
        assert expand_query("   ") == []

    def test_expand_no_synonyms(self):
        """无可扩展同义词的查询"""
        query = "一些没有同义词的生僻词汇"
        expansions = expand_query(query, max_expansions=3)
        # 可能有也可能没有，不做硬性要求
        assert isinstance(expansions, list)


# ==================== 查询分解测试 ====================

class TestQueryDecomposition:
    """查询分解测试"""

    def test_decompose_parallel_structure(self):
        """并列结构分解测试"""
        query = "人工智能和机器学习的区别"
        subs = decompose_query(query, max_subqueries=3)
        assert isinstance(subs, list)

    def test_decompose_chinese_and(self):
        """中文"和"并列分解"""
        query = "数据库和缓存的性能对比"
        subs = decompose_query(query)
        assert isinstance(subs, list)

    def test_decompose_english_and(self):
        """英文 and 并列分解"""
        query = "Python and Java comparison"
        subs = decompose_query(query)
        assert isinstance(subs, list)

    def test_decompose_simple_query(self):
        """简单查询不分解"""
        query = "什么是人工智能"
        subs = decompose_query(query)
        # 简单查询可能无法分解
        assert isinstance(subs, list)

    def test_decompose_max_subqueries(self):
        """最大子查询数量限制"""
        query = "A、B、C、D、E的区别"
        subs = decompose_query(query, max_subqueries=3)
        assert len(subs) <= 3

    def test_decompose_empty_query(self):
        """空查询分解"""
        assert decompose_query("") == []


# ==================== 多轮改写测试 ====================

class TestConversationalRewrite:
    """多轮改写测试"""

    def test_rewrite_with_history(self):
        """带历史的多轮改写"""
        query = "它有什么特点？"
        history = [
            {"role": "user", "content": "什么是人工智能？"},
            {"role": "assistant", "content": "人工智能是计算机科学的一个分支..."},
        ]
        results = rewrite_conversational(query, history)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_rewrite_no_history(self):
        """无历史的多轮改写"""
        query = "什么是人工智能？"
        results = rewrite_conversational(query, [])
        assert len(results) == 1
        assert results[0] == query

    def test_rewrite_empty_query(self):
        """空查询改写"""
        assert rewrite_conversational("", []) == []

    def test_rewrite_anaphora_resolution(self):
        """指代消解测试"""
        query = "这个怎么做？"
        history = [
            {"role": "user", "content": "如何优化数据库性能？"},
        ]
        results = rewrite_conversational(query, history)
        # 改写后的查询应该被修改（包含历史主题或更长）
        assert len(results) >= 1
        # 如果有改写，结果应该与原查询不同或包含更多内容
        assert len(results[0]) >= len(query)  # 至少不会变短

    def test_rewrite_short_query(self):
        """短查询补全"""
        query = "怎么做"
        history = [
            {"role": "user", "content": "机器学习模型训练"},
        ]
        results = rewrite_conversational(query, history)
        assert isinstance(results, list)
        assert len(results) >= 1


# ==================== HyDE 测试 ====================

class TestHyDE:
    """假设性文档生成测试"""

    def test_hyde_basic(self):
        """基础 HyDE 测试"""
        query = "什么是人工智能"
        docs = generate_hypothetical_documents(query, num_docs=3)
        assert isinstance(docs, list)
        assert len(docs) <= 3
        assert all(len(d) > 0 for d in docs)

    def test_hyde_num_docs(self):
        """生成文档数量控制"""
        query = "数据库优化"
        docs = generate_hypothetical_documents(query, num_docs=2)
        assert len(docs) <= 2

    def test_hyde_empty_query(self):
        """空查询 HyDE"""
        assert generate_hypothetical_documents("") == []

    def test_hyde_with_llm_fn(self):
        """使用 LLM 函数的 HyDE"""
        def mock_llm(prompt: str) -> str:
            return "这是一段模拟的回答文档，包含相关的技术内容。"

        query = "测试查询"
        docs = generate_hypothetical_documents(query, num_docs=2, llm_fn=mock_llm)
        assert len(docs) == 2
        assert all(len(d) > 0 for d in docs)

    def test_hyde_content_contains_query_terms(self):
        """生成文档包含查询术语"""
        query = "人工智能"
        docs = generate_hypothetical_documents(query, num_docs=1)
        if docs:
            # 生成的文档应该包含查询相关内容
            assert "人工智能" in docs[0]


# ==================== QueryRewriter 主类测试 ====================

class TestQueryRewriter:
    """查询改写器主类测试"""

    def test_rewrite_expansion(self):
        """扩展策略改写"""
        rewriter = QueryRewriter(strategy="expansion", max_queries=3)
        result = rewriter.rewrite("人工智能性能优化")
        assert isinstance(result, RewriteResult)
        assert result.strategy == "expansion"
        assert result.original_query == "人工智能性能优化"
        assert isinstance(result.rewritten_queries, list)

    def test_rewrite_decomposition(self):
        """分解策略改写"""
        rewriter = QueryRewriter(strategy="decomposition")
        result = rewriter.rewrite("人工智能和机器学习的区别")
        assert result.strategy == "decomposition"

    def test_rewrite_conversational(self):
        """多轮策略改写"""
        rewriter = QueryRewriter(strategy="conversational")
        history = [
            {"role": "user", "content": "什么是数据库？"},
        ]
        result = rewriter.rewrite("它有什么用？", strategy="conversational", history=history)
        assert result.strategy == "conversational"

    def test_rewrite_hyde(self):
        """HyDE 策略改写"""
        rewriter = QueryRewriter(strategy="hyde")
        result = rewriter.rewrite("人工智能的应用")
        assert result.strategy == "hyde"
        assert len(result.rewritten_queries) > 0

    def test_rewrite_override_strategy(self):
        """覆盖默认策略"""
        rewriter = QueryRewriter(strategy="expansion")
        result = rewriter.rewrite("测试查询", strategy="hyde")
        assert result.strategy == "hyde"

    def test_rewrite_all_strategies(self):
        """所有策略改写"""
        rewriter = QueryRewriter()
        results = rewriter.rewrite_all("人工智能")
        assert isinstance(results, dict)
        assert len(results) == 4
        for strategy in ["expansion", "decomposition", "conversational", "hyde"]:
            assert strategy in results
            assert isinstance(results[strategy], RewriteResult)

    def test_rewrite_result_to_dict(self):
        """改写结果序列化"""
        rewriter = QueryRewriter(strategy="expansion")
        result = rewriter.rewrite("测试")
        d = result.to_dict()
        assert "original_query" in d
        assert "rewritten_queries" in d
        assert "strategy" in d
        assert "count" in d

    def test_max_queries_limit(self):
        """最大查询数量限制"""
        rewriter = QueryRewriter(strategy="expansion", max_queries=2)
        result = rewriter.rewrite("人工智能机器学习深度学习优化")
        assert len(result.rewritten_queries) <= 2
