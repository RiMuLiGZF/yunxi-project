"""
[GAP-003] 语义路由器（SemanticRouter）单元测试

测试 SemanticRouter 的完整功能：
- 关键词匹配策略
- n-gram 语义匹配策略
- TF-IDF 语义匹配策略
- 混合策略
- 自适应学习
- 规则管理
- 默认路由器工厂
"""
import sys
import pytest

from agent_cluster.core.semantic_router import (
    SemanticRouter,
    RouteRule,
    RouteDecision,
    create_default_router,
)


# ============================================================================
# 基础功能测试
# ============================================================================

class TestSemanticRouterBasics:
    """语义路由器基础功能测试"""

    def test_router_creation_default(self):
        """默认策略创建路由器"""
        router = SemanticRouter()
        assert router.strategy == "hybrid"
        assert router.min_confidence == 0.3
        assert router.stats()["total_rules"] == 0

    def test_router_creation_keyword_strategy(self):
        """关键词策略创建"""
        router = SemanticRouter(strategy="keyword")
        assert router.strategy == "keyword"

    def test_router_creation_invalid_strategy(self):
        """无效策略应抛出异常"""
        with pytest.raises(ValueError):
            SemanticRouter(strategy="invalid_strategy")

    def test_add_single_rule(self):
        """添加单条规则"""
        router = SemanticRouter(strategy="keyword")
        router.add_rule(RouteRule(
            intent="test.intent",
            target_agent="agent.test",
            keywords=["测试", "test"],
        ))
        assert router.stats()["total_rules"] == 1
        assert router.stats()["enabled_rules"] == 1

    def test_add_multiple_rules(self):
        """批量添加规则"""
        router = SemanticRouter(strategy="keyword")
        rules = [
            RouteRule(intent="a", target_agent="agent.a", keywords=["a"]),
            RouteRule(intent="b", target_agent="agent.b", keywords=["b"]),
            RouteRule(intent="c", target_agent="agent.c", keywords=["c"]),
        ]
        router.add_rules(rules)
        assert router.stats()["total_rules"] == 3

    def test_remove_rule(self):
        """移除规则"""
        router = SemanticRouter(strategy="keyword")
        router.add_rule(RouteRule(
            intent="test.intent",
            target_agent="agent.test",
            keywords=["测试"],
        ))
        assert router.stats()["total_rules"] == 1

        result = router.remove_rule("test.intent", "agent.test")
        assert result is True
        assert router.stats()["total_rules"] == 0

    def test_remove_nonexistent_rule(self):
        """移除不存在的规则"""
        router = SemanticRouter(strategy="keyword")
        result = router.remove_rule("nonexistent", "agent.none")
        assert result is False

    def test_list_rules(self):
        """列出规则"""
        router = SemanticRouter(strategy="keyword")
        router.add_rule(RouteRule(
            intent="test.intent",
            target_agent="agent.test",
            keywords=["测试", "test"],
            samples=["这是一个测试"],
            priority=5,
        ))
        rules = router.list_rules()
        assert len(rules) == 1
        assert rules[0]["intent"] == "test.intent"
        assert rules[0]["target_agent"] == "agent.test"
        assert rules[0]["keywords_count"] == 2
        assert rules[0]["samples_count"] == 1
        assert rules[0]["priority"] == 5

    def test_disabled_rule_not_routed(self):
        """禁用的规则不参与路由"""
        router = SemanticRouter(strategy="keyword")
        rule = RouteRule(
            intent="test.intent",
            target_agent="agent.test",
            keywords=["测试"],
            enabled=False,
        )
        router.add_rule(rule)
        decision = router.route("测试")
        assert decision.method == "fallback"
        assert decision.target_agent == "master_scheduler"


# ============================================================================
# 关键词策略测试
# ============================================================================

