"""
云汐内核 V7 - Token 预算与成本管理中心

灵感来源：
- Token-Budget-Aware Pool Routing (arXiv 2026)
- LLM Cost Optimization: Cut Token Spend 35-50% with Hybrid Routing
- Bifrost Cost-Aware Routing Framework

核心能力：
1. Token 计量：按模型、按 Agent、按会话统计输入/输出 token
2. 预算管控：日/月/请求级预算上限，超支自动拦截
3. 成本感知路由：简单任务走廉价模型，复杂任务走高级模型
4. 阶梯降级：预算紧张时自动切换至更便宜的后端
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class BudgetLevel(str, Enum):
    """预算级别"""

    REQUEST = "request"
    SESSION = "session"
    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass
class ModelPricing:
    """模型定价"""

    model_name: str = ""
    input_price_per_1k: float = 0.0   # 美元/1K input tokens
    output_price_per_1k: float = 0.0  # 美元/1K output tokens

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """估算成本（美元）"""
        return (
            input_tokens / 1000 * self.input_price_per_1k +
            output_tokens / 1000 * self.output_price_per_1k
        )


@dataclass
class UsageRecord:
    """使用记录"""

    timestamp: float = 0.0
    model: str = ""
    agent_id: str = ""
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: float = 0.0


class BudgetManager:
    """Token 预算与成本管理中心"""

    DEFAULT_PRICING: dict[str, ModelPricing] = {
        "gpt-4o": ModelPricing("gpt-4o", 2.50, 10.00),
        "gpt-4o-mini": ModelPricing("gpt-4o-mini", 0.15, 0.60),
        "claude-3-sonnet": ModelPricing("claude-3-sonnet", 3.00, 15.00),
        "mock-model": ModelPricing("mock-model", 0.0, 0.0),
    }

    def __init__(
        self,
        daily_budget_usd: float = 100.0,
        monthly_budget_usd: float = 1000.0,
        request_budget_usd: float = 1.0,
        enable_routing: bool = True,
    ) -> None:
        self.daily_budget = daily_budget_usd
        self.monthly_budget = monthly_budget_usd
        self.request_budget = request_budget_usd
        self.enable_routing = enable_routing

        self._pricing = dict(self.DEFAULT_PRICING)
        self._records: deque[UsageRecord] = deque(maxlen=100000)
        # [V9.5] Rolling aggregation for O(1) budget checks
        self._daily_total: float = 0.0
        self._monthly_total: float = 0.0
        self._daily_window_start: float = 0.0
        self._monthly_window_start: float = 0.0
        self._logger = logger.bind(service="budget_manager")

    # ── 定价管理 ────────────────────────────────────────

    def set_pricing(self, model: str, input_price: float, output_price: float) -> None:
        """设置模型定价"""
        self._pricing[model] = ModelPricing(model, input_price, output_price)

    def get_pricing(self, model: str) -> ModelPricing | None:
        """获取模型定价"""
        return self._pricing.get(model)

    # ── 使用记录 ────────────────────────────────────────

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: str = "",
        session_id: str = "",
        latency_ms: float = 0.0,
    ) -> UsageRecord:
        """记录一次使用"""
        pricing = self.get_pricing(model)
        cost = pricing.estimate_cost(input_tokens, output_tokens) if pricing else 0.0

        record = UsageRecord(
            timestamp=time.time(),
            model=model,
            agent_id=agent_id,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            latency_ms=latency_ms,
        )
        self._records.append(record)

        # [V9.5] 增量更新 rolling totals
        if record.timestamp >= self._daily_window_start and self._daily_window_start > 0:
            self._daily_total += cost
        if record.timestamp >= self._monthly_window_start and self._monthly_window_start > 0:
            self._monthly_total += cost

        self._logger.debug(
            "usage_recorded",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
        )
        return record

    # ── 预算检查 ────────────────────────────────────────

    def _refresh_daily_window(self, now: float) -> None:
        """刷新日窗口聚合（窗口变化时全量重算）"""
        day_start = now - (now % 86400)
        if day_start != self._daily_window_start:
            self._daily_total = sum(
                r.estimated_cost for r in self._records
                if r.timestamp >= day_start
            )
            self._daily_window_start = day_start

    def _refresh_monthly_window(self, now: float) -> None:
        """刷新月窗口聚合（窗口变化时全量重算）"""
        import datetime
        today = datetime.date.today()
        month_start = datetime.datetime(today.year, today.month, 1).timestamp()
        if month_start != self._monthly_window_start:
            self._monthly_total = sum(
                r.estimated_cost for r in self._records
                if r.timestamp >= month_start
            )
            self._monthly_window_start = month_start

    def check_budget(self, level: BudgetLevel, model: str = "", projected_cost: float = 0.0) -> tuple[bool, float, float]:
        """检查预算是否充足

        [V9.5] 使用 rolling aggregation 减少 O(N) 遍历：
        - REQUEST: O(1) 直接比较
        - DAILY: 日窗口内 O(1) 增量维护，仅跨日时 O(N) 重算
        - MONTHLY: 月窗口内 O(1) 增量维护，仅跨月时 O(N) 重算

        Returns:
            (是否充足, 已使用, 预算上限)
        """
        now = time.time()

        if level == BudgetLevel.REQUEST:
            used = projected_cost
            limit = self.request_budget
            return used <= limit, used, limit

        elif level == BudgetLevel.DAILY:
            self._refresh_daily_window(now)
            used = self._daily_total
            return used + projected_cost <= self.daily_budget, used, self.daily_budget

        elif level == BudgetLevel.MONTHLY:
            self._refresh_monthly_window(now)
            used = self._monthly_total
            return used + projected_cost <= self.monthly_budget, used, self.monthly_budget

        return True, 0.0, float("inf")

    def is_budget_available(self, model: str = "", input_tokens: int = 0, output_tokens: int = 0) -> bool:
        """检查当前请求是否在预算内"""
        pricing = self.get_pricing(model)
        projected = pricing.estimate_cost(input_tokens, output_tokens) if pricing else 0.0

        for level in [BudgetLevel.REQUEST, BudgetLevel.DAILY, BudgetLevel.MONTHLY]:
            ok, used, limit = self.check_budget(level, model, projected)
            if not ok:
                self._logger.warning(
                    "budget_exceeded",
                    level=level.value,
                    used=round(used, 4),
                    limit=round(limit, 4),
                    model=model,
                )
                return False
        return True

    # ── 成本感知路由 ────────────────────────────────────

    def select_model_for_task(
        self,
        task_complexity: str = "medium",
        preferred_model: str = "",
    ) -> str:
        """根据任务复杂度和预算选择模型

        Args:
            task_complexity: low | medium | high
            preferred_model: 用户偏好的模型

        Returns:
            推荐的模型名称
        """
        if not self.enable_routing:
            return preferred_model or "gpt-4o-mini"

        # 检查日预算余量
        ok, used, limit = self.check_budget(BudgetLevel.DAILY)
        usage_ratio = used / limit if limit > 0 else 0

        # 预算紧张时强制降级
        if usage_ratio > 0.9:
            return "gpt-4o-mini"
        if usage_ratio > 0.7:
            task_complexity = "low"  # 强制降级

        # 按复杂度路由
        if task_complexity == "low":
            return "gpt-4o-mini"
        elif task_complexity == "medium":
            return preferred_model or "gpt-4o"
        elif task_complexity == "high":
            return preferred_model or "gpt-4o"

        return preferred_model or "gpt-4o-mini"

    # ── 统计 ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取使用统计"""
        now = time.time()
        day_start = now - (now % 86400)

        daily_records = [r for r in self._records if r.timestamp >= day_start]
        total_input = sum(r.input_tokens for r in daily_records)
        total_output = sum(r.output_tokens for r in daily_records)
        total_cost = sum(r.estimated_cost for r in daily_records)

        _, used_daily, _ = self.check_budget(BudgetLevel.DAILY)
        _, used_monthly, _ = self.check_budget(BudgetLevel.MONTHLY)

        return {
            "daily": {
                "requests": len(daily_records),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "estimated_cost_usd": round(total_cost, 4),
                "budget_used_ratio": round(used_daily / self.daily_budget, 4) if self.daily_budget > 0 else 0,
            },
            "monthly": {
                "budget_used_ratio": round(used_monthly / self.monthly_budget, 4) if self.monthly_budget > 0 else 0,
            },
            "total_records": len(self._records),
        }

    def get_model_usage(self, model: str) -> dict[str, Any]:
        """获取指定模型的使用统计"""
        records = [r for r in self._records if r.model == model]
        return {
            "model": model,
            "requests": len(records),
            "input_tokens": sum(r.input_tokens for r in records),
            "output_tokens": sum(r.output_tokens for r in records),
            "estimated_cost_usd": round(sum(r.estimated_cost for r in records), 4),
        }

    def preaggregate(self) -> None:
        """[V9.5-R2] 预聚合：可在空闲时主动调用以平滑跨日切换的O(N)峰值"""
        now = time.time()
        self._refresh_daily_window(now)
        self._refresh_monthly_window(now)
