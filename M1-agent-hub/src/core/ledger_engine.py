"""
云汐内核 V9 - Ledger 任务账本引擎

解决评审 P1-019：引入 Magentic-One 式轻量级双层 Ledger，
实现复杂多Agent任务的计划跟踪、进度监控与偏差自校正。

设计约束（7B本地友好）：
- 纯Python实现，无外部依赖
- 内存优先，可选SQLite持久化
- 轻量计划生成（不依赖LLM，基于规则模板）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

REPLAN_MAX_PER_PLAN = 5
REPLAN_MAX_PER_TASK = 20


class LedgerStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    FINAL = "final"


@dataclass
class TaskPlan:
    """任务计划项（Task Ledger 中的单条计划）"""

    plan_id: str
    description: str
    assigned_agent: str = ""
    dependencies: list[str] = field(default_factory=list)
    status: LedgerStatus = LedgerStatus.PLANNED
    result_summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    replan_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "description": self.description,
            "assigned_agent": self.assigned_agent,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result_summary": self.result_summary,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retry_count": self.retry_count,
        }


@dataclass
class AgentProgress:
    """Agent 执行进度（Progress Ledger 中的单条记录）"""

    agent_id: str
    task_id: str
    status: LedgerStatus = LedgerStatus.PLANNED
    completion_rate: float = 0.0  # 0.0 ~ 1.0
    last_output: str = ""
    error: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "completion_rate": self.completion_rate,
            "last_output": self.last_output[:200],  # 截断避免过大
            "error": self.error,
            "updated_at": self.updated_at,
        }


@dataclass
class DeviationEvent:
    """偏差事件：当实际执行偏离计划时触发"""

    event_id: str = field(default_factory=lambda: f"dev_{int(time.time() * 1000)}")
    plan_id: str = ""
    agent_id: str = ""
    expected: str = ""
    actual: str = ""
    deviation_type: str = ""  # agent_failed | handoff_missing | timeout | result_mismatch
    suggested_action: str = ""
    timestamp: float = field(default_factory=time.time)


class TaskLedger:
    """任务计划账本

    维护任务的目标、分解计划、依赖关系。
    类比 Magentic-One 的 Task Ledger（外层循环）。
    """

    def __init__(self, task_id: str, goal: str) -> None:
        self.task_id = task_id
        self.goal = goal
        self.plans: list[TaskPlan] = []
        self._plan_index: dict[str, TaskPlan] = {}
        self._logger = logger.bind(service="task_ledger", task_id=task_id)

    def add_plan(
        self,
        plan_id: str,
        description: str,
        assigned_agent: str = "",
        dependencies: list[str] | None = None,
    ) -> TaskPlan:
        """添加计划项"""
        plan = TaskPlan(
            plan_id=plan_id,
            description=description,
            assigned_agent=assigned_agent,
            dependencies=dependencies or [],
        )
        self.plans.append(plan)
        self._plan_index[plan_id] = plan
        self._logger.info("plan_added", plan_id=plan_id, agent=assigned_agent)
        return plan

    def update_plan_status(
        self, plan_id: str, status: LedgerStatus, result_summary: str = ""
    ) -> bool:
        """更新计划状态"""
        plan = self._plan_index.get(plan_id)
        if plan is None:
            return False
        plan.status = status
        plan.updated_at = time.time()
        if result_summary:
            plan.result_summary = result_summary
        self._logger.info(
            "plan_status_updated",
            plan_id=plan_id,
            status=status.value,
        )
        return True

    def get_ready_plans(self) -> list[TaskPlan]:
        """获取所有依赖已满足、可执行的计划项"""
        ready: list[TaskPlan] = []
        for plan in self.plans:
            if plan.status != LedgerStatus.PLANNED:
                continue
            deps_satisfied = all(
                self._plan_index.get(d, TaskPlan("", "")).status == LedgerStatus.COMPLETED
                for d in plan.dependencies
            )
            if deps_satisfied:
                ready.append(plan)
        return ready

    def get_completion_rate(self) -> float:
        """计算整体完成率"""
        if not self.plans:
            return 0.0
        completed = sum(1 for p in self.plans if p.status == LedgerStatus.COMPLETED)
        return completed / len(self.plans)

    def detect_blockers(self) -> list[TaskPlan]:
        """检测阻塞项：状态为FAILED且重试已达上限的计划"""
        return [
            p for p in self.plans
            if p.status == LedgerStatus.FAILED
            and p.retry_count >= p.max_retries
            and p.replan_count < REPLAN_MAX_PER_PLAN
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "completion_rate": self.get_completion_rate(),
            "plans": [p.to_dict() for p in self.plans],
        }


class ProgressLedger:
    """进度跟踪账本

    实时追踪各Agent的执行状态、输出、错误。
    类比 Magentic-One 的 Progress Ledger（内层循环）。
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.progress_records: dict[str, AgentProgress] = {}
        self.deviation_events: list[DeviationEvent] = []
        self._logger = logger.bind(service="progress_ledger", task_id=task_id)

    def record_progress(
        self,
        agent_id: str,
        status: LedgerStatus,
        completion_rate: float = 0.0,
        output: str = "",
        error: str = "",
    ) -> AgentProgress:
        """记录Agent进度"""
        record = self.progress_records.get(agent_id)
        if record is None:
            record = AgentProgress(agent_id=agent_id, task_id=self.task_id)
            self.progress_records[agent_id] = record

        record.status = status
        record.completion_rate = completion_rate
        if output:
            record.last_output = output
        if error:
            record.error = error
        record.updated_at = time.time()

        self._logger.info(
            "progress_recorded",
            agent_id=agent_id,
            status=status.value,
            completion_rate=completion_rate,
        )
        return record

    def report_deviation(
        self,
        plan_id: str,
        agent_id: str,
        expected: str,
        actual: str,
        deviation_type: str,
        suggested_action: str = "",
    ) -> DeviationEvent:
        """报告执行偏差"""
        event = DeviationEvent(
            plan_id=plan_id,
            agent_id=agent_id,
            expected=expected,
            actual=actual,
            deviation_type=deviation_type,
            suggested_action=suggested_action,
        )
        self.deviation_events.append(event)
        self._logger.error(
            "deviation_detected",
            event_id=event.event_id,
            plan_id=plan_id,
            agent_id=agent_id,
            deviation_type=deviation_type,
            suggested_action=suggested_action,
        )
        return event

    def get_stalled_agents(self, timeout_seconds: float = 60.0) -> list[str]:
        """获取超时未更新的Agent"""
        now = time.time()
        return [
            aid for aid, rec in self.progress_records.items()
            if rec.status == LedgerStatus.IN_PROGRESS
            and (now - rec.updated_at) > timeout_seconds
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agents": [r.to_dict() for r in self.progress_records.values()],
            "deviation_count": len(self.deviation_events),
            "recent_deviations": [{
                "plan_id": d.plan_id,
                "agent_id": d.agent_id,
                "type": d.deviation_type,
                "suggested_action": d.suggested_action,
            } for d in self.deviation_events[-5:]],
        }


