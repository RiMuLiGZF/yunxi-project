# =============================================================================
# DEPRECATED - 已废弃版本（归档于 _deprecated/）
# =============================================================================
# 本文件已从 src/orchestration/orchestrator_v7.py 归档至此处。
# 废弃原因：V7 编排器已被 V8/V9 扁平化设计替代，仅作为内部依赖链保留。
# 保留版本：V8（稳定）、V9（最新生产版）
# 归档日期：2026-07-19
# 注意：此文件仅供 v8/v9 内部依赖链使用，新代码请勿直接导入。
# =============================================================================

"""
云汐内核 V7 - 整合编排器（已归档）

在 V6 基础上集成 V7 核心能力：
- 多 Agent 集成引擎（EnsembleEngine）：投票/共识/加权合成/最优选择
- Token 预算管理（BudgetManager）：成本感知路由、预算管控
- 任务耐久性（TaskDurabilityManager）：检查点/重放/幂等保护

提供具备群体智能、成本意识、容错能力的 Agent 集群调度中枢。

[DEPRECATED] 本版本已归档，仅作为 V8/V9 内部依赖链保留。
新代码请使用 OrchestratorV9（生产版）或 OrchestratorV8（稳定版）。
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import structlog

from src.orchestration._deprecated.orchestrator_v5 import OrchestratorV5
from src.orchestration.ensemble_engine import EnsembleEngine, EnsembleStrategy, AgentVote, EnsembleResult
from src.resilience.budget_manager import BudgetManager
from src.core.task_durability import TaskDurabilityManager, DurableTask
from src.core.persistence import SQLitePersistence

logger = structlog.get_logger(__name__)


class OrchestratorV7:
    """V7 整合编排器（已归档）

    在 V6 基础上增加：
    1. 集成引擎：对同一问题并行调用多个 Agent，通过策略合成最终答案
    2. 预算管理：token 计量、预算上限、成本感知路由
    3. 任务耐久性：多步骤任务自动检查点，崩溃后精确重放

    [DEPRECATED] 已归档至 _deprecated/，仅供 V8/V9 内部依赖链使用。
    """

    def __init__(
        self,
        orchestrator_v5: OrchestratorV5,
        ensemble_engine: EnsembleEngine | None = None,
        budget_manager: BudgetManager | None = None,
        durability_manager: TaskDurabilityManager | None = None,
    ) -> None:
        self._v5 = orchestrator_v5
        self._ensemble = ensemble_engine or EnsembleEngine()
        self._budget = budget_manager or BudgetManager()
        self._durability = durability_manager
        self._logger = logger.bind(service="orchestrator_v7")

    # ── 核心入口：集成处理 ──────────────────────────────

    async def process_ensemble(
        self,
        query: str,
        agent_ids: list[str],
        trace_id: str | None = None,
        strategy: EnsembleStrategy | None = None,
    ) -> EnsembleResult:
        """多 Agent 集成处理

        对同一问题并行调用多个 Agent，通过策略合成最终答案。
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # [P0-4-2] BudgetManager 全链路传播：ensemble 模式预算检查
        if self._budget is not None and not self._budget.is_budget_available():
            self._logger.warning("budget_exceeded_in_ensemble", trace_id=trace_id)
            # 返回一个标记为预算超支的 EnsembleResult
            return EnsembleResult(
                final_answer="预算已用尽，请联系管理员。",
                strategy=strategy or EnsembleStrategy.VOTING,
                votes=[],
                consensus_reached=False,
                latency_ms=0.0,
            )

        async def caller(agent_id: str, q: str) -> AgentVote:
            result = await self._v5.process(
                user_input=q,
                trace_id=f"{trace_id}_{agent_id}",
            )
            reply = result.get("reply", "")
            confidence = 0.8 if result.get("status") == "success" else 0.3
            return AgentVote(
                agent_id=agent_id,
                response=reply,
                confidence=confidence,
            )

        result = await self._ensemble.run(
            query=query,
            agent_ids=agent_ids,
            caller=caller,
            strategy=strategy,
        )

        # 记录预算
        self._budget.record_usage(
            model=self._v5.get_config("llm.model", "mock-model"),
            input_tokens=len(query),
            output_tokens=len(result.final_answer),
        )

        return result

    # ── 核心入口：预算感知处理 ──────────────────────────

    async def process_budget_aware(
        self,
        user_input: str,
        trace_id: str | None = None,
        task_complexity: str = "medium",
    ) -> dict[str, Any]:
        """预算感知处理

        根据任务复杂度和当前预算选择模型，超支时自动降级。
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # 1. 检查预算
        model = self._budget.select_model_for_task(task_complexity)
        if not self._budget.is_budget_available(model, input_tokens=len(user_input)):
            return {
                "reply": "当前预算已用尽，请联系管理员。",
                "status": "budget_exceeded",
                "trace_id": trace_id,
            }

        # 2. 处理
        result = await self._v5.process(
            user_input=user_input,
            trace_id=trace_id,
            use_llm=True,
        )

        # 3. 记录使用
        self._budget.record_usage(
            model=model,
            input_tokens=len(user_input),
            output_tokens=len(result.get("reply", "")),
            latency_ms=result.get("latency_ms", 0),
        )

        result["model_used"] = model
        result["budget_stats"] = self._budget.get_stats()
        return result

    # ── 核心入口：耐久性任务 ────────────────────────────

    async def run_durable_task(
        self,
        task_id: str,
        activities: list,
        initial_state: dict[str, Any],
    ) -> dict[str, Any]:
        """运行耐久性任务

        任务执行过程中自动保存检查点，崩溃后可从检查点恢复。
        """
        if self._durability is None:
            self._logger.warning("durability_manager_not_configured")
            # 退化为普通执行
            state = dict(initial_state)
            for name, activity in activities:
                result = await activity(state)
                state.update(result)
            return state

        task = self._durability.create_task(task_id, activities)
        return await task.execute(initial_state)

    # ── 兼容入口 ────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        override_intent: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """标准处理（委托给 V5）

        Args:
            override_intent: [P2-003] V9/V8 下发的 V3 意图覆盖，透传至 V2。
        """
        # [P0-4-2] BudgetManager 全链路传播：V7 层预算检查
        if self._budget is not None and not self._budget.is_budget_available(
            model=kwargs.get("model", ""),
            input_tokens=kwargs.get("input_tokens", 0),
            output_tokens=kwargs.get("output_tokens", 0),
        ):
            self._logger.warning("budget_exceeded_in_v7", trace_id=trace_id)
            return {
                "status": "budget_exceeded",
                "reason": "budget_limit_reached",
                "trace_id": trace_id,
            }
        return await self._v5.process(user_input, trace_id=trace_id, override_intent=override_intent, **kwargs)

    async def process_stream(
        self,
        user_input: str,
        trace_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """流式处理（委托给 V5）"""
        async for chunk in self._v5.process_stream(user_input, trace_id=trace_id, **kwargs):
            yield chunk

    # ── 策略推荐 ────────────────────────────────────────

    def recommend_strategy(self, query: str, task_type: str = "") -> EnsembleStrategy:
        """推荐集成策略"""
        return self._ensemble.recommend_strategy(query, task_type)

    # ── 预算查询 ────────────────────────────────────────

    def get_budget_stats(self) -> dict[str, Any]:
        """获取预算统计"""
        return self._budget.get_stats()

    def get_model_usage(self, model: str) -> dict[str, Any]:
        """获取模型使用统计"""
        return self._budget.get_model_usage(model)

    # ── 诊断 ────────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """V7 增强诊断"""
        v5_diagnosis = self._v5.diagnose()
        return {
            **v5_diagnosis,
            "v7": {
                "ensemble": {
                    "default_strategy": self._ensemble.default_strategy.value,
                    "consensus_threshold": self._ensemble.consensus_threshold,
                    "max_debate_rounds": self._ensemble.max_debate_rounds,
                },
                "budget": self._budget.get_stats(),
                "durability": self._durability.stats() if self._durability else None,
            },
        }

    # ── V5/V4/V3/V2/V1 能力透传 ───────────────────────

    def __getattr__(self, name: str) -> Any:
        """透传 V5 的已知方法"""
        return getattr(self._v5, name)
