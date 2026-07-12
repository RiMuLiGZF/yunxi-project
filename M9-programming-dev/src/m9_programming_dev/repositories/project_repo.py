"""M9 项目索引数据仓库.

P2-27: 项目索引的 CRUD 和查询。
数据库作为索引层，文件系统是真相源。
"""

from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_

from ..models_db import ProjectIndex


class ProjectRepository:
    """项目索引数据仓库."""

    def __init__(self, db: Session, projects_dir: str):
        self.db = db
        self._projects_dir = projects_dir
        self._sync_from_filesystem()

    def _sync_from_filesystem(self) -> int:
        """从文件系统同步项目索引到数据库.

        启动时调用一次，确保 DB 索引与文件系统一致。
        幂等操作：已存在的项目跳过。
        """
        if not os.path.exists(self._projects_dir):
            return 0

        synced = 0
        for pid in os.listdir(self._projects_dir):
            meta_path = os.path.join(self._projects_dir, pid, ".project.json")
            if not os.path.exists(meta_path):
                continue

            # 检查是否已在 DB 中
            existing = self.db.query(ProjectIndex).filter(ProjectIndex.id == pid).first()
            if existing:
                continue

            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue

            created_at = self._parse_time(data.get("created_at"))
            updated_at = self._parse_time(data.get("updated_at"))

            # 统计文件数和大小
            proj_path = os.path.join(self._projects_dir, pid)
            file_count, total_size = self._scan_project_size(proj_path)

            idx = ProjectIndex(
                id=pid,
                name=data.get("name", ""),
                path=proj_path,
                description=data.get("description", ""),
                language=data.get("language", ""),
                created_at=created_at,
                updated_at=updated_at,
                file_count=file_count,
                size_bytes=total_size,
            )
            self.db.add(idx)
            synced += 1

        if synced > 0:
            self.db.commit()
            print(f"[Sync] 项目索引同步完成: 新增 {synced} 个项目")

        return synced

    @staticmethod
    def _parse_time(t: Optional[str]) -> Optional[datetime]:
        if not t:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(t, fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _scan_project_size(proj_path: str) -> tuple:
        """扫描项目文件数和总大小（跳过隐藏文件）."""
        count = 0
        total = 0
        try:
            for root, dirs, files in os.walk(proj_path):
                # 跳过隐藏目录
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if f.startswith("."):
                        continue
                    fp = os.path.join(root, f)
                    try:
                        total += os.path.getsize(fp)
                        count += 1
                    except OSError:
                        pass
        except Exception:
            pass
        return count, total

    # ===== CRUD =====

    def get(self, project_id: str) -> Optional[ProjectIndex]:
        """按 ID 获取项目索引."""
        return self.db.query(ProjectIndex).filter(ProjectIndex.id == project_id).first()

    def list(
        self,
        keyword: str = "",
        language: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ProjectIndex], int]:
        """列出项目（支持筛选分页）."""
        query = self.db.query(ProjectIndex)

        if keyword:
            query = query.filter(
                or_(
                    ProjectIndex.name.contains(keyword),
                    ProjectIndex.description.contains(keyword),
                )
            )
        if language:
            query = query.filter(ProjectIndex.language == language)

        total = query.count()
        items = (
            query.order_by(desc(ProjectIndex.updated_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def upsert(self, project_id: str, data: dict) -> ProjectIndex:
        """插入或更新项目索引."""
        idx = self.get(project_id)
        now = datetime.utcnow()

        if idx:
            idx.name = data.get("name", idx.name)
            idx.description = data.get("description", idx.description)
            idx.language = data.get("language", idx.language)
            idx.updated_at = now
            if "path" in data:
                idx.path = data["path"]
        else:
            created_at = self._parse_time(data.get("created_at")) or now
            idx = ProjectIndex(
                id=project_id,
                name=data.get("name", ""),
                path=data.get("path", ""),
                description=data.get("description", ""),
                language=data.get("language", ""),
                created_at=created_at,
                updated_at=now,
            )
            self.db.add(idx)

        self.db.commit()
        self.db.refresh(idx)
        return idx

    def delete(self, project_id: str) -> bool:
        """删除项目索引."""
        idx = self.get(project_id)
        if not idx:
            return False
        self.db.delete(idx)
        self.db.commit()
        return True

    def count(self) -> int:
        """项目总数."""
        return self.db.query(ProjectIndex).count()

    def refresh_stats(self, project_id: str) -> Optional[ProjectIndex]:
        """刷新项目统计信息（文件数、大小）."""
        idx = self.get(project_id)
        if not idx:
            return None

        file_count, total_size = self._scan_project_size(idx.path)
        idx.file_count = file_count
        idx.size_bytes = total_size
        idx.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(idx)
        return idx
