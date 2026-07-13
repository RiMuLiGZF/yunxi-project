'''
指标历史 Repository

封装系统指标历史数据的数据库操作。
'''

from __future__ import annotations

import json
import time
from typing import Optional

from ..database import get_session
from ..db_models import MetricHistoryDB


class MetricRepository:
    '''指标历史数据访问层.'''

    @staticmethod
    def add_metric(
        metric_type: str,
        value: dict,
        aggregation_level: str = 'raw',
        timestamp: Optional[float] = None,
    ) -> None:
        '''新增一条指标记录.'''
        with get_session() as db:
            metric = MetricHistoryDB(
                timestamp=timestamp or time.time(),
                metric_type=metric_type,
                aggregation_level=aggregation_level,
                value_json=json.dumps(value, ensure_ascii=False),
            )
            db.add(metric)
            db.commit()

    @staticmethod
    def get_history(
        metric_type: str,
        aggregation_level: str = 'raw',
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000,
    ) -> list[dict]:
        '''查询指标历史数据.'''
        with get_session() as db:
            query = db.query(MetricHistoryDB).filter(
                MetricHistoryDB.metric_type == metric_type,
                MetricHistoryDB.aggregation_level == aggregation_level,
            )

            if start_time:
                query = query.filter(MetricHistoryDB.timestamp >= start_time)
            if end_time:
                query = query.filter(MetricHistoryDB.timestamp <= end_time)

            metrics = query.order_by(MetricHistoryDB.timestamp.desc()) \
                           .limit(limit).all()
            # 反转成正序
            return [m.to_dict() for m in reversed(metrics)]

    @staticmethod
    def cleanup_old_metrics(retention_minutes: int = 60) -> int:
        '''清理过期原始指标数据.

        Args:
            retention_minutes: 原始数据保留分钟数

        Returns:
            删除的记录数量
        '''
        cutoff_time = time.time() - retention_minutes * 60
        with get_session() as db:
            count = db.query(MetricHistoryDB).filter(
                MetricHistoryDB.aggregation_level == 'raw',
                MetricHistoryDB.timestamp < cutoff_time,
            ).count()
            db.query(MetricHistoryDB).filter(
                MetricHistoryDB.aggregation_level == 'raw',
                MetricHistoryDB.timestamp < cutoff_time,
            ).delete()
            db.commit()
            return count
