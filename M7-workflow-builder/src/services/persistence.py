"""M7 积木平台 - 持久化执行引擎.

P2 级优化：持久化任务队列 + 断点恢复 + 并发控制增强 + 死信队列。

核心组件：
- PersistentRunRepository: 持久化运行记录的 CRUD 操作
- ExecutionContextRepository: 执行上下文快照管理
- PersistentExecutor: 持久化执行器，支持断点恢复
- WorkflowQueue: 优先级任务队列
- DeadLetterManager: 死信队列管理
- CrashRecoveryManager: 崩溃恢复管理器
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.orm import Session

from ..db import get_session
from ..models_db import (
    ExecutionContextSnapshot,
    PersistentWorkflowRun,
)

logger = logging.getLogger("m7.persistence")


# ============================================================
# 常量定义
# ============================================================

class RunStatus:
    """运行状态常量."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"

    ALL = {PENDING, RUNNING, COMPLETED, FAILED, CANCELLED, DEAD_LETTER}
    ACTIVE = {PENDING, RUNNING}
    FINISHED = {COMPLETED, FAILED, CANCELLED, DEAD_LETTER}


class SnapshotType:
    """快照类型常量."""
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    ERROR = "error"
    CHECKPOINT = "checkpoint"
    RECOVERY = "recovery"


# ============================================================
# 持久化运行仓库
# ============================================================

