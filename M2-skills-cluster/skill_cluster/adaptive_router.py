from __future__ import annotations

"""Adaptive Router - 自适应路由.

参考 arXiv 2025 自适应路由算法，实现基于负载、延迟、成功率的动态路由决策。
核心评分公式：
    score = w1 * success_rate + w2 * (1 / normalized_latency) + w3 * (1 / normalized_load)

支持 epsilon-greedy 探索-利用平衡，以及强化学习风格的参数在线更新。
"""

import random
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skill_router import SkillRouter

logger = structlog.get_logger()


class SkillMetrics(BaseModel):
    """技能运行时指标."""

    skill_id: str = Field(..., description="技能 ID")
    total_calls: int = Field(default=0, description="总调用次数")
    success_calls: int = Field(default=0, description="成功次数")
    failed_calls: int = Field(default=0, description="失败次数")
    total_latency_ms: float = Field(default=0.0, description="总延迟（毫秒）")
    avg_latency_ms: float = Field(default=0.0, description="平均延迟")
    min_latency_ms: float = Field(default=float("inf"), description="最小延迟")
    max_latency_ms: float = Field(default=0.0, description="最大延迟")
    current_load: int = Field(default=0, description="当前并发负载")
    max_load: int = Field(default=0, description="历史最大并发")
    last_called_at: float = Field(default=0.0, description="最后调用时间")
    last_error: str | None = Field(default=None, description="最后错误")
    score: float = Field(default=1.0, description="当前综合评分")

    def record_call(
        self, latency_ms: float, success: bool, error: str | None = None
    ) -> None:
        """记录一次调用结果."""
        self.total_calls += 1
        self.total_latency_ms += latency_ms
        self.avg_latency_ms = self.total_latency_ms / self.total_calls
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.last_called_at = time.time()
        self.current_load = max(0, self.current_load - 1)

        if success:
            self.success_calls += 1
            self.last_error = None
        else:
            self.failed_calls += 1
            self.last_error = error

        # 更新评分
        self._update_score()

    def increment_load(self) -> None:
        """增加并发负载计数."""
        self.current_load += 1
        self.max_load = max(self.max_load, self.current_load)

    def _update_score(self) -> None:
        """更新综合评分."""
        if self.total_calls == 0:
            self.score = 1.0
            return

        success_rate = self.success_calls / self.total_calls
        # 延迟反比（归一化到 0-1，假设 5000ms 为最坏情况）
        latency_score = max(
            0.0, 1.0 - (self.avg_latency_ms / 5000.0)
        )
        # 负载反比（假设 10 并发为满载）
        load_score = max(0.0, 1.0 - (self.current_load / 10.0))

        # 权重
        w1, w2, w3 = 0.5, 0.3, 0.2
        self.score = w1 * success_rate + w2 * latency_score + w3 * load_score


