"""
迁移脚本 v001 - initial

M10 系统卫士初始表结构创建。
包含 7 张表：
- audit_logs: 审计日志表
- guard_alerts: 防护告警记录表
- metric_history: 系统指标历史表
- guard_policies: 防护策略配置表
- startup_checks: 启动检查记录表
- reports: 报告记录表
- tide_missions: 潮汐任务记录表

注意：此迁移脚本使用 SQLAlchemy Connection 对象执行 SQL 语句，
与 SQLAlchemyMigrationAdapter 适配层配合使用。
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "initial"
__description__ = "M10 系统卫士初始表结构：audit_logs, guard_alerts, metric_history, guard_policies, startup_checks, reports, tide_missions"


def up(conn):
    """
    升级迁移 - 创建初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. audit_logs - 审计日志表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_id VARCHAR(32) UNIQUE,
            timestamp FLOAT,
            level VARCHAR(20),
            log_type VARCHAR(100),
            trigger_condition VARCHAR(500),
            action VARCHAR(500),
            result VARCHAR(500),
            details_json TEXT DEFAULT '{}',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_id ON audit_logs (log_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_level ON audit_logs (level)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_log_type ON audit_logs (log_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_audit_time_level ON audit_logs (timestamp, level)
    """))

    # ============================================================
    # 2. guard_alerts - 防护告警记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS guard_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id VARCHAR(32) UNIQUE,
            timestamp FLOAT,
            level VARCHAR(20),
            metric_type VARCHAR(50),
            current_value FLOAT,
            threshold_value FLOAT,
            message VARCHAR(500),
            acknowledged BOOLEAN DEFAULT 0,
            acknowledged_at FLOAT,
            acknowledged_by VARCHAR(100),
            details_json TEXT DEFAULT '{}',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_id ON guard_alerts (alert_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_timestamp ON guard_alerts (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_level ON guard_alerts (level)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_metric_type ON guard_alerts (metric_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_alert_time_level ON guard_alerts (timestamp, level)
    """))

    # ============================================================
    # 3. metric_history - 系统指标历史表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS metric_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp FLOAT,
            metric_type VARCHAR(50),
            aggregation_level VARCHAR(20) DEFAULT 'raw',
            value_json TEXT DEFAULT '{}',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_metric_timestamp ON metric_history (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_metric_type ON metric_history (metric_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_metric_aggregation ON metric_history (aggregation_level)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_metric_time_type_agg
        ON metric_history (timestamp, metric_type, aggregation_level)
    """))

    # ============================================================
    # 4. guard_policies - 防护策略配置表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS guard_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_type VARCHAR(50) UNIQUE,
            info_threshold FLOAT,
            warning_threshold FLOAT,
            critical_threshold FLOAT,
            emergency_threshold FLOAT,
            enabled BOOLEAN DEFAULT 1,
            updated_at FLOAT,
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_policy_metric_type ON guard_policies (metric_type)
    """))

    # ============================================================
    # 5. startup_checks - 启动检查记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS startup_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id VARCHAR(32) UNIQUE,
            timestamp FLOAT,
            overall_level VARCHAR(20),
            memory_free_percent FLOAT,
            cpu_usage_percent FLOAT,
            max_temperature FLOAT,
            same_process_count INTEGER,
            details_json TEXT DEFAULT '{}',
            recommendation TEXT DEFAULT '',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_startup_check_id ON startup_checks (check_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_startup_timestamp ON startup_checks (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_startup_level ON startup_checks (overall_level)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_startup_time_level
        ON startup_checks (timestamp, overall_level)
    """))

    # ============================================================
    # 6. reports - 报告记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id VARCHAR(32) UNIQUE,
            report_type VARCHAR(20),
            period_start FLOAT,
            period_end FLOAT,
            title VARCHAR(200),
            health_score FLOAT,
            summary TEXT DEFAULT '',
            markdown_content TEXT DEFAULT '',
            html_content TEXT DEFAULT '',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_id ON reports (report_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_type ON reports (report_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_period_start ON reports (period_start)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_report_type_time
        ON reports (report_type, period_start)
    """))

    # ============================================================
    # 7. tide_missions - 潮汐任务记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS tide_missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id VARCHAR(32) UNIQUE,
            timestamp FLOAT,
            name VARCHAR(200),
            priority VARCHAR(20),
            status VARCHAR(20),
            estimated_memory_mb FLOAT,
            actual_memory_mb FLOAT,
            estimated_duration_sec FLOAT,
            actual_duration_sec FLOAT,
            submitted_by VARCHAR(100) DEFAULT 'system',
            started_at FLOAT,
            completed_at FLOAT,
            result_json TEXT DEFAULT '{}',
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_mission_id ON tide_missions (mission_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_timestamp ON tide_missions (timestamp)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_priority ON tide_missions (priority)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_status ON tide_missions (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_tide_status_time
        ON tide_missions (status, timestamp)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除初始表结构

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 按创建逆序删除，避免外键约束问题
    tables = [
        "tide_missions",
        "reports",
        "startup_checks",
        "guard_policies",
        "metric_history",
        "guard_alerts",
        "audit_logs",
    ]

    for table in tables:
        conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