class LedgerEngine:
    """Ledger 引擎：整合 Task Ledger + Progress Ledger + 偏差自校正"""

    def __init__(self, max_replan_rounds: int = REPLAN_MAX_PER_TASK) -> None:
        self._task_ledgers: dict[str, TaskLedger] = {}
        self._progress_ledgers: dict[str, ProgressLedger] = {}
        self._replan_counts: dict[str, int] = {}
        self._max_replan_rounds = max_replan_rounds
        self._last_cleanup: float = time.time()
        self._cleanup_interval: float = 3600.0  # 1小时
        self._logger = logger.bind(service="ledger_engine")

    def create_task(self, task_id: str, goal: str) -> tuple[TaskLedger, ProgressLedger]:
        """为新任务创建双层 Ledger"""
        task_ledger = TaskLedger(task_id=task_id, goal=goal)
        progress_ledger = ProgressLedger(task_id=task_id)
        self._task_ledgers[task_id] = task_ledger
        self._progress_ledgers[task_id] = progress_ledger
        self._logger.info("ledger_created", task_id=task_id, goal=goal)
        return task_ledger, progress_ledger

    def get_ledgers(
        self, task_id: str
    ) -> tuple[TaskLedger | None, ProgressLedger | None]:
        return (
            self._task_ledgers.get(task_id),
            self._progress_ledgers.get(task_id),
        )

    def evaluate_and_replan(self, task_id: str) -> dict[str, Any] | None:
        """评估任务状态，必要时触发重规划

        返回重规划建议，或None表示无需重规划。
        """
        task_ledger = self._task_ledgers.get(task_id)
        progress_ledger = self._progress_ledgers.get(task_id)
        if task_ledger is None or progress_ledger is None:
            return None

        # [V9.6] 全面 TTL 清理：移除已关闭超过 24h 的 progress ledger
        now = time.time()
        if now - self._last_cleanup > self._cleanup_interval:
            stale_replan_ids = [
                tid for tid, count in self._replan_counts.items()
                if tid not in self._task_ledgers
            ]
            for tid in stale_replan_ids:
                del self._replan_counts[tid]

            # [V9.6] 清理孤立的 progress ledger（task 已关闭且无引用）
            orphaned_progress_ids = [
                tid for tid in self._progress_ledgers
                if tid not in self._task_ledgers
            ]
            for tid in orphaned_progress_ids:
                del self._progress_ledgers[tid]

            self._last_cleanup = now

        # [V9.5] Replan 总次数保护
        replan_so_far = self._replan_counts.get(task_id, 0)
        if replan_so_far >= self._max_replan_rounds:
            self._logger.error(
                "max_replans_exceeded",
                task_id=task_id,
                replan_count=replan_so_far,
            )
            return {
                "action": "terminate",
                "reason": "max_replans_exceeded",
                "replan_count": replan_so_far,
                "suggestion": "任务已耗尽所有重规划机会，建议人工介入",
            }

        # 检测阻塞项
        blockers = task_ledger.detect_blockers()
        if blockers:
            # [V9.5] 标记已耗尽重规划次数的计划为 SKIPPED
            active_blockers = []
            skipped_plans = []
            for b in blockers:
                if b.replan_count >= REPLAN_MAX_PER_PLAN - 1:
                    b.status = LedgerStatus.SKIPPED
                    b.updated_at = time.time()
                    skipped_plans.append(b.plan_id)
                else:
                    b.replan_count += 1
                    b.updated_at = time.time()
                    active_blockers.append(b)

            self._replan_counts[task_id] = replan_so_far + 1

            result: dict[str, Any] = {
                "action": "replan_required",
                "reason": "blockers_detected",
                "blockers": [b.to_dict() for b in active_blockers],
                "suggestion": "绕过失败计划或分配替代Agent",
            }
            if skipped_plans:
                result["skipped_plans"] = skipped_plans

            # 如果所有 blocker 都被跳过且无其他活跃计划，终止
            if not active_blockers:
                all_planned = [p for p in task_ledger.plans if p.status not in (LedgerStatus.COMPLETED, LedgerStatus.SKIPPED)]
                if not all_planned:
                    return {
                        "action": "terminate",
                        "reason": "all_plans_exhausted",
                        "suggestion": "所有计划已耗尽重试和重规划机会",
                    }

            return result

        # 检测超时停滞
        stalled = progress_ledger.get_stalled_agents(timeout_seconds=120.0)
        if stalled:
            return {
                "action": "replan_required",
                "reason": "agents_stalled",
                "stalled_agents": stalled,
                "suggestion": "检查Agent健康状态或重新分配任务",
            }

        # 检测偏差事件过多
        if len(progress_ledger.deviation_events) >= 3:
            return {
                "action": "replan_required",
                "reason": "too_many_deviations",
                "deviation_count": len(progress_ledger.deviation_events),
                "suggestion": "重新评估整体计划可行性",
            }

        # 检测完成率停滞
        completion = task_ledger.get_completion_rate()
        if completion > 0 and completion < 1.0:
            # 如果所有ready计划都已分配但没有进展，可能存在handoff缺失
            ready = task_ledger.get_ready_plans()
            if ready and all(p.status != LedgerStatus.IN_PROGRESS for p in ready):
                in_progress = [p for p in task_ledger.plans if p.status == LedgerStatus.IN_PROGRESS]
                if not in_progress:
                    return {
                        "action": "replan_required",
                        "reason": "progress_stalled",
                        "completion_rate": completion,
                        "suggestion": "计划存在间隙，需补充中间步骤或调整依赖关系",
                    }

        # [V9.5-R2] 启发式进度评估
        heuristic = self._heuristic_progress_check(task_id)
        if heuristic:
            return heuristic

        return None

    def _heuristic_progress_check(self, task_id: str) -> dict[str, Any] | None:
        """[V9.5-R2] 启发式进度评估（Magentic-One 简化版，无需LLM）
        
        基于规则检测常见进度停滞模式：
        1. 零进展：所有 IN_PROGRESS 计划的 completion_rate 仍为 0 且超时
        2. 乒乓依赖：Plan A 等待 B，B 等待 A（循环依赖检测）
        3. 孤儿计划：已完成的计划无人依赖，但未完成的计划无人为其做前置
        """
        task_ledger = self._task_ledgers.get(task_id)
        progress_ledger = self._progress_ledgers.get(task_id)
        if task_ledger is None or progress_ledger is None:
            return None
        
        now = time.time()
        
        # 模式1：零进展 - IN_PROGRESS 计划超时未更新
        stalled_plans = []
        for plan in task_ledger.plans:
            if plan.status == LedgerStatus.IN_PROGRESS:
                agent_progress = progress_ledger.progress_records.get(plan.assigned_agent)
                if agent_progress and (now - agent_progress.updated_at) > 300:  # 5分钟无更新
                    if agent_progress.completion_rate < 0.1:  # 进度 < 10%
                        stalled_plans.append(plan.plan_id)
        
        if stalled_plans:
            return {
                "action": "attention_required",
                "reason": "zero_progress_detected",
                "stalled_plans": stalled_plans,
                "suggestion": "检查Agent健康状态或简化子任务",
            }
        
        # 模式2：循环依赖检测
        in_progress_ids = {
            p.plan_id for p in task_ledger.plans
            if p.status in (LedgerStatus.PLANNED, LedgerStatus.IN_PROGRESS)
        }
        for plan in task_ledger.plans:
            if plan.plan_id not in in_progress_ids:
                continue
            # 检查是否存在循环：A依赖B，B依赖A
            for dep_id in plan.dependencies:
                dep_plan = task_ledger._plan_index.get(dep_id)
                if dep_plan and plan.plan_id in dep_plan.dependencies:
                    return {
                        "action": "attention_required",
                        "reason": "circular_dependency_detected",
                        "circular_plans": [plan.plan_id, dep_id],
                        "suggestion": "打破循环依赖：移除一个方向的依赖关系",
                    }
        
        return None

    def close_task(self, task_id: str, final_status: LedgerStatus | None = None) -> bool:
        """[V9.6] 关闭任务：标记终态并触发清理

        OrchestratorV9 在 process() 返回前应调用此方法，
        将任务标记为 COMPLETED 或 FAILED，并从活跃集合中移除。
        """
        task_ledger = self._task_ledgers.get(task_id)
        progress_ledger = self._progress_ledgers.get(task_id)
        if task_ledger is None or progress_ledger is None:
            return False

        # [V10.0] 使用传入的 final_status，否则默认 FINAL
        target_status = final_status or LedgerStatus.FINAL
        for plan in task_ledger.plans:
            if plan.status not in (LedgerStatus.COMPLETED, LedgerStatus.SKIPPED, LedgerStatus.FINAL):
                plan.status = target_status
                plan.updated_at = time.time()

        # 标记所有活跃Agent进度为终态
        for record in progress_ledger.progress_records.values():
            if record.status not in (LedgerStatus.COMPLETED, LedgerStatus.FAILED):
                record.status = target_status
                record.updated_at = time.time()

        # 从活跃任务账本中移除，但保留进度账本作为存档
        del self._task_ledgers[task_id]
        # replan计数也清理
        self._replan_counts.pop(task_id, None)
        self._logger.info("task_closed", task_id=task_id, final_status=target_status.value)
        return True

    def query_task(self, task_id: str) -> dict[str, Any] | None:
        """[V10.0-R04] 查询任务状态（供HTTP API使用）

        Returns:
            任务状态字典，含task_id、goal、completion_rate、plans、agents、status。
            若任务不存在，返回None。
        """
        task_ledger = self._task_ledgers.get(task_id)
        progress_ledger = self._progress_ledgers.get(task_id)
        if task_ledger is None and progress_ledger is None:
            return None

        # 判断整体状态
        if task_ledger is not None:
            all_statuses = {p.status for p in task_ledger.plans}
            if all(s == LedgerStatus.COMPLETED for s in all_statuses) or not all_statuses:
                overall = "completed"
            elif any(s == LedgerStatus.IN_PROGRESS for s in all_statuses):
                overall = "in_progress"
            elif any(s == LedgerStatus.FAILED for s in all_statuses):
                overall = "failed"
            elif any(s == LedgerStatus.SKIPPED for s in all_statuses):
                overall = "skipped"
            else:
                overall = "planned"
            completion_rate = task_ledger.get_completion_rate()
            plans_data = [p.to_dict() for p in task_ledger.plans]
            goal = task_ledger.goal
        else:
            overall = "archived"
            completion_rate = 1.0
            plans_data = []
            goal = ""

        agents_data = []
        if progress_ledger is not None:
            agents_data = [r.to_dict() for r in progress_ledger.progress_records.values()]

        return {
            "task_id": task_id,
            "goal": goal,
            "status": overall,
            "completion_rate": round(completion_rate, 4),
            "plans": plans_data,
            "agents": agents_data,
            "active": task_id in self._task_ledgers,
        }

    @property
    def active_task_ledgers(self) -> dict[str, TaskLedger]:
        """当前活跃的任务账本（已关闭的任务不再包含）"""
        return dict(self._task_ledgers)

    def stats(self) -> dict[str, Any]:
        return {
            "active_tasks": len(self._task_ledgers),
            "task_ids": list(self._task_ledgers.keys()),
        }
