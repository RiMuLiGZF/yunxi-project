'''
防护告警 Repository

封装告警记录的数据库操作。
'''

from __future__ import annotations

import json
import time
from typing import Optional

from ..database import get_session
from ..db_models import GuardAlertDB


class AlertRepository:
    '''防护告警数据访问层.'''

    @staticmethod
    def add_alert(
        alert_id: str,
        level: str,
        metric_type: str,
        current_value: float,
        threshold_value: float,
        message: str,
        details: Optional[dict] = None,
    ) -> None:
        '''新增一条告警.'''
        with get_session() as db:
            alert = GuardAlertDB(
                alert_id=alert_id,
                timestamp=time.time(),
                level=level,
                metric_type=metric_type,
                current_value=current_value,
                threshold_value=threshold_value,
                message=message,
                details_json=json.dumps(details or {}, ensure_ascii=False),
            )
            db.add(alert)
            db.commit()

    @staticmethod
    def get_alerts(
        limit: int = 100,
        offset: int = 0,
        level: Optional[str] = None,
        metric_type: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> list[dict]:
        '''查询告警列表.'''
        with get_session() as db:
            query = db.query(GuardAlertDB)

            if level:
                query = query.filter(GuardAlertDB.level == level)
            if metric_type:
                query = query.filter(GuardAlertDB.metric_type == metric_type)
            if acknowledged is not None:
                query = query.filter(GuardAlertDB.acknowledged == acknowledged)
            if start_time:
                query = query.filter(GuardAlertDB.timestamp >= start_time)
            if end_time:
                query = query.filter(GuardAlertDB.timestamp <= end_time)

            alerts = query.order_by(GuardAlertDB.timestamp.desc()) \
                          .offset(offset).limit(limit).all()
            return [alert.to_dict() for alert in alerts]

    @staticmethod
    def acknowledge_alert(alert_id: str, acknowledged_by: str = 'system') -> bool:
        '''确认告警.'''
        with get_session() as db:
            alert = db.query(GuardAlertDB).filter(
                GuardAlertDB.alert_id == alert_id
            ).first()
            if not alert:
                return False
            alert.acknowledged = True
            alert.acknowledged_at = time.time()
            alert.acknowledged_by = acknowledged_by
            db.commit()
            return True

    @staticmethod
    def count_active_alerts() -> int:
        '''统计未确认的活跃告警数量.'''
        with get_session() as db:
            return db.query(GuardAlertDB).filter(
                GuardAlertDB.acknowledged == False
            ).count()
