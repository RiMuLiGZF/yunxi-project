"""
云汐内核 V8 - 消息防循环 + 负载感知注册中心

解决评审报告 P1 问题：
1. 消息跳数计数器（hop count）+ 路径记录（breadcrumb）防循环
2. AgentRegistry 增加运行时负载指标（并发数/延迟/错误率）
3. 负载均衡策略（round_robin / least_conn / weighted）

同时实现：
- LazyAgentRegistry：Agent 按需热加载，空闲自动卸载（7B 优化）
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from interfaces import IAgentPlugin, BusMessage

logger = structlog.get_logger(__name__)


# ── 消息防循环 ──────────────────────────────────────────────


class LoopGuard:
    """消息防循环守护

    为每条消息维护跳数计数器和路径记录，
    超过阈值或检测到环路时自动终止传播。
    """

    def __init__(
        self,
        max_hops: int = 10,
        enable_breadcrumb: bool = True,
    ) -> None:
        self.max_hops = max_hops
        self.enable_breadcrumb = enable_breadcrumb
        self._loop_count: int = 0
        self._logger = logger.bind(service="loop_guard")

    def check(self, message: BusMessage) -> tuple[bool, str]:
        """检查消息是否可以继续传播

        Args:
            message: BusMessage（metadata 存储在 message.metadata 字段中）
            如果 message 没有 metadata 字段，则通过 payload 中的 _meta 子键读取。
        """
        meta = self._get_metadata(message)

        # 1. 跳数检查
        hop_count = meta.get("hop_count", 0)
        if hop_count >= self.max_hops:
            self._loop_count += 1
            return False, f"hop_limit_exceeded ({hop_count}/{self.max_hops})"

        # 2. 路径检查
        if self.enable_breadcrumb:
            breadcrumb: list[str] = meta.get("breadcrumb", [])
            if message.sender in breadcrumb:
                self._loop_count += 1
                return False, f"loop_detected (sender={message.sender} in path)"

        return True, "ok"

    def prepare_transit(self, message: BusMessage) -> BusMessage:
        """消息转发前准备：递增跳数、记录路径"""
        msg_dict = message.model_copy(deep=True)
        meta = dict(msg_dict.payload.get("_meta", {}))
        meta["hop_count"] = meta.get("hop_count", 0) + 1
        if self.enable_breadcrumb:
            breadcrumb = list(meta.get("breadcrumb", []))
            breadcrumb.append(message.sender)
            meta["breadcrumb"] = breadcrumb
        msg_dict.payload["_meta"] = meta
        return msg_dict

    @staticmethod
    def _get_metadata(message: BusMessage) -> dict[str, Any]:
        """从 BusMessage 中提取 metadata"""
        if hasattr(message, "metadata") and message.metadata:
            return message.metadata
        return message.payload.get("_meta", {})

    def stats(self) -> dict[str, Any]:
        return {
            "total_loops_blocked": self._loop_count,
            "max_hops": self.max_hops,
            "breadcrumb_enabled": self.enable_breadcrumb,
        }


# ── 负载指标 ──────────────────────────────────────────────


@dataclass
class LoadMetrics:
    """Agent 运行时负载指标"""

    agent_id: str = ""
    inflight_tasks: int = 0
    total_tasks: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    last_response_ms: float = 0.0
    last_active_time: float = field(default_factory=time.time)

    @property
    def error_rate(self) -> float:
        return self.failure_count / max(self.total_tasks, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.total_tasks, 1)

    @property
    def load_score(self) -> float:
        """综合负载评分（越低越好）"""
        # inflight 权重最高
        return (
            self.inflight_tasks * 10.0
            + self.error_rate * 5.0
            + self.avg_latency_ms * 0.001
        )


class LoadBalancer:
    """负载均衡器"""

    def __init__(self, strategy: str = "least_conn") -> None:
        self.strategy = strategy
        self._rr_index: dict[str, int] = defaultdict(int)  # agent_type -> index
        self._logger = logger.bind(service="load_balancer")

    def select(
        self,
        candidates: dict[str, LoadMetrics],
        agent_type: str = "",
    ) -> str | None:
        """从候选 Agent 中选择负载最低的一个

        Args:
            candidates: agent_id -> LoadMetrics
            agent_type: Agent 类型（用于 round_robin 分组）
        """
        if not candidates:
            return None

        if self.strategy == "round_robin":
            return self._select_round_robin(candidates, agent_type)
        elif self.strategy == "least_conn":
            return self._select_least_conn(candidates)
        elif self.strategy == "weighted":
            return self._select_weighted(candidates)
        else:
            return self._select_least_conn(candidates)

    def _select_round_robin(
        self, candidates: dict[str, LoadMetrics], agent_type: str
    ) -> str:
        ids = list(candidates.keys())
        idx = self._rr_index[agent_type] % len(ids)
        self._rr_index[agent_type] += 1
        return ids[idx]

    def _select_least_conn(
        self, candidates: dict[str, LoadMetrics]
    ) -> str:
        return min(candidates, key=lambda a: candidates[a].inflight_tasks)

    def _select_weighted(
        self, candidates: dict[str, LoadMetrics]
    ) -> str:
        return min(candidates, key=lambda a: candidates[a].load_score)


# ── 增强注册中心 ──────────────────────────────────────────


class EnhancedRegistry:
    """增强 Agent 注册中心

    在原 AgentRegistry 基础上增加：
    - 负载指标收集
    - 负载均衡路由
    - Agent 类型分组
    """

    def __init__(self, load_balancer: LoadBalancer | None = None) -> None:
        self._agents: dict[str, IAgentPlugin] = {}
        # [V9.6] 能力反向索引：capability -> set(agent_id)，O(1) 查询
        self._capability_index: dict[str, set[str]] = defaultdict(set)
        self._metrics: dict[str, LoadMetrics] = {}
        self._agent_types: dict[str, list[str]] = defaultdict(list)  # type -> [agent_id]
        self._lock: asyncio.Lock = asyncio.Lock()
        self._load_balancer = load_balancer or LoadBalancer()
        self._logger = logger.bind(service="enhanced_registry")

    async def register(self, agent: IAgentPlugin, agent_type: str = "general") -> None:
        """注册 Agent"""
        async with self._lock:
            self._agents[agent.agent_id] = agent
            # [V9.6] 更新能力反向索引
            if hasattr(agent, "capabilities") and agent.capabilities:
                for cap in agent.capabilities:
                    self._capability_index.setdefault(cap, set()).add(agent.agent_id)
            self._metrics[agent.agent_id] = LoadMetrics(agent_id=agent.agent_id)
            self._agent_types[agent_type].append(agent.agent_id)
        self._logger.info("agent_registered", agent_id=agent.agent_id, type=agent_type)

    async def unregister(self, agent_id: str) -> None:
        """注销 Agent"""
        async with self._lock:
            agent = self._agents.pop(agent_id, None)
            # [V9.6] 清理能力反向索引
            if agent and hasattr(agent, "capabilities") and agent.capabilities:
                for cap in agent.capabilities:
                    cap_set = self._capability_index.get(cap)
                    if cap_set:
                        cap_set.discard(agent_id)
                        if not cap_set:
                            del self._capability_index[cap]
            self._metrics.pop(agent_id, None)
        # 从类型分组中移除
        for atype in self._agent_types:
            if agent_id in self._agent_types[atype]:
                self._agent_types[atype].remove(agent_id)
        self._logger.info("agent_unregistered", agent_id=agent_id)

    def get(self, agent_id: str) -> IAgentPlugin | None:
        return self._agents.get(agent_id)

    def select_by_load(self, agent_type: str = "general") -> IAgentPlugin | None:
        """根据负载选择 Agent"""
        candidate_ids = self._agent_types.get(agent_type, [])
        if not candidate_ids:
            return None

        metrics = {
            aid: self._metrics[aid]
            for aid in candidate_ids
            if aid in self._metrics
        }
        selected_id = self._load_balancer.select(metrics, agent_type)
        if selected_id:
            return self._agents.get(selected_id)
        return None

    def record_task_start(self, agent_id: str) -> None:
        """记录任务开始"""
        m = self._metrics.get(agent_id)
        if m:
            m.inflight_tasks += 1
            m.last_active_time = time.time()

    def record_task_end(
        self,
        agent_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录任务结束"""
        m = self._metrics.get(agent_id)
        if m:
            m.inflight_tasks = max(0, m.inflight_tasks - 1)
            m.total_tasks += 1
            m.total_latency_ms += latency_ms
            m.last_response_ms = latency_ms
            if success:
                m.success_count += 1
            else:
                m.failure_count += 1
            m.last_active_time = time.time()

    def get_metrics(self, agent_id: str) -> LoadMetrics | None:
        return self._metrics.get(agent_id)

    def list_all(self) -> list[IAgentPlugin]:
        return list(self._agents.values())

    def list_ids(self) -> list[str]:
        return list(self._agents.keys())

    def find_by_capability(self, capability: str) -> list[IAgentPlugin]:
        """[V9.6] 按能力查找 Agent（O(1) 索引查询）"""
        agent_ids = self._capability_index.get(capability, set())
        return [self._agents[aid] for aid in agent_ids if aid in self._agents]

    def stats(self) -> dict[str, Any]:
        return {
            "total_agents": len(self._agents),
            "agent_types": {
                t: len(ids) for t, ids in self._agent_types.items()
            },
            "load_balancer_strategy": self._load_balancer.strategy,
            "agents_detail": {
                aid: {
                    "inflight": m.inflight_tasks,
                    "total": m.total_tasks,
                    "error_rate": round(m.error_rate, 3),
                    "avg_latency_ms": round(m.avg_latency_ms, 1),
                }
                for aid, m in self._metrics.items()
            },
        }


