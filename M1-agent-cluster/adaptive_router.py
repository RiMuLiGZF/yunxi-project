"""
云汐内核 V3 - 自适应路由优化器

基于执行历史动态调整路由策略，实现意图分类到 Agent 的映射持续优化。

核心机制：
- 记录每条路由路径的执行结果（成功率、延迟、用户满意度）
- 使用 epsilon-greedy 策略平衡探索与利用
- 根据历史数据动态调整路由权重
- 支持 A/B 测试式路由对比
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RouteRecord:
    """路由执行记录"""

    route_id: str = ""  # "intent -> target_agent"
    intent: str = ""
    target_agent: str = ""
    execution_count: int = 0
    success_count: int = 0
    total_latency_ms: float = 0.0
    avg_score: float = 0.0  # 用户满意度或质量评分
    last_used: float = 0.0
    active: bool = True

    @property
    def success_rate(self) -> float:
        if self.execution_count == 0:
            return 0.5  # 默认中性
        return self.success_count / self.execution_count

    @property
    def avg_latency_ms(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.total_latency_ms / self.execution_count

    @property
    def utility_score(self) -> float:
        """综合效用分数

        综合考虑成功率、延迟、评分。
        """
        latency_penalty = max(0, 1.0 - self.avg_latency_ms / 3000)
        return (
            self.success_rate * 0.5
            + self.avg_score * 0.3
            + latency_penalty * 0.2
        )


class AdaptiveRouter:
    """自适应路由优化器

    动态学习最优的意图 -> Agent 映射关系。
    """

    def __init__(
        self,
        epsilon: float = 0.15,
        min_samples: int = 5,
        decay_factor: float = 0.95,
    ) -> None:
        """初始化

        Args:
            epsilon: 探索率（随机选择路由的概率）
            min_samples: 最小样本数，达到后才启用自适应
            decay_factor: 历史数据衰减因子（旧数据权重降低）
        """
        self._records: dict[str, RouteRecord] = {}
        self._intent_routes: dict[str, list[str]] = {}
        """intent -> [target_agent, ...]"""
        self.epsilon = epsilon
        self.min_samples = min_samples
        self.decay_factor = decay_factor
        self._logger = logger.bind(service="adaptive_router")

    def register_route(self, intent: str, target_agent: str) -> None:
        """注册可用路由"""
        route_id = f"{intent} -> {target_agent}"
        if route_id not in self._records:
            self._records[route_id] = RouteRecord(
                route_id=route_id,
                intent=intent,
                target_agent=target_agent,
            )
        self._intent_routes.setdefault(intent, []).append(target_agent)
        # 去重
        self._intent_routes[intent] = list(dict.fromkeys(self._intent_routes[intent]))

    def select_agent(
        self,
        intent: str,
        default_agent: str = "",
    ) -> tuple[str, bool]:
        """选择目标 Agent

        Args:
            intent: 意图标签
            default_agent: 默认 Agent

        Returns:
            (target_agent, is_exploration): 是否处于探索模式
        """
        candidates = self._intent_routes.get(intent, [])
        if not candidates:
            return default_agent, False
        if len(candidates) == 1:
            return candidates[0], False

        # epsilon-greedy 策略
        if random.random() < self.epsilon:
            # 探索：随机选择
            choice = random.choice(candidates)
            self._logger.debug("exploration_route", intent=intent, choice=choice)
            return choice, True

        # 利用：选择效用最高的
        best_agent = self._get_best_agent(intent, candidates)
        return best_agent, False

    def _get_best_agent(self, intent: str, candidates: list[str]) -> str:
        """获取效用最高的 Agent"""
        best_score = -1.0
        best_agent = candidates[0]

        for agent in candidates:
            route_id = f"{intent} -> {agent}"
            record = self._records.get(route_id)
            if record and record.execution_count >= self.min_samples:
                score = record.utility_score
            else:
                # 样本不足时给予探索奖励
                score = 0.5

            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    def report_result(
        self,
        intent: str,
        target_agent: str,
        success: bool,
        latency_ms: float = 0.0,
        score: float = 0.0,
    ) -> None:
        """报告路由执行结果

        用于更新路由统计，驱动自适应学习。
        """
        route_id = f"{intent} -> {target_agent}"
        record = self._records.get(route_id)
        if not record:
            self.register_route(intent, target_agent)
            record = self._records[route_id]

        # 衰减旧数据
        if record.execution_count > 0:
            record.success_count *= self.decay_factor
            record.total_latency_ms *= self.decay_factor
            record.avg_score *= self.decay_factor
            record.execution_count *= self.decay_factor

        record.execution_count += 1
        if success:
            record.success_count += 1
        record.total_latency_ms += latency_ms
        if score > 0:
            # 指数移动平均
            record.avg_score = record.avg_score * 0.7 + score * 0.3
        record.last_used = time.time()

        self._logger.debug(
            "route_result_recorded",
            route_id=route_id,
            success=success,
            success_rate=round(record.success_rate, 3),
            utility=round(record.utility_score, 3),
        )

    def get_route_stats(self, intent: str | None = None) -> dict[str, Any]:
        """获取路由统计"""
        if intent:
            records = [
                r for r in self._records.values() if r.intent == intent
            ]
        else:
            records = list(self._records.values())

        return {
            "total_routes": len(records),
            "routes": [
                {
                    "route_id": r.route_id,
                    "success_rate": round(r.success_rate, 3),
                    "avg_latency_ms": round(r.avg_latency_ms, 2),
                    "avg_score": round(r.avg_score, 3),
                    "utility": round(r.utility_score, 3),
                    "samples": r.execution_count,
                }
                for r in records
            ],
        }

    def get_recommendations(self) -> list[dict[str, Any]]:
        """生成路由优化建议"""
        recommendations: list[dict[str, Any]] = []

        for intent, agents in self._intent_routes.items():
            if len(agents) <= 1:
                continue

            records = [
                self._records.get(f"{intent} -> {a}")
                for a in agents
            ]
            records = [r for r in records if r and r.execution_count >= self.min_samples]

            if not records:
                continue

            records.sort(key=lambda r: r.utility_score, reverse=True)
            best = records[0]
            worst = records[-1]

            if best.utility_score - worst.utility_score > 0.3:
                recommendations.append({
                    "type": "deprecate_route",
                    "intent": intent,
                    "agent": worst.target_agent,
                    "reason": f"效用分数显著低于最优 ({worst.utility_score:.2f} vs {best.utility_score:.2f})",
                    "suggested_agent": best.target_agent,
                })

        return recommendations
