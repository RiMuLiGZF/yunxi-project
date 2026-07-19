# =============================================================================
# DEPRECATED - 已废弃版本（归档于 _deprecated/）
# =============================================================================
# 本文件已从 src/orchestration/orchestrator_v3.py 归档至此处。
# 废弃原因：V3 编排器已被 V8/V9 扁平化设计替代，仅作为内部依赖链保留。
# 保留版本：V8（稳定）、V9（最新生产版）
# 归档日期：2026-07-19
# 注意：此文件仅供 v8/v9 内部依赖链使用，新代码请勿直接导入。
# =============================================================================

"""
云汐内核 V3 - 整合编排器（已归档）

在 V2 基础上集成 V3 核心能力：
- 分层记忆系统（MemoryManager）
- 反思与评估引擎（ReflectionEngine）
- 自适应路由优化器（AdaptiveRouter）
- 反馈收集与自优化（FeedbackLoop + SelfOptimizer）
- 性能指标收集（MetricsCollector）

提供具备自我进化能力的 Agent 集群调度中枢。

[DEPRECATED] 本版本已归档，仅作为 V8/V9 内部依赖链保留。
新代码请使用 OrchestratorV9（生产版）或 OrchestratorV8（稳定版）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from src.tools.interfaces import AgentTask, AgentResult, IAgentPlugin
from src.agents.agent_registry import AgentRegistry
from src.core.intent_classifier_v2 import SemanticIntentClassifier
from src.core.task_dispatcher import TaskDispatcher
from src.orchestration._deprecated.orchestrator_v2 import OrchestratorV2
from src.memory.memory_system import MemoryManager
from src.core.reflection_engine import ReflectionEngine, MultiAgentPeerReview
from src.core.adaptive_router import AdaptiveRouter
from src.core.feedback_loop import FeedbackCollector, SelfOptimizer
from src.observability.metrics_collector import MetricsCollector

logger = structlog.get_logger(__name__)


class OrchestratorV3:
    """V3 整合编排器（已归档）

    在 V2 基础上增加：
    1. 每次请求自动注入分层记忆上下文
    2. 每次 Agent 执行后自动触发反思
    3. 路由结果自动上报到自适应路由器
    4. 指标自动收集
    5. 反馈闭环

    [DEPRECATED] 已归档至 _deprecated/，仅供 V8/V9 内部依赖链使用。
    """

    def __init__(
        self,
        orchestrator_v2: OrchestratorV2,
        memory: MemoryManager | None = None,
        reflection: ReflectionEngine | None = None,
        adaptive_router: AdaptiveRouter | None = None,
        feedback: FeedbackCollector | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._v2 = orchestrator_v2
        self._memory = memory or MemoryManager()
        self._reflection = reflection or ReflectionEngine()
        self._router = adaptive_router or AdaptiveRouter()
        self._feedback = feedback or FeedbackCollector()
        self._optimizer = SelfOptimizer(self._feedback)
        self._metrics = metrics or MetricsCollector()
        self._peer_review = MultiAgentPeerReview(self._reflection)
        self._logger = logger.bind(service="orchestrator_v3")

    # ── 核心入口 ──────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        enable_guardrails: bool = True,
        enable_tracing: bool = True,
        enable_memory: bool = True,
        enable_reflection: bool = True,
        override_intent: dict | None = None,
    ) -> dict[str, Any]:
        """处理用户请求（V3 增强版）

        流程：
        1. 注入记忆上下文
        2. V2 处理流程（护栏→分类→分发→输出）
        3. 记录指标
        4. 反思与评估
        5. 记忆巩固
        6. 反馈准备

        Args:
            override_intent: [P2-003] V9/V8/V7/V5/V4 下发的 V3 意图覆盖，透传至 V2。
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"
        start_time = time.time()

        # 1. 写入短期记忆
        self._memory.add_short_term(
            trace_id=trace_id,
            content=user_input,
            source="user",
            memory_type="input",
            tags=["user_input"],
        )

        # 2. 获取记忆上下文并注入
        if enable_memory:
            memory_context = self._memory.get_context(
                trace_id=trace_id,
                query=user_input,
            )
            # 将长期记忆中相关内容注入到 user_input 增强上下文
            ltm_items = memory_context.get("long_term_relevant", [])
            if ltm_items:
                memory_hint = " ".join(
                    entry.content for entry in ltm_items[:3]
                )
                user_input = f"[记忆参考: {memory_hint}]\n{user_input}"

        # 3. V2 处理
        result = await self._v2.process(
            user_input=user_input,
            trace_id=trace_id,
            enable_guardrails=enable_guardrails,
            enable_tracing=enable_tracing,
            override_intent=override_intent,
        )

        # 4. 记录 Agent 执行指标
        agent_results = result.get("agent_results", [])
        for ar in agent_results:
            if isinstance(ar, dict):
                self._metrics.record_result(
                    ar.get("agent_id", "unknown"),
                    ar.get("status", "unknown"),
                )
                self._metrics.record_latency(
                    ar.get("agent_id", "unknown"),
                    ar.get("latency_ms", 0),
                )

        # 记录意图分类指标
        classify_result = result.get("classify_result")
        if classify_result and isinstance(classify_result, dict):
            self._metrics.record_intent_classification(
                user_input,
                classify_result.get("intent", ""),
                classify_result.get("confidence", 0),
            )

        # 5. 自适应路由上报
        if classify_result and isinstance(classify_result, dict) and agent_results:
            intent = classify_result.get("intent", "")
            for ar in agent_results:
                if isinstance(ar, dict):
                    self._router.report_result(
                        intent=intent,
                        target_agent=ar.get("agent_id", ""),
                        success=ar.get("status") == "success",
                        latency_ms=ar.get("latency_ms", 0),
                        score=1.0 if ar.get("status") == "success" else 0.0,
                    )

        # 6. 反思与评估
        if enable_reflection and agent_results:
            for ar in agent_results:
                if isinstance(ar, dict) and ar.get("agent_id") != "master_scheduler":
                    await self._reflection.evaluate_and_reflect(
                        trace_id=trace_id,
                        agent_id=ar.get("agent_id", ""),
                        task_id=ar.get("task_id", ""),
                        agent_result=AgentResult(**ar),
                    )

        # 7. 记忆巩固
        if enable_memory:
            # 将 Agent 输出写入短期记忆
            reply = result.get("reply", "")
            if reply:
                self._memory.add_short_term(
                    trace_id=trace_id,
                    content=reply,
                    source=agent_results[0].get("agent_id", "system") if agent_results else "system",
                    memory_type="output",
                    tags=["agent_output"],
                )
            # 触发巩固
            self._memory.consolidate(trace_id)

        # 8. 收集隐式反馈
        session_duration = time.time() - start_time
        retry_count = 1 if result.get("status") == "degraded" else 0
        for ar in agent_results:
            if isinstance(ar, dict) and ar.get("agent_id"):
                self._feedback.collect_implicit(
                    trace_id=trace_id,
                    agent_id=ar.get("agent_id", ""),
                    intent=classify_result.get("intent", "") if classify_result else "",
                    session_duration_sec=session_duration,
                    retry_count=retry_count,
                    was_silent=not bool(reply),
                )

        # 9. 组装 V3 增强结果（诊断数据仅记录在内部日志，不暴露给用户）
        self._logger.debug(
            "v3_internal_stats",
            memory_stats=self._memory.stats(),
            route_stats=self._router.get_route_stats(),
            system_metrics=self._metrics.get_system_metrics(),
        )

        return result

    def _get_reflection_summary(self, agent_results: list[Any]) -> dict[str, Any]:
        """获取反思摘要"""
        summary: dict[str, Any] = {}
        for ar in agent_results:
            if isinstance(ar, dict):
                agent_id = ar.get("agent_id", "")
                if agent_id:
                    stats = self._reflection.get_reflection_stats(agent_id)
                    if stats["total"] > 0:
                        summary[agent_id] = stats
        return summary

    # ── 显式反馈接口 ──────────────────────────────────────

    def submit_feedback(
        self,
        trace_id: str,
        agent_id: str,
        intent: str,
        rating: int,
        comment: str = "",
    ) -> None:
        """用户提交显式反馈"""
        self._feedback.collect_explicit(
            trace_id=trace_id,
            agent_id=agent_id,
            intent=intent,
            rating=rating,
            comment=comment,
        )
        # 同时上报到自适应路由器
        self._router.report_result(
            intent=intent,
            target_agent=agent_id,
            success=rating > 0,
            score=rating,
        )

    # ── 分析与诊断 ────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """系统诊断

        返回：
        - 各 Agent 反思统计
        - 路由优化建议
        - 反馈分析
        - 系统指标
        """
        return {
            "reflections": {
                agent_id: self._reflection.get_reflection_stats(agent_id)
                for agent_id in self._reflection._agent_reflections
            },
            "route_recommendations": self._router.get_recommendations(),
            "feedback_analysis": {
                agent_id: self._optimizer.analyze_agent(agent_id)
                for agent_id in self._feedback._agent_feedbacks
            },
            "system_metrics": self._metrics.export_dashboard_data(),
            "memory_stats": self._memory.stats(),
        }

    # ── V2/V1 能力透传（白名单） ───────────────────────

    def __getattr__(self, name: str) -> Any:
        """仅透传 V2 的已知方法"""
        allowed = {"register_agent_card", "discover_agents", "get_trace", "list_traces",
                   "build_chain_workflow", "build_parallel_workflow", "execute_workflow"}
        if name in allowed:
            return getattr(self._v2, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
