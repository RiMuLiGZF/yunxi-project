"""
云汐内核 V8 - Trace-to-Memory + Swarm 组队 + 失败复盘

评审报告 4 项独创性创新设计的工程实现：

1. Trace-to-Memory：执行链路自动提炼为分层记忆
2. Swarm Formation：基于经验图谱的动态组队
3. Failure Retrospective：失败回溯复盘与策略更新
4. 模型轮换管理器（7B 优化）
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════
# 1. Trace-to-Memory：执行链路沉淀为记忆
# ══════════════════════════════════════════════════════════


class MemoryTier(str, Enum):
    WORKING = "working"
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


@dataclass
class ExtractedMemory:
    """从 Trace 提炼的记忆条目"""

    content: str
    tier: MemoryTier = MemoryTier.LONG_TERM
    memory_type: str = "trace_extract"
    source: str = "trace_to_memory"
    importance: float = 0.6
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TraceToMemory:
    """Trace-to-Memory 转换器

    将 Tracer 中的 Span 事件自动提炼为记忆条目，
    写入对应记忆层级。
    """

    def __init__(self, importance_threshold: float = 0.5) -> None:
        self._importance_threshold = importance_threshold
        self._extracted_count: int = 0
        self._logger = logger.bind(service="trace_to_memory")

    def extract_from_trace(self, trace_dict: dict[str, Any]) -> list[ExtractedMemory]:
        """从 Trace 字典中提炼记忆"""
        memories: list[ExtractedMemory] = []

        spans = trace_dict.get("spans", [])
        if not spans:
            return memories

        # 1. 提取 Guardrails 拦截事件
        for span in spans:
            for event in span.get("events", []):
                if "guardrail" in event.get("name", "").lower():
                    importance = 0.8
                    memories.append(ExtractedMemory(
                        content=f"护栏拦截: {event.get('name', '')} - "
                                f"{event.get('attributes', {})}",
                        tier=MemoryTier.LONG_TERM,
                        memory_type="guardrail_event",
                        importance=importance,
                        tags=["guardrail", "security"],
                        metadata={"trace_id": trace_dict.get("trace_id", "")},
                    ))

        # 2. 提取 Agent 执行摘要
        agent_spans = [s for s in spans if s.get("kind") == "agent"]
        if agent_spans:
            agent_ids = [s.get("attributes", {}).get("agent_id", "") for s in agent_spans]
            durations = [s.get("duration_ms", 0) for s in agent_spans]
            summary = (
                f"Workflow执行: Agent {', '.join(agent_ids[:5])}, "
                f"耗时 {sum(durations):.0f}ms, "
                f"节点数 {len(spans)}"
            )
            memories.append(ExtractedMemory(
                content=summary,
                tier=MemoryTier.LONG_TERM,
                memory_type="execution_summary",
                importance=0.6,
                tags=["workflow", "execution"],
                metadata={"trace_id": trace_dict.get("trace_id", "")},
            ))

        # 3. 提取 Ensemble 投票分歧
        ensemble_spans = [s for s in spans if "ensemble" in s.get("name", "").lower()]
        if ensemble_spans:
            for es in ensemble_spans:
                dissent = es.get("attributes", {}).get("dissent_count", 0)
                if dissent > 0:
                    memories.append(ExtractedMemory(
                        content=f"集成投票分歧: {es.get('name', '')}, "
                                f"异议Agent数 {dissent}",
                        tier=MemoryTier.LONG_TERM,
                        memory_type="ensemble_dissent",
                        importance=0.7,
                        tags=["ensemble", "decision"],
                    ))

        self._extracted_count += len(memories)
        return memories

    def stats(self) -> dict[str, Any]:
        return {
            "total_extracted": self._extracted_count,
            "importance_threshold": self._importance_threshold,
        }


# ══════════════════════════════════════════════════════════
# 2. Swarm Formation：动态组队
# ══════════════════════════════════════════════════════════


@dataclass
class SwarmRecord:
    """组队历史记录"""

    task_type: str
    agent_ids: list[str] = field(default_factory=list)
    success: bool = True
    avg_latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""


@dataclass
class Swarm:
    """动态协作集群"""

    swarm_id: str = ""
    task_type: str = ""
    agents: list[str] = field(default_factory=list)
    coordinator: str = ""
    created_at: float = field(default_factory=time.time)
    status: str = "active"  # active / completed / dissolved


class SwarmManager:
    """Swarm 动态组队管理器

    根据任务类型和历史执行数据，动态组建协作集群。
    """

    def __init__(self, history_capacity: int = 500) -> None:
        self._history: dict[str, list[SwarmRecord]] = defaultdict(list)
        self._active_swarms: dict[str, Swarm] = {}
        self._history_capacity = history_capacity
        self._logger = logger.bind(service="swarm_manager")

    def recommend_team(
        self,
        task_type: str,
        available_agents: list[str],
        team_size: int = 3,
    ) -> list[str]:
        """基于历史数据推荐最佳组队"""
        records = self._history.get(task_type, [])
        if not records:
            # 无历史数据，随机选择
            return available_agents[:team_size]

        # 统计成功组合
        combo_scores: dict[tuple[str, ...], float] = {}
        combo_latency: dict[tuple[str, ...], float] = {}

        for rec in records:
            key = tuple(sorted(rec.agent_ids))
            if rec.success:
                combo_scores[key] = combo_scores.get(key, 0) + 1
                combo_latency[key] = combo_latency.get(key, 0) + rec.avg_latency_ms

        if not combo_scores:
            return available_agents[:team_size]

        # 按成功率排序，平均延迟作为 tiebreaker
        ranked = sorted(
            combo_scores.items(),
            key=lambda x: (-x[1], combo_latency.get(x[0], 0)),
        )

        best_combo = ranked[0][0]
        # 返回在可用列表中的 Agent
        selected = [a for a in best_combo if a in available_agents]
        if not selected:
            selected = available_agents[:team_size]
        return selected[:team_size]

    def create_swarm(
        self,
        task_type: str,
        agent_ids: list[str],
    ) -> Swarm:
        """创建 Swarm"""
        swarm = Swarm(
            swarm_id=f"swarm_{int(time.time()*1000)}",
            task_type=task_type,
            agents=list(agent_ids),
            coordinator=agent_ids[0] if agent_ids else "",
        )
        self._active_swarms[swarm.swarm_id] = swarm
        self._logger.info("swarm_created", swarm_id=swarm.swarm_id, agents=agent_ids)
        return swarm

    def record_result(
        self,
        swarm_id: str,
        success: bool,
        avg_latency_ms: float,
        trace_id: str = "",
    ) -> None:
        """记录 Swarm 执行结果"""
        swarm = self._active_swarms.get(swarm_id)
        if not swarm:
            return

        record = SwarmRecord(
            task_type=swarm.task_type,
            agent_ids=list(swarm.agents),
            success=success,
            avg_latency_ms=avg_latency_ms,
            trace_id=trace_id,
        )

        history = self._history[swarm.task_type]
        history.append(record)
        # 限制容量
        while len(history) > self._history_capacity:
            history.pop(0)

        swarm.status = "completed"
        self._logger.info(
            "swarm_completed",
            swarm_id=swarm_id,
            success=success,
            latency_ms=avg_latency_ms,
        )

    def dissolve_swarm(self, swarm_id: str) -> None:
        """解散 Swarm"""
        swarm = self._active_swarms.pop(swarm_id, None)
        if swarm:
            swarm.status = "dissolved"
            self._logger.info("swarm_dissolved", swarm_id=swarm_id)

    def stats(self) -> dict[str, Any]:
        task_stats = {}
        for tt, records in self._history.items():
            success_count = sum(1 for r in records if r.success)
            task_stats[tt] = {
                "total_attempts": len(records),
                "success_rate": round(success_count / max(len(records), 1), 3),
                "avg_latency_ms": round(
                    sum(r.avg_latency_ms for r in records) / max(len(records), 1), 1
                ),
            }
        return {
            "active_swarms": len(self._active_swarms),
            "task_types_tracked": len(self._history),
            "task_stats": task_stats,
        }


# ══════════════════════════════════════════════════════════
# 3. Failure Retrospective：失败复盘
# ══════════════════════════════════════════════════════════


class FailureType(str, Enum):
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    AGENT_UNAVAILABLE = "agent_unavailable"
    UNKNOWN = "unknown"


@dataclass
class RetrospectiveReport:
    """失败复盘报告"""

    task_id: str = ""
    failure_type: FailureType = FailureType.UNKNOWN
    root_cause: str = ""
    failed_agent: str = ""
    failed_node: str = ""
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    similar_failures: int = 0  # 历史相似失败数
    recommendation: str = ""
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""


class RetrospectiveEngine:
    """失败复盘引擎

    任务失败后自动分析根因，查询历史相似案例，
    生成改进建议并沉淀为记忆。
    """

    def __init__(self, history_capacity: int = 200) -> None:
        self._failure_history: list[RetrospectiveReport] = []
        self._history_capacity = history_capacity
        self._logger = logger.bind(service="retrospective_engine")

    def analyze(
        self,
        task_id: str,
        error: str,
        failed_agent: str = "",
        failed_node: str = "",
        state_snapshot: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> RetrospectiveReport:
        """分析失败原因"""
        # 分类失败类型
        failure_type = self._classify_failure(error)

        # 查询历史相似失败
        similar = self._find_similar(failure_type, failed_agent)

        # 生成建议
        recommendation = self._generate_recommendation(
            failure_type, failed_agent, similar
        )

        report = RetrospectiveReport(
            task_id=task_id,
            failure_type=failure_type,
            root_cause=error[:200],
            failed_agent=failed_agent,
            failed_node=failed_node,
            state_snapshot=state_snapshot or {},
            similar_failures=len(similar),
            recommendation=recommendation,
            trace_id=trace_id,
        )

        self._failure_history.append(report)
        while len(self._failure_history) > self._history_capacity:
            self._failure_history.pop(0)

        self._logger.info(
            "retrospective_completed",
            task_id=task_id,
            failure_type=failure_type.value,
            similar_count=len(similar),
        )
        return report

    def _classify_failure(self, error: str) -> FailureType:
        error_lower = error.lower()
        if "timeout" in error_lower:
            return FailureType.TIMEOUT
        elif "guardrail" in error_lower or "blocked" in error_lower:
            return FailureType.GUARDRAIL_BLOCKED
        elif "budget" in error_lower or "exceeded" in error_lower:
            return FailureType.BUDGET_EXCEEDED
        elif "not found" in error_lower or "unavailable" in error_lower:
            return FailureType.AGENT_UNAVAILABLE
        elif "error" in error_lower or "exception" in error_lower:
            return FailureType.EXCEPTION
        return FailureType.UNKNOWN

    def _find_similar(
        self, failure_type: FailureType, agent: str
    ) -> list[RetrospectiveReport]:
        return [
            r for r in self._failure_history
            if r.failure_type == failure_type and r.failed_agent == agent
        ]

    def _generate_recommendation(
        self,
        failure_type: FailureType,
        agent: str,
        similar: list[RetrospectiveReport],
    ) -> str:
        recommendations = {
            FailureType.TIMEOUT: f"建议：增加Agent '{agent}'的TTL或使用更快的模型。"
                                f"历史同类失败 {len(similar)} 次。",
            FailureType.GUARDRAIL_BLOCKED: "建议：检查输入内容是否包含敏感信息，"
                                          "考虑调整Guardrails规则阈值。",
            FailureType.BUDGET_EXCEEDED: "建议：降低模型级别或增加预算额度。",
            FailureType.AGENT_UNAVAILABLE: f"建议：检查Agent '{agent}'是否已注册且健康。",
            FailureType.EXCEPTION: f"建议：检查Agent '{agent}'的异常处理逻辑。"
                                   f"历史同类失败 {len(similar)} 次。",
            FailureType.UNKNOWN: "建议：收集更多日志信息进行根因分析。",
        }
        return recommendations.get(failure_type, "")

    def get_failure_patterns(
        self, task_type: str = ""
    ) -> list[dict[str, Any]]:
        """获取失败模式统计"""
        patterns: dict[str, int] = defaultdict(int)
        for r in self._failure_history:
            patterns[r.failure_type.value] += 1
        return [{"type": k, "count": v} for k, v in sorted(patterns.items(), key=lambda x: -x[1])]

    def stats(self) -> dict[str, Any]:
        return {
            "total_failures_analyzed": len(self._failure_history),
            "failure_patterns": self.get_failure_patterns(),
        }


# ══════════════════════════════════════════════════════════
# 4. ModelRotationManager（7B 显存优化）
# ══════════════════════════════════════════════════════════


@dataclass
class ModelInfo:
    """模型信息"""

    name: str
    size_mb: int = 5000  # VRAM 占用
    capabilities: list[str] = field(default_factory=list)


class ModelRotationManager:
    """模型轮换管理器

    [V10.0-R03] 本类保留在M1作为"本地/云端路由决策"组件，
    负责模型选择和显存管理决策。实际的模型加载/推理执行
    应通过 InferenceInterface 委托给模块3。

    同一时刻仅保留一个模型在显存中，
    需要切换时先卸载当前模型再加载新模型。
    """

    def __init__(self, max_vram_mb: int = 5120) -> None:
        self.max_vram = max_vram_mb
        self._active_model: str | None = None
        self._active_models: dict[str, int] = {}  # [V9.8] 多模型并发计数
        self._loaded_models: dict[str, ModelInfo] = {}
        self._load_order: list[str] = []  # 最近使用的模型（MRU）
        self._logger = logger.bind(service="model_rotation")
        # [V9.8] 模型降级链：首选 → 次选 → 保底
        self._fallback_chain: dict[str, list[str]] = {
            "gpt-4o": ["gpt-4o-mini", "mock-model"],
            "claude-3-sonnet": ["gpt-4o", "gpt-4o-mini", "mock-model"],
            "gpt-4o-mini": ["mock-model"],
        }
        self._degradation_log: list[dict[str, Any]] = []

    def register_model(self, info: ModelInfo) -> None:
        """注册模型信息"""
        self._loaded_models[info.name] = info
        self._logger.info("model_registered", name=info.name, size_mb=info.size_mb)

    async def acquire(self, model_name: str) -> str | None:
        """[V9.8] 获取模型使用权，支持降级链

        Returns:
            实际分配的模型名称，或 None（全部不可用）
        """
        candidates = [model_name] + self._fallback_chain.get(model_name, [])

        for candidate in candidates:
            # 检查显存（RotationManager 为切换模式：先释放当前再分配）
            vram = self._get_model_vram(candidate)
            if vram is None:
                continue
            # 切换模式：先释放当前活跃模型，再检查目标模型是否适配
            if self._active_model and self._active_model != candidate:
                self.release(self._active_model)
            if vram <= self.max_vram:
                self._active_models[candidate] = self._active_models.get(candidate, 0) + 1
                self._active_model = candidate
                if candidate not in self._load_order:
                    self._load_order.append(candidate)
                if candidate != model_name:
                    self._degradation_log.append({
                        "timestamp": time.time(),
                        "requested": model_name,
                        "allocated": candidate,
                        "reason": "oom_fallback",
                    })
                    self._logger.warning(
                        "model_degraded",
                        requested=model_name,
                        allocated=candidate,
                        available_vram=self.max_vram,
                    )
                return candidate

        self._logger.error(
            "all_models_unavailable",
            requested=model_name,
            candidates=candidates,
        )
        return None

    def release(self, model_name: str) -> None:
        """释放模型"""
        count = self._active_models.get(model_name, 0)
        if count > 0:
            self._active_models[model_name] = count - 1
            if self._active_models[model_name] == 0:
                del self._active_models[model_name]
            self._logger.info("model_released", name=model_name)
        if self._active_model == model_name:
            self._active_model = None

    def get_active(self) -> str | None:
        for name in reversed(self._load_order):
            if name in self._active_models:
                return name
        return self._active_model

    def _get_model_vram(self, model_name: str) -> int | None:
        # [V9.8] 同时检查已加载和已注册的模型
        info = self._loaded_models.get(model_name) or self._registered_models.get(model_name)
        if info is None:
            return None
        return info.size_mb

    def get_available_vram(self) -> int:
        used = 0
        for name, count in self._active_models.items():
            info = self._loaded_models.get(name)
            if info:
                used += info.size_mb * count
        return self.max_vram - used

    def select_model_for_context(self, capabilities_needed: list[str]) -> str | None:
        """根据所需能力选择最佳模型"""
        for name in reversed(self._load_order):  # MRU 优先
            info = self._loaded_models.get(name)
            if info and all(c in info.capabilities for c in capabilities_needed):
                return name
        return None

    def stats(self) -> dict[str, Any]:
        return {
            "active_model": self._active_model,
            "registered_models": list(self._loaded_models.keys()),
            "max_vram_mb": self.max_vram,
            "mru_order": self._load_order[-5:],  # 最近 5 个
        }