# ── Lazy 懒加载注册中心（7B 优化）─────────────────────────


class LazyAgentRegistry:
    """Agent 懒加载注册中心

    Agent 不在启动时全部加载，仅在首次收到任务时创建实例。
    空闲超过 TTL 后自动卸载释放内存。
    """

    def __init__(
        self,
        idle_ttl: float = 300.0,
        min_instances: int = 0,
        max_instances: int = 3,
    ) -> None:
        self._idle_ttl = idle_ttl
        self._min_instances = min_instances
        self._max_instances = max_instances
        self._active: dict[str, IAgentPlugin] = {}  # agent_id -> instance
        self._factory: dict[str, Any] = {}  # agent_id -> factory/callable
        self._last_access: dict[str, float] = {}
        self._logger = logger.bind(service="lazy_registry")

    def register_factory(self, agent_id: str, factory: Any) -> None:
        """注册 Agent 工厂（不立即创建实例）"""
        self._factory[agent_id] = factory
        self._logger.info("factory_registered", agent_id=agent_id)

    async def get(self, agent_id: str) -> IAgentPlugin | None:
        """获取 Agent 实例（懒加载）"""
        if agent_id in self._active:
            self._last_access[agent_id] = time.time()
            return self._active[agent_id]

        factory = self._factory.get(agent_id)
        if factory is None:
            return None

        # 懒加载创建实例
        try:
            if callable(factory):
                instance = factory() if not asyncio.iscoroutinefunction(factory) else await factory()
            else:
                instance = factory
            self._active[agent_id] = instance
            self._last_access[agent_id] = time.time()
            self._logger.info("agent_lazy_loaded", agent_id=agent_id)
            return instance
        except Exception as exc:
            self._logger.error("agent_lazy_load_failed", agent_id=agent_id, error=str(exc))
            return None

    def evict_idle(self) -> int:
        """清理空闲 Agent，返回清理数量"""
        now = time.time()
        evicted = 0
        for agent_id in list(self._active.keys()):
            if len(self._active) <= self._min_instances:
                break
            if now - self._last_access.get(agent_id, 0) > self._idle_ttl:
                del self._active[agent_id]
                self._last_access.pop(agent_id, None)
                evicted += 1
                self._logger.info("agent_evicted_idle", agent_id=agent_id)
        return evicted

    def stats(self) -> dict[str, Any]:
        return {
            "active_instances": len(self._active),
            "registered_factories": len(self._factory),
            "idle_ttl": self._idle_ttl,
            "max_instances": self._max_instances,
        }
