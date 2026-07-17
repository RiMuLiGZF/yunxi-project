"""
云汐内核 V10.0 — 状态快照与断点续跑子Agent (SnapshotAgent)

职责：
- 封装 SnapshotStore，提供状态快照/恢复/断点续跑的统一接口
- 通过 handle_task 响应快照创建、恢复、链查询、校验、清理等请求
- 支持从指定快照点断点续跑

依赖：
- snapshot.snapshot_store.SnapshotStore / SnapshotChain / SnapshotEntry
- interfaces.IAgentPlugin / AgentTask / AgentResult
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.tools.interfaces import AgentResult, AgentTask, IAgentPlugin
from shared_models import ArbitrationLevel, ArbitrationRequest, ArbitrationResult
from src.snapshot.snapshot_store import SnapshotChain, SnapshotEntry, SnapshotStore

logger = structlog.get_logger(__name__)


class SnapshotAgent(IAgentPlugin):
    """状态快照与断点续跑子Agent

    面向Agent集群提供统一的状态快照管理接口，支持：
    - 创建状态快照（自动计算SHA256校验和）
    - 从快照点恢复执行（断点续跑）
    - 查询任务快照链
    - 校验快照完整性
    - 清理过期快照

    挂载到注册中心后，可通过 task.intent 路由到不同的操作：
      - snapshot.create   创建快照
      - snapshot.restore  恢复到快照点
      - snapshot.chain     获取快照链
      - snapshot.verify    校验快照完整性
      - snapshot.cleanup   清理旧快照
      - snapshot.stats     存储统计
    """

    agent_id: str = "agent.snapshot"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "snapshot.create",
        "snapshot.restore",
        "snapshot.chain",
        "snapshot.verify",
        "snapshot.cleanup",
        "snapshot.stats",
    ]

    def __init__(self, store: SnapshotStore | None = None) -> None:
        """
        Args:
            store: 快照存储实例，若为 None 则自动创建
        """
        self._store = store or SnapshotStore()
        self._logger = logger.bind(agent_id=self.agent_id)

    # ── 生命周期 ──────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """Agent 挂载到注册中心时调用"""
        self._logger.info(
            "snapshot_agent_mounted",
            existing_snapshots=self._store.stats()["total_snapshots"],
        )

    async def on_unmount(self) -> None:
        """Agent 从注册中心卸载时调用"""
        self._logger.info(
            "snapshot_agent_unmounting",
            total_snapshots=self._store.stats()["total_snapshots"],
        )

    async def health(self) -> dict[str, Any]:
        """返回健康状态及存储统计"""
        base = await super().health()
        base["store_stats"] = self._store.stats()
        return base

    # ── 核心任务处理 ──────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理快照/恢复/断点续跑请求

        根据 task.intent 路由到对应的操作。
        """
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "snapshot_agent_handling_task",
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
                "snapshot_agent_task_failed",
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
                error=f"SnapshotAgent任务处理失败: {exc}",
                latency_ms=latency_ms,
            )

    # ── Handler 路由 ──────────────────────────────────

    def _get_handler(self, intent: str):
        """根据 intent 返回对应的处理方法"""
        handlers: dict[str, Any] = {
            "snapshot.create": self._handle_create,
            "snapshot.restore": self._handle_restore,
            "snapshot.chain": self._handle_chain,
            "snapshot.verify": self._handle_verify,
            "snapshot.cleanup": self._handle_cleanup,
            "snapshot.stats": self._handle_stats,
        }
        return handlers.get(intent)

    # ── 各操作的具体实现 ──────────────────────────────

    async def _handle_create(self, task: AgentTask) -> dict[str, Any]:
        """处理创建快照请求"""
        p = task.payload
        task_id: str = p.get("task_id", "")
        dag_id: str = p.get("dag_id", "")
        node_states: list[dict[str, Any]] = p.get("node_states", [])
        agent_states: list[dict[str, Any]] = p.get("agent_states", [])
        budget_snapshot: dict[str, Any] = p.get("budget_snapshot", {})

        if not task_id:
            raise ValueError("task_id 不能为空")

        entry = self.create(
            task_id=task_id,
            dag_id=dag_id,
            context={
                "node_states": node_states,
                "agent_states": agent_states,
                "budget_snapshot": budget_snapshot,
            },
        )
        return entry.to_dict()

    async def _handle_restore(self, task: AgentTask) -> dict[str, Any]:
        """处理恢复快照请求"""
        snapshot_id: str = task.payload.get("snapshot_id", "")
        if not snapshot_id:
            raise ValueError("snapshot_id 不能为空")

        result = self.restore(snapshot_id)
        if result is None:
            raise ValueError(f"快照不存在或完整性校验失败: {snapshot_id}")

        return result

    async def _handle_chain(self, task: AgentTask) -> dict[str, Any]:
        """处理获取快照链请求"""
        task_id: str = task.payload.get("task_id", "")
        if not task_id:
            raise ValueError("task_id 不能为空")

        chain_entries = self.get_chain(task_id)
        chain_wrapper = SnapshotChain(self._store, task_id)

        return {
            "task_id": task_id,
            "chain_length": len(chain_entries),
            "entries": [e.to_dict() for e in chain_entries],
            "summary": chain_wrapper.summary(),
        }

    async def _handle_verify(self, task: AgentTask) -> dict[str, Any]:
        """处理校验快照请求"""
        snapshot_id: str = task.payload.get("snapshot_id", "")
        if not snapshot_id:
            raise ValueError("snapshot_id 不能为空")

        is_valid = self.verify(snapshot_id)
        return {
            "snapshot_id": snapshot_id,
            "valid": is_valid,
        }

    async def _handle_cleanup(self, task: AgentTask) -> dict[str, Any]:
        """处理清理旧快照请求"""
        task_id: str = task.payload.get("task_id", "")
        max_age: float = task.payload.get("max_age_seconds", 3600.0)

        if not task_id:
            raise ValueError("task_id 不能为空")

        pruned_count = self.cleanup(task_id, max_age)
        return {
            "task_id": task_id,
            "pruned_count": pruned_count,
            "max_age_seconds": max_age,
        }

    async def _handle_stats(self, task: AgentTask) -> dict[str, Any]:
        """处理存储统计请求"""
        return self._store.stats()

    # ── 公开API ──────────────────────────────────────

    def create(
        self,
        task_id: str,
        dag_id: str,
        context: dict[str, Any],
    ) -> SnapshotEntry:
        """创建一次状态快照

        Args:
            task_id:  任务ID
            dag_id:   DAG ID
            context:  上下文字典，包含 node_states、agent_states、budget_snapshot

        Returns:
            新创建的 SnapshotEntry
        """
        node_states: list[dict[str, Any]] = context.get("node_states", [])
        agent_states: list[dict[str, Any]] = context.get("agent_states", [])
        budget_snapshot: dict[str, Any] = context.get("budget_snapshot", {})

        entry = self._store.create_snapshot(
            task_id=task_id,
            dag_id=dag_id,
            node_states=node_states,
            agent_states=agent_states,
            budget_snapshot=budget_snapshot,
        )

        self._logger.info(
            "snapshot_created",
            snapshot_id=entry.snapshot_id,
            task_id=task_id,
            dag_id=dag_id,
        )

        return entry

    def restore(self, snapshot_id: str) -> dict[str, Any] | None:
        """恢复到指定快照点（断点续跑）

        从快照中提取节点状态、Agent状态和预算快照，用于恢复执行。

        Args:
            snapshot_id: 目标快照ID

        Returns:
            包含恢复所需数据的字典；快照不存在或完整性校验失败时返回None
        """
        entry = self._store.get_snapshot(snapshot_id)
        if entry is None:
            self._logger.warning("restore_snapshot_not_found", snapshot_id=snapshot_id)
            return None

        # 校验完整性
        if not self._store.verify_integrity(snapshot_id):
            self._logger.error(
                "restore_integrity_failed",
                snapshot_id=snapshot_id,
            )
            return None

        # 构建恢复数据
        restore_data = {
            "snapshot_id": entry.snapshot_id,
            "task_id": entry.task_id,
            "dag_id": entry.dag_id,
            "node_states": entry.node_states,
            "agent_states": entry.agent_states,
            "budget_snapshot": entry.budget_snapshot,
            "timestamp": entry.timestamp,
            "parent_id": entry.parent_id,
            "checksum": entry.checksum,
        }

        self._logger.info(
            "snapshot_restored",
            snapshot_id=snapshot_id,
            task_id=entry.task_id,
            dag_id=entry.dag_id,
            timestamp=entry.timestamp,
        )

        return restore_data

    def get_chain(self, task_id: str) -> list[dict[str, Any]]:
        """获取指定任务的完整快照链

        Args:
            task_id: 任务ID

        Returns:
            快照字典列表（按时间正序）
        """
        entries = self._store.get_chain(task_id)
        return [e.to_dict() for e in entries]

    def verify(self, snapshot_id: str) -> bool:
        """校验指定快照的完整性

        Args:
            snapshot_id: 快照唯一标识

        Returns:
            True 表示完整性校验通过
        """
        is_valid = self._store.verify_integrity(snapshot_id)
        self._logger.info(
            "snapshot_verify",
            snapshot_id=snapshot_id,
            valid=is_valid,
        )
        return is_valid

    def cleanup(self, task_id: str, max_age: float) -> int:
        """清理指定任务的过期快照

        Args:
            task_id:         任务ID
            max_age:         最大存活秒数

        Returns:
            被清理的快照数量
        """
        pruned = self._store.prune_older_than(task_id, max_age)
        self._logger.info(
            "snapshot_cleanup",
            task_id=task_id,
            max_age=max_age,
            pruned_count=pruned,
        )
        return pruned
