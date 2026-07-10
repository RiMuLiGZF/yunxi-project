"""
P2-24: 工作流数据仓库

存储工作流定义和运行历史。
迁移过渡期：优先读 DB，DB 为空时自动从 JSON 迁移。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import WorkflowDefinition, WorkflowRun


def _get_workflows_json_path() -> Path:
    """获取 workflows.json 文件路径"""
    return Path.home() / ".yunxi" / "workflows.json"


def _get_runs_json_path() -> Path:
    """获取 workflow_runs.json 文件路径"""
    return Path.home() / ".yunxi" / "workflow_runs.json"


def _load_workflows_json() -> Dict[str, Dict[str, Any]]:
    """从 JSON 加载工作流定义"""
    p = _get_workflows_json_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _load_runs_json() -> Dict[str, List[Dict[str, Any]]]:
    """从 JSON 加载运行历史"""
    p = _get_runs_json_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def migrate_workflows_from_json(db: Session) -> Tuple[int, int]:
    """将工作流数据从 JSON 迁移到数据库.

    幂等操作：已存在的 ID 不覆盖。

    Returns:
        (迁移的工作流数, 迁移的运行记录数)
    """
    # 迁移工作流定义
    workflows_json = _load_workflows_json()
    migrated_wf = 0
    for wf_id, wf_data in workflows_json.items():
        existing = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == wf_id).first()
        if not existing:
            created_at = None
            if wf_data.get("created_at"):
                try:
                    created_at = datetime.strptime(wf_data["created_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    created_at = datetime.utcnow()

            updated_at = None
            if wf_data.get("updated_at"):
                try:
                    updated_at = datetime.strptime(wf_data["updated_at"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    updated_at = created_at

            db_wf = WorkflowDefinition(
                id=wf_id,
                name=wf_data.get("name", ""),
                description=wf_data.get("description", ""),
                category=wf_data.get("category", ""),
                icon=wf_data.get("icon", ""),
                blocks=wf_data.get("blocks", []),
                status=wf_data.get("status", "draft"),
                created_at=created_at,
                updated_at=updated_at,
            )
            db.add(db_wf)
            migrated_wf += 1

    if migrated_wf > 0:
        db.commit()

    # 迁移运行历史
    runs_json = _load_runs_json()
    migrated_runs = 0
    for wf_id, runs in runs_json.items():
        for run_data in runs:
            run_id = run_data.get("id") or str(uuid.uuid4())
            existing = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
            if not existing:
                started_at = None
                if run_data.get("started_at"):
                    try:
                        started_at = datetime.strptime(run_data["started_at"], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass

                finished_at = None
                if run_data.get("finished_at"):
                    try:
                        finished_at = datetime.strptime(run_data["finished_at"], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass

                db_run = WorkflowRun(
                    id=run_id,
                    workflow_id=wf_id,
                    workflow_name=run_data.get("workflow_name", ""),
                    status=run_data.get("status", "pending"),
                    inputs=run_data.get("inputs", {}),
                    outputs=run_data.get("outputs", {}),
                    error_message=run_data.get("error_message", ""),
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=run_data.get("duration_ms", 0),
                )
                db.add(db_run)
                migrated_runs += 1

    if migrated_runs > 0:
        db.commit()

    if migrated_wf > 0 or migrated_runs > 0:
        print(f"[Migration] 工作流迁移完成: {migrated_wf} 个定义, {migrated_runs} 条运行记录")

    return migrated_wf, migrated_runs


class WorkflowRepository:
    """工作流数据仓库"""

    def __init__(self, db: Session):
        self.db = db
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移"""
        try:
            count = self.db.query(WorkflowDefinition).count()
            if count == 0:
                migrate_workflows_from_json(self.db)
        except Exception as e:
            print(f"[Migration] 工作流迁移跳过: {e}")

    # ===== 工作流定义 =====

    def list_workflows(self, keyword: str = "", category: str = "",
                       status: str = "", page: int = 1, page_size: int = 20
                       ) -> Tuple[List[WorkflowDefinition], int]:
        """列出工作流（支持筛选分页）"""
        query = self.db.query(WorkflowDefinition)
        if keyword:
            query = query.filter(
                (WorkflowDefinition.name.contains(keyword)) |
                (WorkflowDefinition.description.contains(keyword))
            )
        if category:
            query = query.filter(WorkflowDefinition.category == category)
        if status:
            query = query.filter(WorkflowDefinition.status == status)

        total = query.count()
        items = (
            query.order_by(desc(WorkflowDefinition.updated_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取单个工作流"""
        return self.db.query(WorkflowDefinition).filter(WorkflowDefinition.id == workflow_id).first()

    def create_workflow(self, name: str, description: str = "", category: str = "",
                        icon: str = "", blocks: Optional[list] = None,
                        status: str = "draft") -> WorkflowDefinition:
        """创建工作流"""
        wf_id = f"wf_{uuid.uuid4().hex[:12]}"
        now = datetime.utcnow()
        wf = WorkflowDefinition(
            id=wf_id,
            name=name,
            description=description,
            category=category,
            icon=icon,
            blocks=blocks or [],
            status=status,
            created_at=now,
            updated_at=now,
        )
        self.db.add(wf)
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def update_workflow(self, workflow_id: str, **kwargs) -> Optional[WorkflowDefinition]:
        """更新工作流"""
        wf = self.get_workflow(workflow_id)
        if not wf:
            return None
        for key, value in kwargs.items():
            if hasattr(wf, key) and value is not None:
                setattr(wf, key, value)
        wf.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流"""
        wf = self.get_workflow(workflow_id)
        if not wf:
            return False
        # 同时删除运行历史
        self.db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).delete()
        self.db.delete(wf)
        self.db.commit()
        return True

    def count_workflows(self) -> int:
        """工作流总数"""
        return self.db.query(WorkflowDefinition).count()

    # ===== 运行历史 =====

    def add_run(self, workflow_id: str, workflow_name: str = "",
                status: str = "running", inputs: Optional[dict] = None) -> WorkflowRun:
        """添加运行记录"""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = WorkflowRun(
            id=run_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=status,
            inputs=inputs or {},
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update_run(self, run_id: str, status: str = "", outputs: Optional[dict] = None,
                   error_message: str = "", duration_ms: int = 0) -> Optional[WorkflowRun]:
        """更新运行状态"""
        run = self.db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not run:
            return None
        if status:
            run.status = status
        if outputs is not None:
            run.outputs = outputs
        if error_message:
            run.error_message = error_message
        if duration_ms > 0:
            run.duration_ms = duration_ms
        if status in ("success", "failed"):
            run.finished_at = datetime.utcnow()
            if run.started_at and not run.duration_ms:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
        self.db.commit()
        self.db.refresh(run)
        return run

    def list_runs(self, workflow_id: str = "", status: str = "",
                  page: int = 1, page_size: int = 20) -> Tuple[List[WorkflowRun], int]:
        """列出运行历史"""
        query = self.db.query(WorkflowRun)
        if workflow_id:
            query = query.filter(WorkflowRun.workflow_id == workflow_id)
        if status:
            query = query.filter(WorkflowRun.status == status)

        total = query.count()
        items = (
            query.order_by(desc(WorkflowRun.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total
