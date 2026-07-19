# =============================================================================
# DEPRECATED - 已废弃版本（归档于 _deprecated/）
# =============================================================================
# 本文件已从 src/orchestration/orchestrator_v2.py 归档至此处。
# 废弃原因：V2 编排器已被 V8/V9 扁平化设计替代，仅作为内部依赖链保留。
# 保留版本：V8（稳定）、V9（最新生产版）
# 归档日期：2026-07-19
# 注意：此文件仅供 v8/v9 内部依赖链使用，新代码请勿直接导入。
# =============================================================================

"""
云汐内核 V2 - 整合编排器（已归档）

将 V2 升级组件（WorkflowEngine、Guardrails、Tracing、AgentCard、SemanticIntentClassifier）
整合为统一的编排层，与 V1 完全兼容且可增量升级。

[DEPRECATED] 本版本已归档，仅作为 V8/V9 内部依赖链保留。
新代码请使用 OrchestratorV9（生产版）或 OrchestratorV8（稳定版）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from src.tools.interfaces import AgentTask, AgentResult, BusMessage, IAgentPlugin, ClassifyResult
from src.agents.agent_registry import AgentRegistry
from src.core.intent_classifier_v2 import SemanticIntentClassifier
from src.core.task_dispatcher import TaskDispatcher
from src.orchestration.workflow_engine import (
    WorkflowEngine,
    WorkflowDefinition,
    WorkflowState,
    WorkflowResult,
    AgentNode,
    WorkflowPatterns,
)
from src.security.guardrail_pipeline import GuardrailPipeline, create_default_pipeline
from src.observability.tracing import Tracer, SpanKind, SpanStatus
from src.agents.agent_card import AgentCardRegistry, build_agent_card

logger = structlog.get_logger(__name__)


class OrchestratorV2:
    """V2 整合编排器（已归档）

    将 Guardrails、Tracing、WorkflowEngine、AgentCard 统一编排，
    提供与 V1 兼容的 API，同时暴露 V2 的高级能力。

    [DEPRECATED] 已归档至 _deprecated/，仅供 V8/V9 内部依赖链使用。
    """

    def __init__(
        self,
        registry: AgentRegistry,
        dispatcher: TaskDispatcher,
        classifier: SemanticIntentClassifier | None = None,
        workflow_engine: WorkflowEngine | None = None,
        tracer: Tracer | None = None,
        guardrail_pipeline: GuardrailPipeline | None = None,
        card_registry: AgentCardRegistry | None = None,
    ) -> None:
        self._registry = registry
        self._dispatcher = dispatcher
        self._classifier = classifier or SemanticIntentClassifier()
        self._workflow_engine = workflow_engine or WorkflowEngine()
        self._tracer = tracer or Tracer()
        self._guardrails = guardrail_pipeline or create_default_pipeline()
        self._card_registry = card_registry or AgentCardRegistry()
        self._logger = logger.bind(service="orchestrator_v2")

    # ── 核心入口：带护栏和追踪的请求处理 ────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        override_intent: dict | None = None,
    ) -> dict[str, Any]:
        """处理用户请求（V2 增强版）

        流程：
        1. 启动 Trace
        2. 输入 Guardrails 检查
        3. 语义意图分类（或使用 V9 下发的 override_intent）
        4. AgentCard 能力发现（确认目标 Agent）
        5. 任务分发（带追踪）
        6. 输出 Guardrails 检查
        7. 完成 Trace

        Args:
            override_intent: [P2-003] V9 的 SemanticIntentClassifierV3 分类结果。
                当提供时，跳过自身的 _classifier.classify()，直接使用覆盖值。

        Returns:
            包含 reply、trace_id、trace_summary、guardrail_results 的结果字典
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"
        trace = self._tracer.start_trace(trace_id, metadata={"user_input": user_input})

        overall_result: dict[str, Any] = {
            "reply": "",
            "trace_id": trace_id,
            "status": "unknown",
        }

        try:
            # 1. 输入护栏
            if enable_guardrails:
                with self._tracer.span("input_guardrails", SpanKind.GUARDRAIL, trace_id) as guardrail_span:
                    passed, sanitized_input, input_results = await self._guardrails.check_input(user_input)
                    guardrail_span.set_attribute("passed", passed)
                    guardrail_span.set_attribute("results_count", len(input_results))
                    if not passed:
                        overall_result["reply"] = "请求被安全策略拦截，请调整输入内容后重试。"
                        overall_result["status"] = "blocked"
                        overall_result["guardrail_results"] = [r.__dict__ for r in input_results]
                        self._tracer.finish_trace(trace_id)
                        return overall_result
                    user_input = sanitized_input or user_input

            # 2. 语义意图分类
            # [P2-003] 如果 V9 下发了 override_intent，跳过自身的分类器
            if override_intent:
                classify_result = ClassifyResult(
                    intent=override_intent.get("intent", "fallback"),
                    confidence=override_intent.get("confidence", 0.0),
                    target_agent=override_intent.get("intent", "master_scheduler"),
                )
            else:
                classify_result = self._classifier.classify(user_input)
            with self._tracer.span("intent_classification", SpanKind.CUSTOM, trace_id) as cls_span:
                cls_span.set_attribute("target_agent", classify_result.target_agent)
                cls_span.set_attribute("intent", classify_result.intent)
                cls_span.set_attribute("confidence", classify_result.confidence)

            # 3. 路由决策
            if classify_result.confidence >= 0.7:
                result = await self._route_direct_v2(
                    user_input, classify_result, trace_id, trace
                )
            elif classify_result.confidence >= 0.4:
                result = self._route_confirm(classify_result, trace_id)
            else:
                result = self._route_fallback(classify_result, trace_id)

            overall_result.update(result)

            # 确保所有路径都携带 classify_result
            if "classify_result" not in overall_result:
                overall_result["classify_result"] = classify_result.model_dump()

            # 4. 输出护栏
            if enable_guardrails:
                reply = overall_result.get("reply", "")
                with self._tracer.span("output_guardrails", SpanKind.GUARDRAIL, trace_id) as og_span:
                    passed, sanitized_reply, output_results = await self._guardrails.check_output(reply)
                    og_span.set_attribute("passed", passed)
                    if not passed:
                        overall_result["reply"] = "回复被安全策略拦截，请联系管理员。"
                        overall_result["status"] = "output_blocked"
                    elif sanitized_reply:
                        overall_result["reply"] = sanitized_reply
                    overall_result["guardrail_results"] = overall_result.get("guardrail_results", []) + [
                        {"type": "output", **r.__dict__} for r in output_results
                    ]

        except Exception as exc:
            self._logger.error("process_error", trace_id=trace_id, error=str(exc))
            overall_result["reply"] = "系统处理异常，请稍后再试。"
            overall_result["status"] = "error"
            overall_result["error"] = str(exc)
        finally:
            trace = self._tracer.finish_trace(trace_id)
            if trace:
                overall_result["trace_summary"] = {
                    "duration_ms": trace.duration_ms,
                    "span_count": len(trace.spans),
                    "is_success": trace.is_success,
                }

        return overall_result

    # ── V2 路由方法 ───────────────────────────────────────

    async def _route_direct_v2(
        self,
        user_input: str,
        classify_result: Any,
        trace_id: str,
        trace: Any,
    ) -> dict[str, Any]:
        """直接路由（V2 增强版）"""
        target = classify_result.target_agent
        intent = classify_result.intent

        # 通过 AgentCard 确认能力
        card = self._card_registry.get(target)
        if card and not card.has_capability(intent):
            self._logger.warning(
                "capability_mismatch",
                agent_id=target,
                intent=intent,
                available=[c.id for c in card.capabilities],
            )

        task = AgentTask(
            trace_id=trace_id,
            source="user",
            target=target,
            intent=intent,
            payload={"user_input": user_input},
            priority=5,
        )

        with self._tracer.span(f"dispatch_{target}", SpanKind.AGENT, trace_id) as dispatch_span:
            dispatch_span.set_attribute("target", target)
            dispatch_span.set_attribute("intent", intent)

            agent_result = await self._dispatcher.dispatch(task)

            dispatch_span.set_attribute("status", agent_result.status)
            dispatch_span.set_attribute("latency_ms", agent_result.latency_ms)

        # 失败降级
        if agent_result.status in ("failure", "timeout"):
            fallback = await self._try_fallback_v2(user_input, trace_id, trace)
            return {
                "reply": fallback.output.get("reply", "") if fallback.output else "处理降级",
                "status": "degraded",
                "agent_results": [agent_result.model_dump(), fallback.model_dump()],
            }

        reply = self._assemble_reply(classify_result, agent_result)
        return {
            "reply": reply,
            "status": "success",
            "agent_results": [agent_result.model_dump()],
            "classify_result": classify_result.model_dump(),
        }

    def _route_confirm(self, classify_result: Any, trace_id: str) -> dict[str, Any]:
        return {
            "reply": f"我猜你想处理「{classify_result.intent}」相关的事情，需要我帮你处理吗？",
            "status": "confirm",
            "classify_result": classify_result.model_dump(),
        }

    def _route_fallback(self, classify_result: Any, trace_id: str) -> dict[str, Any]:
        return {
            "reply": "我不太理解，可以再说详细一些吗？",
            "trace_id": trace_id,
            "status": "fallback",
            "classify_result": classify_result.model_dump(),
        }

    async def _try_fallback_v2(self, user_input: str, trace_id: str, trace: Any) -> AgentResult:
        task = AgentTask(
            trace_id=trace_id,
            source="orchestrator_v2",
            target="master_scheduler",
            intent="general.fallback",
            payload={"user_input": user_input},
        )
        agent = self._registry.get("master_scheduler")
        if agent:
            return await agent.handle_task(task)
        return AgentResult(
            task_id=task.task_id,
            trace_id=trace_id,
            agent_id="master_scheduler",
            status="failure",
            error="master_scheduler not available",
        )

    def _assemble_reply(self, classify_result: Any, agent_result: AgentResult) -> str:
        if agent_result.status == "success" and agent_result.output:
            reply = agent_result.output.get("reply") or agent_result.output.get("answer") or agent_result.output.get("report")
            if reply:
                return str(reply)
            return f"处理完成（{classify_result.intent}）"
        return "处理完成。"

    # ── DAG 工作流编排 ─────────────────────────────────────

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        initial_state: WorkflowState | None = None,
    ) -> WorkflowResult:
        """执行 DAG 工作流

        将 WorkflowEngine 的能力暴露为统一 API。
        """
        initial_state = initial_state or WorkflowState()
        return await self._workflow_engine.execute(workflow, initial_state)

    def build_chain_workflow(
        self,
        name: str,
        agent_sequence: list[tuple[IAgentPlugin, str]],
    ) -> WorkflowDefinition:
        """快速构建串行 Agent 链

        Args:
            agent_sequence: [(agent, intent), ...]
        """
        nodes = [
            AgentNode(f"node_{i}", agent, intent)
            for i, (agent, intent) in enumerate(agent_sequence)
        ]
        return WorkflowPatterns.chain(name, nodes)

    def build_parallel_workflow(
        self,
        name: str,
        entry_agent: IAgentPlugin,
        entry_intent: str,
        parallel_agents: list[tuple[IAgentPlugin, str]],
        merge_agent: IAgentPlugin,
        merge_intent: str,
    ) -> WorkflowDefinition:
        """快速构建并行扇出-归并工作流"""
        entry = AgentNode("entry", entry_agent, entry_intent)
        parallel_nodes = [
            AgentNode(f"parallel_{i}", agent, intent)
            for i, (agent, intent) in enumerate(parallel_agents)
        ]
        merge = AgentNode("merge", merge_agent, merge_intent)
        return WorkflowPatterns.parallel_fan_out(name, entry, parallel_nodes, merge)

    # ── AgentCard 管理 ────────────────────────────────────

    def register_agent_card(self, agent: IAgentPlugin, description: str = "", tags: list[str] | None = None) -> None:
        """为 Agent 注册 AgentCard"""
        card = build_agent_card(
            agent_id=agent.agent_id,
            name=agent.agent_id,
            version=agent.version,
            capabilities=agent.capabilities,
            description=description,
            tags=tags or [],
        )
        self._card_registry.register(card)

    def discover_agents(self, keyword: str, top_k: int = 5) -> list[Any]:
        """语义发现 Agent"""
        return self._card_registry.semantic_search(keyword, top_k)

    # ── 追踪查询 ────────────────────────────────────────────

    def get_trace(self, trace_id: str) -> Any:
        """获取链路追踪详情"""
        return self._tracer.get_trace(trace_id)

    def list_traces(self) -> list[Any]:
        """列出所有追踪"""
        return self._tracer.list_traces()
