'''
审计日志 Repository

封装审计日志的数据库操作。
'''

from __future__ import annotations

import json
import time
from typing import Optional

from ..database import get_session
from ..db_models import AuditLogDB


class AuditRepository:
    '''审计日志数据访问层.'''

    @staticmethod
    def add_log(
        log_id: str,
        level: str,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: Optional[dict] = None,
    ) -> None:
        '''新增一条审计日志.'''
        with get_session() as db:
            log = AuditLogDB(
                log_id=log_id,
                timestamp=time.time(),
                level=level,
                log_type=log_type,
                trigger_condition=trigger_condition,
                action=action,
                result=result,
                details_json=json.dumps(details or {}, ensure_ascii=False),
            )
            db.add(log)
            db.commit()

    @staticmethod
    def get_logs(
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> list[dict]:
        '''查询审计日志列表（按时间倒序）.'''
        with get_session() as db:
            query = db.query(AuditLogDB)

            if level:
                query = query.filter(AuditLogDB.level == level)
            if log_type:
                query = query.filter(AuditLogDB.log_type == log_type)
            if start_time:
                query = query.filter(AuditLogDB.timestamp >= start_time)
            if end_time:
                query = query.filter(AuditLogDB.timestamp <= end_time)

            logs = query.order_by(AuditLogDB.timestamp.desc()) \
                        .offset(offset).limit(limit).all()
            return [log.to_dict() for log in logs]

    @staticmethod
    def count_logs(
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        '''统计审计日志数量.'''
        with get_session() as db:
            query = db.query(AuditLogDB)

            if level:
                query = query.filter(AuditLogDB.level == level)
            if log_type:
                query = query.filter(AuditLogDB.log_type == log_type)
            if start_time:
                query = query.filter(AuditLogDB.timestamp >= start_time)
            if end_time:
                query = query.filter(AuditLogDB.timestamp <= end_time)

            return query.count()

    @staticmethod
    def get_stats() -> dict:
        '''获取审计日志统计信息.'''
        with get_session() as db:
            total = db.query(AuditLogDB).count()
            info_count = db.query(AuditLogDB).filter(AuditLogDB.level == 'info').count()
            warning_count = db.query(AuditLogDB).filter(AuditLogDB.level == 'warning').count()
            critical_count = db.query(AuditLogDB).filter(AuditLogDB.level == 'critical').count()

            # 按类型统计（取前20种）
            type_stats = {}
            for log in db.query(AuditLogDB).limit(1000).all():
                type_stats[log.log_type] = type_stats.get(log.log_type, 0) + 1

            return {
                'total': total,
                'by_level': {
                    'info': info_count,
                    'warning': warning_count,
                    'critical': critical_count,
                },
                'by_type': type_stats,
                'storage': 'database',
            }

    @staticmethod
    def clear_logs() -> int:
        '''清空所有审计日志.

        Returns:
            删除的日志数量
        '''
        with get_session() as db:
            count = db.query(AuditLogDB).count()
            db.query(AuditLogDB).delete()
            db.commit()
            return count

    @staticmethod
    def cleanup_old_logs(retention_days: int = 90) -> int:
        '''清理过期日志.

        Args:
            retention_days: 保留天数

        Returns:
            删除的日志数量
        '''
        cutoff_time = time.time() - retention_days * 86400
        with get_session() as db:
            count = db.query(AuditLogDB).filter(
                AuditLogDB.timestamp < cutoff_time
            ).count()
            db.query(AuditLogDB).filter(
                AuditLogDB.timestamp < cutoff_time
            ).delete()
            db.commit()
            return count
