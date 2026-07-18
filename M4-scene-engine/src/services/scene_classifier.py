"""场景分类器.

实现多层级场景分类：
1. 基于规则的基线分类 - if-else 决策树，快速可解释
2. 基于统计的分类 - 朴素贝叶斯，用户历史数据训练
3. 集成分类 - 规则 + 统计结果加权融合
4. 在线学习 - 用户反馈更新模型，增量学习

使用方式::

    classifier = SceneClassifier()
    result = classifier.classify(features)
    print(result["scene"], result["confidence"])
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from src.models import SCENE_DEFINITIONS


# ---------------------------------------------------------------------------
# 分类结果数据类
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """分类结果."""

    scene: str
    confidence: float
    method: str
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""
    feature_contributions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "scene": self.scene,
            "confidence": round(self.confidence, 4),
            "method": self.method,
            "candidates": [
                {"scene": s, "confidence": round(c, 4)}
                for s, c in self.candidates
            ],
            "reason": self.reason,
            "feature_contributions": {
                k: round(v, 4)
                for k, v in self.feature_contributions.items()
            },
        }


# ---------------------------------------------------------------------------
# 规则引擎
# ---------------------------------------------------------------------------

class RuleBasedClassifier:
    """基于规则的场景分类器.

    使用 if-else 决策树进行场景分类，规则可配置、可解释。
    优点：快速、可解释、无需训练
    缺点：灵活性有限，需要人工配置规则
    """

    def __init__(self) -> None:
        """初始化规则分类器."""
        self._rules: list[dict[str, Any]] = []
        self._init_default_rules()

    def _init_default_rules(self) -> None:
        """初始化默认规则集."""
        self._rules = [
            # 工作开发场景
            {
                "scene": "work_dev",
                "conditions": [
                    {"feature": "location_type", "op": "eq", "value": "office", "weight": 0.3},
                    {"feature": "active_app", "op": "contains_any",
                     "value": ["code", "vscode", "idea", "eclipse"], "weight": 0.3},
                    {"feature": "conversation_topic", "op": "eq", "value": "work", "weight": 0.2},
                    {"feature": "busyness_level", "op": "gt", "value": 0.5, "weight": 0.1},
                    {"feature": "time_period", "op": "eq", "value": "morning", "weight": 0.05},
                    {"feature": "time_period", "op": "eq", "value": "afternoon", "weight": 0.05},
                ],
                "priority": 10,
            },
            # 学习场景
            {
                "scene": "study_plan",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "study", "weight": 0.4},
                    {"feature": "active_app", "op": "contains_any",
                     "value": ["notion", "obsidian", "pdf", "reader"], "weight": 0.2},
                    {"feature": "location_type", "op": "eq", "value": "office", "weight": 0.1},
                    {"feature": "time_period", "op": "eq", "value": "evening", "weight": 0.1},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.1},
                ],
                "priority": 9,
            },
            # 学习（learning 通用学习）
            {
                "scene": "learning",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "study", "weight": 0.35},
                    {"feature": "busyness_level", "op": "gt", "value": 0.3, "weight": 0.15},
                    {"feature": "time_period", "op": "eq", "value": "morning", "weight": 0.1},
                ],
                "priority": 8,
            },
            # 生活管理场景
            {
                "scene": "life_management",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "life", "weight": 0.4},
                    {"feature": "location_type", "op": "eq", "value": "home", "weight": 0.2},
                    {"feature": "time_period", "op": "eq", "value": "evening", "weight": 0.1},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.15},
                ],
                "priority": 7,
            },
            # 创意创作场景
            {
                "scene": "creative",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "creative", "weight": 0.4},
                    {"feature": "active_app", "op": "contains_any",
                     "value": ["photoshop", "figma", "design", "procreate"], "weight": 0.25},
                    {"feature": "mood_tendency", "op": "eq", "value": "positive", "weight": 0.1},
                    {"feature": "time_period", "op": "eq", "value": "evening", "weight": 0.05},
                ],
                "priority": 7,
            },
            # 情绪陪伴场景
            {
                "scene": "emotion_comfort",
                "conditions": [
                    {"feature": "mood_tendency", "op": "eq", "value": "negative", "weight": 0.4},
                    {"feature": "fatigue_level", "op": "gt", "value": 0.6, "weight": 0.2},
                    {"feature": "time_period", "op": "eq", "value": "late_night", "weight": 0.15},
                    {"feature": "location_type", "op": "eq", "value": "home", "weight": 0.1},
                ],
                "priority": 8,
            },
            # 成长场景
            {
                "scene": "growth",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "study", "weight": 0.2},
                    {"feature": "busyness_level", "op": "lt", "value": 0.4, "weight": 0.1},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.15},
                ],
                "priority": 5,
            },
            # 复盘总结场景
            {
                "scene": "review",
                "conditions": [
                    {"feature": "time_period", "op": "eq", "value": "evening", "weight": 0.2},
                    {"feature": "time_period", "op": "eq", "value": "late_night", "weight": 0.15},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.15},
                    {"feature": "busyness_level", "op": "lt", "value": 0.5, "weight": 0.1},
                ],
                "priority": 4,
            },
            # 社交场景
            {
                "scene": "social_relation",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "social", "weight": 0.4},
                    {"feature": "location_type", "op": "eq", "value": "outdoor", "weight": 0.15},
                    {"feature": "mood_tendency", "op": "eq", "value": "positive", "weight": 0.1},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.15},
                ],
                "priority": 6,
            },
            # 形象工坊
            {
                "scene": "appearance",
                "conditions": [
                    {"feature": "conversation_topic", "op": "eq", "value": "creative", "weight": 0.15},
                    {"feature": "location_type", "op": "eq", "value": "home", "weight": 0.1},
                    {"feature": "is_weekend", "op": "eq", "value": 1, "weight": 0.1},
                ],
                "priority": 3,
            },
            # 日常对话（默认兜底）
            {
                "scene": "chat",
                "conditions": [
                    {"feature": "busyness_level", "op": "lt", "value": 0.3, "weight": 0.2},
                    {"feature": "fatigue_level", "op": "lt", "value": 0.3, "weight": 0.15},
                ],
                "priority": 1,
            },
        ]

    def classify(
        self,
        features: dict[str, Any],
    ) -> ClassificationResult:
        """基于规则进行分类.

        Args:
            features: 扁平化特征字典

        Returns:
            ClassificationResult 分类结果
        """
        scene_scores: dict[str, float] = {}
        scene_reasons: dict[str, list[str]] = defaultdict(list)
        feature_contributions: dict[str, float] = defaultdict(float)

        for rule in self._rules:
            scene = rule["scene"]
            conditions = rule["conditions"]
            priority = rule.get("priority", 1)

            total_weight = sum(c["weight"] for c in conditions)
            if total_weight == 0:
                continue

            matched_weight = 0.0
            for cond in conditions:
                if self._check_condition(features, cond):
                    matched_weight += cond["weight"]
                    feature = cond["feature"]
                    feature_contributions[feature] += cond["weight"] * priority / 10.0
                    scene_reasons[scene].append(
                        f"{feature} 满足条件"
                    )

            # 归一化得分
            score = (matched_weight / total_weight) * (priority / 10.0)
            scene_scores[scene] = score

        # 找出 top N
        sorted_scenes = sorted(scene_scores.items(), key=lambda x: x[1], reverse=True)

        if not sorted_scenes or sorted_scenes[0][1] == 0:
            return ClassificationResult(
                scene="chat",
                confidence=0.3,
                method="rule_based",
                candidates=[("chat", 0.3)],
                reason="无匹配规则，默认返回 chat",
            )

        best_scene, best_score = sorted_scenes[0]

        # 归一化置信度到 0-1 范围
        max_possible = max(s for _, s in sorted_scenes) if sorted_scenes else 1.0
        confidence = min(best_score / max(max_possible, 0.01), 1.0)

        candidates = [(s, min(sc / max(max_possible, 0.01), 1.0))
                      for s, sc in sorted_scenes[:5]]

        return ClassificationResult(
            scene=best_scene,
            confidence=confidence,
            method="rule_based",
            candidates=candidates,
            reason=f"匹配规则: {', '.join(scene_reasons.get(best_scene, [])[:3])}",
            feature_contributions=dict(feature_contributions),
        )

    def _check_condition(
        self,
        features: dict[str, Any],
        condition: dict[str, Any],
    ) -> bool:
        """检查单个条件是否满足.

        Args:
            features: 特征字典
            condition: 条件定义

        Returns:
            True 表示条件满足
        """
        feature = condition["feature"]
        op = condition["op"]
        value = condition["value"]
        actual = features.get(feature)

        if actual is None or actual == "" or actual == "unknown":
            return False

        try:
            if op == "eq":
                return str(actual) == str(value)
            elif op == "ne":
                return str(actual) != str(value)
            elif op == "gt":
                return float(actual) > float(value)
            elif op == "gte":
                return float(actual) >= float(value)
            elif op == "lt":
                return float(actual) < float(value)
            elif op == "lte":
                return float(actual) <= float(value)
            elif op == "contains":
                return str(value).lower() in str(actual).lower()
            elif op == "contains_any":
                actual_lower = str(actual).lower()
                return any(str(v).lower() in actual_lower for v in value)
            elif op == "in":
                return actual in value
            elif op == "not_in":
                return actual not in value
        except (ValueError, TypeError):
            return False

        return False

    def add_rule(self, rule: dict[str, Any]) -> None:
        """添加自定义规则.

        Args:
            rule: 规则定义字典
        """
        self._rules.append(rule)
        # 按优先级排序
        self._rules.sort(key=lambda r: r.get("priority", 1), reverse=True)


# ---------------------------------------------------------------------------
# 朴素贝叶斯分类器
# ---------------------------------------------------------------------------

class NaiveBayesClassifier:
    """基于朴素贝叶斯的场景分类器.

    使用用户历史数据训练，计算各场景的后验概率。
    优点：统计学习，概率输出，可增量更新
    缺点：需要训练数据，特征独立性假设
    """

    def __init__(self) -> None:
        """初始化贝叶斯分类器."""
        # 场景先验概率 P(scene)
        self._scene_priors: dict[str, float] = {}
        # 特征条件概率 P(feature=value | scene)
        self._feature_probs: dict[str, dict[str, dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        # 场景出现次数
        self._scene_counts: dict[str, int] = defaultdict(int)
        # 特征值出现次数（按场景）
        self._feature_value_counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        # 总样本数
        self._total_samples = 0
        # 拉普拉斯平滑参数
        self._alpha = 1.0

    def train(self, samples: list[tuple[dict[str, Any], str]]) -> None:
        """批量训练.

        Args:
            samples: [(特征字典, 场景ID), ...] 列表
        """
        for features, scene in samples:
            self._update(features, scene)

    def _update(self, features: dict[str, Any], scene: str) -> None:
        """增量更新单个样本.

        Args:
            features: 特征字典
            scene: 场景ID
        """
        self._total_samples += 1
        self._scene_counts[scene] += 1

        # 只使用离散/类别型特征
        categorical_features = [
            "time_period", "location_type", "motion_state",
            "active_app", "conversation_topic", "mood_tendency",
            "is_weekend", "is_holiday",
        ]

        for feat_name in categorical_features:
            feat_value = str(features.get(feat_name, "unknown"))
            self._feature_value_counts[feat_name][scene][feat_value] += 1

        # 更新先验概率
        self._recalculate_probs()

    def _recalculate_probs(self) -> None:
        """重新计算概率分布."""
        if self._total_samples == 0:
            return

        total = self._total_samples
        for scene, count in self._scene_counts.items():
            self._scene_priors[scene] = (count + self._alpha) / (
                total + self._alpha * len(self._scene_counts)
            )

        # 条件概率
        for feat_name, scene_values in self._feature_value_counts.items():
            for scene, value_counts in scene_values.items():
                scene_total = self._scene_counts[scene]
                num_values = len(value_counts) or 1
                for value, count in value_counts.items():
                    self._feature_probs[feat_name][scene][value] = (
                        count + self._alpha
                    ) / (scene_total + self._alpha * num_values)

    def classify(
        self,
        features: dict[str, Any],
    ) -> ClassificationResult:
        """使用朴素贝叶斯分类.

        Args:
            features: 扁平化特征字典

        Returns:
            ClassificationResult 分类结果
        """
        if self._total_samples == 0:
            return ClassificationResult(
                scene="chat",
                confidence=0.2,
                method="naive_bayes",
                candidates=[("chat", 0.2)],
                reason="无训练数据，返回默认场景",
            )

        # 使用的特征
        categorical_features = [
            "time_period", "location_type", "motion_state",
            "conversation_topic", "mood_tendency",
            "is_weekend", "is_holiday",
        ]

        scene_log_probs: dict[str, float] = {}
        feature_contributions: dict[str, float] = defaultdict(float)

        for scene in self._scene_priors:
            log_prob = math.log(self._scene_priors[scene])

            for feat_name in categorical_features:
                feat_value = str(features.get(feat_name, "unknown"))
                cond_prob = self._feature_probs[feat_name][scene].get(
                    feat_value,
                    self._alpha / (self._scene_counts[scene] + self._alpha * 10)
                )
                log_prob += math.log(cond_prob)
                feature_contributions[feat_name] += abs(math.log(cond_prob)) * 0.1

            scene_log_probs[scene] = log_prob

        # 数值稳定性：减去最大值
        max_log = max(scene_log_probs.values())
        scene_probs = {
            s: math.exp(lp - max_log)
            for s, lp in scene_log_probs.items()
        }

        # 归一化
        total = sum(scene_probs.values())
        if total == 0:
            return ClassificationResult(
                scene="chat",
                confidence=0.2,
                method="naive_bayes",
                candidates=[("chat", 0.2)],
                reason="概率计算失败，返回默认场景",
            )

        scene_probs = {s: p / total for s, p in scene_probs.items()}

        # 排序
        sorted_scenes = sorted(scene_probs.items(), key=lambda x: x[1], reverse=True)
        best_scene, best_prob = sorted_scenes[0]

        candidates = [(s, p) for s, p in sorted_scenes[:5]]

        return ClassificationResult(
            scene=best_scene,
            confidence=best_prob,
            method="naive_bayes",
            candidates=candidates,
            reason=f"基于 {self._total_samples} 条历史数据的贝叶斯推断",
            feature_contributions=dict(feature_contributions),
        )

    def update_from_feedback(
        self,
        features: dict[str, Any],
        scene: str,
        is_correct: bool,
    ) -> None:
        """根据用户反馈在线更新模型.

        Args:
            features: 特征字典
            scene: 场景ID
            is_correct: 反馈是否正确
        """
        if is_correct:
            # 正确反馈：正向更新
            self._update(features, scene)
        else:
            # 错误反馈：轻微惩罚（减少该场景下该特征组合的权重）
            # 简化处理：增加一个 "correction" 样本到所有其他场景
            # 实际生产中应使用更复杂的在线学习算法
            pass

    def get_scene_priors(self) -> dict[str, float]:
        """获取场景先验概率.

        Returns:
            场景ID -> 先验概率 的字典
        """
        return dict(self._scene_priors)


# ---------------------------------------------------------------------------
# 集成分类器
# ---------------------------------------------------------------------------

class EnsembleClassifier:
    """集成场景分类器.

    融合规则分类和统计分类的结果，加权输出最终结果。
    低置信度时回退到规则引擎。
    """

    def __init__(
        self,
        rule_weight: float = 0.4,
        bayes_weight: float = 0.6,
        fallback_threshold: float = 0.3,
    ) -> None:
        """初始化集成分类器.

        Args:
            rule_weight: 规则分类器权重
            bayes_weight: 贝叶斯分类器权重
            fallback_threshold: 低置信度回退阈值
        """
        self.rule_classifier = RuleBasedClassifier()
        self.bayes_classifier = NaiveBayesClassifier()
        self.rule_weight = rule_weight
        self.bayes_weight = bayes_weight
        self.fallback_threshold = fallback_threshold

    def classify(
        self,
        features: dict[str, Any],
    ) -> ClassificationResult:
        """集成分类.

        Args:
            features: 扁平化特征字典

        Returns:
            ClassificationResult 分类结果
        """
        # 1. 规则分类
        rule_result = self.rule_classifier.classify(features)

        # 2. 贝叶斯分类
        bayes_result = self.bayes_classifier.classify(features)

        # 3. 加权融合
        has_bayes_training = self.bayes_classifier._total_samples > 10

        if not has_bayes_training:
            # 贝叶斯训练数据不足，直接使用规则结果
            return ClassificationResult(
                scene=rule_result.scene,
                confidence=rule_result.confidence,
                method="ensemble_rule_only",
                candidates=rule_result.candidates,
                reason=f"贝叶斯训练不足，使用规则分类: {rule_result.reason}",
                feature_contributions=rule_result.feature_contributions,
            )

        # 融合得分
        scene_scores: dict[str, float] = defaultdict(float)
        feature_contributions: dict[str, float] = defaultdict(float)

        # 规则分类贡献
        for scene, conf in rule_result.candidates:
            scene_scores[scene] += conf * self.rule_weight

        # 贝叶斯分类贡献
        for scene, conf in bayes_result.candidates:
            scene_scores[scene] += conf * self.bayes_weight

        # 特征贡献融合
        for feat, contrib in rule_result.feature_contributions.items():
            feature_contributions[feat] += contrib * self.rule_weight
        for feat, contrib in bayes_result.feature_contributions.items():
            feature_contributions[feat] += contrib * self.bayes_weight

        # 排序
        sorted_scenes = sorted(scene_scores.items(), key=lambda x: x[1], reverse=True)
        best_scene, best_score = sorted_scenes[0]

        # 归一化
        total_weight = self.rule_weight + self.bayes_weight
        confidence = best_score / total_weight

        candidates = [(s, sc / total_weight) for s, sc in sorted_scenes[:5]]

        # 低置信度回退到规则引擎
        if confidence < self.fallback_threshold:
            return ClassificationResult(
                scene=rule_result.scene,
                confidence=rule_result.confidence,
                method="ensemble_fallback_rule",
                candidates=rule_result.candidates,
                reason=f"集成置信度 {confidence:.2%} 低于阈值，回退到规则引擎",
                feature_contributions=rule_result.feature_contributions,
            )

        return ClassificationResult(
            scene=best_scene,
            confidence=confidence,
            method="ensemble",
            candidates=candidates,
            reason=(
                f"集成分类（规则{self.rule_weight:.0%}+贝叶斯{self.bayes_weight:.0%}）"
                f" - 规则: {rule_result.scene}({rule_result.confidence:.1%}), "
                f"贝叶斯: {bayes_result.scene}({bayes_result.confidence:.1%})"
            ),
            feature_contributions=dict(feature_contributions),
        )

    def record_feedback(
        self,
        features: dict[str, Any],
        scene_id: str,
        is_correct: bool,
    ) -> None:
        """记录用户反馈，更新模型.

        Args:
            features: 特征字典
            scene_id: 场景ID
            is_correct: 是否正确
        """
        self.bayes_classifier.update_from_feedback(features, scene_id, is_correct)

    def set_weights(self, rule_weight: float, bayes_weight: float) -> None:
        """设置分类器权重.

        Args:
            rule_weight: 规则分类器权重
            bayes_weight: 贝叶斯分类器权重
        """
        total = rule_weight + bayes_weight
        if total > 0:
            self.rule_weight = rule_weight / total
            self.bayes_weight = bayes_weight / total


# ---------------------------------------------------------------------------
# 场景分类器（对外主接口）
# ---------------------------------------------------------------------------

class SceneClassifier:
    """场景分类器主类.

    封装规则分类、贝叶斯分类和集成分类，提供统一接口。
    支持在线学习和用户反馈。
    """

    def __init__(self) -> None:
        """初始化场景分类器."""
        self._ensemble = EnsembleClassifier()
        self._feedback_count = 0
        self._correct_count = 0

    def classify(
        self,
        features: dict[str, Any],
        method: str = "ensemble",
    ) -> ClassificationResult:
        """分类场景.

        Args:
            features: 扁平化特征字典
            method: 分类方法 ensemble/rule/bayes

        Returns:
            ClassificationResult 分类结果
        """
        if method == "rule":
            return self._ensemble.rule_classifier.classify(features)
        elif method == "bayes":
            return self._ensemble.bayes_classifier.classify(features)
        else:
            return self._ensemble.classify(features)

    def record_feedback(
        self,
        features: dict[str, Any],
        scene_id: str,
        is_correct: bool,
    ) -> dict[str, Any]:
        """记录用户反馈，更新模型.

        Args:
            features: 特征字典
            scene_id: 场景ID
            is_correct: 是否正确

        Returns:
            反馈统计信息
        """
        self._feedback_count += 1
        if is_correct:
            self._correct_count += 1

        self._ensemble.record_feedback(features, scene_id, is_correct)

        accuracy = self._correct_count / self._feedback_count if self._feedback_count else 0.0

        return {
            "feedback_count": self._feedback_count,
            "correct_count": self._correct_count,
            "accuracy": round(accuracy, 4),
            "scene_id": scene_id,
            "is_correct": is_correct,
        }

    def train_with_history(
        self,
        history: list[tuple[dict[str, Any], str]],
    ) -> dict[str, Any]:
        """使用历史数据训练贝叶斯分类器.

        Args:
            history: [(特征字典, 场景ID), ...] 历史数据

        Returns:
            训练统计
        """
        self._ensemble.bayes_classifier.train(history)

        return {
            "trained_samples": len(history),
            "scene_distribution": dict(self._ensemble.bayes_classifier._scene_counts),
            "total_samples": self._ensemble.bayes_classifier._total_samples,
        }

    def get_feature_importance(
        self,
        scene_id: str | None = None,
    ) -> dict[str, float]:
        """获取特征重要性分析.

        Args:
            scene_id: 场景ID，None 则返回全局平均

        Returns:
            特征名 -> 重要性得分 的字典
        """
        # 基于规则权重估算特征重要性
        importance: dict[str, float] = defaultdict(float)

        for rule in self._ensemble.rule_classifier._rules:
            if scene_id and rule["scene"] != scene_id:
                continue
            priority = rule.get("priority", 1)
            for cond in rule["conditions"]:
                importance[cond["feature"]] += cond["weight"] * priority / 10.0

        # 归一化
        if importance:
            max_val = max(importance.values())
            if max_val > 0:
                importance = {k: v / max_val for k, v in importance.items()}

        return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

    def get_stats(self) -> dict[str, Any]:
        """获取分类器统计信息.

        Returns:
            统计信息字典
        """
        return {
            "feedback_count": self._feedback_count,
            "correct_count": self._correct_count,
            "accuracy": round(
                self._correct_count / self._feedback_count
                if self._feedback_count else 0.0,
                4,
            ),
            "bayes_trained_samples": self._ensemble.bayes_classifier._total_samples,
            "rule_count": len(self._ensemble.rule_classifier._rules),
            "method": "ensemble",
        }
