"""
云汐内核 V10.0 — 注册发现与负载均衡子Agent (Discovery-Agent)

职责：
- Agent 注册与发现：注册/注销 Agent，按能力查找可用 Agent
- 负载评估与排序：通过 LoadEvaluator 计算综合负载评分
- 端云调度策略：通过 SchedulingPolicy 决定本地/云端执行
- 与 Bus-Agent 协作：发布 Agent 发现与注册事件到消息总线
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.tools.interfaces import AgentResult, AgentTask, BusMessage, IAgentPlugin
from shared_models import SchedulingDecision
from src.discovery.load_evaluator import LoadEvaluator
from src.discovery.scheduling_policy import SchedulingPolicy

logger = structlog.get_logger(__name__)

# ── Bus 事件主题 ──────────────────────────────────────────
_TOPIC_AGENT_REGISTERED = "discovery.agent_registered"
_TOPIC_AGENT_FOUND = "discovery.agent_found"
_TOPIC_LOAD_UPDATE = "discovery.load_update"
_TOPIC_SCHEDULING = "discovery.scheduling"


class DiscoveryAgent(IAgentPlugin):
    """注册发现与负载均衡子Agent

    作为 V10.0 架构中的子Agent之一，负责：
    1. Agent 注册中心：维护可用 Agent 的注册信息
    2. 能力发现：根据能力需求匹配可用 Agent
    3. 负载评估：综合多维指标评估 Agent 负载
    4. 调度策略：端云协同场景下的调度决策

    挂载到注册中心后，可通过 task.intent 路由到不同操作：
      - discovery.register    注册 Agent
      - discovery.unregister  注销 Agent
      - discovery.find        按能力查找 Agent
      - discovery.load_update 更新负载评分
      - discovery.find_best   查找最优 Agent
      - discovery.ranking    获取负载排名
      - discovery.schedule    调度决策
      - discovery.list        列出所有已注册 Agent
      - discovery.stats       统计信息
    """

    agent_id: str = "agent.discovery"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "discovery.register",
        "discovery.unregister",
        "discovery.find",
        "discovery.load_update",
        "discovery.find_best",
        "discovery.ranking",
        "discovery.schedule",
        "discovery.list",
        "discovery.stats",
    ]

    def __init__(
        self,
        load_evaluator: LoadEvaluator | None = None,
        scheduling_policy: SchedulingPolicy | None = None,
        bus_publish: Any | None = None,
    ) -> None:
        """
        Args:
            load_evaluator:    负载评估器，若为 None 则自动创建
            scheduling_policy: 调度策略引擎，若为 None 则自动创建
            bus_publish:       消息总线发布函数，签名为 (BusMessage) -> None
        """
        self._registry: dict[str, dict[str, Any]] = {}
        self._load_evaluator = load_evaluator or LoadEvaluator()
        self._scheduling_policy = scheduling_policy or SchedulingPolicy()
        self._bus_publish = bus_publish
        self._logger = logger.bind(agent_id=self.agent_id)

    # ── 消息总线事件发布 ──────────────────────────────────

    async def _publish_event(
        self,
        topic: str,
        payload: dict[str, Any],
        trace_id: str = "",
    ) -> None:
        """向消息总线发布事件"""
        msg = BusMessage(
            topic=topic,
            sender=self.agent_id,
            msg_type="system.config_change",
            payload=payload,
            trace_id=trace_id,
        )

        if self._bus_publish is not None:
            try:
                await self._bus_publish(msg)
            except Exception as exc:
                self._logger.warning(
                    "bus_publish_failed",
                    topic=topic,
                    error=str(exc),
                )
        else:
            self._logger.debug("bus_publish_skipped", topic=topic)

    # ── 公开 API ────────────────────────────────────────

    def register_agent(self, agent_info: dict[str, Any]) -> bool:
        """注册一个 Agent

        Args:
            agent_info: Agent 信息字典，必须包含 agent_id，可选包含：
                        - capabilities: list[str]
                        - role: str
                        - endpoint: str
                        - metadata: dict

        Returns:
            注册成功返回 True
        """
        agent_id: str = agent_info.get("agent_id", "")
        if not agent_id:
            self._logger.warning("register_missing_agent_id")
            return False

        if agent_id in self._registry:
            self._logger.warning("register_already_exists", agent_id=agent_id)
            return False

        self._registry[agent_id] = {
            "agent_id": agent_id,
            "capabilities": agent_info.get("capabilities", []),
            "role": agent_info.get("role", "executor"),
            "endpoint": agent_info.get("endpoint", ""),
            "metadata": agent_info.get("metadata", {}),
            "registered_at": time.time(),
            "status": "active",
        }

        self._logger.info(
            "agent_registered",
            agent_id=agent_id,
            capabilities=self._registry[agent_id]["capabilities"],
        )
        return True

    def find_agent(
        self,
        capabilities: list[str],
        load_preference: str = "lowest",
    ) -> str | None:
        """根据能力需求查找最优 Agent

        Args:
            capabilities:   需求的能力标签列表
            load_preference: 负载偏好，"lowest" 表示选择负载最轻的

        Returns:
            匹配的 agent_id，无匹配时返回 None
        """
        if not capabilities:
            self._logger.warning("find_agent_empty_capabilities")
            return None

        # 筛选具备所有所需能力的 Agent
        candidates = [
            aid
            for aid, info in self._registry.items()
            if info["status"] == "active"
            and all(cap in info["capabilities"] for cap in capabilities)
        ]

        if not candidates:
            self._logger.warning(
                "find_agent_no_match",
                required_capabilities=capabilities,
            )
            return None

        # 根据负载偏好选择
        if load_preference == "lowest":
            best = self._load_evaluator.get_top_agent(candidates)
            if best:
                return best

        # 无负载评分时返回第一个匹配
        self._logger.info(
            "find_agent_fallback",
            candidates=candidates,
            reason="no_load_scores",
        )
        return candidates[0]

    def get_load_ranking(self) -> list[tuple[str, float]]:
        """获取所有已注册 Agent 的负载排名

        Returns:
            按 composite 从低到高排序的 (agent_id, composite) 列表
        """
        all_ids = list(self._registry.keys())
        return self._load_evaluator.get_ranked(all_ids)

    # ── 核心任务处理 ──────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理注册/发现/负载均衡请求

        根据 task.intent 路由到对应的处理逻辑，
        并在需要时向消息总线发布事件。
        """
        start_time = time.time()
        intent = task.intent

        self._logger.info(
            "handling_discovery_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=intent,
        )

        try:
            handler = self._get_handler(intent)
            if handler is None:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"未知发现操作: {intent}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            output = await handler(task)
            latency_ms = (time.time() - start_time) * 1000

            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=output,
                latency_ms=latency_ms,
            )

        except ValueError as exc:
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.error(
                "discovery_task_error",
                trace_id=task.trace_id,
                intent=intent,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
                latency_ms=latency_ms,
            )

    # ── Handler 路由 ──────────────────────────────────

    def _get_handler(self, intent: str):
        """根据 intent 返回对应的处理方法"""
        handlers: dict[str, Any] = {
            "discovery.register": self._handle_register,
            "discovery.unregister": self._handle_unregister,
            "discovery.find": self._handle_find,
            "discovery.load_update": self._handle_load_update,
            "discovery.find_best": self._handle_find_best,
            "discovery.ranking": self._handle_ranking,
            "discovery.schedule": self._handle_schedule,
            "discovery.list": self._handle_list,
            "discovery.stats": self._handle_stats,
        }
        return handlers.get(intent)

    # ── 各操作的具体实现 ──────────────────────────────

    async def _handle_register(self, task: AgentTask) -> dict[str, Any]:
        """处理 Agent 注册请求"""
        agent_info: dict[str, Any] = task.payload.get("agent_info", {})
        ok = self.register_agent(agent_info)

        if ok:
            agent_id = agent_info.get("agent_id", "")
            await self._publish_event(
                topic=_TOPIC_AGENT_REGISTERED,
                payload={
                    "event": "agent_registered",
                    "agent_id": agent_id,
                    "capabilities": agent_info.get("capabilities", []),
                    "role": agent_info.get("role", "executor"),
                },
                trace_id=task.trace_id,
            )

        return {"success": ok, "agent_id": agent_info.get("agent_id", "")}

    async def _handle_unregister(self, task: AgentTask) -> dict[str, Any]:
        """处理 Agent 注销请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        info = self._registry.pop(agent_id, None)
        ok = info is not None

        if ok:
            self._logger.info("agent_unregistered", agent_id=agent_id)

        return {"success": ok, "agent_id": agent_id}

    async def _handle_find(self, task: AgentTask) -> dict[str, Any]:
        """处理按能力查找 Agent 请求"""
        capabilities: list[str] = task.payload.get("capabilities", [])
        load_preference: str = task.payload.get("load_preference", "lowest")

        agent_id = self.find_agent(
            capabilities=capabilities,
            load_preference=load_preference,
        )

        if agent_id:
            await self._publish_event(
                topic=_TOPIC_AGENT_FOUND,
                payload={
                    "event": "agent_found",
                    "agent_id": agent_id,
                    "capabilities": capabilities,
                    "load_preference": load_preference,
                },
                trace_id=task.trace_id,
            )

        return {
            "agent_id": agent_id,
            "capabilities_requested": capabilities,
            "found": agent_id is not None,
        }

    async def _handle_load_update(self, task: AgentTask) -> dict[str, Any]:
        """处理负载评分更新请求"""
        agent_id: str = task.payload.get("agent_id", "")
        metrics: dict[str, Any] = task.payload.get("metrics", {})

        if not agent_id:
            raise ValueError("agent_id 不能为空")

        score = self._load_evaluator.update_score(agent_id, metrics)

        await self._publish_event(
            topic=_TOPIC_LOAD_UPDATE,
            payload={
                "event": "load_updated",
                "agent_id": agent_id,
                "composite": score.composite,
                "overloaded": self._load_evaluator.detect_overload(agent_id),
            },
            trace_id=task.trace_id,
        )

        return {
            "agent_id": agent_id,
            "composite": score.composite,
            "vram_score": score.vram_score,
            "cpu_score": score.cpu_score,
            "battery_score": score.battery_score,
            "network_score": score.network_score,
            "overloaded": self._load_evaluator.detect_overload(agent_id),
        }

    async def _handle_find_best(self, task: AgentTask) -> dict[str, Any]:
        """处理查找最优 Agent 请求"""
        candidates: list[str] = task.payload.get("candidates", [])

        best_id = self._load_evaluator.get_top_agent(candidates)

        return {
            "best_agent_id": best_id,
            "candidates": candidates,
            "found": best_id is not None,
        }

    async def _handle_ranking(self, task: AgentTask) -> dict[str, Any]:
        """处理负载排名请求"""
        ranking = self.get_load_ranking()

        return {
            "ranking": [
                {"agent_id": aid, "composite": score}
                for aid, score in ranking
            ],
            "count": len(ranking),
        }

    async def _handle_schedule(self, task: AgentTask) -> dict[str, Any]:
        """处理调度决策请求"""
        p = task.payload
        battery_pct: float = float(p.get("battery_pct", 100.0))
        network_available: bool = bool(p.get("network_available", True))
        task_complexity: float = float(p.get("task_complexity", 0.5))

        # 可选：动态切换策略
        strategy_str: str = p.get("strategy", "")
        if strategy_str:
            try:
                self._scheduling_policy.strategy = SchedulingDecision(strategy_str)
            except ValueError:
                raise ValueError(f"无效策略: {strategy_str}")

        decision = self._scheduling_policy.decide(
            battery_pct=battery_pct,
            network_available=network_available,
            task_complexity=task_complexity,
        )

        await self._publish_event(
            topic=_TOPIC_SCHEDULING,
            payload={
                "event": "scheduling_decision",
                "decision": decision.value,
                "battery_pct": battery_pct,
                "network_available": network_available,
                "task_complexity": task_complexity,
                "strategy": self._scheduling_policy.strategy.value,
            },
            trace_id=task.trace_id,
        )

        return {
            "decision": decision.value,
            "strategy": self._scheduling_policy.strategy.value,
            "battery_pct": battery_pct,
            "network_available": network_available,
            "task_complexity": task_complexity,
        }

    async def _handle_list(self, task: AgentTask) -> dict[str, Any]:
        """处理列出所有已注册 Agent 请求"""
        agents = list(self._registry.values())

        return {
            "count": len(agents),
            "agents": agents,
        }

    async def _handle_stats(self, task: AgentTask) -> dict[str, Any]:
        """处理统计信息请求"""
        load_scores = self._load_evaluator.scores()
        policy_config = self._scheduling_policy.config_snapshot()

        # 统计过载 Agent 数
        overloaded_count = sum(
            1 for scores in load_scores.values()
            if scores.get("composite", 0) > 0.85
        )

        return {
            "registered_agents": len(self._registry),
            "tracked_load_scores": len(load_scores),
            "overloaded_agents": overloaded_count,
            "policy": policy_config,
        }

    # ── 生命周期回调 ──────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """Agent 挂载到注册中心时调用"""
        self._logger.info("discovery_agent_mounted")

    async def on_unmount(self) -> None:
        """Agent 从注册中心卸载时调用"""
        self._logger.info("discovery_agent_unmounting")

    async def health(self) -> dict[str, Any]:
        """返回健康状态及发现服务统计"""
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "registered_count": len(self._registry),
            "policy": self._scheduling_policy.config_snapshot(),
        }
