"""
迁移脚本 v002 - alert_notifications

新增告警通知相关字段和表：
- 为 guard_alerts 增加通知状态字段
- 新增 notification_channels 表（通知渠道配置）
- 新增 notification_logs 表（通知发送记录）
"""

from __future__ import annotations

# 迁移元数据
__migration_name__ = "alert_notifications"
__description__ = "新增告警通知能力：notification_channels, notification_logs，扩展 guard_alerts"


def up(conn):
    """
    升级迁移 - 新增告警通知相关表和字段

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # ============================================================
    # 1. 为 guard_alerts 增加通知状态字段
    # ============================================================
    try:
        conn.execute(text("""
            ALTER TABLE guard_alerts ADD COLUMN notification_status VARCHAR(20) DEFAULT 'pending'
        """))
    except Exception:
        # 列已存在，跳过
        pass

    try:
        conn.execute(text("""
            ALTER TABLE guard_alerts ADD COLUMN notified_at FLOAT
        """))
    except Exception:
        pass

    try:
        conn.execute(text("""
            ALTER TABLE guard_alerts ADD COLUMN notification_error TEXT DEFAULT ''
        """))
    except Exception:
        pass

    # ============================================================
    # 2. notification_channels - 通知渠道配置表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name VARCHAR(100) UNIQUE NOT NULL,
            channel_type VARCHAR(50) NOT NULL,
            config_json TEXT DEFAULT '{}',
            enabled BOOLEAN DEFAULT 1,
            priority_threshold VARCHAR(20) DEFAULT 'warning',
            created_at FLOAT,
            updated_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_channel_type ON notification_channels (channel_type)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_channel_enabled ON notification_channels (enabled)
    """))

    # ============================================================
    # 3. notification_logs - 通知发送记录表
    # ============================================================
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id VARCHAR(32),
            channel_name VARCHAR(100),
            status VARCHAR(20) DEFAULT 'sent',
            retry_count INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            sent_at FLOAT,
            created_at FLOAT
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_notif_alert_id ON notification_logs (alert_id)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_notif_channel ON notification_logs (channel_name)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_notif_status ON notification_logs (status)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_notif_sent_at ON notification_logs (sent_at)
    """))


def down(conn):
    """
    降级迁移（回滚） - 删除告警通知相关表和字段

    Args:
        conn: SQLAlchemy Connection 对象
    """
    from sqlalchemy import text

    # 删除新增的表
    conn.execute(text("DROP TABLE IF EXISTS notification_logs"))
    conn.execute(text("DROP TABLE IF EXISTS notification_channels"))

    # 注意：SQLite 不支持 DROP COLUMN，回滚时只能删除列数据
    # 实际回滚建议通过备份恢复
