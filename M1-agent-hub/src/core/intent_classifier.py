"""
云汐内核 - 多 Agent 集群调度系统
意图分类器模块

基于关键词匹配的意图识别引擎，
支持置信度计算、动态规则添加/删除。
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from src.tools.interfaces import ClassifyResult

logger = structlog.get_logger(__name__)


class IntentClassifier:
    """意图分类器

    基于关键词匹配进行意图识别，支持：
    - 精确匹配、前缀/后缀匹配、包含匹配三种模式
    - 置信度计算与阈值决策
    - 运行时动态添加/删除意图映射规则
    """

    def __init__(self) -> None:
        self._rules: list[IntentRule] = []
        """意图映射规则列表"""
        self._init_default_rules()
        self._logger = logger.bind(service="intent_classifier")

    def _init_default_rules(self) -> None:
        """初始化默认意图映射规则"""
        default_rules = [
            # ── 笔记相关 ──
            IntentRule(
                keywords=["记笔记", "记录", "笔记", "知识点", "整理笔记"],
                target_agent="agent.note",
                intent="note.create",
            ),
            IntentRule(
                keywords=["查笔记", "找笔记", "笔记在哪", "搜索笔记", "我的笔记"],
                target_agent="agent.note",
                intent="note.search",
            ),
            # ── 情绪相关 ──
            IntentRule(
                keywords=["难过", "开心", "焦虑", "陪伴", "聊聊", "心情"],
                target_agent="agent.emotion",
                intent="emotion.chat",
            ),
            IntentRule(
                keywords=["情绪日记", "心情记录", "记录心情"],
                target_agent="agent.emotion",
                intent="emotion.diary",
            ),
            IntentRule(
                keywords=["自杀", "绝望", "不想活", "活不下去", "没有意义"],
                target_agent="agent.emotion",
                intent="emotion.support",
            ),
            # ── 复盘相关 ──
            IntentRule(
                keywords=["复盘", "总结", "回顾", "进步", "反思"],
                target_agent="agent.review",
                intent="review.summary",
            ),
            IntentRule(
                keywords=["目标", "进度", "计划", "完成情况", "里程碑"],
                target_agent="agent.review",
                intent="review.goal",
            ),
            # ── 开发相关 ──
            IntentRule(
                keywords=["代码", "编程", "bug", "项目", "开发"],
                target_agent="agent.dev",
                intent="dev.code",
            ),
            IntentRule(
                keywords=["怎么实现", "原理", "架构", "技术选型", "方案设计"],
                target_agent="agent.dev",
                intent="dev.qa",
            ),
            IntentRule(
                keywords=["技术决策", "选型", "方案对比"],
                target_agent="agent.dev",
                intent="dev.decision",
            ),
        ]
        self._rules.extend(default_rules)

    # ── 规则管理 ──────────────────────────────────────────

    def add_rule(self, rule: IntentRule) -> None:
        """动态添加意图映射规则"""
        self._rules.append(rule)
        self._logger.info(
            "rule_added",
            target_agent=rule.target_agent,
            intent=rule.intent,
            keywords_count=len(rule.keywords),
        )

    def remove_rule(self, target_agent: str, intent: str) -> bool:
        """删除指定的意图映射规则

        Returns:
            是否成功删除
        """
        original_len = len(self._rules)
        self._rules = [
            r
            for r in self._rules
            if not (r.target_agent == target_agent and r.intent == intent)
        ]
        removed = len(self._rules) < original_len
        if removed:
            self._logger.info("rule_removed", target_agent=target_agent, intent=intent)
        return removed

    def list_rules(self) -> list[IntentRule]:
        """列出所有意图映射规则"""
        return list(self._rules)

    # ── 分类逻辑 ──────────────────────────────────────────

    def classify(self, user_input: str) -> ClassifyResult:
        """对用户输入进行意图分类

        Args:
            user_input: 用户输入的文本

        Returns:
            ClassifyResult: 分类结果，包含目标 Agent、意图、置信度等
        """
        if not user_input or not user_input.strip():
            return ClassifyResult(
                target_agent="master_scheduler",
                intent="general.fallback",
                confidence=0.0,
                requires_confirmation=False,
            )

        input_lower = user_input.strip().lower()
        best_result: ClassifyResult | None = None

        for rule in self._rules:
            keyword_confidences: list[float] = []
            for keyword in rule.keywords:
                kw_lower = keyword.lower()
                confidence = self._calc_confidence(input_lower, kw_lower, keyword)
                if confidence > 0:
                    keyword_confidences.append(confidence)

            if not keyword_confidences:
                continue

            max_conf = max(keyword_confidences)

            if best_result is None or max_conf > best_result.confidence:
                requires_confirm = 0.4 <= max_conf < 0.7
                best_result = ClassifyResult(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=max_conf,
                    requires_confirmation=requires_confirm,
                )

        # 未匹配任何规则
        if best_result is None:
            best_result = ClassifyResult(
                target_agent="master_scheduler",
                intent="general.fallback",
                confidence=0.0,
                requires_confirmation=False,
            )

        self._logger.debug(
            "intent_classified",
            user_input=user_input[:50],
            target_agent=best_result.target_agent,
            intent=best_result.intent,
            confidence=best_result.confidence,
            requires_confirmation=best_result.requires_confirmation,
        )

        return best_result

    def _calc_confidence(
        self, input_lower: str, kw_lower: str, original_kw: str
    ) -> float:
        """计算用户输入与关键词的匹配置信度

        匹配模式优先级：
        - 精确匹配（完全相同）= 1.0
        - 前缀匹配（输入以关键词开头）= 0.8
        - 后缀匹配（输入以关键词结尾）= 0.8
        - 包含匹配（关键词在输入中）= 0.6
        """
        # 精确匹配
        if input_lower == kw_lower:
            return 1.0

        # 前缀匹配
        if input_lower.startswith(kw_lower):
            return 0.8

        # 后缀匹配
        if input_lower.endswith(kw_lower):
            return 0.8

        # 包含匹配
        if kw_lower in input_lower:
            return 0.6

        return 0.0


class IntentRule:
    """意图映射规则

    定义一组关键词与其对应的目标 Agent 和意图标签。
    """

    def __init__(
        self,
        keywords: list[str],
        target_agent: str,
        intent: str,
    ) -> None:
        self.keywords = keywords
        self.target_agent = target_agent
        self.intent = intent

    def __repr__(self) -> str:
        return (
            f"IntentRule(keywords={self.keywords}, "
            f"target_agent='{self.target_agent}', intent='{self.intent}')"
        )