class AdaptiveRouter:
    """自适应路由器.

    在 SkillRouter 之上增加运行时指标收集和动态路由决策能力。
    """

    def __init__(
        self,
        router: SkillRouter | None = None,
        epsilon: float = 0.1,
    ) -> None:
        self._router = router or SkillRouter()
        self._metrics: dict[str, SkillMetrics] = {}
        self._epsilon = epsilon  # 探索概率

    # ---- 核心路由 ----

    def select_skill(
        self,
        candidates: list[str],
        request: SkillInvokeRequest | None = None,
    ) -> str | None:
        """从候选技能中选择最优技能.

        使用 epsilon-greedy 策略：以 epsilon 概率随机探索，
        以 1-epsilon 概率选择评分最高的技能。

        Args:
            candidates: 候选技能 ID 列表.
            request: 可选的请求上下文（预留用于未来基于内容的匹配）.

        Returns:
            选中的技能 ID，若无候选则返回 None.
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # 确保所有候选都有指标记录
        for sid in candidates:
            if sid not in self._metrics:
                self._metrics[sid] = SkillMetrics(skill_id=sid)

        # Epsilon-greedy
        if random.random() < self._epsilon:
            choice = random.choice(candidates)
            logger.debug(
                "adaptive_router_explore",
                chosen=choice,
                candidates=candidates,
            )
            return choice

        # 利用：选择评分最高
        best = max(
            candidates, key=lambda sid: self._metrics[sid].score
        )
        logger.debug(
            "adaptive_router_exploit",
            chosen=best,
            score=self._metrics[best].score,
            candidates=candidates,
        )
        return best

    async def invoke(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
    ) -> SkillInvokeResult:
        """自适应调用技能.

        在调用前自动选择最优技能（当多个技能可处理时），
        调用后自动更新指标。
        """
        sid = request.skill_id

        # 初始化或获取指标
        if sid not in self._metrics:
            self._metrics[sid] = SkillMetrics(skill_id=sid)

        metrics = self._metrics[sid]
        metrics.increment_load()

        start = time.perf_counter()
        try:
            result = await self._router.invoke(request, agent_id)
            latency = (time.perf_counter() - start) * 1000

            success = result.status == "success"
            metrics.record_call(latency, success, result.error)
            # 移除冗余的 score += 0.01，统一在 _update_score 中计算

            return result
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            metrics.record_call(latency, False, str(e))
            raise

    # ---- 批量路由 ----

    async def invoke_batch(
        self,
        requests: list[SkillInvokeRequest],
        agent_id: str,
    ) -> list[SkillInvokeResult]:
        """批量自适应调用.

        为每个请求选择最优技能后并发执行。
        """
        # 先批量选择（当前简单实现：直接按请求中的 skill_id）
        # 未来可扩展为动态重路由
        # 改为并发执行（原实现为串行）
        import asyncio
        semaphore = asyncio.Semaphore(10)

        async def _invoke_with_limit(req: SkillInvokeRequest) -> SkillInvokeResult:
            async with semaphore:
                return await self.invoke(req, agent_id)

        return await asyncio.gather(*[_invoke_with_limit(req) for req in requests])

    # ---- 统计 ----

    def get_metrics(self, skill_id: str) -> SkillMetrics | None:
        """获取技能指标."""
        return self._metrics.get(skill_id)

    def get_all_metrics(self) -> dict[str, SkillMetrics]:
        """获取所有技能指标."""
        return dict(self._metrics)

    def get_top_skills(self, n: int = 5) -> list[tuple[str, float]]:
        """获取评分最高的技能.

        Returns:
            (skill_id, score) 列表，按评分降序.
        """
        sorted_items = sorted(
            self._metrics.items(),
            key=lambda x: x[1].score,
            reverse=True,
        )
        return [(sid, m.score) for sid, m in sorted_items[:n]]

    def get_unhealthy_skills(
        self, threshold: float = 0.3
    ) -> list[tuple[str, float]]:
        """获取不健康技能（评分低于阈值）.

        Returns:
            (skill_id, score) 列表.
        """
        return [
            (sid, m.score)
            for sid, m in self._metrics.items()
            if m.score < threshold
        ]

    # ---- 配置 ----

    def set_epsilon(self, epsilon: float) -> None:
        """设置探索概率.

        Args:
            epsilon: 0-1 之间的浮点数，越高越倾向于随机探索.
        """
        self._epsilon = max(0.0, min(1.0, epsilon))

    def decay_epsilon(self, decay_factor: float = 0.99) -> None:
        """衰减探索概率（随着系统稳定减少探索）."""
        self._epsilon *= decay_factor
        self._epsilon = max(0.01, self._epsilon)  # 保留最小探索

    # ---- 统计 ----

    def get_stats(self) -> dict[str, Any]:
        """获取路由统计."""
        if not self._metrics:
            return {
                "total_skills": 0,
                "avg_score": 0.0,
                "total_calls": 0,
            }

        total_calls = sum(m.total_calls for m in self._metrics.values())
        avg_score = sum(m.score for m in self._metrics.values()) / len(
            self._metrics
        )
        return {
            "total_skills": len(self._metrics),
            "avg_score": round(avg_score, 3),
            "total_calls": total_calls,
            "top_skill": self.get_top_skills(1)[0]
            if self._metrics
            else None,
            "unhealthy_count": len(self.get_unhealthy_skills()),
        }
