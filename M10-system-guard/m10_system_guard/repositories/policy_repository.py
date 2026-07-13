'''
防护策略 Repository

封装防护策略配置的数据库操作。
'''

from __future__ import annotations

import time
from typing import Optional

from ..database import get_session
from ..db_models import GuardPolicyDB


class PolicyRepository:
    '''防护策略数据访问层.'''

    @staticmethod
    def get_policies() -> dict:
        '''获取所有防护策略.'''
        with get_session() as db:
            policies = db.query(GuardPolicyDB).all()
            result = {}
            for p in policies:
                result[p.metric_type] = p.to_dict()
            return result

    @staticmethod
    def get_policy(metric_type: str) -> Optional[dict]:
        '''获取指定指标的防护策略.'''
        with get_session() as db:
            policy = db.query(GuardPolicyDB).filter(
                GuardPolicyDB.metric_type == metric_type
            ).first()
            return policy.to_dict() if policy else None

    @staticmethod
    def upsert_policy(
        metric_type: str,
        info_threshold: float,
        warning_threshold: float,
        critical_threshold: float,
        emergency_threshold: float,
        enabled: bool = True,
    ) -> dict:
        '''更新或插入防护策略.'''
        with get_session() as db:
            policy = db.query(GuardPolicyDB).filter(
                GuardPolicyDB.metric_type == metric_type
            ).first()

            if policy:
                policy.info_threshold = info_threshold
                policy.warning_threshold = warning_threshold
                policy.critical_threshold = critical_threshold
                policy.emergency_threshold = emergency_threshold
                policy.enabled = enabled
                policy.updated_at = time.time()
            else:
                policy = GuardPolicyDB(
                    metric_type=metric_type,
                    info_threshold=info_threshold,
                    warning_threshold=warning_threshold,
                    critical_threshold=critical_threshold,
                    emergency_threshold=emergency_threshold,
                    enabled=enabled,
                )
                db.add(policy)

            db.commit()
            return policy.to_dict()

    @staticmethod
    def init_default_policies(config_thresholds: dict) -> None:
        '''初始化默认防护策略（如果数据库中为空）.'''
        with get_session() as db:
            existing_count = db.query(GuardPolicyDB).count()
            if existing_count > 0:
                return  # 已有数据，跳过初始化

            for metric_type, thresholds in config_thresholds.items():
                policy = GuardPolicyDB(
                    metric_type=metric_type,
                    info_threshold=thresholds.get('info', 60.0),
                    warning_threshold=thresholds.get('warning', 75.0),
                    critical_threshold=thresholds.get('critical', 85.0),
                    emergency_threshold=thresholds.get('emergency', 95.0),
                    enabled=True,
                )
                db.add(policy)

            db.commit()
