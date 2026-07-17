"""
云汐内核 V7 - 任务耐久性执行引擎

灵感来源：
- Temporal.io Durable Execution
- OpenAI Agents SDK + Temporal Integration (2025)
- 持久化执行：工作流状态自动记录，崩溃后精确重放

核心创新：
1. 检查点（Checkpoint）- 任务执行过程中自动保存状态
2. 重放（Replay）- 崩溃后从检查点恢复，不重复执行已完成步骤
3. 幂等保护 - 已完成的 Activity 不会重复执行

与 Temporal 的区别：
- 轻量级：无外部依赖，基于 SQLite + asyncio
- 内嵌式：直接集成到现有任务分发流程中
- 透明性：Agent 无需感知耐久性机制
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

import structlog

from src.core.persistence import SQLitePersistence

logger = structlog.get_logger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    CHECKPOINTED = "checkpointed"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERED = "recovered"


@dataclass
class Checkpoint:
    """检查点"""

    checkpoint_id: str = ""
    task_id: str = ""
    step_index: int = 0
    step_name: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def to_json(self) -> str:
        return json.dumps({
            "checkpoint_id": self.checkpoint_id,
            "task_id": self.task_id,
            "step_index": self.step_index,
            "step_name": self.step_name,
            "state": self.state,
            "timestamp": self.timestamp,
        }, ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            checkpoint_id=data.get("checkpoint_id", ""),
            task_id=data.get("task_id", ""),
            step_index=data.get("step_index", 0),
            step_name=data.get("step_name", ""),
            state=data.get("state", {}),
            timestamp=data.get("timestamp", 0.0),
        )


Activity = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
"""Activity 函数签名：输入状态，返回结果"""


class DurableTask:
    """耐久性任务

    封装一个多步骤任务，支持检查点和重放。
    """

    def __init__(
        self,
        task_id: str,
        activities: list[tuple[str, Activity]],
        persistence: SQLitePersistence | None = None,
    ) -> None:
        self.task_id = task_id
        self.activities = activities
        self.persistence = persistence
        self._checkpoints: list[Checkpoint] = []
        self._current_step: int = 0
        self._final_result: dict[str, Any] | None = None
        self._status = TaskStatus.PENDING
        self._logger = logger.bind(service="durable_task", task_id=task_id)

    # ── 执行 ────────────────────────────────────────────

    async def execute(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        """执行任务（支持重放）"""
        self._status = TaskStatus.RUNNING

        # 1. 尝试恢复之前的检查点
        recovered = await self._recover()
        if recovered:
            self._logger.info("task_recovered", from_step=self._current_step)
            self._status = TaskStatus.RECOVERED

        state = dict(initial_state)

        # 2. 从当前步骤继续执行
        for i in range(self._current_step, len(self.activities)):
            step_name, activity = self.activities[i]

            self._logger.info("activity_starting", step=i, name=step_name)
            step_start = time.time()

            try:
                # 执行 Activity
                result = await activity(state)

                # 更新状态
                state.update(result)

                # 保存检查点
                await self._save_checkpoint(i, step_name, state)
                self._current_step = i + 1

                self._logger.info(
                    "activity_completed",
                    step=i,
                    name=step_name,
                    latency_ms=round((time.time() - step_start) * 1000, 2),
                )

            except Exception as exc:
                self._status = TaskStatus.FAILED
                self._logger.error("activity_failed", step=i, name=step_name, error=str(exc))
                raise

        self._status = TaskStatus.COMPLETED
        self._final_result = state
        return state

    # ── 检查点管理 ──────────────────────────────────────

    async def _save_checkpoint(self, step_index: int, step_name: str, state: dict[str, Any]) -> None:
        """保存检查点"""
        cp = Checkpoint(
            checkpoint_id=f"cp_{uuid.uuid4().hex[:12]}",
            task_id=self.task_id,
            step_index=step_index,
            step_name=step_name,
            state=dict(state),
            timestamp=time.time(),
        )
        self._checkpoints.append(cp)

        if self.persistence:
            try:
                # 复用 persistence 的 events 表存储检查点
                self.persistence.save_event({
                    "event_id": cp.checkpoint_id,
                    "event_type": "task.checkpoint",
                    "trace_id": self.task_id,
                    "timestamp": cp.timestamp,
                    "version": 1,
                    "payload": {
                        "task_id": self.task_id,
                        "step_index": step_index,
                        "step_name": step_name,
                        "state": state,
                    },
                    "metadata": {},
                })
            except Exception as exc:
                self._logger.warning("checkpoint_persist_failed", error=str(exc))

    async def _recover(self) -> bool:
        """从持久化存储恢复检查点"""
        if self.persistence is None:
            return False

        try:
            events = self.persistence.load_events(
                trace_id=self.task_id,
                event_type="task.checkpoint",
                limit=1000,
            )
            if not events:
                return False

            # 找到最新的检查点
            latest = max(events, key=lambda e: e.get("timestamp", 0))
            payload = latest.get("payload", {})

            self._current_step = payload.get("step_index", 0) + 1
            self._logger.info(
                "checkpoint_recovered",
                step=self._current_step,
                checkpoint_id=latest.get("event_id", ""),
            )
            return True
        except Exception as exc:
            self._logger.warning("recover_failed", error=str(exc))
            return False

    # ── 状态查询 ────────────────────────────────────────

    def get_status(self) -> TaskStatus:
        return self._status

    def get_progress(self) -> dict[str, Any]:
        """获取任务进度"""
        return {
            "task_id": self.task_id,
            "status": self._status.value,
            "current_step": self._current_step,
            "total_steps": len(self.activities),
            "progress_ratio": self._current_step / len(self.activities) if self.activities else 0,
            "checkpoints": len(self._checkpoints),
        }


class TaskDurabilityManager:
    """任务耐久性管理器"""

    def __init__(self, persistence: SQLitePersistence | None = None) -> None:
        self.persistence = persistence
        self._tasks: dict[str, DurableTask] = {}
        self._logger = logger.bind(service="task_durability_manager")

    def create_task(
        self,
        task_id: str,
        activities: list[tuple[str, Activity]],
    ) -> DurableTask:
        """创建耐久性任务"""
        task = DurableTask(task_id, activities, self.persistence)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> DurableTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[str]:
        """列出所有任务 ID"""
        return list(self._tasks.keys())

    def stats(self) -> dict[str, Any]:
        """获取统计"""
        return {
            "total_tasks": len(self._tasks),
            "status_distribution": {
                status.value: sum(1 for t in self._tasks.values() if t.get_status() == status)
                for status in TaskStatus
            },
        }
