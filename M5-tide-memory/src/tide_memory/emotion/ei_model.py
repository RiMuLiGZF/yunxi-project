"""
EI 情绪指数引擎
基于效价-唤醒度模型计算情绪指数

⚠️ 高涉密 - EI计算核心参数仅本地留存
"""

from __future__ import annotations

from typing import Dict, Optional


class EIEngine:
    """
    EI情绪指数引擎
    
    根据valence（效价）和arousal（唤醒度）计算综合情绪指数。
    EI范围 0-1，值越高表示情绪越强烈（不分正负）。
    """

    def __init__(self, va_model=None):
        self._va_model = va_model  # ValenceArousalModel
        self._history = []  # 情绪历史（仅内存，不落盘）

    def infer_from_text(self, text: str) -> Dict:
        """
        从文本推断情绪
        
        返回: {valence, arousal, ei_score, dominant_emotion, confidence}
        """
        if self._va_model:
            va = self._va_model.infer(text)
        else:
            # 无模型时返回中性默认值
            va = {"valence": 0.0, "arousal": 0.2, "confidence": 0.3}

        ei = self._calculate_ei(va["valence"], va["arousal"])
        dominant = self._label_emotion(va["valence"], va["arousal"])

        result = {
            "valence": va["valence"],
            "arousal": va["arousal"],
            "ei_score": round(ei, 4),
            "dominant_emotion": dominant,
            "confidence": va.get("confidence", 0.5),
        }

        # 记录历史（内存中，用于趋势计算）
        self._history.append(result)
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

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
        if arousal > 0.6:
            if valence > 0.3:
                return "excited"      # 兴奋
            elif valence < -0.3:
                return "anxious"      # 焦虑
            else:
                return "alert"        # 警觉
        elif arousal < 0.3:
            if valence > 0.3:
                return "calm"         # 平静
            elif valence < -0.3:
                return "sad"          # 悲伤
            else:
                return "relaxed"      # 放松
        else:
            if valence > 0.2:
                return "positive"     # 积极
            elif valence < -0.2:
                return "negative"     # 消极
            else:
                return "neutral"      # 中性

    def get_trend(self, window: int = 10) -> Dict:
        """获取情绪趋势"""
        if len(self._history) < 2:
            return {"trend": "insufficient_data", "avg_ei": 0}

        recent = self._history[-window:]
        avg_ei = sum(r["ei_score"] for r in recent) / len(recent)
        first_half = sum(r["ei_score"] for r in recent[:window//2]) / (window//2)
        second_half = sum(r["ei_score"] for r in recent[window//2:]) / (window - window//2)

        if second_half > first_half * 1.1:
            trend = "rising"
        elif second_half < first_half * 0.9:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "avg_ei": round(avg_ei, 4),
            "samples": len(recent),
        }

    def get_history(self, limit: int = 100) -> list:
        """获取情绪历史（不包含原始文本）"""
        return self._history[-limit:]
