"""场景预测引擎.

基于历史数据和上下文，预测用户接下来可能进入的场景。
支持多种预测方法：马尔可夫链、模式匹配、上下文加权预测。

使用方式::

    predictor = ScenePredictor()
    predictor.record_transition("work", "rest")
    result = predictor.predict_next("work")
    print(result["predicted_scene"], result["confidence"])
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional


@dataclass
class PredictionResult:
    """预测结果."""
    predicted_scene: str
    confidence: float
    candidates: list[dict[str, Any]] = field(default_factory=list)
    method: str = "ensemble"
    explanation: str = ""


class MarkovChainPredictor:
    """马尔可夫链预测器.

    基于一阶马尔可夫链，根据当前场景预测下一场景。
    从历史切换序列中学习转移概率。
    """

    def __init__(self) -> None:
        self._transitions: dict[str, Counter] = defaultdict(Counter)
        self._totals: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def record_transition(self, from_scene: str, to_scene: str) -> None:
        """记录一次场景切换."""
        with self._lock:
            self._transitions[from_scene][to_scene] += 1
            self._totals[from_scene] += 1

    def predict(self, current_scene: str, top_n: int = 3) -> list[tuple[str, float]]:
        """预测下一场景.

        Returns:
            [(scene_id, probability), ...] 按概率降序排列
        """
        with self._lock:
            total = self._totals.get(current_scene, 0)
            if total == 0:
                return []
            counter = self._transitions[current_scene]
            results = [
                (scene, count / total)
                for scene, count in counter.most_common(top_n)
            ]
        return results

    def get_transition_matrix(self) -> dict[str, dict[str, float]]:
        """获取完整转移矩阵."""
        result = {}
        with self._lock:
            for from_scene, counter in self._transitions.items():
                total = self._totals[from_scene]
                if total > 0:
                    result[from_scene] = {
                        to_scene: count / total
                        for to_scene, count in counter.items()
                    }
        return result


class PatternMatcher:
    """模式匹配预测器.

    基于每日/每周模式识别，匹配相似时间段的场景。
    """

    def __init__(self, max_patterns: int = 1000) -> None:
        self._patterns: dict[tuple[int, int], Counter] = defaultdict(Counter)
        self._weekly_patterns: dict[tuple[int, int], Counter] = defaultdict(Counter)
        self._lock = Lock()
        self._max_patterns = max_patterns

    def record_scene_at(self, scene_id: str, timestamp: float) -> None:
        """记录某时刻的场景."""
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        hour = dt.hour
        minute_slot = dt.minute // 30  # 30 分钟一个槽位
        weekday = dt.weekday()

        key_daily = (hour, minute_slot)
        key_weekly = (weekday, hour)

        with self._lock:
            self._patterns[key_daily][scene_id] += 1
            self._weekly_patterns[key_weekly][scene_id] += 1

    def predict_at(self, timestamp: float, top_n: int = 3) -> list[tuple[str, float]]:
        """预测某时刻的场景."""
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        hour = dt.hour
        minute_slot = dt.minute // 30
        weekday = dt.weekday()

        key_daily = (hour, minute_slot)
        key_weekly = (weekday, hour)

        with self._lock:
            daily_counter = self._patterns.get(key_daily, Counter())
            weekly_counter = self._weekly_patterns.get(key_weekly, Counter())

        # 融合：日模式权重 0.6，周模式权重 0.4
        scores: dict[str, float] = defaultdict(float)

        daily_total = sum(daily_counter.values())
        if daily_total > 0:
            for scene, count in daily_counter.items():
                scores[scene] += 0.6 * (count / daily_total)

        weekly_total = sum(weekly_counter.values())
        if weekly_total > 0:
            for scene, count in weekly_counter.items():
                scores[scene] += 0.4 * (count / weekly_total)

        sorted_scenes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scenes[:top_n]


class ContextPredictor:
    """上下文感知预测器.

    结合当前上下文（时间、位置、行为），加权预测下一场景。
    """

    def __init__(self) -> None:
        self._context_history: list[tuple[dict[str, Any], str]] = []
        self._lock = Lock()
        self._max_history = 500

    def record(self, context: dict[str, Any], scene_id: str) -> None:
        """记录上下文-场景对."""
        with self._lock:
            self._context_history.append((context, scene_id))
            if len(self._context_history) > self._max_history:
                self._context_history.pop(0)

    def predict(
        self,
        current_context: dict[str, Any],
        top_n: int = 3,
    ) -> list[tuple[str, float]]:
        """基于上下文预测场景.

        使用简单的 k-近邻思想，找历史上最相似的上下文。
        """
        with self._lock:
            history = list(self._context_history)

        if not history:
            return []

        # 计算相似度
        scored = []
        ctx_time = current_context.get("time_of_day", "")
        ctx_loc = current_context.get("location_type", "")
        ctx_activity = current_context.get("activity", "")

        for hist_ctx, scene_id in history:
            similarity = 0.0
            # 时间相似
            if ctx_time and hist_ctx.get("time_of_day") == ctx_time:
                similarity += 0.4
            # 位置相似
            if ctx_loc and hist_ctx.get("location_type") == ctx_loc:
                similarity += 0.35
            # 活动相似
            if ctx_activity and hist_ctx.get("activity") == ctx_activity:
                similarity += 0.25
            if similarity > 0:
                scored.append((scene_id, similarity))

        if not scored:
            return []

        # 按场景聚合相似度
        scene_scores: dict[str, float] = defaultdict(float)
        scene_counts: dict[str, int] = defaultdict(int)
        for scene_id, sim in scored:
            scene_scores[scene_id] += sim
            scene_counts[scene_id] += 1

        # 归一化（取平均相似度）
        for scene_id in scene_scores:
            scene_scores[scene_id] = scene_scores[scene_id] / scene_counts[scene_id]

        sorted_scenes = sorted(scene_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_scenes[:top_n]


class ScenePredictor:
    """场景预测引擎 - 集成多种预测方法."""

    def __init__(self, enable_ensemble: bool = True) -> None:
        self.markov = MarkovChainPredictor()
        self.pattern = PatternMatcher()
        self.context = ContextPredictor()
        self.enable_ensemble = enable_ensemble

        # 预测历史（用于评估准确率）
        self._prediction_history: deque = deque(maxlen=200)
        self._lock = Lock()

        # 权重配置
        self.weights = {
            "markov": 0.35,
            "pattern": 0.35,
            "context": 0.30,
        }

    def record_transition(self, from_scene: str, to_scene: str,
                          context: Optional[dict[str, Any]] = None,
                          timestamp: Optional[float] = None) -> None:
        """记录场景切换（同时更新所有预测器）."""
        ts = timestamp or time.time()
        self.markov.record_transition(from_scene, to_scene)
        self.pattern.record_scene_at(to_scene, ts)
        if context:
            self.context.record(context, to_scene)

    def predict_next(
        self,
        current_scene: str,
        context: Optional[dict[str, Any]] = None,
        top_n: int = 5,
    ) -> PredictionResult:
        """预测下一场景.

        Args:
            current_scene: 当前场景 ID
            context: 当前上下文字典（可选）
            top_n: 返回候选数量

        Returns:
            PredictionResult 预测结果
        """
        markov_results = self.markov.predict(current_scene, top_n)
        pattern_results = self.pattern.predict_at(time.time(), top_n)
        context_results = self.context.predict(context or {}, top_n) if context else []

        if not self.enable_ensemble:
            # 只使用马尔可夫
            if markov_results:
                predicted, conf = markov_results[0]
                return PredictionResult(
                    predicted_scene=predicted,
                    confidence=conf,
                    candidates=[{"scene": s, "probability": p} for s, p in markov_results],
                    method="markov",
                    explanation=f"基于马尔可夫链，从 {current_scene} 转移概率最高",
                )
            return PredictionResult(predicted_scene="", confidence=0.0, method="markov")

        # 集成预测
        combined_scores: dict[str, float] = defaultdict(float)
        method_contributions: dict[str, list] = defaultdict(list)

        for scene, prob in markov_results:
            weighted = prob * self.weights["markov"]
            combined_scores[scene] += weighted
            method_contributions[scene].append(("markov", prob))

        for scene, prob in pattern_results:
            weighted = prob * self.weights["pattern"]
            combined_scores[scene] += weighted
            method_contributions[scene].append(("pattern", prob))

        for scene, prob in context_results:
            weighted = prob * self.weights["context"]
            combined_scores[scene] += weighted
            method_contributions[scene].append(("context", prob))

        if not combined_scores:
            return PredictionResult(
                predicted_scene="",
                confidence=0.0,
                method="ensemble",
                explanation="历史数据不足，无法做出预测",
            )

        sorted_scenes = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        predicted_scene, confidence = sorted_scenes[0]

        # 生成解释
        contribs = method_contributions.get(predicted_scene, [])
        if contribs:
            methods = ", ".join([f"{m}({p:.0%})" for m, p in contribs])
            explanation = f"综合 {methods} 预测，置信度 {confidence:.1%}"
        else:
            explanation = "集成预测结果"

        candidates = [
            {
                "scene": scene,
                "confidence": conf,
                "contributions": dict(method_contributions.get(scene, [])),
            }
            for scene, conf in sorted_scenes[:top_n]
        ]

        result = PredictionResult(
            predicted_scene=predicted_scene,
            confidence=min(confidence, 1.0),
            candidates=candidates,
            method="ensemble",
            explanation=explanation,
        )

        # 记录预测（用于后续准确率评估）
        with self._lock:
            self._prediction_history.append({
                "predicted": predicted_scene,
                "confidence": confidence,
                "current_scene": current_scene,
                "timestamp": time.time(),
            })

        return result

    def predict_scene_at(
        self,
        target_timestamp: float,
        context: Optional[dict[str, Any]] = None,
    ) -> PredictionResult:
        """预测某个时刻的场景."""
        pattern_results = self.pattern.predict_at(target_timestamp, 5)

        if not pattern_results:
            return PredictionResult(
                predicted_scene="",
                confidence=0.0,
                method="pattern",
                explanation="无历史模式数据",
            )

        predicted, conf = pattern_results[0]
        return PredictionResult(
            predicted_scene=predicted,
            confidence=conf,
            candidates=[{"scene": s, "probability": p} for s, p in pattern_results],
            method="pattern",
            explanation=f"基于历史时间模式，该时刻最可能为 {predicted}",
        )

    def evaluate_accuracy(self, actual_scene: str) -> dict[str, Any]:
        """评估预测准确率（对比实际场景和之前的预测）.

        Args:
            actual_scene: 实际切换到的场景

        Returns:
            准确率统计
        """
        with self._lock:
            history = list(self._prediction_history)

        if not history:
            return {"total": 0, "correct": 0, "accuracy": 0.0}

        # 用最近的预测和实际场景对比
        correct = 0
        total = min(len(history), 50)  # 最近 50 次
        for pred in history[-total:]:
            if pred["predicted"] == actual_scene:
                correct += 1

        return {
            "total": total,
            "correct": correct,
            "accuracy": correct / total if total > 0 else 0.0,
            "avg_confidence": sum(p["confidence"] for p in history[-total:]) / total if total > 0 else 0.0,
        }

    def get_prediction_stats(self) -> dict[str, Any]:
        """获取预测统计信息."""
        with self._lock:
            total = len(self._prediction_history)

        transition_matrix = self.markov.get_transition_matrix()
        unique_scenes = set()
        for from_s in transition_matrix:
            unique_scenes.add(from_s)
            for to_s in transition_matrix[from_s]:
                unique_scenes.add(to_s)

        return {
            "total_predictions": total,
            "unique_scenes": len(unique_scenes),
            "transition_count": sum(
                sum(c.values()) for c in self.markov._transitions.values()
            ),
            "weights": dict(self.weights),
            "method": "ensemble" if self.enable_ensemble else "markov_only",
        }

    def train_with_history_data(
        self,
        scene_sequence: list[str],
        context_sequence: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """使用历史场景序列训练.

        Args:
            scene_sequence: 场景序列 [scene_1, scene_2, scene_3, ...]
            context_sequence: 对应上下文序列（可选）

        Returns:
            训练统计
        """
        transitions = 0
        for i in range(len(scene_sequence) - 1):
            from_scene = scene_sequence[i]
            to_scene = scene_sequence[i + 1]
            ctx = context_sequence[i] if context_sequence and i < len(context_sequence) else None
            self.record_transition(from_scene, to_scene, context=ctx)
            transitions += 1

        return {
            "sequence_length": len(scene_sequence),
            "transitions_recorded": transitions,
            "unique_scenes": len(set(scene_sequence)),
        }