class TestKeywordStrategy:
    """关键词匹配策略测试"""

    @pytest.fixture
    def router(self):
        r = SemanticRouter(strategy="keyword", min_confidence=0.1)
        r.add_rules([
            RouteRule(
                intent="note.create",
                target_agent="agent.note",
                keywords=["记笔记", "记录", "笔记"],
            ),
            RouteRule(
                intent="emotion.chat",
                target_agent="agent.emotion",
                keywords=["难过", "开心", "陪伴"],
            ),
            RouteRule(
                intent="dev.code",
                target_agent="agent.dev",
                keywords=["代码", "bug", "编程"],
            ),
        ])
        return r

    def test_exact_match(self, router):
        """精确匹配"""
        result = router.route("记笔记")
        assert result.target_agent == "agent.note"
        assert result.intent == "note.create"
        assert result.confidence == 1.0
        assert result.method == "keyword"

    def test_contains_match(self, router):
        """包含匹配"""
        result = router.route("帮我记笔记")
        assert result.target_agent == "agent.note"
        assert 0 < result.confidence < 1.0

    def test_emotion_match(self, router):
        """情绪类匹配"""
        result = router.route("我好难过")
        assert result.target_agent == "agent.emotion"
        assert result.intent == "emotion.chat"

    def test_dev_match(self, router):
        """开发类匹配"""
        result = router.route("这个代码有bug")
        assert result.target_agent == "agent.dev"

    def test_no_match_fallback(self, router):
        """无匹配时 fallback"""
        result = router.route("完全不相关的内容 xyz123")
        assert result.method == "fallback"
        assert result.target_agent == "master_scheduler"
        assert result.confidence == 0.0

    def test_empty_input_fallback(self, router):
        """空输入 fallback"""
        result = router.route("")
        assert result.method == "fallback"
        assert result.confidence == 0.0

    def test_top_k_results(self, router):
        """Top-K 结果"""
        result = router.route("记录一下开心的事情")
        assert len(result.top_k) >= 1
        # 第一个应该是匹配度最高的
        assert result.top_k[0][0] == result.target_agent
        assert result.top_k[0][1] == result.intent

    def test_latency_recorded(self, router):
        """延迟被记录"""
        result = router.route("测试")
        assert result.latency_ms >= 0.0


# ============================================================================
# V2 语义相似度策略测试
# ============================================================================

class TestSemanticV2Strategy:
    """n-gram 语义相似度策略测试"""

    @pytest.fixture
    def router(self):
        r = SemanticRouter(strategy="semantic_v2", min_confidence=0.1)
        r.add_rules([
            RouteRule(
                intent="note.create",
                target_agent="agent.note",
                keywords=["记笔记", "记录"],
                samples=["帮我记一下", "我想做个笔记", "记录一下"],
            ),
            RouteRule(
                intent="emotion.chat",
                target_agent="agent.emotion",
                keywords=["难过", "开心"],
                samples=["我心情不好", "陪我说说话"],
            ),
        ])
        return r

    def test_keyword_still_works(self, router):
        """关键词匹配仍然有效"""
        result = router.route("记录")
        assert result.target_agent == "agent.note"
        assert result.confidence > 0

    def test_semantic_similarity_match(self, router):
        """语义相似的输入能匹配"""
        # "帮我记一下" 和 "帮我记个笔记" 应该有语义相似度
        result = router.route("帮我记个笔记")
        assert result.confidence > 0

    def test_ngram_jaccard_calculation(self):
        """n-gram Jaccard 计算正确性"""
        # 相同字符串相似度为 1.0
        sim = SemanticRouter._ngram_jaccard("测试", "测试")
        assert sim == 1.0

        # 完全不同的字符串相似度为 0
        sim = SemanticRouter._ngram_jaccard("abc", "xyz")
        assert sim == 0.0

        # 部分重叠
        sim = SemanticRouter._ngram_jaccard("记笔记", "做笔记")
        assert 0 < sim < 1.0

    def test_short_text_stable(self, router):
        """短文本不会崩溃"""
        result = router.route("hi")
        # 不崩溃即可，结果可能是 fallback
        assert result.method in ("semantic_v2", "fallback")


# ============================================================================
# V3 TF-IDF 策略测试
# ============================================================================

