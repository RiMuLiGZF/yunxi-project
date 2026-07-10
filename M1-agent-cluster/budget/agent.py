"""
预算管控子Agent — BudgetAgent

职责：
- 封装现有 BudgetManager，提供预算检查/使用记录/熔断请求处理
- 成本感知模型选择：根据任务复杂度推荐最优模型
- 超预算熔断：日/月/请求级预算超支时自动拦截

依赖：
- budget_manager.BudgetManager：Token预算与成本管理中心
- interfaces.IAgentPlugin / AgentTask / AgentResult：插件接口
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from interfaces import (
    AgentTask,
    AgentResult,
    IAgentPlugin,
)
from budget_manager import BudgetManager, BudgetLevel

logger = structlog.get_logger(__name__)


class BudgetAgent(IAgentPlugin):
    """预算管控子Agent

    面向Agent集群提供统一的预算管控接口，支持：
    - 预算充足性检查（日/月/请求级）
    - 使用量记录与成本估算
    - 成本感知模型选择
    - 超预算熔断
    - 成本预警列表
    - 预算报告生成
    """

    agent_id: str = "agent.budget"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "budget.check",
        "budget.record",
        "budget.select_model",
        "budget.alerts",
        "budget.circuit",
        "budget.report",
    ]

    def __init__(
        self,
        daily_budget_usd: float = 100.0,
        monthly_budget_usd: float = 1000.0,
        request_budget_usd: float = 1.0,
    ) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        self._manager = BudgetManager(
            daily_budget_usd=daily_budget_usd,
            monthly_budget_usd=monthly_budget_usd,
            request_budget_usd=request_budget_usd,
            enable_routing=True,
        )
        # 超预算熔断任务缓存：task_id -> bool（是否已被熔断）
        self._circuit_triggered: dict[str, bool] = {}

    # ── 生命周期 ──────────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """挂载时初始化预算窗口"""
        self._manager.preaggregate()
        self._logger.info(
            "budget_agent_mounted",
            daily_budget=self._manager.daily_budget,
            monthly_budget=self._manager.monthly_budget,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查：包含预算使用情况"""
        base = await super().health()
        base["budget_stats"] = self._manager.get_stats()
        return base

    # ── 核心任务处理 ─────────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理预算检查/使用记录/熔断请求

        支持的 intent：
        - budget.check      ：检查预算是否充足
        - budget.record     ：记录使用量
        - budget.select_model：成本感知模型选择
        - budget.alerts     ：获取成本预警列表
        - budget.circuit    ：超预算熔断
        - budget.report     ：获取预算报告
        """
        start_time = time.time()
        self._logger.info(
            "budget_agent_handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=task.intent,
        )

        try:
            intent = task.intent
            payload = task.payload

            if intent == "budget.check":
                output = await self._handle_check(payload)
            elif intent == "budget.record":
                output = await self._handle_record(payload)
            elif intent == "budget.select_model":
                output = self._handle_select_model(payload)
            elif intent == "budget.alerts":
                output = self.get_alerts()
            elif intent == "budget.circuit":
                output = {"circuit_triggered": self.enforce_circuit(task.task_id)}
            elif intent == "budget.report":
                output = self.get_budget_report()
            else:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"不支持的intent: {intent}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=output,
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as exc:
            self._logger.error(
                "budget_agent_task_failed",
                error=str(exc),
                exc_info=True,
                task_id=task.task_id,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"BudgetAgent任务处理失败: {exc}",
                latency_ms=(time.time() - start_time) * 1000,
            )

    # ── 内部Handler ──────────────────────────────────────

    async def _handle_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理预算检查请求"""
        level_str: str = payload.get("level", "daily")
        model: str = payload.get("model", "")
        projected_cost: float = payload.get("projected_cost", 0.0)

        level_map = {
            "request": BudgetLevel.REQUEST,
            "session": BudgetLevel.SESSION,
            "daily": BudgetLevel.DAILY,
            "monthly": BudgetLevel.MONTHLY,
        }
        level = level_map.get(level_str, BudgetLevel.DAILY)

        is_ok, used, limit = self.check_budget(level, model, projected_cost)
        return {
            "sufficient": is_ok,
            "level": level_str,
            "used": round(used, 6),
            "limit": round(limit, 6),
            "usage_ratio": round(used / limit, 4) if limit > 0 else 0.0,
        }

    async def _handle_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理使用记录请求"""
        model: str = payload.get("model", "")
        input_tokens: int = payload.get("input_tokens", 0)
        output_tokens: int = payload.get("output_tokens", 0)
        agent_id: str = payload.get("agent_id", "")
        latency_ms: float = payload.get("latency_ms", 0.0)

        record = self.record_usage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_id=agent_id,
        )
        return {
            "recorded": True,
            "estimated_cost": round(record.estimated_cost, 6),
            "timestamp": record.timestamp,
        }

    def _handle_select_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理模型选择请求"""
        task_complexity: str = payload.get("task_complexity", "medium")
        preferred_model: str = payload.get("preferred_model", "")

        selected = self.select_model(task_complexity)
        return {
            "selected_model": selected,
            "task_complexity": task_complexity,
            "preferred_model": preferred_model,
        }

    # ── 公开API ──────────────────────────────────────────

    def check_budget(
        self,
        level: BudgetLevel,
        model: str = "",
        projected_cost: float = 0.0,
    ) -> tuple[bool, float, float]:
        """检查预算是否充足

        Args:
            level: 预算级别（request/session/daily/monthly）
            model: 模型名称（用于成本估算）
            projected_cost: 预估成本

        Returns:
            (是否充足, 已使用金额, 预算上限)
        """
        return self._manager.check_budget(level, model, projected_cost)

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """记录一次LLM使用

        Args:
            model: 模型名称
            input_tokens: 输入token数
            output_tokens: 输出token数
            agent_id: Agent标识

        Returns:
            包含记录详情的字典
        """
        record = self._manager.record_usage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            agent_id=agent_id,
        )
        self._logger.info(
            "usage_recorded",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=round(record.estimated_cost, 6),
            agent_id=agent_id,
        )
        return {
            "timestamp": record.timestamp,
            "model": record.model,
            "agent_id": record.agent_id,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "estimated_cost": round(record.estimated_cost, 6),
            "latency_ms": record.latency_ms,
        }

    def select_model(self, task_complexity: str) -> str:
        """成本感知模型选择

        根据任务复杂度（low/medium/high）和当前预算余量，
        推荐最具成本效益的模型。

        Args:
            task_complexity: 任务复杂度（low/medium/high）

        Returns:
            推荐的模型名称
        """
        selected = self._manager.select_model_for_task(
            task_complexity=task_complexity,
        )
        self._logger.info(
            "model_selected",
            task_complexity=task_complexity,
            selected_model=selected,
        )
        return selected

    def get_alerts(self) -> list[dict[str, Any]]:
        """获取成本预警列表

        当预算使用率超过阈值（70%/90%/100%）时生成预警。

        Returns:
            预警列表
        """
        alerts: list[dict[str, Any]] = []

        # 日预算预警
        ok_daily, used_daily, limit_daily = self._manager.check_budget(BudgetLevel.DAILY)
        ratio_daily = used_daily / limit_daily if limit_daily > 0 else 0.0
        if ratio_daily >= 1.0:
            alerts.append({
                "level": "critical",
                "type": "daily_budget_exceeded",
                "message": f"日预算已超支: {ratio_daily:.1%}",
                "used": round(used_daily, 4),
                "limit": round(limit_daily, 4),
            })
        elif ratio_daily >= 0.9:
            alerts.append({
                "level": "warning",
                "type": "daily_budget_near_limit",
                "message": f"日预算即将耗尽: {ratio_daily:.1%}",
                "used": round(used_daily, 4),
                "limit": round(limit_daily, 4),
            })
        elif ratio_daily >= 0.7:
            alerts.append({
                "level": "info",
                "type": "daily_budget_warning",
                "message": f"日预算使用率较高: {ratio_daily:.1%}",
                "used": round(used_daily, 4),
                "limit": round(limit_daily, 4),
            })

        # 月预算预警
        ok_monthly, used_monthly, limit_monthly = self._manager.check_budget(BudgetLevel.MONTHLY)
        ratio_monthly = used_monthly / limit_monthly if limit_monthly > 0 else 0.0
        if ratio_monthly >= 1.0:
            alerts.append({
                "level": "critical",
                "type": "monthly_budget_exceeded",
                "message": f"月预算已超支: {ratio_monthly:.1%}",
                "used": round(used_monthly, 4),
                "limit": round(limit_monthly, 4),
            })
        elif ratio_monthly >= 0.9:
            alerts.append({
                "level": "warning",
                "type": "monthly_budget_near_limit",
                "message": f"月预算即将耗尽: {ratio_monthly:.1%}",
                "used": round(used_monthly, 4),
                "limit": round(limit_monthly, 4),
            })

        self._logger.debug("budget_alerts_generated", count=len(alerts))
        return alerts

    def enforce_circuit(self, task_id: str) -> bool:
        """超预算熔断

        检查当前预算状态，若任一级别预算已耗尽则触发熔断。
        每个task_id仅触发一次熔断（幂等）。

        Args:
            task_id: 任务ID

        Returns:
            True表示已触发熔断，False表示预算正常
        """
        # 幂等检查：已被熔断的任务直接返回
        if self._circuit_triggered.get(task_id, False):
            self._logger.debug("circuit_already_triggered", task_id=task_id)
            return True

        # 检查各级别预算
        for level in [BudgetLevel.REQUEST, BudgetLevel.DAILY, BudgetLevel.MONTHLY]:
            is_ok, used, limit = self._manager.check_budget(level)
            if not is_ok:
                self._circuit_triggered[task_id] = True
                self._logger.warning(
                    "budget_circuit_triggered",
                    task_id=task_id,
                    level=level.value,
                    used=round(used, 4),
                    limit=round(limit, 4),
                )
                return True

        self._logger.debug("budget_circuit_ok", task_id=task_id)
        return False

    def get_budget_report(self) -> dict[str, Any]:
        """生成预算报告

        Returns:
            包含各级别预算使用情况、模型使用分布、预警的完整报告
        """
        stats = self._manager.get_stats()
        alerts = self.get_alerts()

        report: dict[str, Any] = {
            "generated_at": time.time(),
            "daily_budget": {
                "used": stats["daily"].get("estimated_cost_usd", 0.0),
                "limit": self._manager.daily_budget,
                "ratio": stats["daily"].get("budget_used_ratio", 0.0),
                "requests": stats["daily"].get("requests", 0),
                "input_tokens": stats["daily"].get("input_tokens", 0),
                "output_tokens": stats["daily"].get("output_tokens", 0),
            },
            "monthly_budget": {
                "used_ratio": stats["monthly"].get("budget_used_ratio", 0.0),
                "limit": self._manager.monthly_budget,
            },
            "total_records": stats.get("total_records", 0),
            "active_alerts": len(alerts),
            "alerts": alerts,
            "circuit_triggered_count": len(self._circuit_triggered),
        }
        return report
