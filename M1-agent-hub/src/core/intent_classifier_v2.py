"""
云汐内核 V2 - 语义意图分类器

在 V1 关键词匹配的基础上，增加语义相似度计算能力。
支持同义词扩展、口语化表达理解、语义召回。

生产环境可接入 LLM 或 Embedding 模型进行语义理解，
当前实现使用轻量级的语义相似度算法（基于字符 n-gram + Jaccard），
作为无外部依赖的基线方案。
"""

from __future__ import annotations

from typing import Any

import structlog
from src.tools.interfaces import ClassifyResult
from src.core.intent_classifier import IntentClassifier, IntentRule

logger = structlog.get_logger(__name__)


class SemanticIntentClassifier(IntentClassifier):
    """语义意图分类器（V2 升级）

    继承 V1 的关键词匹配能力，叠加语义相似度计算，
    显著提升对同义词、口语化表达的识别准确率。
    """

    # 同义词扩展映射
    SYNONYMS: dict[str, list[str]] = {
        "记笔记": ["记下来", "做个笔记", "写笔记", "记一下", "记录下来"],
        "难过": ["伤心", "难受", "不开心", "低落", "抑郁"],
        "开心": ["高兴", "快乐", "兴奋", "喜悦", "愉快"],
        "焦虑": ["着急", "不安", "担心", "紧张", "心慌"],
        "复盘": ["回顾", "反思", "总结", "复盘一下"],
        "目标": ["计划", "规划", "打算", "志向", "理想"],
        "代码": ["程序", "脚本", "编程", "写代码", "coding"],
        "bug": ["报错", "错误", "异常", "故障", "缺陷"],
        "陪伴": ["聊天", "说话", "谈心", "倾诉", "聊聊"],
    }

    def __init__(self, semantic_weight: float = 0.3) -> None:
        """初始化语义分类器

        Args:
            semantic_weight: 语义分数在最终置信度中的权重（0-1）
        """
        super().__init__()
        self.semantic_weight = semantic_weight
        self._keyword_weight = 1.0 - semantic_weight
        self._logger = logger.bind(service="intent_classifier_v2")

    def classify(self, user_input: str) -> ClassifyResult:
        """语义分类主入口

        结合关键词匹配和语义相似度计算最终置信度。
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
            semantic_confidences: list[float] = []

            for keyword in rule.keywords:
                kw_lower = keyword.lower()
                # V1: 关键词匹配
                kw_conf = self._calc_confidence(input_lower, kw_lower, keyword)
                if kw_conf > 0:
                    keyword_confidences.append(kw_conf)

                # V2: 语义相似度
                sem_conf = self._calc_semantic_similarity(input_lower, keyword)
                if sem_conf > 0:
                    semantic_confidences.append(sem_conf)

                # V2: 同义词扩展匹配
                for synonym in self._get_synonyms(keyword):
                    syn_conf = self._calc_confidence(input_lower, synonym.lower(), synonym)
                    if syn_conf > 0:
                        keyword_confidences.append(syn_conf * 0.9)  # 同义词略降权

            # 融合置信度
            kw_max = max(keyword_confidences) if keyword_confidences else 0.0
            sem_max = max(semantic_confidences) if semantic_confidences else 0.0

            # 如果语义分数高但关键词分数低，给予一定补偿
            fused_conf = self._fuse_confidence(kw_max, sem_max)

            if fused_conf <= 0:
                continue

            if best_result is None or fused_conf > best_result.confidence:
                requires_confirm = 0.4 <= fused_conf < 0.7
                best_result = ClassifyResult(
                    target_agent=rule.target_agent,
                    intent=rule.intent,
                    confidence=round(fused_conf, 3),
                    requires_confirmation=requires_confirm,
                )

        if best_result is None:
            best_result = ClassifyResult(
                target_agent="master_scheduler",
                intent="general.fallback",
                confidence=0.0,
                requires_confirmation=False,
            )

        self._logger.debug(
            "intent_classified_v2",
            user_input=user_input[:50],
            target_agent=best_result.target_agent,
            intent=best_result.intent,
            confidence=best_result.confidence,
        )

        return best_result

    def _fuse_confidence(self, keyword_conf: float, semantic_conf: float) -> float:
        """融合关键词和语义置信度"""
        # 如果关键词匹配已很高，优先使用关键词
        if keyword_conf >= 0.8:
            return keyword_conf
        # 如果语义匹配很高，给予语义补偿
        if semantic_conf >= 0.7:
            return max(keyword_conf, semantic_conf * 0.85)
        # 线性融合
        return self._keyword_weight * keyword_conf + self.semantic_weight * semantic_conf

    def _get_synonyms(self, keyword: str) -> list[str]:
        """获取关键词的同义词列表"""
        return self.SYNONYMS.get(keyword, [])

    def _calc_semantic_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的语义相似度

        使用字符级 n-gram Jaccard 相似度作为轻量级语义代理。
        生产环境可替换为 embedding cosine similarity。
        """
        # 生成字符 n-gram
        def ngrams(s: str, n: int = 2) -> set[str]:
            return set(s[i:i + n] for i in range(len(s) - n + 1))

        grams1 = ngrams(text1, 2) | ngrams(text1, 3)
        grams2 = ngrams(text2, 2) | ngrams(text2, 3)

        if not grams1 or not grams2:
            return 0.0

        intersection = len(grams1 & grams2)
        union = len(grams1 | grams2)

        if union == 0:
            return 0.0

        return round(intersection / union, 3)

    def _calc_confidence(self, input_lower: str, kw_lower: str, original_kw: str) -> float:
        """复用 V1 的关键词匹配置信度计算"""
        return super()._calc_confidence(input_lower, kw_lower, original_kw)
