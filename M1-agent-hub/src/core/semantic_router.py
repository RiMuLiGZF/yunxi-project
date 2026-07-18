"""
云汐内核 V12.1 - 语义路由器（Semantic Router）

整合 V1/V2/V3 三代意图分类器与自适应路由优化器，
提供端到端的语义路由决策能力：
文本输入 -> 语义相似度匹配 -> 意图分类 -> 路由决策 -> 目标 Agent

核心设计：
- 分层漏斗：关键词粗筛 -> TF-IDF 语义匹配 -> （可选）LLM 精筛
- 多策略融合：支持关键词、语义、同义词、自适应多维度打分
- 可插拔：不同场景可选择不同分类器组合
- 自适应学习：根据执行结果动态调整路由权重

参考：
- https://github.com/aurelio-labs/semantic-router
- https://truto.one/blog/how-to-implement-semantic-routing-for-ai-agents/
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RouteDecision:
    """路由决策结果"""

    target_agent: str
    intent: str
    confidence: float
    method: str  # "keyword" | "semantic_v2" | "semantic_v3" | "adaptive" | "fallback"
    top_k: list[tuple[str, str, float]] = field(default_factory=list)
    # [(target_agent, intent, score), ...]
    latency_ms: float = 0.0
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteRule:
    """路由规则"""

    intent: str
    target_agent: str
    keywords: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    """语义训练样本"""
    enabled: bool = True
    priority: int = 0


class SemanticRouter:
    """语义路由器（统一入口）

    整合多层分类器，提供最优路由决策。

    使用方式::

        router = SemanticRouter(strategy="hybrid")
        router.add_rule(RouteRule(
            intent="note.create",
            target_agent="agent.note",
            keywords=["记笔记", "记录", "笔记"],
            samples=["帮我记一下今天的事情", "我想做个笔记"],
        ))
        decision = router.route("帮我记个笔记")
        print(decision.target_agent)  # "agent.note"
    """

    STRATEGIES = {"keyword", "semantic_v2", "semantic_v3", "hybrid", "adaptive"}

    def __init__(
        self,
        strategy: str = "hybrid",
        min_confidence: float = 0.3,
        semantic_weight: float = 0.5,
        enable_adaptive: bool = False,
    ) -> None:
        """初始化语义路由器

        Args:
            strategy: 路由策略
                - keyword: 仅关键词匹配（最快，最低资源）
                - semantic_v2: n-gram 语义相似度
                - semantic_v3: TF-IDF 余弦相似度
                - hybrid: 关键词 + 语义融合（默认）
                - adaptive: 混合 + 自适应学习
            min_confidence: 最低置信度阈值
            semantic_weight: 语义分数在混合策略中的权重
            enable_adaptive: 是否启用自适应学习
        """
        if strategy not in self.STRATEGIES:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Supported: {', '.join(sorted(self.STRATEGIES))}"
            )

        self.strategy = strategy
        self.min_confidence = min_confidence
        self.semantic_weight = semantic_weight
        self.enable_adaptive = enable_adaptive or strategy == "adaptive"

        self._rules: list[RouteRule] = []
        self._keyword_weight = 1.0 - semantic_weight

        # V3 TF-IDF 分类器（懒加载）
        self._v3_classifier = None
        self._v3_trained = False

        # 自适应路由器（懒加载）
        self._adaptive_router = None

        self._logger = logger.bind(service="semantic_router")

    # ── 规则管理 ──────────────────────────────────────────

    def add_rule(self, rule: RouteRule) -> None:
        """添加路由规则"""
        self._rules.append(rule)
        self._v3_trained = False  # 标记需要重新训练
        self._logger.info(
            "route_rule_added",
            intent=rule.intent,
            target_agent=rule.target_agent,
            keywords_count=len(rule.keywords),
            samples_count=len(rule.samples),
        )

    def add_rules(self, rules: list[RouteRule]) -> None:
        """批量添加路由规则"""
        for rule in rules:
            self._rules.append(rule)
        self._v3_trained = False
        self._logger.info("route_rules_added", count=len(rules))

    def remove_rule(self, intent: str, target_agent: str) -> bool:
        """移除路由规则

        Returns:
            是否成功移除
        """
        original_len = len(self._rules)
        self._rules = [
            r for r in self._rules
            if not (r.intent == intent and r.target_agent == target_agent)
        ]
        removed = len(self._rules) < original_len
        if removed:
            self._v3_trained = False
            self._logger.info("route_rule_removed", intent=intent, target_agent=target_agent)
        return removed

    def list_rules(self) -> list[dict[str, Any]]:
        """列出所有路由规则"""
        return [
            {
                "intent": r.intent,
                "target_agent": r.target_agent,
                "keywords_count": len(r.keywords),
                "samples_count": len(r.samples),
                "enabled": r.enabled,
                "priority": r.priority,
            }
            for r in self._rules
        ]

    # ── V1: 关键词匹配 ────────────────────────────────────

    def _keyword_match(self, text: str) -> list[tuple[RouteRule, float]]:
        """关键词匹配打分"""
        results = []
        text_lower = text.lower()

        for rule in self._rules:
            if not rule.enabled:
                continue
            best_score = 0.0
            for kw in rule.keywords:
                kw_lower = kw.lower()
                score = self._keyword_score(text_lower, kw_lower)
                if score > best_score:
                    best_score = score
            if best_score > 0:
                results.append((rule, best_score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    @staticmethod
    def _keyword_score(text: str, keyword: str) -> float:
        """关键词匹配置信度"""
        if text == keyword:
            return 1.0
        if text.startswith(keyword) or text.endswith(keyword):
            return 0.8
        if keyword in text:
            return 0.6
        return 0.0

    # ── V2: n-gram 语义相似度 ────────────────────────────

    def _semantic_v2_match(self, text: str) -> list[tuple[RouteRule, float]]:
        """n-gram Jaccard 语义相似度匹配"""
        results = []

        for rule in self._rules:
            if not rule.enabled:
                continue
            best_score = 0.0

            # 与关键词比较
            for kw in rule.keywords:
                sim = self._ngram_jaccard(text, kw)
                if sim > best_score:
                    best_score = sim

            # 与样本比较
            for sample in rule.samples:
                sim = self._ngram_jaccard(text, sample)
                if sim > best_score:
                    best_score = sim

            if best_score > 0:
                results.append((rule, best_score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    @staticmethod
    def _ngram_jaccard(text1: str, text2: str, n: int = 2) -> float:
        """字符 n-gram Jaccard 相似度"""
        def grams(s: str) -> set[str]:
            return set(s[i:i + n] for i in range(len(s) - n + 1))

        g1 = grams(text1.lower())
        g2 = grams(text2.lower())
        if not g1 or not g2:
            return 0.0
        intersection = len(g1 & g2)
        union = len(g1 | g2)
        return intersection / union if union > 0 else 0.0

    # ── V3: TF-IDF 余弦相似度 ────────────────────────────

    def _ensure_v3_trained(self) -> None:
        """确保 V3 分类器已训练"""
        if self._v3_trained and self._v3_classifier is not None:
            return

        try:
            from src.core.semantic_intent_v3 import SemanticIntentClassifierV3
        except ImportError:
            from semantic_intent_v3 import SemanticIntentClassifierV3

        self._v3_classifier = SemanticIntentClassifierV3(
            min_confidence=self.min_confidence,
            top_k=5,
        )

        # 构建训练样本：intent -> [keywords + samples]
        samples: dict[str, list[str]] = {}
        for rule in self._rules:
            if not rule.enabled:
                continue
            key = f"{rule.target_agent}::{rule.intent}"
            samples[key] = list(rule.keywords) + list(rule.samples)

        if samples:
            self._v3_classifier.train(samples)
            self._v3_trained = True

    def _semantic_v3_match(self, text: str) -> list[tuple[RouteRule, float]]:
        """TF-IDF 余弦相似度匹配"""
        self._ensure_v3_trained()
        if self._v3_classifier is None:
            return []

        result = self._v3_classifier.classify(text)
        top_k = result.get("top_k", [])

        # 解码 intent key -> (target_agent, intent)
        decoded = []
        for intent_key, score in top_k:
            if "::" in intent_key:
                target_agent, intent = intent_key.split("::", 1)
            else:
                target_agent, intent = "unknown", intent_key

            # 找到对应的 rule
            rule = next(
                (r for r in self._rules
                 if r.intent == intent and r.target_agent == target_agent),
                None,
            )
            if rule is not None:
                decoded.append((rule, score))

        return decoded

    # ── 混合策略融合 ──────────────────────────────────────

    def _hybrid_match(self, text: str) -> list[tuple[RouteRule, float, str]]:
        """混合策略：关键词 + 语义融合

        Returns:
            [(rule, fused_score, method), ...]
        """
        keyword_matches = self._keyword_match(text)
        semantic_matches = self._semantic_v2_match(text)

        # 用 intent+target_agent 作为 key 进行合并
        kw_map: dict[str, tuple[RouteRule, float]] = {}
        for rule, score in keyword_matches:
            key = f"{rule.target_agent}::{rule.intent}"
            kw_map[key] = (rule, score)

        sem_map: dict[str, tuple[RouteRule, float]] = {}
        for rule, score in semantic_matches:
            key = f"{rule.target_agent}::{rule.intent}"
            sem_map[key] = (rule, score)

        all_keys = set(kw_map.keys()) | set(sem_map.keys())
        fused = []

        for key in all_keys:
            rule = kw_map.get(key, sem_map[key])[0]
            kw_score = kw_map.get(key, (None, 0.0))[1]
            sem_score = sem_map.get(key, (None, 0.0))[1]

            # 关键词精确匹配优先
            if kw_score >= 0.8:
                fused_score = kw_score
                method = "keyword"
            elif sem_score >= 0.7 and kw_score < 0.3:
                # 语义高分但关键词低分，给予语义补偿
                fused_score = sem_score * 0.85
                method = "semantic_v2"
            else:
                # 加权融合
                fused_score = (
                    self._keyword_weight * kw_score
                    + self.semantic_weight * sem_score
                )
                method = "hybrid"

            fused.append((rule, fused_score, method))

        fused.sort(key=lambda x: x[1], reverse=True)
        return fused

    # ── 主路由入口 ────────────────────────────────────────

    def route(self, text: str) -> RouteDecision:
        """对输入文本进行语义路由决策

        Args:
            text: 用户输入文本

        Returns:
            RouteDecision 路由决策结果
        """
        start = time.time()

        if not text or not text.strip():
            return RouteDecision(
                target_agent="master_scheduler",
                intent="general.fallback",
                confidence=0.0,
                method="fallback",
                latency_ms=0.0,
                requires_confirmation=False,
            )

        text = text.strip()

        # 根据策略选择匹配方法
        if self.strategy == "keyword":
            matches = self._keyword_match(text)
            if matches and matches[0][1] >= self.min_confidence:
                rule, score = matches[0]
                top_k = [(r.target_agent, r.intent, s) for r, s in matches[:5]]
                latency = (time.time() - start) * 1000
                return RouteDecision(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=round(score, 4),
                    method="keyword",
                    top_k=top_k,
                    latency_ms=round(latency, 2),
                    requires_confirmation=self.min_confidence <= score < 0.7,
                )

        elif self.strategy == "semantic_v2":
            matches = self._semantic_v2_match(text)
            if matches and matches[0][1] >= self.min_confidence:
                rule, score = matches[0]
                top_k = [(r.target_agent, r.intent, s) for r, s in matches[:5]]
                latency = (time.time() - start) * 1000
                return RouteDecision(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=round(score, 4),
                    method="semantic_v2",
                    top_k=top_k,
                    latency_ms=round(latency, 2),
                    requires_confirmation=self.min_confidence <= score < 0.7,
                )

        elif self.strategy == "semantic_v3":
            matches = self._semantic_v3_match(text)
            if matches and matches[0][1] >= self.min_confidence:
                rule, score = matches[0]
                top_k = [(r.target_agent, r.intent, s) for r, s in matches[:5]]
                latency = (time.time() - start) * 1000
                return RouteDecision(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=round(score, 4),
                    method="semantic_v3",
                    top_k=top_k,
                    latency_ms=round(latency, 2),
                    requires_confirmation=self.min_confidence <= score < 0.7,
                )

        elif self.strategy in ("hybrid", "adaptive"):
            matches = self._hybrid_match(text)
            if matches and matches[0][1] >= self.min_confidence:
                rule, score, method = matches[0]
                top_k = [(r.target_agent, r.intent, s) for r, s, _ in matches[:5]]

                # 自适应路由：如果启用且有多个候选，可能调整选择
                if self.enable_adaptive and self._adaptive_router is not None:
                    selected_agent, is_exploration = self._adaptive_router.select_agent(
                        intent=rule.intent,
                        default_agent=rule.target_agent,
                    )
                    if selected_agent != rule.target_agent:
                        # 自适应调整了目标 Agent
                        rule = next(
                            (r for r in self._rules
                             if r.intent == rule.intent and r.target_agent == selected_agent),
                            rule,
                        )
                        method = "adaptive"

                latency = (time.time() - start) * 1000
                return RouteDecision(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=round(score, 4),
                    method=method,
                    top_k=top_k,
                    latency_ms=round(latency, 2),
                    requires_confirmation=self.min_confidence <= score < 0.7,
                )

        # Fallback
        latency = (time.time() - start) * 1000
        return RouteDecision(
            target_agent="master_scheduler",
            intent="general.fallback",
            confidence=0.0,
            method="fallback",
            latency_ms=round(latency, 2),
            requires_confirmation=False,
        )

    def batch_route(self, texts: list[str]) -> list[RouteDecision]:
        """批量路由"""
        return [self.route(t) for t in texts]

    # ── 自适应学习 ────────────────────────────────────────

    def report_result(
        self,
        intent: str,
        target_agent: str,
        success: bool,
        latency_ms: float = 0.0,
        score: float = 0.0,
    ) -> None:
        """报告路由执行结果，用于自适应学习

        Args:
            intent: 意图标签
            target_agent: 目标 Agent
            success: 是否成功
            latency_ms: 执行延迟（毫秒）
            score: 质量评分（0-1）
        """
        if not self.enable_adaptive:
            return

        if self._adaptive_router is None:
            try:
                from src.core.adaptive_router import AdaptiveRouter
            except ImportError:
                from adaptive_router import AdaptiveRouter
            self._adaptive_router = AdaptiveRouter()

        # 确保路由已注册
        self._adaptive_router.register_route(intent, target_agent)
        self._adaptive_router.report_result(
            intent=intent,
            target_agent=target_agent,
            success=success,
            latency_ms=latency_ms,
            score=score,
        )

    def add_adaptive_candidate(self, intent: str, target_agent: str) -> None:
        """添加自适应候选 Agent"""
        if self._adaptive_router is None:
            try:
                from src.core.adaptive_router import AdaptiveRouter
            except ImportError:
                from adaptive_router import AdaptiveRouter
            self._adaptive_router = AdaptiveRouter()

        self._adaptive_router.register_route(intent, target_agent)

    # ── 统计信息 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """获取路由器统计信息"""
        enabled_rules = [r for r in self._rules if r.enabled]
        stats_dict: dict[str, Any] = {
            "strategy": self.strategy,
            "min_confidence": self.min_confidence,
            "total_rules": len(self._rules),
            "enabled_rules": len(enabled_rules),
            "total_keywords": sum(len(r.keywords) for r in enabled_rules),
            "total_samples": sum(len(r.samples) for r in enabled_rules),
            "v3_trained": self._v3_trained,
            "adaptive_enabled": self.enable_adaptive,
        }

        if self._adaptive_router is not None:
            stats_dict["adaptive_stats"] = self._adaptive_router.get_route_stats()

        if self._v3_classifier is not None and self._v3_trained:
            v3_stats = self._v3_classifier.stats()
            stats_dict["v3_vocab_size"] = v3_stats.get("vocab_size", 0)
            stats_dict["v3_intents"] = v3_stats.get("intents_count", 0)

        return stats_dict

    def get_recommendations(self) -> list[dict[str, Any]]:
        """获取路由优化建议"""
        if self._adaptive_router is None:
            return []
        return self._adaptive_router.get_recommendations()


# ── 便捷工厂函数 ──────────────────────────────────────────


def create_default_router() -> SemanticRouter:
    """创建默认配置的语义路由器（内置云汐常用意图）

    包含笔记、情绪、复盘、开发等常用意图的路由规则。
    """
    router = SemanticRouter(strategy="hybrid", min_confidence=0.25)

    default_rules = [
        # 笔记
        RouteRule(
            intent="note.create",
            target_agent="agent.note",
            keywords=["记笔记", "记录", "笔记", "知识点", "整理笔记"],
            samples=[
                "帮我记一下",
                "我想做个笔记",
                "记录今天的事情",
                "保存这个知识点",
            ],
            priority=1,
        ),
        RouteRule(
            intent="note.search",
            target_agent="agent.note",
            keywords=["查笔记", "找笔记", "笔记在哪", "搜索笔记", "我的笔记"],
            samples=[
                "帮我找一下之前的笔记",
                "我记得记过这个",
                "搜索笔记内容",
            ],
            priority=1,
        ),
        # 情绪
        RouteRule(
            intent="emotion.chat",
            target_agent="agent.emotion",
            keywords=["难过", "开心", "焦虑", "陪伴", "聊聊", "心情"],
            samples=[
                "我心情不好",
                "陪我说说话",
                "我有点焦虑",
                "今天好难过",
            ],
            priority=1,
        ),
        RouteRule(
            intent="emotion.support",
            target_agent="agent.emotion",
            keywords=["自杀", "绝望", "不想活", "活不下去", "没有意义"],
            samples=[
                "我不想活了",
                "活着没有意义",
                "感觉很绝望",
            ],
            priority=10,
        ),
        # 复盘
        RouteRule(
            intent="review.summary",
            target_agent="agent.review",
            keywords=["复盘", "总结", "回顾", "进步", "反思"],
            samples=[
                "帮我复盘一下今天",
                "回顾一下这周的收获",
                "做个总结",
            ],
            priority=1,
        ),
        RouteRule(
            intent="review.goal",
            target_agent="agent.review",
            keywords=["目标", "进度", "计划", "完成情况", "里程碑"],
            samples=[
                "我的目标完成得怎么样",
                "看看计划进度",
                "还有多少没完成",
            ],
            priority=1,
        ),
        # 开发
        RouteRule(
            intent="dev.code",
            target_agent="agent.dev",
            keywords=["代码", "编程", "bug", "项目", "开发"],
            samples=[
                "帮我写段代码",
                "这个 bug 怎么修",
                "帮我看看这个程序",
            ],
            priority=1,
        ),
        RouteRule(
            intent="dev.qa",
            target_agent="agent.dev",
            keywords=["怎么实现", "原理", "架构", "技术选型", "方案设计"],
            samples=[
                "这个功能怎么实现",
                "原理是什么",
                "技术方案怎么选",
            ],
            priority=1,
        ),
    ]

    router.add_rules(default_rules)
    return router
