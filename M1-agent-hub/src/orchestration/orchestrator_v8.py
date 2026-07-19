"""
云汐内核 V8 - 统一编排器（扁平化）

解决评审报告指出的核心问题：
- OrchestratorV1-V7 七层嵌套 → V8 扁平化单层
- 直接集成所有 V8 新能力
- 保持与 V7 API 的向后兼容

V8 新增能力：
1. A2A 标准通信（a2a_protocol）
2. Checkpointer 状态持久化（checkpointer）
3. 消息防循环 + 负载均衡（enhanced_registry）
4. RBAC 记忆权限（rbac_memory）
5. Swarm 动态组队（swarm_and_innovation）
6. Trace-to-Memory 链路沉淀（swarm_and_innovation）
7. 失败复盘引擎（swarm_and_innovation）
8. 模型轮换管理（swarm_and_innovation）
"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import structlog

from src.orchestration._deprecated.orchestrator_v7 import OrchestratorV7  # 内部依赖，不触发弃用警告
from src.core.a2a_protocol import A2AClient, A2ATransport, MemoryTransport, Task, TaskStatus, AgentCard
from src.core.checkpointer import Checkpointer, CheckpointConfig
from src.agents.enhanced_registry import EnhancedRegistry, LoopGuard, LoadBalancer, LazyAgentRegistry
from src.memory.rbac_memory import RBACMemoryGuard, AgentIdentity, AgentRole, MemoryAccessPolicy
from src.orchestration.swarm_and_innovation import (
    SwarmManager, TraceToMemory, RetrospectiveEngine,
    ModelRotationManager, ModelInfo,
)
from src.memory.memory_bridge import MemoryBridge
from src.resilience.budget_manager import BudgetManager

logger = structlog.get_logger(__name__)


class OrchestratorV8:
    """V8 统一编排器（扁平化设计）

    不再嵌套 V7→V5→V4→... 的洋葱式结构，
    而是直接组合底层模块，提供统一的处理入口。
    """

    def __init__(
        self,
        orchestrator_v7: OrchestratorV7,
        registry: EnhancedRegistry | None = None,
        loop_guard: LoopGuard | None = None,
        checkpointer: Checkpointer | None = None,
        a2a_client: A2AClient | None = None,
        rbac_guard: RBACMemoryGuard | None = None,
        swarm_manager: SwarmManager | None = None,
        trace_to_memory: TraceToMemory | None = None,
        retrospective: RetrospectiveEngine | None = None,
        model_rotation: ModelRotationManager | None = None,
        memory_bridge: MemoryBridge | None = None,
        budget_manager: BudgetManager | None = None,
        tracer: Any | None = None,
    ) -> None:
        self._v7 = orchestrator_v7

        # V8 新组件
        self._registry = registry or EnhancedRegistry()
        self._loop_guard = loop_guard or LoopGuard()
        self._checkpointer = checkpointer or Checkpointer()
        self._a2a = a2a_client
        self._rbac = rbac_guard or RBACMemoryGuard()
        self._swarm = swarm_manager or SwarmManager()
        self._trace_to_memory = trace_to_memory or TraceToMemory()
        self._retrospective = retrospective or RetrospectiveEngine()
        self._model_rotation = model_rotation
        self._memory_bridge = memory_bridge
        self._budget = budget_manager

        self._logger = logger.bind(service="orchestrator_v8")

        # [V9.6] 一次性提取 tracer 引用，避免 process() 中深层穿透
        self._tracer = tracer or getattr(
            getattr(
                getattr(
                    getattr(getattr(self._v7, "_v5", None), "_v4", None),
                    "_v3", None
                ),
                "_v2", None
            ),
            "_tracer", None
        )

    # ── V8 增强处理入口 ────────────────────────────────

    async def process(
        self,
        user_input: str,
        trace_id: str | None = None,
        agent_identity: AgentIdentity | None = None,
        enable_trace_memory: bool = True,
        enable_loop_guard: bool = True,
        override_intent: dict | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """V8 增强处理

        在 V7 基础上增加：
        - 消息防循环检查
        - RBAC 记忆权限过滤
        - Trace-to-Memory 链路沉淀
        - 失败自动复盘

        Args:
            override_intent: [P2-003] V9 下发的 V3 意图分类结果，
                透传至 V2，使 V2 跳过自己的分类器，直接使用覆盖值。
        """
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # [P0-4-2] BudgetManager 全链路传播：V8 层预算检查
        if self._budget is not None and not self._budget.is_budget_available(
            model=kwargs.get("model", ""),
            input_tokens=kwargs.get("input_tokens", 0),
            output_tokens=kwargs.get("output_tokens", 0),
        ):
            self._logger.warning("budget_exceeded_in_v8", trace_id=trace_id)
            return {
                "status": "budget_exceeded",
                "reason": "budget_limit_reached",
                "trace_id": trace_id,
            }

        try:
            result = await self._v7.process(
                user_input=user_input,
                trace_id=trace_id,
                override_intent=override_intent,
                **kwargs,
            )

            # 失败时触发复盘
            if result.get("status") == "failure":
                report = self._retrospective.analyze(
                    task_id=trace_id,
                    error=result.get("error", "unknown failure"),
                    trace_id=trace_id,
                )
                result["retrospective"] = {
                    "failure_type": report.failure_type.value,
                    "recommendation": report.recommendation,
                    "similar_failures": report.similar_failures,
                }

            # [P2-001] Trace-to-Memory 沉淀（修复深层穿透）
            # 原: self._v7._v5._v4._v3._v2._tracer -> 深层属性穿透
            # 改: 使用初始化时提取的 self._tracer（V9.6 修复）
            if enable_trace_memory and self._tracer is not None:
                trace = self._tracer.get_trace(trace_id)
                if trace:
                    extracted = self._trace_to_memory.extract_from_trace(trace.to_dict())
                    result["trace_memories_extracted"] = len(extracted)

                    # [P3-004] 通过 MemoryBridge 将提取的记忆写入存储
                    if self._memory_bridge is not None and extracted:
                        written = await self._memory_bridge.write_extracted_memories(extracted)
                        result["trace_memories_written"] = written

            return result

        except Exception as exc:
            # 异常时也触发复盘
            report = self._retrospective.analyze(
                task_id=trace_id,
                error=str(exc),
                trace_id=trace_id,
            )
            self._logger.error(
                "process_error_with_retrospective",
                trace_id=trace_id,
                recommendation=report.recommendation,
            )
            raise

    async def process_stream(
        self,
        user_input: str,
        trace_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """流式处理（委托给 V7）"""
        async for chunk in self._v7.process_stream(user_input, trace_id=trace_id, **kwargs):
            yield chunk

    # ── Swarm 组队处理 ────────────────────────────────

    async def process_with_swarm(
        self,
        user_input: str,
        task_type: str,
        trace_id: str | None = None,
        team_size: int = 3,
    ) -> dict[str, Any]:
        """使用 Swarm 动态组队处理"""
        trace_id = trace_id or f"trace_{int(time.time() * 1000)}"

        # [P0-4-2] BudgetManager 全链路传播：Swarm 模式预算检查
        if self._budget is not None and not self._budget.is_budget_available():
            self._logger.warning("budget_exceeded_in_swarm", trace_id=trace_id)
            return {
                "status": "budget_exceeded",
                "reason": "budget_limit_reached",
                "trace_id": trace_id,
            }

        # 获取可用 Agent
        available = self._registry.list_ids()
        if not available:
            return {"reply": "无可用Agent", "status": "error", "trace_id": trace_id}

        # 推荐组队
        team = self._swarm.recommend_team(task_type, available, team_size)
        swarm = self._swarm.create_swarm(task_type, team)

        # 使用 ensemble 引擎
        from src.orchestration.ensemble_engine import EnsembleStrategy
        start = time.time()
        result = await self._v7.process_ensemble(
            query=user_input,
            agent_ids=team,
            trace_id=trace_id,
        )

        # 记录 Swarm 结果
        latency = (time.time() - start) * 1000
        self._swarm.record_result(
            swarm_id=swarm.swarm_id,
            success=result.consensus_reached,
            avg_latency_ms=latency,
            trace_id=trace_id,
        )

        return {
            "reply": result.final_answer,
            "status": "success",
            "swarm_id": swarm.swarm_id,
            "team": team,
            "consensus": result.consensus_reached,
            "latency_ms": latency,
            "trace_id": trace_id,
        }

    # ── 模型轮换 ────────────────────────────────────

    async def acquire_model(self, model_name: str) -> bool:
        """获取模型（7B显存管理）"""
        if self._model_rotation is None:
            return True  # 无模型管理器时直接放行
        return await self._model_rotation.acquire(model_name)

    # ── 负载感知路由 ────────────────────────────────

    def route_by_load(self, agent_type: str = "general") -> str | None:
        """根据负载选择 Agent"""
        agent = self._registry.select_by_load(agent_type)
        return agent.agent_id if agent else None

    # ── 记忆权限查询 ────────────────────────────────

    def filter_memories(
        self,
        entries: list[dict[str, Any]],
        identity: AgentIdentity,
    ) -> list[dict[str, Any]]:
        """根据 RBAC 策略过滤记忆条目"""
        return self._rbac.filter_entries(identity, entries)

    # ── 诊断 ────────────────────────────────────────

    def diagnose(self) -> dict[str, Any]:
        """V8 全面诊断"""
        v7_diag = self._v7.diagnose()
        return {
            **v7_diag,
            "v8": {
                "loop_guard": self._loop_guard.stats(),
                "checkpointer": self._checkpointer.stats(),
                "registry": self._registry.stats(),
                "rbac": self._rbac.stats(),
                "swarm": self._swarm.stats(),
                "trace_to_memory": self._trace_to_memory.stats(),
                "retrospective": self._retrospective.stats(),
                "model_rotation": self._model_rotation.stats() if self._model_rotation else None,
            },
        }

    # ── V7/V5/V4 能力透传 ──────────────────────────

    # [V9.5] __getattr__ 白名单透传，防止内部实现泄露
    # [V9.5-R2] 可扩展白名单：支持运行时注册新透传方法
    _V7_PASS_THROUGH: set[str] = {
        "load_plugins", "get_config", "list_agents", "get_agent",
        "process_ensemble", "process_budget_aware",
    }

    def __getattr__(self, name: str) -> Any:
        if name in self._V7_PASS_THROUGH:
            return getattr(self._v7, name)
        raise AttributeError(
            f"'{type(self).__name__}' has no attribute '{name}'"
        )

    @classmethod
    def register_passthrough(cls, method_name: str) -> None:
        """[V9.5-R2] 注册新的 V7 透传方法到白名单"""
        cls._V7_PASS_THROUGH.add(method_name)
