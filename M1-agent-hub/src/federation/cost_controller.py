"""
成本管控与账单系统 — CostController

管理外部 Agent 的预算、扣费、告警和账单统计。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from shared_models import (
    CostRecord,
    FederationBudget,
)

logger = structlog.get_logger(__name__)


class CostController:
    """成本管控器

    功能：
    - 月度预算设置
    - 实时扣费
    - 三级预算告警（50%/80%/100%）
    - 超预算熔断
    - 账单明细查询
    """

    def __init__(
        self,
        monthly_budget: float = 10.0,  # 默认月度预算 10 美元
        currency: str = "USD",
    ) -> None:
        self._budget = FederationBudget(
            monthly_budget=monthly_budget,
            currency=currency,
            last_reset_month=self._current_month(),
        )
        self._records: list[CostRecord] = []
        self._logger = logger.bind(component="cost_controller")

    # ── 预算管理 ────────────────────────────────────────

    def set_monthly_budget(self, amount: float) -> dict[str, Any]:
        """设置月度预算

        Returns:
            预算设置结果
        """
        self._budget.monthly_budget = amount
        # 重新计算告警状态
        self._check_thresholds()

        self._logger.info(
            "monthly_budget_set",
            amount=amount,
            currency=self._budget.currency,
        )

        return {
            "success": True,
            "monthly_budget": amount,
            "currency": self._budget.currency,
            "spent_this_month": self._budget.spent_this_month,
            "remaining": self.remaining_budget(),
        }

    def get_budget(self) -> FederationBudget:
        """获取预算状态"""
        self._ensure_month_reset()
        return self._budget.model_copy()

    def remaining_budget(self) -> float:
        """获取剩余预算"""
        self._ensure_month_reset()
        return max(0.0, self._budget.monthly_budget - self._budget.spent_this_month)

    def budget_exceeded(self) -> bool:
        """是否超预算"""
        self._ensure_month_reset()
        return self._budget.spent_this_month >= self._budget.monthly_budget

    # ── 扣费 ────────────────────────────────────────────

    def record_cost(
        self,
        task_id: str,
        agent_id: str,
        agent_name: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        task_type: str = "general",
        success: bool = True,
    ) -> CostRecord:
        """记录一次调用费用

        Args:
            task_id: 任务 ID
            agent_id: Agent ID
            agent_name: Agent 名称
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            cost: 费用（美元）
            task_type: 任务类型
            success: 是否成功

        Returns:
            CostRecord 记录
        """
        self._ensure_month_reset()

        record = CostRecord(
            record_id=uuid.uuid4().hex[:12],
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            currency=self._budget.currency,
            task_type=task_type,
            success=success,
        )

        self._records.append(record)

        # 成功的调用才计入已花费
        if success:
            self._budget.spent_this_month += cost
            self._check_thresholds()

        self._logger.info(
            "cost_recorded",
            agent_id=agent_id,
            cost=round(cost, 6),
            task_type=task_type,
            success=success,
            total_spent=round(self._budget.spent_this_month, 4),
        )

        return record

    # ── 告警检查 ────────────────────────────────────────

    def _check_thresholds(self) -> list[str]:
        """检查预算阈值，返回触发的告警列表"""
        alerts: list[str] = []
        budget = self._budget.monthly_budget
        spent = self._budget.spent_this_month

        if budget <= 0:
            return alerts

        ratio = spent / budget

        if ratio >= 1.0 and not self._budget.alert_threshold_100:
            self._budget.alert_threshold_100 = True
            alerts.append("critical: 本月预算已用完，切换到内部模式")
            self._logger.warning("budget_100_percent", spent=round(spent, 4), budget=budget)

        if ratio >= 0.8 and not self._budget.alert_threshold_80:
            self._budget.alert_threshold_80 = True
            alerts.append("warning: 预算已用 80%，注意控制")
            self._logger.warning("budget_80_percent", spent=round(spent, 4), budget=budget)

        if ratio >= 0.5 and not self._budget.alert_threshold_50:
            self._budget.alert_threshold_50 = True
            alerts.append("info: 本月已用一半预算")
            self._logger.info("budget_50_percent", spent=round(spent, 4), budget=budget)

        return alerts

    def check_and_get_alerts(self) -> list[str]:
        """检查并返回当前告警"""
        self._ensure_month_reset()
        return self._check_thresholds()

    # ── 账单查询 ────────────────────────────────────────

    def get_records(
        self,
        agent_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        task_type: str | None = None,
        limit: int = 100,
    ) -> list[CostRecord]:
        """查询账单明细

        Args:
            agent_id: 按 Agent 筛选
            start_time: 开始时间
            end_time: 结束时间
            task_type: 任务类型
            limit: 最大返回数

        Returns:
            费用记录列表
        """
        results = list(self._records)

        if agent_id:
            results = [r for r in results if r.agent_id == agent_id]
        if start_time:
            results = [r for r in results if r.timestamp >= start_time]
        if end_time:
            results = [r for r in results if r.timestamp <= end_time]
        if task_type:
            results = [r for r in results if r.task_type == task_type]

        # 按时间倒序
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    def get_daily_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """按日统计账单

        Args:
            days: 最近几天

        Returns:
            每日统计列表
        """
        now = time.time()
        day_seconds = 86400
        daily: dict[str, dict[str, Any]] = {}

        for i in range(days):
            day_start = now - (i + 1) * day_seconds
            day_end = now - i * day_seconds
            day_key = time.strftime("%Y-%m-%d", time.localtime(day_start))
            daily[day_key] = {
                "date": day_key,
                "total_cost": 0.0,
                "call_count": 0,
                "agents": set(),
            }

        for record in self._records:
            for day_key, day_data in daily.items():
                day_start = time.mktime(time.strptime(day_key, "%Y-%m-%d"))
                day_end = day_start + day_seconds
                if day_start <= record.timestamp < day_end:
                    day_data["total_cost"] += record.cost
                    day_data["call_count"] += 1
                    day_data["agents"].add(record.agent_id)
                    break

        result = []
        for day_key in sorted(daily.keys(), reverse=True):
            data = daily[day_key]
            data["agents"] = list(data["agents"])
            result.append(data)

        return result

    # ── 月度重置 ────────────────────────────────────────

    def _ensure_month_reset(self) -> None:
        """确保月度重置（跨月时重置已花费金额）"""
        current = self._current_month()
        if current != self._budget.last_reset_month:
            self._budget.spent_this_month = 0.0
            self._budget.alert_threshold_50 = False
            self._budget.alert_threshold_80 = False
            self._budget.alert_threshold_100 = False
            self._budget.last_reset_month = current
            self._logger.info("budget_monthly_reset", month=current)

    def _current_month(self) -> str:
        """获取当前月份字符串"""
        return time.strftime("%Y-%m")

    # ── 统计 ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """成本统计总览"""
        self._ensure_month_reset()
        budget = self._budget
        ratio = budget.spent_this_month / budget.monthly_budget if budget.monthly_budget > 0 else 0

        return {
            "monthly_budget": budget.monthly_budget,
            "spent_this_month": round(budget.spent_this_month, 4),
            "remaining": round(self.remaining_budget(), 4),
            "usage_ratio": round(ratio * 100, 2),
            "currency": budget.currency,
            "alert_50": budget.alert_threshold_50,
            "alert_80": budget.alert_threshold_80,
            "alert_100": budget.alert_threshold_100,
            "total_records": len(self._records),
            "successful_calls": sum(1 for r in self._records if r.success),
        }
