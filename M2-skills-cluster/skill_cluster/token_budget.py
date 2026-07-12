from __future__ import annotations
from collections import deque

"""Token Budget - Token 预算控制器.

为 Agent 调用设置 Token 消耗上限，支持上下文优先级裁剪、
模型分级路由、实时预算追踪和超限拦截。
"""

import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class BudgetEntry(BaseModel):
    """预算条目."""

    category: str = Field(..., description="消耗类别: input/output/tool/think")
    tokens: int = Field(..., description="Token 数量")
    timestamp: float = Field(default_factory=time.time, description="时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class BudgetAlert(BaseModel):
    """预算告警."""

    alert_type: str = Field(..., description="告警类型: warning/exceeded/exhausted")
    message: str = Field(..., description="告警消息")
    total_tokens: int = Field(..., description="当前总消耗")
    budget_limit: int = Field(..., description="预算上限")
    remaining: int = Field(..., description="剩余 Token")
    timestamp: float = Field(default_factory=time.time, description="时间")


class TokenBudget:
    """Token 预算控制器.

    追踪每次 Agent 会话的 Token 消耗，支持预算分配、
    实时监控、超限拦截和上下文优先级裁剪。
    """

    def __init__(
        self,
        total_budget: int = 100_000,
        alert_threshold: float = 0.8,
    ) -> None:
        self._total_budget = total_budget
        self._alert_threshold = alert_threshold
        self._consumed: int = 0
        self._entries: deque[BudgetEntry] = deque(maxlen=10000)
        self._alerts: deque[BudgetAlert] = deque(maxlen=1000)
        self._category_budgets: dict[str, int] = {}
        self._category_consumed: dict[str, int] = {}

    @property
    def remaining(self) -> int:
        return max(0, self._total_budget - self._consumed)

    @property
    def is_exhausted(self) -> bool:
        return self._consumed >= self._total_budget

    @property
    def usage_ratio(self) -> float:
        if self._total_budget == 0:
            return 1.0
        return self._consumed / self._total_budget

    # ---- 预算分配 ----

    def allocate_category(self, category: str, budget: int) -> None:
        """为特定类别分配独立预算.

        Args:
            category: 类别名（如 "input", "output", "tool", "think"）.
            budget: 该类别的 Token 预算上限.
        """
        self._category_budgets[category] = budget
        self._category_consumed.setdefault(category, 0)

    def set_total_budget(self, budget: int) -> None:
        """调整总预算."""
        self._total_budget = max(0, budget)

    # ---- 消费记录 ----

    def consume(
        self,
        tokens: int,
        category: str = "input",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, BudgetAlert | None]:
        """消费 Token.

        Args:
            tokens: 消费数量.
            category: 消费类别.
            metadata: 元数据.

        Returns:
            (是否允许消费, 告警信息).
        """
        # 检查总预算
        if self._consumed + tokens > self._total_budget:
            alert = BudgetAlert(
                alert_type="exceeded",
                message=f"Token 消费超出总预算: 需要 {tokens}, 剩余 {self.remaining}",
                total_tokens=self._consumed,
                budget_limit=self._total_budget,
                remaining=self.remaining,
            )
            self._alerts.append(alert)
            logger.warning(
                "token_budget_exceeded",
                requested=tokens,
                remaining=self.remaining,
                total=self._consumed,
            )
            return False, alert

        # 检查类别预算
        cat_budget = self._category_budgets.get(category)
        if cat_budget is not None:
            cat_consumed = self._category_consumed.get(category, 0)
            if cat_consumed + tokens > cat_budget:
                alert = BudgetAlert(
                    alert_type="warning",
                    message=f"类别 '{category}' 预算不足: 需要 {tokens}, "
                    f"类别剩余 {cat_budget - cat_consumed}",
                    total_tokens=self._consumed,
                    budget_limit=self._total_budget,
                    remaining=self.remaining,
                )
                self._alerts.append(alert)
                return False, alert

        # 执行消费
        self._consumed += tokens
        self._category_consumed[category] = (
            self._category_consumed.get(category, 0) + tokens
        )
        entry = BudgetEntry(
            category=category,
            tokens=tokens,
            metadata=metadata or {},
        )
        self._entries.append(entry)

        # 检查告警阈值
        alert = None
        if (
            not self.is_exhausted
            and self.usage_ratio >= self._alert_threshold
        ):
            # 仅在首次达到阈值时告警
            recent = [
                a for a in self._alerts if a.alert_type == "warning"
            ]
            if not recent or self.usage_ratio - (
                (recent[-1].total_tokens) / self._total_budget
                if self._total_budget
                else 0
            ) > 0.05:
                alert = BudgetAlert(
                    alert_type="warning",
                    message=f"Token 预算已达 {self.usage_ratio:.0%}",
                    total_tokens=self._consumed,
                    budget_limit=self._total_budget,
                    remaining=self.remaining,
                )
                self._alerts.append(alert)

        return True, alert

    def try_consume(
        self, tokens: int, category: str = "input"
    ) -> bool:
        """尝试消费，不返回告警的简化接口.

        先预检查，若超限则不执行 consume。
        """
        if self._consumed + tokens > self._total_budget:
            return False
        cat_budget = self._category_budgets.get(category)
        if cat_budget is not None:
            cat_consumed = self._category_consumed.get(category, 0)
            if cat_consumed + tokens > cat_budget:
                return False
        allowed, _ = self.consume(tokens, category)
        return allowed

    # ---- 上下文裁剪 ----

    def trim_context(
        self,
        context_items: list[dict[str, Any]],
        token_field: str = "tokens",
        priority_field: str = "priority",
    ) -> list[dict[str, Any]]:
        """按优先级裁剪上下文列表，使其符合剩余预算.

        Args:
            context_items: 上下文项列表，每项必须包含 token_field 和 priority_field.
            token_field: Token 数量的字段名.
            priority_field: 优先级字段名（1=最高，数字越大优先级越低）.

        Returns:
            裁剪后的上下文列表.
        """
        remaining = self.remaining
        sorted_items = sorted(
            context_items,
            key=lambda x: x.get(priority_field, 999),
        )
        result: list[dict[str, Any]] = []
        total = 0

        for item in sorted_items:
            cost = item.get(token_field, 0)
            if total + cost <= remaining:
                result.append(item)
                total += cost
            else:
                break

        trimmed = len(context_items) - len(result)
        if trimmed > 0:
            logger.info(
                "context_trimmed",
                original=len(context_items),
                kept=len(result),
                trimmed=trimmed,
                saved_tokens=total,
            )

        return result

    # ---- 模型路由建议 ----

    def suggest_model_tier(self) -> str:
        """根据剩余预算建议模型层级.

        Returns:
            "large" / "medium" / "small"
        """
        ratio = self.usage_ratio
        if ratio < 0.3:
            return "large"
        elif ratio < 0.7:
            return "medium"
        else:
            return "small"

    # ---- 查询 ----

    def get_summary(self) -> dict[str, Any]:
        """获取预算摘要."""
        return {
            "total_budget": self._total_budget,
            "consumed": self._consumed,
            "remaining": self.remaining,
            "usage_ratio": round(self.usage_ratio, 4),
            "is_exhausted": self.is_exhausted,
            "suggested_model": self.suggest_model_tier(),
            "category_breakdown": dict(self._category_consumed),
            "alert_count": len(self._alerts),
        }

    def get_category_usage(self, category: str) -> int:
        """获取类别消费量."""
        return self._category_consumed.get(category, 0)

    def get_entries(self, limit: int = 100) -> list[BudgetEntry]:
        """获取消费记录."""
        return list(self._entries)[-limit:]

    def get_alerts(self, limit: int = 10) -> list[BudgetAlert]:
        """获取告警记录."""
        return list(self._alerts)[-limit:]

    def reset(self) -> None:
        """重置预算."""
        self._consumed = 0
        self._entries.clear()
        self._alerts.clear()
        self._category_consumed = {k: 0 for k in self._category_consumed}
