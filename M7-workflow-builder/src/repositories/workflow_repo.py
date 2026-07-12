"""M7 工作流定义数据仓库.

P2-25: 封装工作流定义的数据库 CRUD 和查询。
迁移过渡期：优先读 DB，DB 为空时自动从 JSON 迁移。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_

from ..models_db import WorkflowDefinition


def _get_workflows_json_path(data_dir: Optional[str] = None) -> Path:
    """获取 m7_workflows.json 文件路径."""
    base = Path(data_dir) if data_dir else Path.home() / ".yunxi"
    return base / "m7_workflows.json"


def _load_workflows_json(data_dir: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """从 JSON 加载工作流定义."""
    p = _get_workflows_json_path(data_dir)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def migrate_workflows_from_json(db: Session, data_dir: Optional[str] = None) -> int:
    """将 m7_workflows.json 迁移到数据库.

    幂等操作：已存在的 ID 不覆盖。

    Args:
        db: 数据库 session
        data_dir: 数据目录

    Returns:
        迁移的工作流数量
    """
    workflows_json = _load_workflows_json(data_dir)
    if not workflows_json:
        return 0

    migrated = 0
    for wf_id, wf_data in workflows_json.items():
        existing = db.query(WorkflowDefinition).filter(WorkflowDefinition.id == wf_id).first()
        if existing:
            continue

        created_at = _parse_time(wf_data.get("created_at"))
        updated_at = _parse_time(wf_data.get("updated_at")) or created_at

        db_wf = WorkflowDefinition(
            id=wf_id,
            name=wf_data.get("name", ""),
            description=wf_data.get("description", ""),
            category=wf_data.get("category", ""),
            status=wf_data.get("status", "draft"),
            blocks=wf_data.get("blocks", []),
            connections=wf_data.get("connections", []),
            variables=wf_data.get("variables", []),
            trigger=wf_data.get("trigger", {}),
            created_at=created_at,
            updated_at=updated_at,
            run_count=wf_data.get("run_count", 0),
            created_by=wf_data.get("created_by", ""),
            tags=wf_data.get("tags", []),
        )
        db.add(db_wf)
        migrated += 1

    if migrated > 0:
        db.commit()
        print(f"[Migration] M7 工作流定义迁移完成: {migrated} 条")

    return migrated


def _parse_time(t: Optional[str]) -> Optional[datetime]:
    """解析时间字符串."""
    if not t:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


class WorkflowRepository:
    """工作流定义数据仓库."""

    def __init__(self, db: Session, data_dir: Optional[str] = None):
        self.db = db
        self._data_dir = data_dir
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移."""
        try:
            count = self.db.query(WorkflowDefinition).count()
            if count == 0:
                migrate_workflows_from_json(self.db, self._data_dir)
        except Exception as e:
            print(f"[Migration] M7 工作流迁移跳过: {e}")

    # ===== CRUD =====

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """按 ID 获取工作流."""
        return self.db.query(WorkflowDefinition).filter(WorkflowDefinition.id == workflow_id).first()

    def list(
        self,
        keyword: str = "",
        category: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[WorkflowDefinition], int]:
        """列出工作流（支持筛选分页）."""
        query = self.db.query(WorkflowDefinition)

        if keyword:
            query = query.filter(
                or_(
                    WorkflowDefinition.name.contains(keyword),
                    WorkflowDefinition.description.contains(keyword),
                )
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

    def create(self, workflow_id: str, data: Dict[str, Any]) -> WorkflowDefinition:
        """创建工作流."""
        now = datetime.utcnow()
        wf = WorkflowDefinition(
            id=workflow_id,
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", ""),
            status=data.get("status", "draft"),
            blocks=data.get("blocks", []),
            connections=data.get("connections", []),
            variables=data.get("variables", []),
            trigger=data.get("trigger", {}),
            created_at=now,
            updated_at=now,
            run_count=data.get("run_count", 0),
            created_by=data.get("created_by", ""),
            tags=data.get("tags", []),
        )
        self.db.add(wf)
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def update(self, workflow_id: str, data: Dict[str, Any]) -> Optional[WorkflowDefinition]:
        """更新工作流."""
        wf = self.get(workflow_id)
        if not wf:
            return None

        updateable_fields = [
            "name", "description", "category", "status",
            "blocks", "connections", "variables", "trigger", "tags",
        ]
        for field in updateable_fields:
            if field in data and data[field] is not None:
                setattr(wf, field, data[field])

        wf.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(wf)
        return wf

    def delete(self, workflow_id: str) -> bool:
        """删除工作流."""
        wf = self.get(workflow_id)
        if not wf:
            return False
        self.db.delete(wf)
        self.db.commit()
        return True

    def increment_run_count(self, workflow_id: str) -> bool:
        """增加运行次数."""
        wf = self.get(workflow_id)
        if not wf:
            return False
        wf.run_count = (wf.run_count or 0) + 1
        wf.updated_at = datetime.utcnow()
        self.db.commit()
        return True

    def count(self) -> int:
        """工作流总数."""
        return self.db.query(WorkflowDefinition).count()

    def get_all_dict(self) -> Dict[str, Dict[str, Any]]:
        """获取所有工作流为 {id: dict} 格式（兼容旧接口）."""
        all_wf = self.db.query(WorkflowDefinition).all()
        return {wf.id: wf.to_dict() for wf in all_wf}

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息."""
        from sqlalchemy import func
        total = self.count()
        total_run_count = self.db.query(func.sum(WorkflowDefinition.run_count)).scalar() or 0

        # 状态统计
        status_result = (
            self.db.query(WorkflowDefinition.status, func.count(WorkflowDefinition.id))
            .group_by(WorkflowDefinition.status)
            .all()
        )
        status_counts = {s: c for s, c in status_result}

        # 分类统计
        cat_result = (
            self.db.query(WorkflowDefinition.category, func.count(WorkflowDefinition.id))
            .group_by(WorkflowDefinition.category)
            .all()
        )
        category_counts = {c or "未分类": n for c, n in cat_result}

        return {
            "total_workflows": total,
            "total_run_count": total_run_count,
            "workflow_status": status_counts,
            "workflow_categories": category_counts,
        }
