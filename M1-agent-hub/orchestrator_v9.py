"""
云汐内核 V9 - 统一编排器

在 V8 基础上集成 V9 核心能力：
- 语义意图分类（SemanticIntentClassifierV3）
- GroupChat 对话引擎
- OTLP Trace 导出

扁平化设计：直接组合所有模块，无嵌套委托链。
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import structlog

from orchestrator_v8 import OrchestratorV8
from semantic_intent_v3 import SemanticIntentClassifierV3
from group_chat import (
    GroupChatEngine, GroupChatAgent, RoundRobinSelector,
    CompositeTermination, MaxRoundTermination, KeywordTermination,
    ConvergenceTermination,
)
from otlp_exporter import OTLPExporter, OTLPSpan
from guardrails_v2 import GuardrailsV2
from ledger_engine import LedgerEngine, LedgerStatus
from budget_manager import BudgetManager

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class OrchestratorV9:
    """V9 统一编排器

    在 V8 基础上集成 V9 核心能力：
    - 语义意图分类（SemanticIntentClassifierV3）
    - GroupChat 对话引擎（含收敛检测）
    - OTLP Trace 导出
    - Guardrails V2 输入安检
    - Ledger 双层任务账本
    """

    def __init__(
        self,
        orchestrator_v8: OrchestratorV8,
        intent_classifier: SemanticIntentClassifierV3 | None = None,
        otlp_exporter: OTLPExporter | None = None,
        guardrails: GuardrailsV2 | None = None,
        ledger: LedgerEngine | None = None,
        budget_manager: BudgetManager | None = None,
    ) -> None:
        self._v8: OrchestratorV8 = orchestrator_v8
        self._intent: SemanticIntentClassifierV3 = intent_classifier or SemanticIntentClassifierV3()
        self._otlp: OTLPExporter | None = otlp_exporter
        self._guardrails: GuardrailsV2 = guardrails or GuardrailsV2()
        self._ledger: LedgerEngine = ledger or LedgerEngine()
        self._budget: BudgetManager | None = budget_manager
        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="orchestrator_v9")

    # ── 语义意图路由 ────────────────────────────────

    def classify_intent(self, text: str) -> dict[str, Any]:
        """语义意图分类"""
        return self._intent.classify(text)

    def train_intent(self, samples: dict[str, list[str]]) -> None:
        """训练意图分类器"""
        self._intent.train(samples)

    # ── GroupChat ──────────────────────────────────

    async def run_group_chat(
        self,
        agents: list[GroupChatAgent],
        task: str = "",
        max_round: int = 10,
    ) -> dict[str, Any]:
        """运行 GroupChat（含收敛检测）

        [P2-023] 将已有 SemanticIntentClassifierV3 实例注入 ConvergenceTermination，
        避免每次调用创建独立分类器。
        """
        engine = GroupChatEngine(
            agents=agents,
            selector=RoundRobinSelector(),
            termination=CompositeTermination(
                MaxRoundTermination(max_round),
                KeywordTermination("TERMINATE"),
                ConvergenceTermination(
                    window_size=3,
                    similarity_threshold=0.85,
                    classifier=self._intent,  # [P2-023] 复用全局分类器实例
                ),
            ),
        )
        return await engine.run(task=task)

    # ── OTLP 导出 ──────────────────────────────────

    def export_trace(self, trace_dict: dict[str, Any]) -> None:
        """导出 Trace 到 OTLP"""
        if self._otlp is None:
            return
        trace_id = trace_dict.get("trace_id", "")
        for span_dict in trace_dict.get("spans", []):
            span = OTLPSpan(
                trace_id=trace_id,
                span_id=span_dict.get("span_id", ""),
                parent_span_id=span_dict.get("parent_id", ""),
                name=span_dict.get("name", ""),
                start_time_ns=int(span_dict.get("start_time", 0) * 1e9),
                end_time_ns=int(span_dict.get("end_time", 0) * 1e9),
                attributes=span_dict.get("attributes", {}),
                events=[{"name": e[0], "timestamp": e[1], "attributes": {}} for e in span_dict.get("events", [])],
            )
            self._otlp.export_span(span)

    # ── 兼容入口（集成 Guardrails + Ledger）─────────────────

    def _run_guardrails(self, user_input: str) -> GuardrailsResult:
        """[P1-1-1] 步骤1：输入安检"""
        return self._guardrails.check(user_input)

    def _is_simple_query(self, user_input: str) -> bool:
        """[P3-005] 判定是否为简单查询"""
        if len(user_input) < 20:
            return True
        simple_keywords = {
            "hello", "hi", "你好", "在吗", "状态", "status", "help", "帮助",
        }
        lower_input = user_input.lower()
        for kw in simple_keywords:
            if kw in lower_input:
                return True
        return False

    def _run_intent(self, user_input: str) -> dict[str, Any]:
        """[P1-1-1] 步骤2.5：V3 意图分类结果注入处理链"""
        return self._intent.classify(user_input)

    def _run_budget(self, task_id: str, model: str = "", input_tokens: int = 0, output_tokens: int = 0) -> bool:
        """[P1-1-1] 步骤2.6：BudgetManager 预算检查点"""
        if self._budget is None:
            return True
        if not self._budget.is_budget_available(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ):
            self._logger.warning(
                "budget_exceeded_in_process",
                task_id=task_id,
            )
            return False
        return True

    async def _delegate_v8(self, user_input: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """[P1-1-1] 步骤3：透传 V8 处理（携带 override_intent）"""
        v8_result = await self._v8.process(user_input, **kwargs)

        # [V9.6] Ledger 数据闭环：任务完成后标记终态
        task_id = kwargs.get("task_id", "")
        if self._ledger is not None and task_id:
            final_status = LedgerStatus.COMPLETED if v8_result.get("status") == "success" else LedgerStatus.FAILED
            self._ledger.close_task(task_id, final_status)

        return v8_result

    def _run_ledger_replan(self, task_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
        """[P1-1-1] 步骤4：Ledger 重规划评估与自动执行

        [P1-7-2] evaluate_and_replan() 返回建议后，根据 reason 自动触发具体动作。
        """
        replan = self._ledger.evaluate_and_replan(task_id)
        if not replan:
            return None

        result["ledger_replan"] = replan
        action_result: dict[str, Any] = {
            "reason": replan.get("reason"),
            "executed": False,
        }

        reason = replan.get("reason", "")
        if reason == "blockers_detected":
            # 将失败 plan 的 assigned_agent 清空，等待重新分配
            task_ledger, _ = self._ledger.get_ledgers(task_id)
            if task_ledger is not None:
                cleared: list[str] = []
                for blocker in replan.get("blockers", []):
                    plan_id = blocker.get("plan_id", "")
                    if plan_id in task_ledger._plan_index:
                        task_ledger._plan_index[plan_id].assigned_agent = ""
                        cleared.append(plan_id)
                action_result["executed"] = True
                action_result["cleared_plans"] = cleared
        elif reason == "agents_stalled":
            result["stalled_agents"] = replan.get("stalled_agents", [])
            action_result["executed"] = True
        elif reason in ("too_many_deviations", "progress_stalled"):
            result["needs_replan"] = True
            action_result["executed"] = True

        return action_result

    async def process(self, user_input: str, **kwargs: Any) -> dict[str, Any]:
        """[P1-1-1] 统一处理入口：按顺序调用各私有子方法"""
        # 步骤1：输入安检
        guard_result = self._run_guardrails(user_input)
        if guard_result.blocked:
            self._logger.warning(
                "input_blocked_by_guardrails",
                reason=guard_result.block_reason,
                risk_score=guard_result.risk_score,
            )
            return {
                "status": "blocked",
                "reason": guard_result.block_reason,
                "risk_score": guard_result.risk_score,
                "detections": guard_result.detections,
            }

        # [P3-005] 简单查询预筛：跳过 V3 意图分类和 Ledger 跟踪，直接委托 V8
        if self._is_simple_query(user_input):
            return await self._delegate_v8(guard_result.sanitized_text, kwargs)

        # 步骤2：Ledger 跟踪（如有task_id）
        task_id = kwargs.get("task_id", "")
        if task_id:
            from ledger_engine import LedgerStatus
            self._ledger.create_task(task_id=task_id, goal=user_input)
            _, progress_ledger = self._ledger.get_ledgers(task_id)
            if progress_ledger:
                progress_ledger.record_progress(
                    agent_id="orchestrator",
                    status=LedgerStatus.IN_PROGRESS,
                )

        # [P2-003] 步骤2.5：V3 意图分类结果注入处理链
        sanitized_input = guard_result.sanitized_text
        v3_intent = self._run_intent(sanitized_input)
        kwargs["override_intent"] = v3_intent

        # [P3-005] 步骤2.6：BudgetManager 预算检查点
        if not self._run_budget(
            task_id=task_id,
            model=kwargs.get("model", ""),
            input_tokens=kwargs.get("input_tokens", 0),
            output_tokens=kwargs.get("output_tokens", 0),
        ):
            return {
                "status": "budget_exceeded",
                "reason": "budget_limit_reached",
                "task_id": task_id,
            }

        # 步骤3：透传 V8 处理（携带 override_intent）
        result = await self._delegate_v8(sanitized_input, kwargs)

        # 步骤4：Ledger 重规划评估与自动执行
        if task_id:
            replan_action = self._run_ledger_replan(task_id, result)
            if replan_action:
                result["replan_action"] = replan_action

        return result

    async def process_stream(self, user_input: str, **kwargs: Any) -> AsyncIterator[Any]:
        # [P3-004] Guardrails 入口检查
        guard_result = self._guardrails.check(user_input)
        if guard_result.blocked:
            yield {"status": "blocked", "reason": guard_result.block_reason}
            return
        async for chunk in self._v8.process_stream(user_input, **kwargs):
            yield chunk

    # ── 诊断 ────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        v8_diag = self._v8.diagnose()
        return {
            **v8_diag,
            "v9": {
                "intent_classifier": self._intent.stats(),
                "otlp_exporter": self._otlp.stats() if self._otlp else None,
                "guardrails": {
                    "enabled": True,
                    "injection_threshold": self._guardrails.injection_detector.threshold,
                    "pii_sanitize": self._guardrails.enable_pii,
                },
                "ledger": self._ledger.stats(),
                "budget_manager": self._budget.get_stats() if self._budget else None,
            },
        }

    # [V9.5] __getattr__ 白名单透传，防止内部实现泄露
    # [V9.5-R2] 可扩展白名单：支持运行时注册新透传方法
    _V8_PASS_THROUGH: set[str] = {
        "load_plugins", "get_config", "list_agents", "get_agent",
        "process_ensemble", "process_budget_aware", "acquire_model",
        "route_by_load", "filter_memories", "process_with_swarm",
        "cancel_task",  # [V9.9] 透传任务取消能力到上层
    }

    def __getattr__(self, name: str) -> Any:
        if name in self._V8_PASS_THROUGH:
            return getattr(self._v8, name)
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute '{name}'"
        )

    @classmethod
    def register_passthrough(cls, method_name: str) -> None:
        """[V9.5-R2] 注册新的 V8 透传方法到白名单"""
        cls._V8_PASS_THROUGH.add(method_name)
