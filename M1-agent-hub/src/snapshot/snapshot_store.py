"""
云汐内核 V10.0 — 状态快照与断点续跑存储 (SnapshotStore / SnapshotChain)

职责：
- SnapshotEntry：单次状态快照数据结构，包含SHA256校验和
- SnapshotStore：快照的增删查改、链式管理、完整性校验与过期清理
- SnapshotChain：快照链的便捷操作包装（遍历、差异比较等）

依赖：
- interfaces / shared_models：核心数据模型
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════
# SnapshotEntry — 快照条目
# ══════════════════════════════════════════════════════════


@dataclass
class SnapshotEntry:
    """单次状态快照条目

    Attributes:
        snapshot_id:   快照唯一标识（UUID）
        task_id:       所属任务ID
        dag_id:        所属DAG ID
        node_states:   各节点状态快照列表
        agent_states:  各Agent实例状态快照列表
        budget_snapshot: 预算使用快照
        timestamp:     创建时间戳
        checksum:      内容完整性校验（SHA256）
        parent_id:     前序快照ID（形成链，首条为None）
    """

    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = ""
    dag_id: str = ""
    node_states: list[dict[str, Any]] = field(default_factory=list)
    agent_states: list[dict[str, Any]] = field(default_factory=list)
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    checksum: str = ""
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "task_id": self.task_id,
            "dag_id": self.dag_id,
            "node_states": self.node_states,
            "agent_states": self.agent_states,
            "budget_snapshot": self.budget_snapshot,
            "timestamp": self.timestamp,
            "checksum": self.checksum,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotEntry:
        """从字典反序列化"""
        return cls(
            snapshot_id=data.get("snapshot_id", ""),
            task_id=data.get("task_id", ""),
            dag_id=data.get("dag_id", ""),
            node_states=data.get("node_states", []),
            agent_states=data.get("agent_states", []),
            budget_snapshot=data.get("budget_snapshot", {}),
            timestamp=data.get("timestamp", 0.0),
            checksum=data.get("checksum", ""),
            parent_id=data.get("parent_id"),
        )


# ══════════════════════════════════════════════════════════
# SnapshotStore — 快照存储
# ══════════════════════════════════════════════════════════


class SnapshotStore:
    """状态快照存储

    管理所有任务的状态快照，支持：
    - 创建快照（自动计算SHA256校验和）
    - 按ID获取单条快照
    - 按task_id获取完整快照链
    - 获取某任务的最新快照
    - 校验快照完整性（SHA256）
    - 清理过期快照
    - 统计信息
    """

    def __init__(self) -> None:
        # snapshot_id -> SnapshotEntry
        self._snapshots: dict[str, SnapshotEntry] = {}
        # task_id -> [snapshot_id, ...] 按时间顺序排列的快照链
        self._chains: dict[str, list[str]] = {}
        self._logger = logger.bind(component="snapshot_store")

    # ── SHA256 校验工具 ──────────────────────────────

    @staticmethod
    def _compute_checksum(
        task_id: str,
        dag_id: str,
        node_states: list[dict[str, Any]],
        agent_states: list[dict[str, Any]],
        budget_snapshot: dict[str, Any],
    ) -> str:
        """计算快照内容的SHA256校验和

        Args:
            task_id:         任务ID
            dag_id:          DAG ID
            node_states:     节点状态列表
            agent_states:    Agent状态列表
            budget_snapshot: 预算快照

        Returns:
            SHA256十六进制摘要字符串
        """
        content = json.dumps(
            {
                "task_id": task_id,
                "dag_id": dag_id,
                "node_states": node_states,
                "agent_states": agent_states,
                "budget_snapshot": budget_snapshot,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    # ── 核心操作 ──────────────────────────────────────

    def create_snapshot(
        self,
        task_id: str,
        dag_id: str,
        node_states: list[dict[str, Any]],
        agent_states: list[dict[str, Any]],
        budget_snapshot: dict[str, Any],
    ) -> SnapshotEntry:
        """创建一次状态快照

        自动计算SHA256校验和，并将快照追加到对应任务的快照链中。

        Args:
            task_id:         任务ID
            dag_id:          DAG ID
            node_states:     各节点当前状态列表
            agent_states:     各Agent实例当前状态列表
            budget_snapshot: 预算使用快照

        Returns:
            新创建的 SnapshotEntry
        """
        # 计算校验和
        checksum = self._compute_checksum(
            task_id=task_id,
            dag_id=dag_id,
            node_states=node_states,
            agent_states=agent_states,
            budget_snapshot=budget_snapshot,
        )

        # 确定前序快照ID（链式关联）
        parent_id: str | None = None
        chain = self._chains.get(task_id, [])
        if chain:
            parent_id = chain[-1]

        # 创建快照条目
        entry = SnapshotEntry(
            snapshot_id=uuid.uuid4().hex,
            task_id=task_id,
            dag_id=dag_id,
            node_states=node_states,
            agent_states=agent_states,
            budget_snapshot=budget_snapshot,
            timestamp=time.time(),
            checksum=checksum,
            parent_id=parent_id,
        )

        # 存入索引
        self._snapshots[entry.snapshot_id] = entry

        # 追加到任务快照链
        if task_id not in self._chains:
            self._chains[task_id] = []
        self._chains[task_id].append(entry.snapshot_id)

        self._logger.info(
            "snapshot_created",
            snapshot_id=entry.snapshot_id,
            task_id=task_id,
            parent_id=parent_id,
            chain_length=len(self._chains[task_id]),
        )

        return entry

    def get_snapshot(self, snapshot_id: str) -> SnapshotEntry | None:
        """根据快照ID获取快照条目

        Args:
            snapshot_id: 快照唯一标识

        Returns:
            SnapshotEntry 或 None（不存在时）
        """
        entry = self._snapshots.get(snapshot_id)
        if entry is None:
            self._logger.debug("snapshot_not_found", snapshot_id=snapshot_id)
        return entry

    def get_chain(self, task_id: str) -> list[SnapshotEntry]:
        """获取指定任务的完整快照链

        按时间顺序返回所有快照。

        Args:
            task_id: 任务ID

        Returns:
            SnapshotEntry 列表（按时间正序）
        """
        chain_ids = self._chains.get(task_id, [])
        entries: list[SnapshotEntry] = []
        for sid in chain_ids:
            entry = self._snapshots.get(sid)
            if entry is not None:
                entries.append(entry)
        return entries

    def get_latest(self, task_id: str) -> SnapshotEntry | None:
        """获取指定任务的最新快照

        Args:
            task_id: 任务ID

        Returns:
            最新的 SnapshotEntry 或 None（无快照时）
        """
        chain_ids = self._chains.get(task_id, [])
        if not chain_ids:
            return None
        return self._snapshots.get(chain_ids[-1])

    def verify_integrity(self, snapshot_id: str) -> bool:
        """校验快照内容的完整性（SHA256）

        重新计算快照内容的SHA256，与存储的校验和比对。

        Args:
            snapshot_id: 快照唯一标识

        Returns:
            True 表示完整性校验通过
        """
        entry = self._snapshots.get(snapshot_id)
        if entry is None:
            self._logger.warning("verify_snapshot_not_found", snapshot_id=snapshot_id)
            return False

        expected = self._compute_checksum(
            task_id=entry.task_id,
            dag_id=entry.dag_id,
            node_states=entry.node_states,
            agent_states=entry.agent_states,
            budget_snapshot=entry.budget_snapshot,
        )

        is_valid = expected == entry.checksum
        if not is_valid:
            self._logger.warning(
                "snapshot_integrity_failed",
                snapshot_id=snapshot_id,
                expected=expected,
                actual=entry.checksum,
            )
        else:
            self._logger.debug("snapshot_integrity_ok", snapshot_id=snapshot_id)

        return is_valid

    def prune_older_than(self, task_id: str, max_age_seconds: float) -> int:
        """清理指定任务中超过最大存活时间的旧快照

        保留最新的快照不被清理。清理后更新快照链。

        Args:
            task_id:          任务ID
            max_age_seconds:  最大存活秒数

        Returns:
            被清理的快照数量
        """
        chain_ids = self._chains.get(task_id, [])
        if not chain_ids:
            return 0

        now = time.time()
        cutoff = now - max_age_seconds
        pruned_ids: list[str] = []

        for sid in chain_ids:
            entry = self._snapshots.get(sid)
            if entry is None:
                pruned_ids.append(sid)
                continue
            if entry.timestamp < cutoff and sid != chain_ids[-1]:
                # 不清理最新快照
                pruned_ids.append(sid)

        if not pruned_ids:
            return 0

        # 从存储中移除
        for sid in pruned_ids:
            self._snapshots.pop(sid, None)

        # 更新快照链
        self._chains[task_id] = [sid for sid in chain_ids if sid not in pruned_ids]

        self._logger.info(
            "snapshots_pruned",
            task_id=task_id,
            pruned_count=len(pruned_ids),
            remaining_count=len(self._chains[task_id]),
        )

        return len(pruned_ids)

    def stats(self) -> dict[str, Any]:
        """快照存储统计信息

        Returns:
            包含总快照数、任务数、各任务快照数等统计
        """
        chain_lengths = {
            tid: len(sids) for tid, sids in self._chains.items()
        }
        return {
            "total_snapshots": len(self._snapshots),
            "total_tasks_with_snapshots": len(self._chains),
            "chain_lengths": chain_lengths,
            "average_chain_length": (
                sum(chain_lengths.values()) / len(chain_lengths)
                if chain_lengths
                else 0.0
            ),
        }


# ══════════════════════════════════════════════════════════
# SnapshotChain — 快照链便捷操作
# ══════════════════════════════════════════════════════════


class SnapshotChain:
    """快照链便捷操作包装

    封装对 SnapshotStore 中某任务快照链的常用操作：
    - 遍历链上的所有快照
    - 比较相邻快照的差异
    - 从指定快照点恢复
    - 获取链的摘要信息
    """

    def __init__(self, store: SnapshotStore, task_id: str) -> None:
        """
        Args:
            store:   快照存储实例
            task_id: 目标任务ID
        """
        self._store = store
        self._task_id = task_id
        self._logger = logger.bind(component="snapshot_chain", task_id=task_id)

    @property
    def task_id(self) -> str:
        """目标任务ID"""
        return self._task_id

    def entries(self) -> list[SnapshotEntry]:
        """获取完整快照链"""
        return self._store.get_chain(self._task_id)

    def latest(self) -> SnapshotEntry | None:
        """获取最新快照"""
        return self._store.get_latest(self._task_id)

    def get_entry(self, snapshot_id: str) -> SnapshotEntry | None:
        """根据快照ID获取指定快照"""
        return self._store.get_snapshot(snapshot_id)

    def diff(
        self, snapshot_id_a: str, snapshot_id_b: str
    ) -> dict[str, Any]:
        """比较两个快照之间的差异

        Args:
            snapshot_id_a: 基准快照ID
            snapshot_id_b: 目标快照ID

        Returns:
            包含节点状态变化、Agent状态变化、预算变化的差异字典
        """
        entry_a = self._store.get_snapshot(snapshot_id_a)
        entry_b = self._store.get_snapshot(snapshot_id_b)

        if entry_a is None or entry_b is None:
            return {"error": "快照不存在", "snapshot_id_a": snapshot_id_a, "snapshot_id_b": snapshot_id_b}

        return {
            "snapshot_id_a": snapshot_id_a,
            "snapshot_id_b": snapshot_id_b,
            "timestamp_a": entry_a.timestamp,
            "timestamp_b": entry_b.timestamp,
            "time_delta": round(entry_b.timestamp - entry_a.timestamp, 4),
            "node_state_changes": self._compare_states(entry_a.node_states, entry_b.node_states),
            "agent_state_changes": self._compare_states(entry_a.agent_states, entry_b.agent_states),
            "budget_changes": self._compare_budget(entry_a.budget_snapshot, entry_b.budget_snapshot),
        }

    @staticmethod
    def _compare_states(
        states_a: list[dict[str, Any]],
        states_b: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """比较两组状态列表的差异

        以ID为key匹配，返回变化项列表。
        """
        map_a = {s.get("id", s.get("node_id", s.get("agent_id", ""))): s for s in states_a}
        map_b = {s.get("id", s.get("node_id", s.get("agent_id", ""))): s for s in states_b}

        changes: list[dict[str, Any]] = []
        all_keys = set(map_a.keys()) | set(map_b.keys())

        for key in sorted(all_keys):
            old_state = map_a.get(key)
            new_state = map_b.get(key)
            if old_state is None:
                changes.append({"id": key, "change": "added", "new_state": new_state})
            elif new_state is None:
                changes.append({"id": key, "change": "removed", "old_state": old_state})
            elif old_state != new_state:
                changes.append({
                    "id": key,
                    "change": "modified",
                    "old_state": old_state,
                    "new_state": new_state,
                })

        return changes

    @staticmethod
    def _compare_budget(
        budget_a: dict[str, Any],
        budget_b: dict[str, Any],
    ) -> dict[str, Any]:
        """比较两个预算快照的差异"""
        all_keys = set(budget_a.keys()) | set(budget_b.keys())
        changes: dict[str, Any] = {}
        for key in all_keys:
            old_val = budget_a.get(key)
            new_val = budget_b.get(key)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}
        return changes

    def restore_point(self, snapshot_id: str) -> dict[str, Any] | None:
        """获取指定快照的恢复数据

        用于断点续跑：返回快照中保存的节点状态、Agent状态和预算快照。

        Args:
            snapshot_id: 目标快照ID

        Returns:
            包含恢复所需数据的字典，快照不存在时返回None
        """
        entry = self._store.get_snapshot(snapshot_id)
        if entry is None:
            self._logger.warning("restore_snapshot_not_found", snapshot_id=snapshot_id)
            return None

        # 校验完整性
        if not self._store.verify_integrity(snapshot_id):
            self._logger.error(
                "restore_snapshot_integrity_failed",
                snapshot_id=snapshot_id,
            )
            return None

        self._logger.info(
            "restore_point_prepared",
            snapshot_id=snapshot_id,
            task_id=self._task_id,
            timestamp=entry.timestamp,
        )

        return {
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

    def summary(self) -> dict[str, Any]:
        """获取快照链摘要信息

        Returns:
            包含链长度、时间跨度、首尾快照等摘要信息
        """
        chain = self.entries()
        if not chain:
            return {
                "task_id": self._task_id,
                "length": 0,
                "exists": False,
            }

        first = chain[0]
        last = chain[-1]

        return {
            "task_id": self._task_id,
            "exists": True,
            "length": len(chain),
            "first_snapshot_id": first.snapshot_id,
            "last_snapshot_id": last.snapshot_id,
            "time_span": round(last.timestamp - first.timestamp, 4),
            "first_timestamp": first.timestamp,
            "last_timestamp": last.timestamp,
        }
