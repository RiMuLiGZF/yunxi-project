"""
云汐内核 V10.0 — 生命周期管理子Agent (Lifecycle-Agent)

职责：
- 接收生命周期管理请求（创建/激活/挂起/恢复/终止/归档）
- 管理实例池中所有 Agent 的状态转移
- 与 Bus-Agent 协作：发布状态变更事件到消息总线
- 支持引用计数的增减操作
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.tools.interfaces import AgentResult, AgentTask, BusMessage, IAgentPlugin
from shared_models import AgentLifeState, AgentRole
from src.lifecycle.instance_pool import AgentInstance, AgentInstancePool

logger = structlog.get_logger(__name__)

# ── Bus 事件主题 ──────────────────────────────────────────
_TOPIC_LIFECYCLE = "lifecycle.state_change"
_TOPIC_LIFECYCLE_REF = "lifecycle.ref_change"


class LifecycleAgent(IAgentPlugin):
    """生命周期管理子Agent

    作为 V10.0 架构中的子Agent之一，负责管理所有 Agent 实例的
    生命周期状态转移。通过消息总线向其他 Agent 广播状态变更事件，
    确保集群内各节点对实例状态达成一致认知。

    挂载到注册中心后，可通过 task.intent 路由到不同的生命周期操作：
      - lifecycle.create    创建实例
      - lifecycle.activate  激活实例
      - lifecycle.suspend   挂起实例
      - lifecycle.resume    恢复实例
      - lifecycle.drain     优雅终止
      - lifecycle.terminate 强制终止
      - lifecycle.archive   归档实例
      - lifecycle.add_ref   增加引用
      - lifecycle.release_ref 释放引用
      - lifecycle.get       查询实例
      - lifecycle.list      按状态列表
      - lifecycle.stats     池统计
    """

    agent_id: str = "agent.lifecycle"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "lifecycle.create",
        "lifecycle.activate",
        "lifecycle.suspend",
        "lifecycle.resume",
        "lifecycle.drain",
        "lifecycle.terminate",
        "lifecycle.archive",
        "lifecycle.add_ref",
        "lifecycle.release_ref",
        "lifecycle.get",
        "lifecycle.list",
        "lifecycle.stats",
    ]

    def __init__(
        self,
        pool: AgentInstancePool | None = None,
        bus_publish: Any | None = None,
    ) -> None:
        """
        Args:
            pool:         实例池，若为 None 则自动创建
            bus_publish:  消息总线发布函数，签名为 (BusMessage) -> None
                          若为 None 则仅记录日志而不发布事件
        """
        self._pool = pool or AgentInstancePool()
        self._bus_publish = bus_publish
        self._logger = logger.bind(agent_id=self.agent_id)

    # ── 消息总线事件发布 ──────────────────────────────────

    async def _publish_state_change(
        self,
        agent_id: str,
        old_state: str,
        new_state: str,
        reason: str = "",
        trace_id: str = "",
    ) -> None:
        """向消息总线发布状态变更事件"""
        msg = BusMessage(
            topic=_TOPIC_LIFECYCLE,
            sender=self.agent_id,
            msg_type="system.config_change",
            payload={
                "event": "lifecycle.state_change",
                "agent_id": agent_id,
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
            },
            trace_id=trace_id,
        )

        if self._bus_publish is not None:
            try:
                await self._bus_publish(msg)
            except Exception as exc:
                self._logger.warning(
                    "bus_publish_failed",
                    topic=_TOPIC_LIFECYCLE,
                    error=str(exc),
                )
        else:
            self._logger.debug(
                "bus_publish_skipped",
                topic=_TOPIC_LIFECYCLE,
                agent_id=agent_id,
                new_state=new_state,
            )

    async def _publish_ref_change(
        self,
        agent_id: str,
        ref_count: int,
        action: str,
        trace_id: str = "",
    ) -> None:
        """向消息总线发布引用计数变更事件"""
        msg = BusMessage(
            topic=_TOPIC_LIFECYCLE_REF,
            sender=self.agent_id,
            msg_type="system.config_change",
            payload={
                "event": "lifecycle.ref_change",
                "agent_id": agent_id,
                "ref_count": ref_count,
                "action": action,
            },
            trace_id=trace_id,
        )

        if self._bus_publish is not None:
            try:
                await self._bus_publish(msg)
            except Exception as exc:
                self._logger.warning(
                    "bus_publish_failed",
                    topic=_TOPIC_LIFECYCLE_REF,
                    error=str(exc),
                )

    # ── 核心任务处理 ──────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理生命周期管理请求

        根据 task.intent 路由到对应的实例池操作，
        并向消息总线发布状态变更事件。
        """
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "handling_lifecycle_task",
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
                    error=f"未知生命周期操作: {intent}",
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
        except KeyError as exc:
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
                "lifecycle_task_error",
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
            "lifecycle.create": self._handle_create,
            "lifecycle.activate": self._handle_activate,
            "lifecycle.suspend": self._handle_suspend,
            "lifecycle.resume": self._handle_resume,
            "lifecycle.drain": self._handle_drain,
            "lifecycle.terminate": self._handle_terminate,
            "lifecycle.archive": self._handle_archive,
            "lifecycle.add_ref": self._handle_add_ref,
            "lifecycle.release_ref": self._handle_release_ref,
            "lifecycle.get": self._handle_get,
            "lifecycle.list": self._handle_list,
            "lifecycle.stats": self._handle_stats,
        }
        return handlers.get(intent)

    # ── 各操作的具体实现 ──────────────────────────────

    async def _handle_create(self, task: AgentTask) -> dict[str, Any]:
        """处理创建实例请求"""
        p = task.payload
        agent_id: str = p.get("agent_id", "")
        role_str: str = p.get("role", "executor")
        capabilities: list[str] = p.get("capabilities", [])
        config: dict[str, Any] = p.get("config", {})

        if not agent_id:
            raise ValueError("agent_id 不能为空")

        role = AgentRole(role_str)
        instance = self._pool.create(
            agent_id=agent_id,
            role=role,
            capabilities=capabilities,
            config=config,
        )

        await self._publish_state_change(
            agent_id=agent_id,
            old_state="",
            new_state=instance.state.value,
            reason="created",
            trace_id=task.trace_id,
        )

        return instance.to_dict()

    async def _handle_activate(self, task: AgentTask) -> dict[str, Any]:
        """处理激活实例请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        old_state = instance.state.value if instance else ""

        ok = self._pool.activate(agent_id)

        await self._publish_state_change(
            agent_id=agent_id,
            old_state=old_state,
            new_state=self._pool.get_instance(agent_id).state.value if ok else old_state,
            reason="activated",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok}

    async def _handle_suspend(self, task: AgentTask) -> dict[str, Any]:
        """处理挂起实例请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        old_state = instance.state.value if instance else ""

        ok = self._pool.suspend(agent_id)

        await self._publish_state_change(
            agent_id=agent_id,
            old_state=old_state,
            new_state=self._pool.get_instance(agent_id).state.value if ok else old_state,
            reason="suspended",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok}

    async def _handle_resume(self, task: AgentTask) -> dict[str, Any]:
        """处理恢复实例请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        old_state = instance.state.value if instance else ""

        ok = self._pool.resume(agent_id)

        await self._publish_state_change(
            agent_id=agent_id,
            old_state=old_state,
            new_state=self._pool.get_instance(agent_id).state.value if ok else old_state,
            reason="resumed",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok}

    async def _handle_drain(self, task: AgentTask) -> dict[str, Any]:
        """处理优雅终止请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        old_state = instance.state.value if instance else ""

        ok = self._pool.drain(agent_id)

        new_state = self._pool.get_instance(agent_id).state.value if ok else old_state
        await self._publish_state_change(
            agent_id=agent_id,
            old_state=old_state,
            new_state=new_state,
            reason="draining" if new_state == "draining" else "drained_immediately",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok, "state": new_state}

    async def _handle_terminate(self, task: AgentTask) -> dict[str, Any]:
        """处理强制终止请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        old_state = instance.state.value if instance else ""

        ok = self._pool.terminate(agent_id)

        await self._publish_state_change(
            agent_id=agent_id,
            old_state=old_state,
            new_state="terminated" if ok else old_state,
            reason="force_terminated",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok}

    async def _handle_archive(self, task: AgentTask) -> dict[str, Any]:
        """处理归档请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        ok = self._pool.archive(agent_id)

        await self._publish_state_change(
            agent_id=agent_id,
            old_state="terminated",
            new_state="archived" if ok else "terminated",
            reason="archived",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "success": ok}

    async def _handle_add_ref(self, task: AgentTask) -> dict[str, Any]:
        """处理增加引用请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        ref_count = self._pool.add_ref(agent_id)

        await self._publish_ref_change(
            agent_id=agent_id,
            ref_count=ref_count,
            action="add_ref",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "ref_count": ref_count}

    async def _handle_release_ref(self, task: AgentTask) -> dict[str, Any]:
        """处理释放引用请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        ref_count = self._pool.release_ref(agent_id)

        await self._publish_ref_change(
            agent_id=agent_id,
            ref_count=ref_count,
            action="release_ref",
            trace_id=task.trace_id,
        )

        return {"agent_id": agent_id, "ref_count": ref_count}

    async def _handle_get(self, task: AgentTask) -> dict[str, Any]:
        """处理查询实例请求"""
        agent_id: str = task.payload.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 不能为空")

        instance = self._pool.get_instance(agent_id)
        if instance is None:
            return {"agent_id": agent_id, "found": False}

        return {"agent_id": agent_id, "found": True, "instance": instance.to_dict()}

    async def _handle_list(self, task: AgentTask) -> dict[str, Any]:
        """处理按状态列表查询请求"""
        state_str: str = task.payload.get("state", "")
        if not state_str:
            raise ValueError("state 不能为空")

        state = AgentLifeState(state_str)
        instances = self._pool.list_by_state(state)

        return {
            "state": state_str,
            "count": len(instances),
            "instances": [inst.to_dict() for inst in instances],
        }

    async def _handle_stats(self, task: AgentTask) -> dict[str, Any]:
        """处理池统计请求"""
        return self._pool.stats()

    # ── 生命周期回调 ──────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """Agent 挂载到注册中心时调用"""
        self._logger.info("lifecycle_agent_mounted")

    async def on_unmount(self) -> None:
        """Agent 从注册中心卸载时调用"""
        self._logger.info("lifecycle_agent_unmounting")

    async def health(self) -> dict[str, Any]:
        """返回健康状态及池统计信息"""
        pool_stats = self._pool.stats()
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "pool_stats": pool_stats,
        }
