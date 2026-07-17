"""
云汐内核 V10.0 — 死锁仲裁子Agent (ArbiterAgent)

职责：
- 集成 WaitForGraph + ArbitrationEngine，提供统一的死锁检测与仲裁接口
- 通过 handle_task 响应死锁检测、仲裁请求、等待关系更新等请求
- 支持多级仲裁策略（自动 → 协商 → 人工介入）

依赖：
- arbiter.wait_for_graph.WaitForGraph / ArbitrationEngine
- interfaces.IAgentPlugin / AgentTask / AgentResult
- shared_models：ArbitrationRequest / ArbitrationResult
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.tools.interfaces import AgentResult, AgentTask, IAgentPlugin
from shared_models import ArbitrationRequest, ArbitrationResult
from src.arbiter.wait_for_graph import ArbitrationEngine, WaitForGraph

logger = structlog.get_logger(__name__)


class ArbiterAgent(IAgentPlugin):
    """死锁仲裁子Agent

    面向Agent集群提供统一的死锁检测与仲裁接口，支持：
    - 死锁环检测（基于等待图的DFS环检测）
    - 三级仲裁（自动解决 → 协商解决 → 人工介入）
    - 等待关系图的实时更新
    - 仲裁历史查询与统计

    挂载到注册中心后，可通过 task.intent 路由到不同的操作：
      - arbiter.check_deadlock   检测死锁环
      - arbiter.arbitrate        发起仲裁
      - arbiter.update_wait_for  更新等待关系
      - arbiter.resolve_wait_for 解除等待关系
      - arbiter.status           获取仲裁系统状态
      - arbiter.history           获取仲裁历史
    """

    agent_id: str = "agent.arbiter"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "arbiter.check_deadlock",
        "arbiter.arbitrate",
        "arbiter.update_wait_for",
        "arbiter.resolve_wait_for",
        "arbiter.status",
        "arbiter.history",
    ]

    def __init__(
        self,
        graph: WaitForGraph | None = None,
        engine: ArbitrationEngine | None = None,
    ) -> None:
        """
        Args:
            graph:  等待图实例，若为 None 则自动创建
            engine: 仲裁引擎实例，若为 None 则自动创建
        """
        self._graph = graph or WaitForGraph()
        self._engine = engine or ArbitrationEngine()
        self._logger = logger.bind(agent_id=self.agent_id)

    # ── 生命周期 ──────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """Agent 挂载到注册中心时调用"""
        self._logger.info(
            "arbiter_agent_mounted",
            graph_stats=self._graph.stats(),
            engine_stats=self._engine.stats(),
        )

    async def on_unmount(self) -> None:
        """Agent 从注册中心卸载时调用"""
        await self._graph.clear()
        self._logger.info("arbiter_agent_unmounting")

    async def health(self) -> dict[str, Any]:
        """返回健康状态及仲裁系统统计"""
        base = await super().health()
        base["graph_stats"] = self._graph.stats()
        base["engine_stats"] = self._engine.stats()
        return base

    # ── 核心任务处理 ──────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理仲裁请求

        根据 task.intent 路由到对应的操作。
        """
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "arbiter_agent_handling_task",
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
                    error=f"不支持的intent: {intent}",
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
                "arbiter_agent_task_failed",
                error=str(exc),
                exc_info=True,
                task_id=task.task_id,
                intent=intent,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"ArbiterAgent任务处理失败: {exc}",
                latency_ms=latency_ms,
            )

    # ── Handler 路由 ──────────────────────────────────

    def _get_handler(self, intent: str):
        """根据 intent 返回对应的处理方法"""
        handlers: dict[str, Any] = {
            "arbiter.check_deadlock": self._handle_check_deadlock,
            "arbiter.arbitrate": self._handle_arbitrate,
            "arbiter.update_wait_for": self._handle_update_wait_for,
            "arbiter.resolve_wait_for": self._handle_resolve_wait_for,
            "arbiter.status": self._handle_status,
            "arbiter.history": self._handle_history,
        }
        return handlers.get(intent)

    # ── 各操作的具体实现 ──────────────────────────────

    async def _handle_check_deadlock(self, task: AgentTask) -> dict[str, Any]:
        """处理死锁检测请求"""
        cycles = await self.check_deadlock()
        deadlocked = await self._graph.get_deadlocked_agents()

        return {
            "has_deadlock": len(cycles) > 0,
            "cycles": cycles,
            "deadlocked_agents": list(deadlocked),
            "deadlocked_count": len(deadlocked),
        }

    async def _handle_arbitrate(self, task: AgentTask) -> dict[str, Any]:
        """处理仲裁请求"""
        p = task.payload
        conflict_type: str = p.get("conflict_type", "")
        involved_agents: list[str] = p.get("involved_agents", [])
        task_ids: list[str] = p.get("task_ids", [])
        context: dict[str, Any] = p.get("context", {})

        if not conflict_type:
            raise ValueError("conflict_type 不能为空")
        if not involved_agents:
            raise ValueError("involved_agents 不能为空")

        result = self.arbitrate(
            conflict_type=conflict_type,
            involved_agents=involved_agents,
            task_ids=task_ids,
            context=context,
        )

        return result.model_dump()

    async def _handle_update_wait_for(self, task: AgentTask) -> dict[str, Any]:
        """处理更新等待关系请求"""
        waiter: str = task.payload.get("waiter", "")
        holder: str = task.payload.get("holder", "")

        if not waiter or not holder:
            raise ValueError("waiter 和 holder 不能为空")

        await self.update_wait_for(waiter, holder)

        return {
            "waiter": waiter,
            "holder": holder,
            "action": "added",
        }

    async def _handle_resolve_wait_for(self, task: AgentTask) -> dict[str, Any]:
        """处理解除等待关系请求"""
        waiter: str = task.payload.get("waiter", "")
        holder: str = task.payload.get("holder", "")

        if not waiter or not holder:
            raise ValueError("waiter 和 holder 不能为空")

        await self.resolve_wait_for(waiter, holder)

        return {
            "waiter": waiter,
            "holder": holder,
            "action": "removed",
        }

    async def _handle_status(self, task: AgentTask) -> dict[str, Any]:
        """处理获取仲裁系统状态请求"""
        return await self.get_status()

    async def _handle_history(self, task: AgentTask) -> dict[str, Any]:
        """处理获取仲裁历史请求"""
        limit: int = task.payload.get("limit", 100)
        history = self._engine.get_history(limit=limit)

        return {
            "count": len(history),
            "records": [r.model_dump() for r in history],
        }

    # ── 公开API ──────────────────────────────────────

    async def check_deadlock(self) -> list[list[str]]:
        """检测当前等待图中的所有死锁环

        Returns:
            所有环的列表，每个环是一个 agent_id 列表
        """
        cycles = await self._graph.detect_cycle()
        self._logger.info(
            "deadlock_check_completed",
            cycles_found=len(cycles),
        )
        return cycles

    def arbitrate(
        self,
        conflict_type: str,
        involved_agents: list[str],
        task_ids: list[str],
        context: dict[str, Any],
    ) -> ArbitrationResult:
        """发起仲裁请求

        构建仲裁请求并提交给仲裁引擎，执行三级仲裁。

        Args:
            conflict_type:    冲突类型（resource_deadlock / priority_conflict / dependency_cycle / timeout）
            involved_agents:   涉及的Agent ID列表
            task_ids:         涉及的任务ID列表
            context:          附加上下文（agent_info、resource_id 等）

        Returns:
            仲裁结果
        """
        request = ArbitrationRequest(
            conflict_type=conflict_type,
            involved_agents=involved_agents,
            task_ids=task_ids,
            context=context,
        )

        result = self._engine.submit(request)

        self._logger.info(
            "arbitration_completed",
            request_id=request.request_id,
            level=result.level.value,
            decision=result.decision,
            involved_agents=involved_agents,
        )

        return result

    async def update_wait_for(self, waiter: str, holder: str) -> None:
        """更新等待关系：添加 waiter 等待 holder 的边

        Args:
            waiter: 等待方Agent ID
            holder: 被等待方Agent ID
        """
        await self._graph.add_edge(waiter, holder)
        self._logger.info(
            "wait_for_updated",
            waiter=waiter,
            holder=holder,
        )

    async def resolve_wait_for(self, waiter: str, holder: str) -> None:
        """解除等待关系：移除 waiter 等待 holder 的边

        Args:
            waiter: 等待方Agent ID
            holder: 被等待方Agent ID
        """
        await self._graph.remove_edge(waiter, holder)
        self._logger.info(
            "wait_for_resolved",
            waiter=waiter,
            holder=holder,
        )

    async def get_status(self) -> dict[str, Any]:
        """获取仲裁系统整体状态

        Returns:
            包含等待图统计、仲裁引擎统计、死锁检测结果的完整状态
        """
        cycles = await self._graph.detect_cycle()
        deadlocked = set()
        for cycle in cycles:
            deadlocked.update(cycle)

        return {
            "graph_stats": self._graph.stats(),
            "engine_stats": self._engine.stats(),
            "current_deadlocks": {
                "has_deadlock": len(cycles) > 0,
                "cycles": cycles,
                "deadlocked_agents": list(deadlocked),
                "deadlocked_count": len(deadlocked),
            },
        }
