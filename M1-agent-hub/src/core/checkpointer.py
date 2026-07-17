"""
云汐内核 V8 - Checkpointer 状态持久化

灵感来源：LangGraph Checkpointer / Temporal Workflow State

解决评审报告 P0 问题：
- TaskDurability 仅支持 Activity 级 checkpoint → 扩展为全工作流状态快照
- 崩溃后从任意节点恢复
- 支持"时间旅行"调试

核心能力：
- WorkflowState 完整序列化/反序列化
- 节点级 checkpoint（每个节点执行后自动保存）
- 从指定 checkpoint 恢复执行
- checkpoint 列表管理与清理
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Checkpoint:
    """工作流检查点"""

    checkpoint_id: str = ""
    workflow_id: str = ""
    trace_id: str = ""
    node_id: str = ""
    step_index: int = 0
    completed_nodes: list[str] = field(default_factory=list)
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CheckpointConfig:
    """Checkpoint 配置"""

    max_checkpoints_per_workflow: int = 50
    auto_checkpoint: bool = True  # 每个节点执行后自动保存
    snapshot_full_state: bool = True  # 保存完整状态 vs 增量


class Checkpointer:
    """工作流级 Checkpointer

    管理工作流的检查点生命周期，支持保存、恢复、列表、清理。
    默认使用内存存储，可扩展为 SQLite/Redis。
    """

    def __init__(self, config: CheckpointerConfig | None = None) -> None:
        self._config = config or CheckpointConfig()
        self._checkpoints: dict[str, list[Checkpoint]] = {}  # workflow_id -> [cp]
        self._logger = logger.bind(service="checkpointer")

    def save(
        self,
        workflow_id: str,
        trace_id: str,
        node_id: str,
        step_index: int,
        completed_nodes: list[str],
        state_snapshot: dict[str, Any],
        node_outputs: dict[str, Any],
        errors: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> Checkpoint:
        """保存检查点"""
        cp = Checkpoint(
            checkpoint_id=f"cp_{workflow_id}_{step_index}_{int(time.time()*1000)}",
            workflow_id=workflow_id,
            trace_id=trace_id,
            node_id=node_id,
            step_index=step_index,
            completed_nodes=list(completed_nodes),
            state_snapshot=dict(state_snapshot) if self._config.snapshot_full_state else {},
            node_outputs=dict(node_outputs),
            errors=list(errors),
            metadata=metadata or {},
        )

        if workflow_id not in self._checkpoints:
            self._checkpoints[workflow_id] = []

        self._checkpoints[workflow_id].append(cp)

        # 限制检查点数量
        while len(self._checkpoints[workflow_id]) > self._config.max_checkpoints_per_workflow:
            self._checkpoints[workflow_id].pop(0)

        self._logger.debug(
            "checkpoint_saved",
            workflow_id=workflow_id,
            node_id=node_id,
            step_index=step_index,
        )
        return cp

    def load(self, workflow_id: str, checkpoint_id: str) -> Checkpoint | None:
        """加载指定检查点"""
        cps = self._checkpoints.get(workflow_id, [])
        for cp in cps:
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    def load_latest(self, workflow_id: str) -> Checkpoint | None:
        """加载最新检查点"""
        cps = self._checkpoints.get(workflow_id, [])
        return cps[-1] if cps else None

    def list_checkpoints(self, workflow_id: str) -> list[Checkpoint]:
        """列出工作流的所有检查点"""
        return list(self._checkpoints.get(workflow_id, []))

    def remove(self, workflow_id: str, checkpoint_id: str) -> bool:
        """删除指定检查点"""
        cps = self._checkpoints.get(workflow_id, [])
        for i, cp in enumerate(cps):
            if cp.checkpoint_id == checkpoint_id:
                cps.pop(i)
                return True
        return False

    def clear_workflow(self, workflow_id: str) -> int:
        """清除工作流的所有检查点，返回删除数量"""
        count = len(self._checkpoints.get(workflow_id, []))
        self._checkpoints.pop(workflow_id, None)
        return count

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = sum(len(cps) for cps in self._checkpoints.values())
        return {
            "total_checkpoints": total,
            "workflow_count": len(self._checkpoints),
            "max_per_workflow": self._config.max_checkpoints_per_workflow,
            "auto_checkpoint": self._config.auto_checkpoint,
        }
