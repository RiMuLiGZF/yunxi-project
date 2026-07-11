"""M7 运行记录数据仓库.

P2-26: 封装工作流运行记录的数据库 CRUD 和查询。
迁移过渡期：优先读 DB，DB 为空时自动从 JSON 迁移。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models_db import WorkflowRunRecord
from .workflow_repo import _parse_time


def _get_runs_json_path(data_dir: Optional[str] = None) -> Path:
    """获取 m7_runs.json 文件路径."""
    base = Path(data_dir) if data_dir else Path.home() / ".yunxi"
    return base / "m7_runs.json"


def _load_runs_json(data_dir: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """从 JSON 加载运行记录."""
    p = _get_runs_json_path(data_dir)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def migrate_runs_from_json(db: Session, data_dir: Optional[str] = None) -> int:
    """将 m7_runs.json 迁移到数据库.

    幂等操作：已存在的 ID 不覆盖。

    Args:
        db: 数据库 session
        data_dir: 数据目录

    Returns:
        迁移的运行记录数量
    """
    runs_json = _load_runs_json(data_dir)
    if not runs_json:
        return 0

    migrated = 0
    for wf_id, run_list in runs_json.items():
        for run_data in run_list:
            run_id = run_data.get("run_id")
            if not run_id:
                continue

            existing = db.query(WorkflowRunRecord).filter(WorkflowRunRecord.id == run_id).first()
            if existing:
                continue

            started_at = _parse_time(run_data.get("started_at"))
            finished_at = _parse_time(run_data.get("finished_at"))

            db_run = WorkflowRunRecord(
                id=run_id,
                workflow_id=wf_id,
                workflow_name=run_data.get("workflow_name", ""),
                status=run_data.get("status", "pending"),
                steps=run_data.get("steps", []),
                inputs=run_data.get("inputs", {}),
                outputs=run_data.get("outputs", {}),
                error=run_data.get("error", ""),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=run_data.get("duration_ms", 0),
                triggered_by=run_data.get("triggered_by", "manual"),
            )
            db.add(db_run)
            migrated += 1

    if migrated > 0:
        db.commit()
        print(f"[Migration] M7 运行记录迁移完成: {migrated} 条")

    return migrated


class RunRepository:
    """运行记录数据仓库."""

    def __init__(self, db: Session, data_dir: Optional[str] = None):
        self.db = db
        self._data_dir = data_dir
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移."""
        try:
            count = self.db.query(WorkflowRunRecord).count()
            if count == 0:
                migrate_runs_from_json(self.db, self._data_dir)
        except Exception as e:
            print(f"[Migration] M7 运行记录迁移跳过: {e}")

    # ===== CRUD =====

    def get(self, run_id: str) -> Optional[WorkflowRunRecord]:
        """按 ID 获取运行记录."""
        return self.db.query(WorkflowRunRecord).filter(WorkflowRunRecord.id == run_id).first()

    def list_by_workflow(
        self, workflow_id: str, limit: int = 50, offset: int = 0
    ) -> List[WorkflowRunRecord]:
        """获取指定工作流的运行历史（按时间倒序）."""
        return (
            self.db.query(WorkflowRunRecord)
            .filter(WorkflowRunRecord.workflow_id == workflow_id)
            .order_by(desc(WorkflowRunRecord.started_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def list(
        self,
        workflow_id: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[WorkflowRunRecord], int]:
        """列出运行记录（支持筛选分页）."""
        query = self.db.query(WorkflowRunRecord)

        if workflow_id:
            query = query.filter(WorkflowRunRecord.workflow_id == workflow_id)
        if status:
            query = query.filter(WorkflowRunRecord.status == status)

        total = query.count()
        items = (
            query.order_by(desc(WorkflowRunRecord.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def add(self, workflow_id: str, run_data: Dict[str, Any]) -> WorkflowRunRecord:
        """添加运行记录."""
        run_id = run_data.get("run_id")
        if not run_id:
            import uuid
            run_id = f"run_{uuid.uuid4().hex[:12]}"

        started_at = _parse_time(run_data.get("started_at")) or datetime.utcnow()
        finished_at = _parse_time(run_data.get("finished_at"))

        run = WorkflowRunRecord(
            id=run_id,
            workflow_id=workflow_id,
            workflow_name=run_data.get("workflow_name", ""),
            status=run_data.get("status", "pending"),
            steps=run_data.get("steps", []),
            inputs=run_data.get("inputs", {}),
            outputs=run_data.get("outputs", {}),
            error=run_data.get("error", ""),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=run_data.get("duration_ms", 0),
            triggered_by=run_data.get("triggered_by", "manual"),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update(self, run_id: str, updates: Dict[str, Any]) -> bool:
        """更新运行记录."""
        run = self.get(run_id)
        if not run:
            return False

        for key, value in updates.items():
            attr = key if key != "run_id" else "id"
            if hasattr(run, attr) and value is not None:
                setattr(run, attr, value)

        # 如果状态变为终态，设置结束时间
        if updates.get("status") in ("success", "failed", "cancelled") and not run.finished_at:
            run.finished_at = datetime.utcnow()
            if run.started_at and not run.duration_ms:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

        self.db.commit()
        return True

    def delete_by_workflow(self, workflow_id: str) -> int:
        """删除指定工作流的所有运行记录，返回删除数量."""
        count = (
            self.db.query(WorkflowRunRecord)
            .filter(WorkflowRunRecord.workflow_id == workflow_id)
            .delete()
        )
        self.db.commit()
        return count

    def count(self) -> int:
        """运行记录总数."""
        return self.db.query(WorkflowRunRecord).count()

    def count_by_workflow(self, workflow_id: str) -> int:
        """指定工作流的运行记录数."""
        return (
            self.db.query(WorkflowRunRecord)
            .filter(WorkflowRunRecord.workflow_id == workflow_id)
            .count()
        )
