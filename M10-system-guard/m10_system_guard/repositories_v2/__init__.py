"""
M10 系统卫士 - 标准 Repository 实现（基于 shared.data_access）
============================================================

使用 shared.data_access.SQLAlchemyRepository 重构的标准 Repository 层，
替代原有静态方法风格的自建实现。

接入内容：
- 继承 SQLAlchemyRepository 获得标准 CRUD
- 使用 UnitOfWork 管理事务
- 提供与旧版兼容的方法，方便渐进式迁移
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# 导入 shared.data_access 的标准组件
from shared.data_access import SQLAlchemyRepository, PaginationResult

# 导入 M10 的模型
from ..db_models import (
    AuditLogDB,
    GuardAlertDB,
    MetricHistoryDB,
    GuardPolicyDB,
)


# ============================================================
# 审计日志 Repository
# ============================================================

class AuditLogRepository(SQLAlchemyRepository[AuditLogDB]):
    """
    审计日志 Repository（标准实现）。

    继承 SQLAlchemyRepository 获得标准 CRUD + 分页 + 批量操作，
    在此基础上添加业务特定方法。
    """

    model_class = AuditLogDB

    # ---- 业务方法 ----

    def add_log(
        self,
        log_id: str,
        level: str,
        log_type: str,
        trigger_condition: str,
        action: str,
        result: str,
        details: Optional[dict] = None,
    ) -> AuditLogDB:
        """
        新增一条审计日志。

        Args:
            log_id: 日志ID
            level: 级别 (info/warning/critical)
            log_type: 日志类型
            trigger_condition: 触发条件
            action: 动作
            result: 结果
            details: 详细信息

        Returns:
            创建后的日志实例
        """
        return self.create({
            "log_id": log_id,
            "timestamp": time.time(),
            "level": level,
            "log_type": log_type,
            "trigger_condition": trigger_condition,
            "action": action,
            "result": result,
            "details_json": json.dumps(details or {}, ensure_ascii=False),
        })

    def list_logs(
        self,
        page: int = 1,
        page_size: int = 100,
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> PaginationResult:
        """
        分页查询审计日志（按时间倒序）。

        Args:
            page: 页码
            page_size: 每页大小
            level: 按级别过滤
            log_type: 按类型过滤
            start_time: 开始时间戳
            end_time: 结束时间戳

        Returns:
            分页结果
        """
        query = self.query()

        if level:
            query = query.filter(level=level)
        if log_type:
            query = query.filter(log_type=log_type)
        if start_time:
            query = query.add_filter("timestamp", "gte", start_time)
        if end_time:
            query = query.add_filter("timestamp", "lte", end_time)

        query = query.order_by("timestamp", ascending=False)
        return query.paginate(page=page, page_size=page_size)

    def count_logs(
        self,
        level: Optional[str] = None,
        log_type: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> int:
        """统计审计日志数量"""
        filters: Dict[str, Any] = {}
        if level:
            filters["level"] = level
        if log_type:
            filters["log_type"] = log_type

        count = self.count(**filters)

        # 时间范围过滤
        if start_time or end_time:
            query = self.query()
            if start_time:
                query = query.add_filter("timestamp", "gte", start_time)
            if end_time:
                query = query.add_filter("timestamp", "lte", end_time)
            count = query.count()

        return count

    def get_stats(self) -> dict:
        """
        获取审计日志统计信息。

        Returns:
            统计字典
        """
        total = self.count()
        info_count = self.count(level="info")
        warning_count = self.count(level="warning")
        critical_count = self.count(level="critical")

        # 按类型统计（取前 20 种）
        type_stats: Dict[str, int] = {}
        all_logs = self._session.query(AuditLogDB).limit(1000).all()
        for log in all_logs:
            type_stats[log.log_type] = type_stats.get(log.log_type, 0) + 1

        return {
            "total": total,
            "by_level": {
                "info": info_count,
                "warning": warning_count,
                "critical": critical_count,
            },
            "by_type": type_stats,
            "storage": "database",
        }

    def clear_logs(self) -> int:
        """清空所有审计日志，返回删除数量"""
        count = self.count()
        self._session.query(AuditLogDB).delete()
        self._session.flush()
        return count

    def cleanup_old_logs(self, retention_days: int = 90) -> int:
        """
        清理过期日志。

        Args:
            retention_days: 保留天数

        Returns:
            删除的日志数量
        """
        cutoff_time = time.time() - retention_days * 86400
        result = self._session.query(AuditLogDB).filter(
            AuditLogDB.timestamp < cutoff_time
        ).delete()
        self._session.flush()
        return result


# ============================================================
# 防护告警 Repository
# ============================================================

class AlertRepository(SQLAlchemyRepository[GuardAlertDB]):
    """防护告警 Repository（标准实现）"""

    model_class = GuardAlertDB

    def add_alert(
        self,
        alert_id: str,
        level: str,
        metric_type: str,
        current_value: float,
        threshold_value: float,
        message: str,
        details: Optional[dict] = None,
    ) -> GuardAlertDB:
        """新增一条告警"""
        return self.create({
            "alert_id": alert_id,
            "timestamp": time.time(),
            "level": level,
            "metric_type": metric_type,
            "current_value": current_value,
            "threshold_value": threshold_value,
            "message": message,
            "details_json": json.dumps(details or {}, ensure_ascii=False),
        })

    def list_alerts(
        self,
        page: int = 1,
        page_size: int = 100,
        level: Optional[str] = None,
        metric_type: Optional[str] = None,
        acknowledged: Optional[bool] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> PaginationResult:
        """分页查询告警列表"""
        query = self.query()

        if level:
            query = query.filter(level=level)
        if metric_type:
            query = query.filter(metric_type=metric_type)
        if acknowledged is not None:
            query = query.filter(acknowledged=acknowledged)
        if start_time:
            query = query.add_filter("timestamp", "gte", start_time)
        if end_time:
            query = query.add_filter("timestamp", "lte", end_time)

        query = query.order_by("timestamp", ascending=False)
        return query.paginate(page=page, page_size=page_size)

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "system") -> bool:
        """确认告警"""
        alert = self._session.query(GuardAlertDB).filter(
            GuardAlertDB.alert_id == alert_id
        ).first()
        if not alert:
            return False
        alert.acknowledged = True
        alert.acknowledged_at = time.time()
        alert.acknowledged_by = acknowledged_by
        self._session.flush()
        return True

    def count_active_alerts(self) -> int:
        """统计未确认的活跃告警数量"""
        return self.count(acknowledged=False)


# ============================================================
# 指标历史 Repository
# ============================================================

class MetricRepository(SQLAlchemyRepository[MetricHistoryDB]):
    """指标历史 Repository（标准实现）"""

    model_class = MetricHistoryDB

    def add_metric(
        self,
        metric_type: str,
        value: dict,
        aggregation_level: str = "raw",
        timestamp: Optional[float] = None,
    ) -> MetricHistoryDB:
        """新增一条指标记录"""
        return self.create({
            "timestamp": timestamp or time.time(),
            "metric_type": metric_type,
            "aggregation_level": aggregation_level,
            "value_json": json.dumps(value, ensure_ascii=False),
        })

    def get_history(
        self,
        metric_type: str,
        aggregation_level: str = "raw",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000,
    ) -> List[MetricHistoryDB]:
        """查询指标历史数据（按时间正序）"""
        query = self.query().filter(
            metric_type=metric_type,
            aggregation_level=aggregation_level,
        )

        if start_time:
            query = query.add_filter("timestamp", "gte", start_time)
        if end_time:
            query = query.add_filter("timestamp", "lte", end_time)

        query = query.order_by("timestamp", ascending=True)
        results = query.limit(limit).all()
        return results

    def cleanup_old_metrics(self, retention_minutes: int = 60) -> int:
        """清理过期原始指标数据"""
        cutoff_time = time.time() - retention_minutes * 60
        result = self._session.query(MetricHistoryDB).filter(
            MetricHistoryDB.aggregation_level == "raw",
            MetricHistoryDB.timestamp < cutoff_time,
        ).delete()
        self._session.flush()
        return result


# ============================================================
# 防护策略 Repository
# ============================================================

class PolicyRepository(SQLAlchemyRepository[GuardPolicyDB]):
    """防护策略 Repository（标准实现）"""

    model_class = GuardPolicyDB

    def get_policies(self) -> Dict[str, dict]:
        """获取所有防护策略（按 metric_type 索引）"""
        policies = self.list_all()
        result = {}
        for p in policies:
            result[p.metric_type] = p.to_dict()
        return result

    def get_policy(self, metric_type: str) -> Optional[dict]:
        """获取指定指标的防护策略"""
        policy = self._session.query(GuardPolicyDB).filter(
            GuardPolicyDB.metric_type == metric_type
        ).first()
        return policy.to_dict() if policy else None

    def upsert_policy(
        self,
        metric_type: str,
        info_threshold: float,
        warning_threshold: float,
        critical_threshold: float,
        emergency_threshold: float,
        enabled: bool = True,
    ) -> dict:
        """更新或插入防护策略"""
        policy = self._session.query(GuardPolicyDB).filter(
            GuardPolicyDB.metric_type == metric_type
        ).first()

        if policy:
            policy.info_threshold = info_threshold
            policy.warning_threshold = warning_threshold
            policy.critical_threshold = critical_threshold
            policy.emergency_threshold = emergency_threshold
            policy.enabled = enabled
            policy.updated_at = time.time()
            self._session.flush()
        else:
            policy = self.create({
                "metric_type": metric_type,
                "info_threshold": info_threshold,
                "warning_threshold": warning_threshold,
                "critical_threshold": critical_threshold,
                "emergency_threshold": emergency_threshold,
                "enabled": enabled,
            })

        return policy.to_dict()

    def init_default_policies(self, config_thresholds: dict) -> None:
        """初始化默认防护策略（如果数据库中为空）"""
        if self.count() > 0:
            return  # 已有数据，跳过初始化

        for metric_type, thresholds in config_thresholds.items():
            self.create({
                "metric_type": metric_type,
                "info_threshold": thresholds.get("info", 60.0),
                "warning_threshold": thresholds.get("warning", 75.0),
                "critical_threshold": thresholds.get("critical", 85.0),
                "emergency_threshold": thresholds.get("emergency", 95.0),
                "enabled": True,
            })


# ============================================================
# 导出
# ============================================================

__all__ = [
    "AuditLogRepository",
    "AlertRepository",
    "MetricRepository",
    "PolicyRepository",
]
