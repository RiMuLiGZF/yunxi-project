"""
潮汐预测器

基于历史水位数据，使用简单移动平均 + 线性外推预测未来水位变化。
预测潮汐阶段的转换时机，为调度决策提供前瞻性。
"""

from __future__ import annotations

import time
import math
from typing import List, Tuple, Optional

import structlog

from .models import TidePhase, TidePrediction, TideStrategy

logger = structlog.get_logger(__name__)


class TidePredictor:
    """潮汐预测器

    算法：
    1. 指数加权移动平均（EWMA）平滑水位数据
    2. 计算短期和长期趋势线
    3. 线性外推预测未来水位
    4. 预测各时间点的潮汐阶段
    """

    def __init__(self, strategy: Optional[TideStrategy] = None):
        self._strategy = strategy or TideStrategy()
        self._smoothed_level: Optional[float] = None
        self._alpha = 0.3  # EWMA 平滑系数

    def update_strategy(self, strategy: TideStrategy):
        self._strategy = strategy

    def predict(
        self,
        level_history: List[Tuple[float, float]],
        horizon_minutes: int = 30,
    ) -> TidePrediction:
        """预测未来水位变化

        Args:
            level_history: 历史水位 [(timestamp, level), ...]
            horizon_minutes: 预测时长（分钟）

        Returns:
            潮汐预测结果
        """
        prediction = TidePrediction(
            horizon_minutes=horizon_minutes,
            generated_at=time.time(),
        )

        if len(level_history) < 10:
            # 数据不足，无法预测
            prediction.confidence = 0.0
            return prediction

        # 1. 平滑数据
        smoothed = self._exponential_smoothing(level_history)

        # 2. 计算趋势（线性回归）
        slope, intercept, confidence = self._linear_regression(smoothed)

        # 3. 外推预测
        now = time.time()
        points = []
        for minute in range(1, horizon_minutes + 1):
            future_ts = now + minute * 60
            # 预测值 = 当前值 + 斜率 * 时间差（分钟）
            # 同时加入均值回归（避免极端外推）
            current_level = smoothed[-1][1]
            mean_level = sum(l for _, l in smoothed[-30:]) / min(30, len(smoothed))

            # 线性趋势
            linear_pred = current_level + slope * minute

            # 均值回归（向历史均值靠拢）
            reversion_strength = min(0.5, minute / 60)  # 越远回归越强
            reverted_pred = linear_pred * (1 - reversion_strength) + mean_level * reversion_strength

            # 限制在合理范围
            pred_level = max(0.0, min(100.0, reverted_pred))
            points.append((future_ts, pred_level))

        prediction.points = points
        prediction.confidence = confidence

        # 4. 计算各时间点的潮汐阶段
        # 从历史的最后一个阶段开始预测
        if len(smoothed) > 0:
            last_level = smoothed[-1][1]
            current_phase = self._strategy.get_phase_for_level(last_level)

            for minute in [5, 10, 15, 30]:
                if minute <= horizon_minutes:
                    idx = min(minute - 1, len(points) - 1)
                    pred_level = points[idx][1]
                    phase = self._strategy.get_phase_for_level(pred_level, current_phase)
                    prediction.predicted_phases[minute] = phase
                    current_phase = phase

        return prediction

    def _exponential_smoothing(
        self, data: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """指数加权移动平均（EWMA）"""
        if not data:
            return []

        smoothed = []
        ema = data[0][1]
        for ts, val in data:
            ema = self._alpha * val + (1 - self._alpha) * ema
            smoothed.append((ts, ema))
        return smoothed

    def _linear_regression(
        self, data: List[Tuple[float, float]]
    ) -> Tuple[float, float, float]:
        """简单线性回归

        Returns:
            (slope_per_minute, intercept, confidence)
            slope: 每分钟变化量（正=上涨，负=下降）
            confidence: 拟合优度 R² (0-1)
        """
        if len(data) < 3:
            return (0.0, data[0][1] if data else 50.0, 0.0)

        # 以最后一个点为时间原点，单位：分钟
        last_ts = data[-1][0]
        xs = [(ts - last_ts) / 60 for ts, _ in data]  # 分钟
        ys = [val for _, val in data]

        n = len(xs)
        sum_x = sum(xs)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs, ys))
        sum_x2 = sum(x * x for x in xs)

        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-10:
            return (0.0, sum_y / n, 0.0)

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        # 计算 R²
        y_mean = sum_y / n
        ss_total = sum((y - y_mean) ** 2 for y in ys)
        ss_residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))

        r_squared = 1 - (ss_residual / ss_total) if ss_total > 0 else 0.0
        confidence = max(0.0, min(1.0, r_squared))

        return (slope, intercept, confidence)

    def predict_next_phase_change(
        self,
        level_history: List[Tuple[float, float]],
        current_phase: TidePhase,
    ) -> Optional[float]:
        """预测下一次阶段切换的时间（分钟）

        Returns:
            预计分钟数，None 表示无法预测
        """
        if len(level_history) < 10:
            return None

        prediction = self.predict(level_history, horizon_minutes=60)
        if prediction.confidence < 0.3:
            return None

        next_change = prediction._next_phase_change_minutes()
        return next_change
