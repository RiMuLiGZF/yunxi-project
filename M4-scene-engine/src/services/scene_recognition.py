"""智能场景识别服务.

整合特征提取器和场景分类器，提供高层场景识别接口。
支持置信度评估、候选场景列表、用户反馈和特征重要性分析。

使用方式::

    service = SceneRecognitionService()
    result = service.recognize_scene(context)
    print(result["scene"], result["confidence"])
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any

from src.models import SCENE_DEFINITIONS
from src.services.feature_extractor import FeatureExtractor, FeatureVector
from src.services.scene_classifier import SceneClassifier


class SceneRecognitionService:
    """智能场景识别服务.

    整合特征提取和场景分类，提供完整的场景识别功能。
    支持：
    - 多模态特征输入
    - 置信度评估
    - 候选场景列表
    - 用户反馈与在线学习
    - 特征重要性分析
    """

    def __init__(
        self,
        max_history: int = 500,
        enable_online_learning: bool = True,
        recognition_cache_ttl: int = 30,
    ) -> None:
        """初始化场景识别服务.

        Args:
            max_history: 最大历史记录数（用于在线学习）
            enable_online_learning: 是否启用在线学习
            recognition_cache_ttl: 识别结果缓存 TTL（秒）
        """
        self.feature_extractor = FeatureExtractor()
        self.classifier = SceneClassifier()
        self.enable_online_learning = enable_online_learning
        self._cache_ttl = recognition_cache_ttl

        # 识别历史（用于在线学习和统计）
        self._recognition_history: deque[dict[str, Any]] = deque(maxlen=max_history)

        # 缓存：context hash -> (result, timestamp)
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._lock = Lock()

        # 最后一次识别结果
        self._last_result: dict[str, Any] | None = None
        self._last_confidence: float = 0.0

    # -------------------------------------------------------------------
    # 核心识别方法
    # -------------------------------------------------------------------

    def recognize_scene(
        self,
        context: dict[str, Any] | None = None,
        method: str = "ensemble",
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """识别当前场景.

        Args:
            context: 上下文数据
            method: 分类方法 ensemble/rule/bayes
            use_cache: 是否使用缓存

        Returns:
            识别结果字典:
            {
                "scene": "work_dev",
                "confidence": 0.85,
                "method": "ensemble",
                "candidates": [...],
                "reason": "...",
                "features": {...},
                "feature_importance": {...},
                "timestamp": 123456.789,
            }
        """
        ctx = context or {}
        ts = time.time()

        # 缓存检查
        cache_key = self._make_cache_key(ctx, method)
        if use_cache and cache_key in self._cache:
            result, cached_ts = self._cache[cache_key]
            if ts - cached_ts < self._cache_ttl:
                return result

        # 1. 特征提取
        features = self.feature_extractor.extract(ctx, timestamp=ts)
        flat_features = features.to_flat_dict()

        # 2. 场景分类
        classification = self.classifier.classify(flat_features, method=method)

        # 3. 构建结果
        result = {
            "scene": classification.scene,
            "confidence": classification.confidence,
            "method": classification.method,
            "candidates": [
                {"scene": s, "confidence": round(c, 4)}
                for s, c in classification.candidates
            ],
            "reason": classification.reason,
            "features": features.to_dict(),
            "feature_contributions": classification.feature_contributions,
            "timestamp": ts,
        }

        # 4. 记录历史
        self._record_recognition(features, classification, ctx)

        # 5. 更新缓存
        if use_cache:
            with self._lock:
                self._cache[cache_key] = (result, ts)
                # 清理过期缓存
                self._cleanup_cache(ts)

        # 保存最后结果
        self._last_result = result
        self._last_confidence = classification.confidence

        return result

    # -------------------------------------------------------------------
    # 置信度相关
    # -------------------------------------------------------------------

    def get_recognition_confidence(self) -> float:
        """获取最近一次识别的置信度.

        Returns:
            置信度 0.0-1.0
        """
        return self._last_confidence

    def get_scene_candidates(
        self,
        top_n: int = 5,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """获取候选场景列表.

        Args:
            top_n: 返回前 N 个候选
            context: 上下文数据，None 则使用最近一次

        Returns:
            候选场景列表，按置信度降序
        """
        if context is not None:
            result = self.recognize_scene(context)
            return result.get("candidates", [])[:top_n]

        if self._last_result is not None:
            return self._last_result.get("candidates", [])[:top_n]

        # 默认候选
        return [
            {"scene": scene_id, "confidence": 1.0 / len(SCENE_DEFINITIONS)}
            for scene_id in list(SCENE_DEFINITIONS.keys())[:top_n]
        ]

    # -------------------------------------------------------------------
    # 用户反馈与在线学习
    # -------------------------------------------------------------------

    def record_feedback(
        self,
        scene_id: str,
        is_correct: bool,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录用户反馈，更新模型.

        Args:
            scene_id: 场景ID
            is_correct: 识别是否正确
            context: 上下文数据，None 则使用最近一次

        Returns:
            反馈结果字典
        """
        if not self.enable_online_learning:
            return {
                "success": False,
                "reason": "online_learning_disabled",
            }

        # 获取特征
        if context is not None:
            features = self.feature_extractor.extract(context)
        elif self._last_result is not None:
            features = self.feature_extractor.extract(
                self._last_result.get("features", {})
            )
        else:
            features = self.feature_extractor.extract({})

        flat_features = features.to_flat_dict()

        # 更新分类器
        feedback_result = self.classifier.record_feedback(
            flat_features, scene_id, is_correct
        )

        return {
            "success": True,
            "scene_id": scene_id,
            "is_correct": is_correct,
            "feedback_stats": feedback_result,
        }

    # -------------------------------------------------------------------
    # 特征重要性分析
    # -------------------------------------------------------------------

    def get_feature_importance(
        self,
        scene_id: str | None = None,
    ) -> dict[str, Any]:
        """获取特征重要性分析.

        Args:
            scene_id: 场景ID，None 则返回全局

        Returns:
            特征重要性分析结果
        """
        importance = self.classifier.get_feature_importance(scene_id)
        categories = self.feature_extractor.get_feature_categories()

        # 按类别分组
        by_category: dict[str, dict[str, float]] = {}
        for cat, feats in categories.items():
            cat_importance = {f: importance.get(f, 0.0) for f in feats}
            if any(v > 0 for v in cat_importance.values()):
                by_category[cat] = cat_importance

        return {
            "scene_id": scene_id,
            "overall_importance": importance,
            "by_category": by_category,
            "top_features": sorted(
                importance.items(), key=lambda x: x[1], reverse=True
            )[:10],
        }

    # -------------------------------------------------------------------
    # 历史与统计
    # -------------------------------------------------------------------

    def get_recognition_history(
        self,
        limit: int = 20,
        scene_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """获取识别历史.

        Args:
            limit: 返回条数
            scene_id: 筛选场景ID

        Returns:
            识别历史列表
        """
        history = list(self._recognition_history)
        history.reverse()  # 最新的在前

        if scene_id:
            history = [h for h in history if h.get("scene") == scene_id]

        return history[:limit]

    def get_stats(self) -> dict[str, Any]:
        """获取识别服务统计信息.

        Returns:
            统计信息字典
        """
        classifier_stats = self.classifier.get_stats()

        # 场景分布统计
        scene_counts: dict[str, int] = {}
        for record in self._recognition_history:
            scene = record.get("scene", "unknown")
            scene_counts[scene] = scene_counts.get(scene, 0) + 1

        # 平均置信度
        if self._recognition_history:
            avg_confidence = sum(
                r.get("confidence", 0) for r in self._recognition_history
            ) / len(self._recognition_history)
        else:
            avg_confidence = 0.0

        return {
            **classifier_stats,
            "total_recognitions": len(self._recognition_history),
            "scene_distribution": scene_counts,
            "average_confidence": round(avg_confidence, 4),
            "cache_size": len(self._cache),
            "online_learning_enabled": self.enable_online_learning,
        }

    # -------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------

    def _make_cache_key(self, context: dict[str, Any], method: str) -> str:
        """生成缓存键.

        Args:
            context: 上下文
            method: 分类方法

        Returns:
            缓存键字符串
        """
        # 简化：取主要特征的 hash
        key_parts = [
            method,
            str(context.get("hour", "")),
            str(context.get("location", "")),
            str(context.get("active_app", "")),
            str(context.get("motion_state", "")),
        ]
        return "|".join(key_parts)

    def _cleanup_cache(self, now: float) -> None:
        """清理过期缓存（调用方需持有锁）.

        Args:
            now: 当前时间戳
        """
        expired = [
            key for key, (_, ts) in self._cache.items()
            if now - ts > self._cache_ttl
        ]
        for key in expired:
            del self._cache[key]

    def _record_recognition(
        self,
        features: FeatureVector,
        classification: Any,
        context: dict[str, Any],
    ) -> None:
        """记录识别结果到历史.

        Args:
            features: 特征向量
            classification: 分类结果
            context: 原始上下文
        """
        record = {
            "scene": classification.scene,
            "confidence": classification.confidence,
            "method": classification.method,
            "time_period": features.time_period,
            "location_type": features.location_type,
            "timestamp": time.time(),
        }
        with self._lock:
            self._recognition_history.append(record)

    # -------------------------------------------------------------------
    # 训练与初始化
    # -------------------------------------------------------------------

    def train_with_history_data(
        self,
        history_data: list[tuple[dict[str, Any], str]],
    ) -> dict[str, Any]:
        """使用历史数据训练模型.

        Args:
            history_data: [(上下文字典, 场景ID), ...] 历史数据

        Returns:
            训练结果统计
        """
        # 提取特征
        feature_samples = []
        for context, scene_id in history_data:
            features = self.feature_extractor.extract(context)
            feature_samples.append((features.to_flat_dict(), scene_id))

        # 训练分类器
        train_result = self.classifier.train_with_history(feature_samples)

        return train_result
