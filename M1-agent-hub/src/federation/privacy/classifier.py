"""
隐私卫士 — 风险分类器

职责：根据检测到的 PII 和涉密等级，评估综合风险等级和风险分值。
"""

from __future__ import annotations

from typing import Any

from shared_models import SecurityClassification

from .types import SEVERITY_WEIGHT, SECURITY_LEVEL_WEIGHT


class RiskClassifier:
    """风险分类器

    采用加权评分制评估综合风险等级：
    - critical: 风险分 >= 20 或存在 critical 类 PII
    - high: 风险分 >= 10
    - medium: 风险分 >= 3
    - low: 风险分 < 3 或无 PII
    - none: 完全无 PII
    """

    @staticmethod
    def assess_risk_level(
        detections: list[dict[str, Any]],
        security_level: SecurityClassification,
    ) -> tuple[str, float]:
        """评估综合风险等级

        [V11.1 修复] 采用加权评分制：
        风险分 = Σ(单类 PII 权重 × 数量) × 涉密等级权重

        Args:
            detections: 检测到的 PII 列表
            security_level: 涉密等级

        Returns:
            (风险等级, 风险分值)
        """
        if not detections:
            return "none", 0.0

        # 计算加权总分
        base_score = 0.0
        has_critical = False
        has_high = False

        for d in detections:
            severity = d.get("severity", "medium")
            weight = SEVERITY_WEIGHT.get(severity, 1.0)
            base_score += weight
            if severity == "critical":
                has_critical = True
            elif severity == "high":
                has_high = True

        # 涉密等级加权
        sec_weight = SECURITY_LEVEL_WEIGHT.get(security_level, 1.0)
        total_score = base_score * sec_weight

        # 判定风险等级
        if has_critical or total_score >= 20:
            risk_level = "critical"
        elif has_high and total_score >= 8 or total_score >= 10:
            risk_level = "high"
        elif total_score >= 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        return risk_level, total_score