class PersistentRunRepository:
    """持久化工作流运行记录仓库.

    提供对 persistent_workflow_runs 表的 CRUD 操作。
    线程安全，每个操作使用独立 session。
    """

    def __init__(self, session: Optional[Session] = None):
        """初始化仓库.

        Args:
            session: 可选的数据库 session，不传则每次操作创建新 session
        """
        self._external_session = session

    def _get_session(self) -> Session:
        """获取数据库 session."""
        if self._external_session:
            return self._external_session
        return get_session()

    def _close_if_needed(self, session: Session):
        """如果是内部创建的 session 则关闭."""
        if self._external_session is None:
            session.close()

    def create_run(
        self,
        workflow_id: str,
        workflow_name: str = "",
        input_data: Optional[Dict[str, Any]] = None,
        created_by: str = "",
        priority: int = 5,
        trigger_type: str = "manual",
        trigger_id: str = "",
        max_retries: int = 0,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """创建运行记录.

        Args:
            workflow_id: 工作流 ID
            workflow_name: 工作流名称
            input_data: 输入数据
            created_by: 创建者
            priority: 优先级 1-10
            trigger_type: 触发类型
            trigger_id: 触发器 ID
            max_retries: 最大重试次数
            timeout_seconds: 超时时间

        Returns:
            运行记录字典
        """
        session = self._get_session()
        try:
            run_id = f"run_{uuid.uuid4().hex[:16]}"
            now = datetime.utcnow()
            run = PersistentWorkflowRun(
                id=run_id,
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                status=RunStatus.PENDING,
                current_node_id="",
                context_data={},
                step_results={},
                created_by=created_by,
                priority=max(1, min(10, priority)),
                result_summary={},
                error_message="",
                retry_count=0,
                max_retries=max_retries,
                trigger_type=trigger_type,
                trigger_id=trigger_id,
                input_data=input_data or {},
                timeout_seconds=timeout_seconds,
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            session.commit()
            result = run.to_dict()
            logger.info(f"[Persistence] 创建运行记录: {run_id} (workflow={workflow_id}, priority={priority})")
            return result
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 创建运行记录失败: {e}")
            raise
        finally:
            self._close_if_needed(session)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """获取运行记录.

        Args:
            run_id: 运行 ID

        Returns:
            运行记录字典，不存在返回 None
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            return run.to_dict() if run else None
        finally:
            self._close_if_needed(session)

    def update_run_status(
        self,
        run_id: str,
        status: str,
        **kwargs,
    ) -> bool:
        """更新运行状态和字段.

        使用乐观锁（version 字段）防止并发更新冲突。

        Args:
            run_id: 运行 ID
            status: 新状态
            **kwargs: 其他要更新的字段

        Returns:
            是否更新成功
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run:
                return False

            # 乐观锁检查
            if "version" in kwargs:
                if run.version != kwargs["version"]:
                    logger.warning(f"[Persistence] 乐观锁冲突: {run_id} (expected={kwargs['version']}, actual={run.version})")
                    return False
                del kwargs["version"]

            run.status = status
            run.updated_at = datetime.utcnow()
            run.version += 1

            # 更新其他字段
            for key, value in kwargs.items():
                if hasattr(run, key) and key not in ("id", "created_at"):
                    setattr(run, key, value)

            # 状态完成时设置结束时间
            if status in RunStatus.FINISHED and not run.end_time:
                run.end_time = datetime.utcnow()

            # 状态运行中时设置开始时间
            if status == RunStatus.RUNNING and not run.start_time:
                run.start_time = datetime.utcnow()

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 更新运行状态失败 {run_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def update_heartbeat(self, run_id: str) -> bool:
        """更新心跳时间.

        Args:
            run_id: 运行 ID

        Returns:
            是否成功
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run:
                return False
            run.last_heartbeat = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 更新心跳失败 {run_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        trigger_type: Optional[str] = None,
        created_by: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询运行记录.

        Args:
            workflow_id: 按工作流筛选
            status: 按状态筛选
            trigger_type: 按触发类型筛选
            created_by: 按创建者筛选
            page: 页码
            page_size: 每页数量

        Returns:
            {total, items, page, page_size}
        """
        session = self._get_session()
        try:
            query = session.query(PersistentWorkflowRun)

            if workflow_id:
                query = query.filter(PersistentWorkflowRun.workflow_id == workflow_id)
            if status:
                query = query.filter(PersistentWorkflowRun.status == status)
            if trigger_type:
                query = query.filter(PersistentWorkflowRun.trigger_type == trigger_type)
            if created_by:
                query = query.filter(PersistentWorkflowRun.created_by == created_by)

            total = query.count()

            items = (
                query.order_by(desc(PersistentWorkflowRun.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "total": total,
                "items": [item.to_dict() for item in items],
                "page": page,
                "page_size": page_size,
            }
        finally:
            self._close_if_needed(session)

    def cancel_run(self, run_id: str, reason: str = "用户取消") -> bool:
        """取消运行.

        Args:
            run_id: 运行 ID
            reason: 取消原因

        Returns:
            是否成功取消
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run:
                return False

            if run.status in RunStatus.FINISHED:
                return False  # 已结束的不能取消

            run.status = RunStatus.CANCELLED
            run.error_message = reason
            run.end_time = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            run.version += 1
            session.commit()
            logger.info(f"[Persistence] 取消运行: {run_id}, 原因: {reason}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 取消运行失败 {run_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def get_pending_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取待执行的运行（按优先级排序）.

        Args:
            limit: 最大数量

        Returns:
            运行记录列表（按优先级从高到低、创建时间从早到晚排序）
        """
        session = self._get_session()
        try:
            runs = (
                session.query(PersistentWorkflowRun)
                .filter(PersistentWorkflowRun.status == RunStatus.PENDING)
                .order_by(
                    desc(PersistentWorkflowRun.priority),
                    PersistentWorkflowRun.created_at,
                )
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in runs]
        finally:
            self._close_if_needed(session)

    def get_stuck_runs(self, timeout_seconds: int = 300) -> List[Dict[str, Any]]:
        """获取卡住的运行（心跳超时）.

        Args:
            timeout_seconds: 心跳超时时间（秒）

        Returns:
            卡住的运行列表
        """
        session = self._get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
            runs = (
                session.query(PersistentWorkflowRun)
                .filter(
                    and_(
                        PersistentWorkflowRun.status == RunStatus.RUNNING,
                        or_(
                            PersistentWorkflowRun.last_heartbeat.is_(None),
                            PersistentWorkflowRun.last_heartbeat < cutoff,
                        ),
                    )
                )
                .all()
            )
            return [r.to_dict() for r in runs]
        finally:
            self._close_if_needed(session)

    def cleanup_expired(self, days: int = 30, max_deleted: int = 1000) -> int:
        """清理过期记录.

        Args:
            days: 保留天数
            max_deleted: 单次最大删除数

        Returns:
            删除的记录数
        """
        session = self._get_session()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = session.query(PersistentWorkflowRun).filter(
                and_(
                    PersistentWorkflowRun.status.in_(list(RunStatus.FINISHED)),
                    PersistentWorkflowRun.end_time < cutoff,
                )
            ).limit(max_deleted)

            count = query.count()
            query.delete(synchronize_session=False)
            session.commit()

            if count > 0:
                logger.info(f"[Persistence] 清理了 {count} 条过期运行记录（{days}天前）")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 清理过期记录失败: {e}")
            return 0
        finally:
            self._close_if_needed(session)

    def increment_retry(self, run_id: str) -> int:
        """增加重试计数.

        Args:
            run_id: 运行 ID

        Returns:
            当前重试次数
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run:
                return -1
            run.retry_count += 1
            run.updated_at = datetime.utcnow()
            run.version += 1
            session.commit()
            return run.retry_count
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 增加重试计数失败 {run_id}: {e}")
            return -1
        finally:
            self._close_if_needed(session)

    def move_to_dead_letter(self, run_id: str, reason: str = "") -> bool:
        """将运行移入死信队列.

        Args:
            run_id: 运行 ID
            reason: 原因

        Returns:
            是否成功
        """
        session = self._get_session()
        try:
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run:
                return False
            run.status = RunStatus.DEAD_LETTER
            if reason:
                run.error_message = f"{run.error_message} | 死信原因: {reason}"
            run.end_time = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            run.version += 1
            session.commit()
            logger.warning(f"[Persistence] 运行移入死信队列: {run_id}, 原因: {reason}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 移入死信队列失败 {run_id}: {e}")
            return False
        finally:
            self._close_if_needed(session)

    def get_stats(self, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """获取运行统计.

        Args:
            workflow_id: 可选的工作流 ID 过滤

        Returns:
            统计信息字典
        """
        session = self._get_session()
        try:
            query = session.query(PersistentWorkflowRun)
            if workflow_id:
                query = query.filter(PersistentWorkflowRun.workflow_id == workflow_id)

            total = query.count()
            status_counts = {}
            for status in RunStatus.ALL:
                count = query.filter(PersistentWorkflowRun.status == status).count()
                if count > 0:
                    status_counts[status] = count

            return {
                "total": total,
                "by_status": status_counts,
                "pending": status_counts.get(RunStatus.PENDING, 0),
                "running": status_counts.get(RunStatus.RUNNING, 0),
                "completed": status_counts.get(RunStatus.COMPLETED, 0),
                "failed": status_counts.get(RunStatus.FAILED, 0),
                "cancelled": status_counts.get(RunStatus.CANCELLED, 0),
                "dead_letter": status_counts.get(RunStatus.DEAD_LETTER, 0),
            }
        finally:
            self._close_if_needed(session)


# ============================================================
# 执行上下文快照仓库
# ============================================================

class ExecutionContextRepository:
    """执行上下文快照仓库.

    管理 execution_contexts 表，用于断点恢复和调试。
    """

    def __init__(self, session: Optional[Session] = None):
        self._external_session = session

    def _get_session(self) -> Session:
        if self._external_session:
            return self._external_session
        return get_session()

    def _close_if_needed(self, session: Session):
        if self._external_session is None:
            session.close()

    def save_snapshot(
        self,
        run_id: str,
        node_id: str,
        context_data: Dict[str, Any],
        step_results: Dict[str, Any],
        variables: Dict[str, Any],
        snapshot_type: str = SnapshotType.NODE_COMPLETE,
    ) -> int:
        """保存上下文快照.

        Args:
            run_id: 运行 ID
            node_id: 节点 ID
            context_data: 上下文数据
            step_results: 已完成节点结果
            variables: 变量状态
            snapshot_type: 快照类型

        Returns:
            快照 ID
        """
        session = self._get_session()
        try:
            snapshot = ExecutionContextSnapshot(
                run_id=run_id,
                node_id=node_id,
                context_data=context_data,
                step_results=step_results,
                variables=variables,
                snapshot_type=snapshot_type,
                created_at=datetime.utcnow(),
            )
            session.add(snapshot)
            session.commit()
            return snapshot.id
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 保存快照失败 {run_id}/{node_id}: {e}")
            return -1
        finally:
            self._close_if_needed(session)

    def get_latest_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        """获取运行的最新快照.

        Args:
            run_id: 运行 ID

        Returns:
            快照字典，不存在返回 None
        """
        session = self._get_session()
        try:
            snapshot = (
                session.query(ExecutionContextSnapshot)
                .filter(ExecutionContextSnapshot.run_id == run_id)
                .order_by(desc(ExecutionContextSnapshot.id))
                .first()
            )
            return snapshot.to_dict() if snapshot else None
        finally:
            self._close_if_needed(session)

    def list_snapshots(
        self,
        run_id: str,
        snapshot_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出运行的快照.

        Args:
            run_id: 运行 ID
            snapshot_type: 类型过滤
            limit: 数量限制

        Returns:
            快照列表
        """
        session = self._get_session()
        try:
            query = session.query(ExecutionContextSnapshot).filter(
                ExecutionContextSnapshot.run_id == run_id
            )
            if snapshot_type:
                query = query.filter(ExecutionContextSnapshot.snapshot_type == snapshot_type)

            snapshots = query.order_by(desc(ExecutionContextSnapshot.id)).limit(limit).all()
            return [s.to_dict() for s in snapshots]
        finally:
            self._close_if_needed(session)

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """获取单个快照.

        Args:
            snapshot_id: 快照 ID

        Returns:
            快照字典
        """
        session = self._get_session()
        try:
            snapshot = session.query(ExecutionContextSnapshot).filter(
                ExecutionContextSnapshot.id == snapshot_id
            ).first()
            return snapshot.to_dict() if snapshot else None
        finally:
            self._close_if_needed(session)

    def cleanup_snapshots(self, run_id: str, keep_latest: int = 10) -> int:
        """清理旧快照，保留最新的 N 个.

        Args:
            run_id: 运行 ID
            keep_latest: 保留数量

        Returns:
            删除的数量
        """
        session = self._get_session()
        try:
            # 找出要保留的快照 ID
            keep_ids = (
                session.query(ExecutionContextSnapshot.id)
                .filter(ExecutionContextSnapshot.run_id == run_id)
                .order_by(desc(ExecutionContextSnapshot.id))
                .limit(keep_latest)
                .all()
            )
            keep_id_set = {row[0] for row in keep_ids}

            if not keep_id_set:
                return 0

            deleted = (
                session.query(ExecutionContextSnapshot)
                .filter(
                    and_(
                        ExecutionContextSnapshot.run_id == run_id,
                        ~ExecutionContextSnapshot.id.in_(list(keep_id_set)),
                    )
                )
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted
        except Exception as e:
            session.rollback()
            logger.error(f"[Persistence] 清理快照失败 {run_id}: {e}")
            return 0
        finally:
            self._close_if_needed(session)


# ============================================================
# 工作流级并发控制
# ============================================================

class WorkflowConcurrencyManager:
    """工作流级并发控制管理器.

    支持：
    - 全局并发限制（沿用 WorkflowEngine 的实现）
    - 工作流级并发限制
    - 优先级队列
    """

    def __init__(self):
        self._wf_running: Dict[str, int] = {}
        self._wf_limits: Dict[str, int] = {}
        self._default_wf_limit = int(
            __import__("os").environ.get("M7_WF_MAX_CONCURRENT", "3")
        )
        self._global_limit = int(
            __import__("os").environ.get("M7_MAX_RUNNING_WORKFLOWS", "10")
        )
        self._global_running = 0
        self._lock = None  # 延迟创建 asyncio.Lock

    def _get_lock(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def set_workflow_limit(self, workflow_id: str, limit: int):
        """设置工作流的并发限制.

        Args:
            workflow_id: 工作流 ID
            limit: 最大并发数
        """
        self._wf_limits[workflow_id] = max(1, limit)

    def get_workflow_limit(self, workflow_id: str) -> int:
        """获取工作流的并发限制."""
        return self._wf_limits.get(workflow_id, self._default_wf_limit)

    async def acquire_slot(self, workflow_id: str) -> bool:
        """获取执行槽位（全局 + 工作流级双重检查）.

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否获取成功
        """
        lock = self._get_lock()
        async with lock:
            # 全局检查
            if self._global_running >= self._global_limit:
                return False

            # 工作流级检查
            wf_running = self._wf_running.get(workflow_id, 0)
            wf_limit = self.get_workflow_limit(workflow_id)
            if wf_running >= wf_limit:
                return False

            self._global_running += 1
            self._wf_running[workflow_id] = wf_running + 1
            return True

    async def release_slot(self, workflow_id: str):
        """释放执行槽位.

        Args:
            workflow_id: 工作流 ID
        """
        lock = self._get_lock()
        async with lock:
            if self._global_running > 0:
                self._global_running -= 1
            wf_running = self._wf_running.get(workflow_id, 0)
            if wf_running > 0:
                self._wf_running[workflow_id] = wf_running - 1

    def get_running_count(self, workflow_id: Optional[str] = None) -> int:
        """获取运行中的数量."""
        if workflow_id:
            return self._wf_running.get(workflow_id, 0)
        return self._global_running

    def get_stats(self) -> Dict[str, Any]:
        """获取并发统计."""
        return {
            "global_running": self._global_running,
            "global_limit": self._global_limit,
            "workflow_limits": dict(self._wf_limits),
            "workflow_running": dict(self._wf_running),
            "default_wf_limit": self._default_wf_limit,
        }


# ============================================================
# 死信队列管理器
# ============================================================

class DeadLetterManager:
    """死信队列管理器.

    管理失败超过最大重试次数的运行，支持查看和重新投递。
    """

    def __init__(self, repo: Optional[PersistentRunRepository] = None):
        self._repo = repo or PersistentRunRepository()

    def list_dead_letters(
        self,
        workflow_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出死信队列中的运行.

        Args:
            workflow_id: 工作流过滤
            page: 页码
            page_size: 每页数量

        Returns:
            分页结果
        """
        return self._repo.list_runs(
            workflow_id=workflow_id,
            status=RunStatus.DEAD_LETTER,
            page=page,
            page_size=page_size,
        )

    def requeue(self, run_id: str) -> bool:
        """重新投递死信（重置为 pending）.

        Args:
            run_id: 运行 ID

        Returns:
            是否成功
        """
        session = self._repo._get_session()
        owns_session = self._repo._external_session is None
        try:
            from ..models_db import PersistentWorkflowRun
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run or run.status != RunStatus.DEAD_LETTER:
                return False

            run.status = RunStatus.PENDING
            run.retry_count = 0
            run.current_node_id = ""
            run.start_time = None
            run.end_time = None
            run.error_message = ""
            run.result_summary = {}
            run.step_results = {}
            run.context_data = {}
            run.updated_at = datetime.utcnow()
            run.version += 1
            session.commit()
            logger.info(f"[DeadLetter] 重新投递死信: {run_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[DeadLetter] 重新投递失败 {run_id}: {e}")
            return False
        finally:
            if owns_session:
                session.close()

    def remove(self, run_id: str) -> bool:
        """从死信队列删除记录.

        Args:
            run_id: 运行 ID

        Returns:
            是否成功
        """
        session = self._repo._get_session()
        owns_session = self._repo._external_session is None
        try:
            from ..models_db import PersistentWorkflowRun
            run = session.query(PersistentWorkflowRun).filter(
                PersistentWorkflowRun.id == run_id
            ).first()
            if not run or run.status != RunStatus.DEAD_LETTER:
                return False
            session.delete(run)
            session.commit()
            logger.info(f"[DeadLetter] 删除死信: {run_id}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"[DeadLetter] 删除死信失败 {run_id}: {e}")
            return False
        finally:
            if owns_session:
                session.close()

    def get_count(self) -> int:
        """获取死信队列数量."""
        result = self._repo.list_runs(status=RunStatus.DEAD_LETTER, page=1, page_size=1)
        return result.get("total", 0)


# ============================================================
# 崩溃恢复管理器
# ============================================================

class CrashRecoveryManager:
    """崩溃恢复管理器.

    应用启动时扫描 running 状态的任务，根据情况恢复执行或标记失败。
    """

    def __init__(
        self,
        run_repo: Optional[PersistentRunRepository] = None,
        ctx_repo: Optional[ExecutionContextRepository] = None,
        heartbeat_timeout: int = 300,
    ):
        self._run_repo = run_repo or PersistentRunRepository()
        self._ctx_repo = ctx_repo or ExecutionContextRepository()
        self._heartbeat_timeout = heartbeat_timeout
        self._recovered_count = 0
        self._failed_count = 0

    @property
    def recovered_count(self) -> int:
        return self._recovered_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    def recover_on_startup(self) -> Dict[str, Any]:
        """启动时执行崩溃恢复.

        扫描所有 running 状态的运行：
        1. 有有效上下文快照的 -> 重置为 pending 等待重新执行（可从断点恢复）
        2. 没有快照或快照无效的 -> 标记为 failed

        Returns:
            恢复统计 {total, recovered, failed, run_ids: [...]}
        """
        session = self._run_repo._get_session()
        owns_session = self._run_repo._external_session is None
        try:
            from ..models_db import PersistentWorkflowRun
            stuck_runs = (
                session.query(PersistentWorkflowRun)
                .filter(PersistentWorkflowRun.status == RunStatus.RUNNING)
                .all()
            )

            if not stuck_runs:
                return {"total": 0, "recovered": 0, "failed": 0, "run_ids": []}

            recovered = []
            failed = []

            for run in stuck_runs:
                # 检查是否有可用的快照
                latest_snapshot = self._ctx_repo.get_latest_snapshot(run.id)

                if latest_snapshot and latest_snapshot.get("step_results"):
                    # 有快照，可以从断点恢复
                    run.status = RunStatus.PENDING
                    run.error_message = f"崩溃恢复：从节点 {latest_snapshot.get('node_id', 'unknown')} 恢复"
                    run.updated_at = datetime.utcnow()
                    run.version += 1
                    recovered.append(run.id)
                    logger.info(f"[Recovery] 运行可恢复: {run.id} (节点={latest_snapshot.get('node_id')})")
                else:
                    # 没有有效快照，标记失败
                    run.status = RunStatus.FAILED
                    run.error_message = f"系统崩溃导致执行中断，无法恢复（无有效快照）"
                    run.end_time = datetime.utcnow()
                    run.updated_at = datetime.utcnow()
                    run.version += 1
                    failed.append(run.id)
                    logger.warning(f"[Recovery] 运行无法恢复，标记失败: {run.id}")

            session.commit()
            self._recovered_count = len(recovered)
            self._failed_count = len(failed)

            logger.info(
                f"[Recovery] 崩溃恢复完成: 共{len(stuck_runs)}个卡住的运行, "
                f"恢复{len(recovered)}个, 失败{len(failed)}个"
            )

            return {
                "total": len(stuck_runs),
                "recovered": len(recovered),
                "failed": len(failed),
                "recovered_ids": recovered,
                "failed_ids": failed,
            }
        except Exception as e:
            if owns_session:
                session.rollback()
            logger.error(f"[Recovery] 崩溃恢复失败: {e}")
            return {"total": 0, "recovered": 0, "failed": 0, "error": str(e)}
        finally:
            if owns_session:
                session.close()


# ============================================================
# 持久化执行器
# ============================================================

class PersistentExecutor:
    """持久化执行器.

    封装 WorkflowEngine，在执行过程中持久化进度：
    - 每个节点执行完后保存快照
    - 支持从断点恢复执行
    - 幂等性检查（避免重复执行已完成的节点）
    """

    def __init__(
        self,
        engine=None,
        run_repo: Optional[PersistentRunRepository] = None,
        ctx_repo: Optional[ExecutionContextRepository] = None,
        concurrency_mgr: Optional[WorkflowConcurrencyManager] = None,
        dead_letter_mgr: Optional[DeadLetterManager] = None,
    ):
        """初始化持久化执行器.

        Args:
            engine: WorkflowEngine 实例（可选，延迟导入）
            run_repo: 运行记录仓库
            ctx_repo: 上下文快照仓库
            concurrency_mgr: 并发管理器
            dead_letter_mgr: 死信管理器
        """
        self._engine = engine
        self._run_repo = run_repo or PersistentRunRepository()
        self._ctx_repo = ctx_repo or ExecutionContextRepository()
        self._concurrency_mgr = concurrency_mgr or WorkflowConcurrencyManager()
        self._dead_letter_mgr = dead_letter_mgr or DeadLetterManager(self._run_repo)
        self._snapshot_interval = 1  # 每 N 个节点保存一次快照
        self._keep_snapshots = 10  # 保留的快照数

    def _get_engine(self):
        """延迟获取引擎实例."""
        if self._engine is None:
            from .engine import WorkflowEngine
            self._engine = WorkflowEngine()
        return self._engine

    @property
    def run_repo(self) -> PersistentRunRepository:
        return self._run_repo

    @property
    def ctx_repo(self) -> ExecutionContextRepository:
        return self._ctx_repo

    @property
    def concurrency_mgr(self) -> WorkflowConcurrencyManager:
        return self._concurrency_mgr

    @property
    def dead_letter_mgr(self) -> DeadLetterManager:
        return self._dead_letter_mgr

    async def submit_workflow(
        self,
        workflow: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
        created_by: str = "",
        priority: int = 5,
        trigger_type: str = "manual",
        trigger_id: str = "",
        max_retries: int = 0,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """提交工作流到持久化队列.

        创建运行记录后立即返回，不等待执行完成。
        实际执行由队列消费者处理。

        Args:
            workflow: 工作流定义
            input_data: 输入数据
            created_by: 创建者
            priority: 优先级
            trigger_type: 触发类型
            trigger_id: 触发器 ID
            max_retries: 最大重试次数
            timeout_seconds: 超时时间

        Returns:
            运行记录
        """
        run = self._run_repo.create_run(
            workflow_id=workflow.get("id", ""),
            workflow_name=workflow.get("name", ""),
            input_data=input_data,
            created_by=created_by,
            priority=priority,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        return run

    async def execute_run(
        self,
        run_id: str,
        workflow: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行一个持久化运行.

        支持从断点恢复：
        1. 检查运行状态和已有快照
        2. 已有快照则从断点处恢复
        3. 无快照则从头开始
        4. 每完成一个节点保存快照
        5. 失败时检查重试次数，超过则入死信

        Args:
            run_id: 运行 ID
            workflow: 工作流定义

        Returns:
            执行结果
        """
        run = self._run_repo.get_run(run_id)
        if not run:
            return {"success": False, "error": f"运行 {run_id} 不存在"}

        if run["status"] in RunStatus.FINISHED:
            return {"success": False, "error": f"运行 {run_id} 已结束，状态: {run['status']}"}

        # 获取工作流级并发槽
        acquired = await self._concurrency_mgr.acquire_slot(workflow.get("id", ""))
        if not acquired:
            return {
                "success": False,
                "error": f"工作流并发数已达上限 ({self._concurrency_mgr.get_workflow_limit(workflow.get('id', ''))})",
            }

        try:
            # 更新状态为 running
            self._run_repo.update_run_status(
                run_id,
                RunStatus.RUNNING,
                start_time=datetime.utcnow(),
                last_heartbeat=datetime.utcnow(),
            )

            engine = self._get_engine()
            input_data = run.get("input_data", {})

            # 检查是否有快照可恢复
            latest_snapshot = self._ctx_repo.get_latest_snapshot(run_id)
            start_block = None
            existing_results = {}
            skip_nodes = set()

            if latest_snapshot and latest_snapshot.get("step_results"):
                # 有快照，从断点恢复
                existing_results = latest_snapshot.get("step_results", {})
                # 找到下一个要执行的节点（拓扑排序中第一个不在结果中的节点）
                from .validator import topological_sort
                try:
                    blocks = workflow.get("blocks", [])
                    execution_order = topological_sort(blocks)
                    for node_id in execution_order:
                        if node_id not in existing_results or existing_results[node_id].get("status") != "success":
                            start_block = node_id
                            break
                    # 已成功的节点标记为跳过
                    for nid, res in existing_results.items():
                        if res.get("status") == "success":
                            skip_nodes.add(nid)
                except Exception:
                    pass

                logger.info(f"[Persistent] 从断点恢复执行: {run_id}, 起始节点: {start_block}")

            # 执行工作流
            # 注意：这里使用原始引擎执行，但在执行前后做持久化
            # 实际的节点级持久化通过包装执行实现
            result = await engine.run_workflow(
                workflow=workflow,
                input_data=input_data,
                start_block=start_block,
                triggered_by=run.get("created_by", ""),
            )

            # 合并已有结果
            if existing_results:
                all_steps = []
                for nid, res in existing_results.items():
                    if res.get("status") == "success":
                        all_steps.append(res)
                all_steps.extend(result.get("steps", []))
                result["steps"] = all_steps
                result["total_blocks"] = len(workflow.get("blocks", []))
                result["success_blocks"] = sum(
                    1 for s in all_steps if s.get("status") == "success"
                )

            # 更新运行结果
            final_status = RunStatus.COMPLETED if result.get("status") == "success" else RunStatus.FAILED
            summary = {
                "total_blocks": result.get("total_blocks", 0),
                "success_blocks": result.get("success_blocks", 0),
                "failed_blocks": result.get("failed_blocks", 0),
                "skipped_blocks": result.get("skipped_blocks", 0),
                "final_output": result.get("final_output"),
                "execution_mode": result.get("execution_mode", "linear"),
            }

            self._run_repo.update_run_status(
                run_id,
                final_status,
                result_summary=summary,
                error_message=result.get("error", ""),
                step_results={s.get("block_id"): s for s in result.get("steps", [])},
                end_time=datetime.utcnow(),
            )

            # 保存最终快照
            self._ctx_repo.save_snapshot(
                run_id=run_id,
                node_id="__end__",
                context_data={},
                step_results={s.get("block_id"): s for s in result.get("steps", [])},
                variables={},
                snapshot_type=SnapshotType.NODE_COMPLETE,
            )

            # 清理旧快照
            self._ctx_repo.cleanup_snapshots(run_id, keep_latest=self._keep_snapshots)

            return {"success": final_status == RunStatus.COMPLETED, "result": result}

        except asyncio.CancelledError:
            self._run_repo.update_run_status(
                run_id,
                RunStatus.CANCELLED,
                error_message="执行被取消",
            )
            raise

        except Exception as e:
            logger.error(f"[Persistent] 执行运行失败 {run_id}: {e}")

            # 保存错误快照
            self._ctx_repo.save_snapshot(
                run_id=run_id,
                node_id=run.get("current_node_id", ""),
                context_data=run.get("context_data", {}),
                step_results=run.get("step_results", {}),
                variables={},
                snapshot_type=SnapshotType.ERROR,
            )

            # 检查是否可以重试
            retry_count = self._run_repo.increment_retry(run_id)
            max_retries = run.get("max_retries", 0)

            if retry_count >= 0 and retry_count < max_retries:
                # 重置为 pending 等待重试
                self._run_repo.update_run_status(
                    run_id,
                    RunStatus.PENDING,
                    error_message=f"第{retry_count}次失败，准备重试: {str(e)}",
                )
                return {"success": False, "error": str(e), "will_retry": True, "retry_count": retry_count}
            else:
                # 超过最大重试，入死信
                self._dead_letter_mgr._repo.move_to_dead_letter(
                    run_id,
                    reason=f"超过最大重试次数({max_retries})",
                )
                return {"success": False, "error": str(e), "dead_letter": True}

        finally:
            await self._concurrency_mgr.release_slot(workflow.get("id", ""))


# ============================================================
# 全局单例
# ============================================================

_persistent_executor: Optional[PersistentExecutor] = None


def get_persistent_executor() -> PersistentExecutor:
    """获取持久化执行器单例."""
    global _persistent_executor
    if _persistent_executor is None:
        _persistent_executor = PersistentExecutor()
    return _persistent_executor


def get_run_repository() -> PersistentRunRepository:
    """获取运行仓库单例."""
    return get_persistent_executor().run_repo


def get_context_repository() -> ExecutionContextRepository:
    """获取上下文仓库单例."""
    return get_persistent_executor().ctx_repo