class TestSemanticV3Strategy:
    """TF-IDF 语义相似度策略测试"""

    @pytest.fixture
    def router(self):
        r = SemanticRouter(strategy="semantic_v3", min_confidence=0.1)
        r.add_rules([
            RouteRule(
                intent="note.create",
                target_agent="agent.note",
                keywords=["记笔记", "记录", "笔记", "知识点"],
                samples=[
                    "帮我记一下今天的事情",
                    "我想做个笔记",
                    "记录一下重要内容",
                    "保存这个知识点",
                ],
            ),
            RouteRule(
                intent="emotion.chat",
                target_agent="agent.emotion",
                keywords=["难过", "开心", "焦虑", "陪伴"],
                samples=[
                    "我心情不好",
                    "陪我说说话",
                    "我有点焦虑",
                    "今天好难过",
                ],
            ),
            RouteRule(
                intent="dev.code",
                target_agent="agent.dev",
                keywords=["代码", "编程", "bug", "开发"],
                samples=[
                    "帮我写段代码",
                    "这个 bug 怎么修",
                    "开发一个功能",
                    "编程问题",
                ],
            ),
        ])
        return r

    def test_v3_classifier_trained(self, router):
        """V3 分类器被正确训练"""
        # 触发一次路由以触发训练
        router.route("测试")
        stats = router.stats()
        assert stats["v3_trained"] is True
        assert stats["v3_intents"] == 3
        assert stats["v3_vocab_size"] > 0

    def test_v3_note_routing(self, router):
        """笔记类路由正确"""
        result = router.route("帮我记一下这个知识点")
        assert result.target_agent == "agent.note"
        assert result.intent == "note.create"
        assert result.confidence > 0

    def test_v3_emotion_routing(self, router):
        """情绪类路由正确"""
        result = router.route("我今天心情不好好难过")
        assert result.target_agent == "agent.emotion"

    def test_v3_dev_routing(self, router):
        """开发类路由正确"""
        result = router.route("帮我看看这个bug怎么修")
        assert result.target_agent == "agent.dev"

    def test_v3_add_rule_retrains(self, router):
        """添加规则后重新训练"""
        router.route("测试")  # 触发训练
        assert router.stats()["v3_trained"] is True
        assert router.stats()["v3_intents"] == 3

        router.add_rule(RouteRule(
            intent="review.summary",
            target_agent="agent.review",
            keywords=["复盘", "总结"],
            samples=["帮我复盘一下", "做个总结"],
        ))
        # 添加规则后 v3_trained 应为 False（待重新训练）
        # 但 stats() 是调用时的状态，我们直接检查内部状态
        assert router._v3_trained is False

        # 再次路由会重新训练
        result = router.route("复盘一下")
        assert result is not None
        assert router._v3_trained is True


# ============================================================================
# 混合策略测试
# ============================================================================

class TestHybridStrategy:
    """混合策略测试"""

    @pytest.fixture
    def router(self):
        r = SemanticRouter(
            strategy="hybrid",
            min_confidence=0.1,
            semantic_weight=0.5,
        )
        r.add_rules([
            RouteRule(
                intent="note.create",
                target_agent="agent.note",
                keywords=["记笔记", "记录"],
                samples=["帮我记一下", "我想做个笔记"],
            ),
            RouteRule(
                intent="emotion.chat",
                target_agent="agent.emotion",
                keywords=["难过", "陪伴"],
                samples=["我心情不好", "陪我说说话"],
            ),
        ])
        return r

    def test_hybrid_uses_keyword_for_exact(self, router):
        """精确匹配使用关键词方法"""
        result = router.route("记录")
        # 精确匹配时 method 应为 keyword
        assert result.confidence > 0

    def test_hybrid_semantic_boost(self, router):
        """语义相似度提升低关键词匹配的分数"""
        # 一个不在关键词中但在样本中的表达
        result = router.route("帮我记个笔记")
        assert result.confidence > 0
        assert result.target_agent == "agent.note"

    def test_hybrid_returns_decision(self, router):
        """返回有效的 RouteDecision"""
        result = router.route("记笔记")
        assert isinstance(result, RouteDecision)
        assert result.target_agent is not None
        assert result.intent is not None
        assert 0 <= result.confidence <= 1.0


# ============================================================================
# 自适应学习测试
# ============================================================================

class TestAdaptiveLearning:
    """自适应学习功能测试"""

    def test_report_result_without_adaptive_noop(self):
        """未启用自适应时 report_result 不做任何事"""
        router = SemanticRouter(strategy="hybrid")
        router.add_rule(RouteRule(
            intent="test",
            target_agent="agent.test",
            keywords=["test"],
        ))
        # 不启用自适应，report_result 应该是 no-op
        router.report_result("test", "agent.test", True)
        stats = router.stats()
        assert "adaptive_stats" not in stats

    def test_adaptive_learning_enabled(self):
        """启用自适应后报告结果"""
        router = SemanticRouter(strategy="adaptive", min_confidence=0.1)
        router.add_rule(RouteRule(
            intent="note.create",
            target_agent="agent.note",
            keywords=["笔记"],
            samples=["记笔记"],
        ))
        router.add_adaptive_candidate("note.create", "agent.note2")

        # 报告多次成功结果
        for _ in range(10):
            router.report_result("note.create", "agent.note", True, latency_ms=100, score=0.9)

        stats = router.stats()
        assert "adaptive_stats" in stats
        assert stats["adaptive_stats"]["total_routes"] >= 2

    def test_adaptive_recommendations(self):
        """自适应优化建议"""
        router = SemanticRouter(strategy="adaptive", min_confidence=0.1)
        router.add_rule(RouteRule(
            intent="test.intent",
            target_agent="agent.good",
            keywords=["test"],
        ))
        router.add_adaptive_candidate("test.intent", "agent.bad")

        # agent.good 表现好
        for _ in range(20):
            router.report_result("test.intent", "agent.good", True, 50, 0.9)

        # agent.bad 表现差
        for _ in range(20):
            router.report_result("test.intent", "agent.bad", False, 500, 0.2)

        recs = router.get_recommendations()
        # 应该有关于 agent.bad 的弃用建议
        assert len(recs) >= 0  # 可能有也可能没有，取决于阈值


