"""
P2-22: 审计日志数据仓库

封装审计日志的数据库 CRUD 和查询。
迁移过渡期：优先读 DB，DB 为空时自动从 JSON 迁移。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from ..models import AuditLog


def _get_audit_json_path() -> Path:
    """获取 audit_logs.json 文件路径"""
    return Path.home() / ".yunxi" / "audit_logs.json"


def _load_audit_json() -> List[Dict[str, Any]]:
    """从 JSON 文件加载审计日志"""
    json_path = _get_audit_json_path()
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def migrate_audit_from_json(db: Session, batch_size: int = 500) -> int:
    """将 audit_logs.json 迁移到数据库.

    幂等操作：表中有数据则跳过（通过检查最大 ID 实现增量迁移）。
    大批量分批插入，避免内存问题。

    Args:
        db: 数据库 session
        batch_size: 每批插入数量

    Returns:
        迁移的日志数量
    """
    logs_json = _load_audit_json()
    if not logs_json:
        return 0

    # 获取数据库中已有的最大 ID
    from sqlalchemy import func
    max_db_id = db.query(func.max(AuditLog.id)).scalar() or 0

    # 只迁移 ID 大于 max_db_id 的日志
    new_logs = [log for log in logs_json if log.get("id", 0) > max_db_id]
    if not new_logs:
        return 0

    migrated = 0
    batch = []

    for log in new_logs:
        # 解析时间
        created_at = None
        if log.get("created_at"):
            try:
                created_at = datetime.strptime(log["created_at"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = datetime.utcnow()

        details = log.get("details", {})
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {"raw": details}

        batch.append(AuditLog(
            id=log.get("id"),
            user_id=log.get("user_id") or 0,
            username=log.get("username", ""),
            action=log.get("action", ""),
            module=log.get("module", "system"),
            result=log.get("result", "success"),
            ip=log.get("ip", ""),
            user_agent=log.get("user_agent", "")[:500],
            details=details,
            created_at=created_at,
        ))

        if len(batch) >= batch_size:
            db.add_all(batch)
            db.commit()
            migrated += len(batch)
            batch = []

    if batch:
        db.add_all(batch)
        db.commit()
        migrated += len(batch)

    print(f"[Migration] 审计日志迁移完成: 新增 {migrated} 条 (总计 {max_db_id + migrated} 条)")
    return migrated


class AuditRepository:
    """审计日志数据仓库"""

    def __init__(self, db: Session):
        self.db = db
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移（增量）"""
        try:
            migrate_audit_from_json(self.db)
        except Exception as e:
            print(f"[Migration] 审计日志迁移跳过: {e}")

    def add(self, user_id: Optional[int] = None, username: str = "",
            action: str = "", module: str = "system", result: str = "success",
            ip: str = "", user_agent: str = "",
            details: Optional[Dict[str, Any]] = None) -> AuditLog:
        """添加一条审计日志"""
        log = AuditLog(
            user_id=user_id or 0,
            username=username,
            action=action,
            module=module,
            result=result,
            ip=ip,
            user_agent=user_agent[:500] if user_agent else "",
            details=details or {},
            created_at=datetime.utcnow(),
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def query(
        self,
        username: Optional[str] = None,
        action: Optional[str] = None,
        module: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AuditLog], int]:
        """查询审计日志（支持筛选和分页）

        Returns:
            (日志列表, 总数)
        """
        query = self.db.query(AuditLog)

        if username:
            query = query.filter(AuditLog.username.contains(username))
        if action:
            query = query.filter(AuditLog.action == action)
        if module:
            query = query.filter(AuditLog.module == module)
        if result:
            query = query.filter(AuditLog.result == result)
        if start_time:
            try:
                st = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
                query = query.filter(AuditLog.created_at >= st)
            except ValueError:
                pass
        if end_time:
            try:
                et = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
                query = query.filter(AuditLog.created_at <= et)
            except ValueError:
                pass

        total = query.count()
        logs = (
            query.order_by(desc(AuditLog.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return logs, total

    def count(self) -> int:
        """总日志数"""
        return self.db.query(AuditLog).count()

    def get_by_id(self, log_id: int) -> Optional[AuditLog]:
        """按 ID 获取日志"""
        return self.db.query(AuditLog).filter(AuditLog.id == log_id).first()

    def get_user_actions(self, username: str, limit: int = 20) -> List[AuditLog]:
        """获取指定用户的最近操作"""
        return (
            self.db.query(AuditLog)
            .filter(AuditLog.username == username)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
            .all()
        )

    def get_action_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取操作统计"""
        from sqlalchemy import func
        from datetime import timedelta
        start = datetime.utcnow() - timedelta(days=days)
        result = (
            self.db.query(
                AuditLog.action,
                func.count(AuditLog.id).label("count"),
            )
            .filter(AuditLog.created_at >= start)
            .group_by(AuditLog.action)
            .all()
        )
        return {
            "period_days": days,
            "total": sum(r[1] for r in result),
            "by_action": {r[0]: r[1] for r in result},
        }
