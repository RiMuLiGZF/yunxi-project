"""
EI 情绪指数引擎
基于效价-唤醒度模型计算情绪指数

⚠️ 高涉密 - EI计算核心参数仅本地留存
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..common.constants import (
    VALENCE_DEFAULT,
    AROUSAL_DEFAULT,
    DEFAULT_EMOTION_CONFIDENCE,
    NO_MODEL_CONFIDENCE,
    EMOTION_HISTORY_MAX_SIZE,
    EMOTION_TREND_WINDOW,
    EMOTION_TREND_RISE_FACTOR,
    EMOTION_TREND_DECLINE_FACTOR,
    EMOTION_HISTORY_LIMIT,
    EMOTION_NEUTRAL,
    EMOTION_EXCITED,
    EMOTION_ANXIOUS,
    EMOTION_ALERT,
    EMOTION_CALM,
    EMOTION_SAD,
    EMOTION_RELAXED,
    EMOTION_POSITIVE,
    EMOTION_NEGATIVE,
    AROUSAL_HIGH_THRESHOLD,
    AROUSAL_LOW_THRESHOLD,
    VALENCE_POSITIVE_HIGH,
    VALENCE_NEGATIVE_HIGH,
    VALENCE_POSITIVE_MID,
    VALENCE_NEGATIVE_MID,
)


class EIEngine:
    """
    EI情绪指数引擎
    
    根据valence（效价）和arousal（唤醒度）计算综合情绪指数。
    EI范围 0-1，值越高表示情绪越强烈（不分正负）。
    """

    def __init__(self, va_model=None) -> None:
        self._va_model = va_model  # ValenceArousalModel
        self._history = []  # 情绪历史（仅内存，不落盘）

    def infer_from_text(self, text: str) -> Dict[str, Any]:
        """
        从文本推断情绪
        
        返回: {valence, arousal, ei_score, dominant_emotion, confidence}
        """
        if self._va_model:
            va = self._va_model.infer(text)
        else:
            # 无模型时返回中性默认值
            va = {"valence": VALENCE_DEFAULT, "arousal": AROUSAL_DEFAULT, "confidence": NO_MODEL_CONFIDENCE}

        ei = self._calculate_ei(va["valence"], va["arousal"])
        dominant = self._label_emotion(va["valence"], va["arousal"])

        result = {
            "valence": va["valence"],
            "arousal": va["arousal"],
            "ei_score": round(ei, 4),
            "dominant_emotion": dominant,
            "confidence": va.get("confidence", DEFAULT_EMOTION_CONFIDENCE),
        }

        # 记录历史（内存中，用于趋势计算）
        self._history.append(result)
        if len(self._history) > EMOTION_HISTORY_MAX_SIZE:
            self._history = self._history[-EMOTION_HISTORY_MAX_SIZE:]

        return result

    def _calculate_ei(self, valence: float, arousal: float) -> float:
        """
        计算EI情绪指数（情绪强度）
        基于效价和唤醒度的欧氏距离归一化
        """
        import math
        # 效价范围 [-1, 1]，唤醒度 [0, 1]
        # 映射到统一空间计算强度
        v_normalized = abs(valence)  # 正负向都是情绪强度
        a_normalized = arousal
        ei = math.sqrt(v_normalized ** 2 + a_normalized ** 2) / math.sqrt(2)
        return min(1.0, max(0.0, ei))

    def _label_emotion(self, valence: float, arousal: float) -> str:
        """给情绪打标签（Russell情绪环模型）"""
        if arousal > AROUSAL_HIGH_THRESHOLD:
            if valence > VALENCE_POSITIVE_HIGH:
                return EMOTION_EXCITED      # 兴奋
            elif valence < VALENCE_NEGATIVE_HIGH:
                return EMOTION_ANXIOUS      # 焦虑
            else:
                return EMOTION_ALERT        # 警觉
        elif arousal < AROUSAL_LOW_THRESHOLD:
            if valence > VALENCE_POSITIVE_HIGH:
                return EMOTION_CALM         # 平静
            elif valence < VALENCE_NEGATIVE_HIGH:
                return EMOTION_SAD          # 悲伤
            else:
                return EMOTION_RELAXED      # 放松
        else:
            if valence > VALENCE_POSITIVE_MID:
                return EMOTION_POSITIVE     # 积极
            elif valence < VALENCE_NEGATIVE_MID:
                return EMOTION_NEGATIVE     # 消极
            else:
                return EMOTION_NEUTRAL      # 中性

    def get_trend(self, window: int = EMOTION_TREND_WINDOW) -> Dict:
        """获取情绪趋势"""
        if len(self._history) < 2:
            return {"trend": "insufficient_data", "avg_ei": 0}

        recent = self._history[-window:]
        avg_ei = sum(r["ei_score"] for r in recent) / len(recent)
        first_half = sum(r["ei_score"] for r in recent[:window//2]) / (window//2)
        second_half = sum(r["ei_score"] for r in recent[window//2:]) / (window - window//2)

        if second_half > first_half * EMOTION_TREND_RISE_FACTOR:
            trend = "rising"
        elif second_half < first_half * EMOTION_TREND_DECLINE_FACTOR:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "avg_ei": round(avg_ei, 4),
            "samples": len(recent),
        }

    def get_history(self, limit: int = EMOTION_HISTORY_LIMIT) -> list:
        """获取情绪历史（不包含原始文本）"""
        return self._history[-limit:]
# vim: set et ts=4 sw=4:
