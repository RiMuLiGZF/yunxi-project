"""
迁移脚本 v003 - performance_indexes

为 M10 系统卫士模块添加性能优化索引。

包含：
- guard_alerts：acknowledged、acknowledged+timestamp 复合索引
- guard_policies：enabled、updated_at 索引
- tide_missions：submitted_by、priority+status 复合索引
- 各表时间+类型复合索引优化

注意：所有索引使用 CREATE INDEX IF NOT EXISTS，保证幂等。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "performance_indexes"
__description__ = "M10 性能优化索引：补充告警、策略、任务等表的常用查询索引"


def up(conn):
    """
    升级迁移 - 添加性能优化索引

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # guard_alerts 新增索引
    # ============================================================

    # 确认状态索引（未确认告警查询）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_acknowledged
        ON guard_alerts (acknowledged)
    """))

    # 确认状态+时间复合索引（按时间查看未确认告警）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_ack_time
        ON guard_alerts (acknowledged, timestamp)
    """))

    # 指标类型+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_metric_time
        ON guard_alerts (metric_type, timestamp)
    """))

    # 级别+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_level_time
        ON guard_alerts (level, timestamp)
    """))

    # ============================================================
    # guard_policies 新增索引
    # ============================================================

    # 启用状态索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_policy_enabled
        ON guard_policies (enabled)
    """))

    # 更新时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_policy_updated_at
        ON guard_policies (updated_at)
    """))

    # ============================================================
    # metric_history 新增索引
    # ============================================================

    # 类型+时间复合索引（指标历史查询）
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_metric_type_time
        ON metric_history (metric_type, timestamp)
    """))

    # ============================================================
    # tide_missions 新增索引
    # ============================================================

    # 提交者索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_submitted_by
        ON tide_missions (submitted_by)
    """))

    # 优先级+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_priority_status
        ON tide_missions (priority, status)
    """))

    # 提交者+状态复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_submitter_status
        ON tide_missions (submitted_by, status)
    """))

    # ============================================================
    # reports 新增索引
    # ============================================================

    # 创建时间索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_created_at
        ON reports (created_at)
    """))

    # 健康评分索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_health_score
        ON reports (health_score)
    """))

    # 类型+创建时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_type_created
        ON reports (report_type, created_at)
    """))

    # ============================================================
    # startup_checks 新增索引
    # ============================================================

    # 级别+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_startup_level_time
        ON startup_checks (overall_level, timestamp)
    """))

    # ============================================================
    # audit_logs 新增索引
    # ============================================================

    # 类型+时间复合索引
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_type_time
        ON audit_logs (log_type, timestamp)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除新增的索引

    只删除本迁移新增的索引，保留原有索引。

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除
    indexes_to_drop = [
        # audit_logs
        "idx_audit_type_time",
        # startup_checks
        "idx_startup_level_time",
        # reports
        "idx_report_type_created",
        "idx_report_health_score",
        "idx_report_created_at",
        # tide_missions
        "idx_tide_submitter_status",
        "idx_tide_priority_status",
        "idx_tide_submitted_by",
        # metric_history
        "idx_metric_type_time",
        # guard_policies
        "idx_policy_updated_at",
        "idx_policy_enabled",
        # guard_alerts
        "idx_alert_level_time",
        "idx_alert_metric_time",
        "idx_alert_ack_time",
        "idx_alert_acknowledged",
    ]

    for idx_name in indexes_to_drop:
        conn.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