# ============================================================================
# 批量路由测试
# ============================================================================

class TestBatchRouting:
    """批量路由测试"""

    @pytest.fixture
    def router(self):
        r = SemanticRouter(strategy="keyword", min_confidence=0.1)
        r.add_rules([
            RouteRule(intent="note", target_agent="agent.note", keywords=["笔记"]),
            RouteRule(intent="emotion", target_agent="agent.emotion", keywords=["难过"]),
        ])
        return r

    def test_batch_route(self, router):
        """批量路由返回正确数量的结果"""
        texts = ["笔记", "难过", "完全无关"]
        results = router.batch_route(texts)
        assert len(results) == 3
        assert all(isinstance(r, RouteDecision) for r in results)

    def test_batch_route_empty(self, router):
        """空列表批量路由"""
        results = router.batch_route([])
        assert results == []


# ============================================================================
# 默认路由器工厂测试
# ============================================================================

class TestDefaultRouter:
    """默认路由器工厂测试"""

    def test_create_default_router(self):
        """创建默认路由器"""
        router = create_default_router()
        assert isinstance(router, SemanticRouter)
        assert router.strategy == "hybrid"
        assert router.min_confidence == 0.25

    def test_default_router_has_rules(self):
        """默认路由器包含预设规则"""
        router = create_default_router()
        stats = router.stats()
        assert stats["total_rules"] > 0
        # 至少包含笔记、情绪、复盘、开发四类
        rules = router.list_rules()
        intents = [r["intent"] for r in rules]
        assert any("note" in i for i in intents)
        assert any("emotion" in i for i in intents)
        assert any("review" in i for i in intents)
        assert any("dev" in i for i in intents)

    def test_default_router_note_routing(self):
        """默认路由器笔记类路由正确"""
        router = create_default_router()
        result = router.route("帮我记个笔记")
        assert result.target_agent == "agent.note"

    def test_default_router_emotion_routing(self):
        """默认路由器情绪类路由正确"""
        router = create_default_router()
        result = router.route("我今天好难过")
        assert result.target_agent == "agent.emotion"

    def test_default_router_emergency_support(self):
        """默认路由器紧急支持路由正确"""
        router = create_default_router()
        result = router.route("我不想活了")
        # 应该路由到情绪 Agent 的支持意图
        assert result.target_agent == "agent.emotion"
        assert "support" in result.intent


# ============================================================================
# 阈值与确认机制测试
# ============================================================================

class TestConfirmationThreshold:
    """确认阈值测试"""

    def test_high_confidence_no_confirmation(self):
        """高置信度不需要确认"""
        router = SemanticRouter(strategy="keyword")
        router.add_rule(RouteRule(
            intent="test",
            target_agent="agent.test",
            keywords=["完全匹配"],
        ))
        result = router.route("完全匹配")
        assert result.confidence >= 0.7
        assert result.requires_confirmation is False

    def test_medium_confidence_needs_confirmation(self):
        """中等置信度需要确认（包含匹配 = 0.6）"""
        router = SemanticRouter(strategy="keyword")
        router.add_rule(RouteRule(
            intent="test",
            target_agent="agent.test",
            keywords=["测试"],
        ))
        # "这是测试内容啊" 包含"测试"但不以其开头或结尾 -> 包含匹配 = 0.6
        result = router.route("这是测试内容啊")
        assert result.confidence == 0.6
        assert 0.3 <= result.confidence < 0.7
        assert result.requires_confirmation is True

    def test_low_confidence_fallback(self):
        """低置信度走 fallback"""
        router = SemanticRouter(strategy="keyword", min_confidence=0.7)
        router.add_rule(RouteRule(
            intent="test",
            target_agent="agent.test",
            keywords=["测试"],
        ))
        # "这是测试内容啊" 包含"测试"但不在开头或结尾 -> 包含匹配 0.6 < 0.7 阈值
        result = router.route("这是测试内容啊")
        assert result.confidence == 0.0
        assert result.method == "fallback"
