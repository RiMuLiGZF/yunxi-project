"""
迁移脚本 v002 - wearable_tables

P0 批次迁移：可穿戴设备表从 M8 迁移到 M6。
包含可穿戴设备、健康数据、通知、设备配置四张核心表及相关索引。

表清单：
- wearable_devices: 可穿戴设备表
- wearable_health_data: 可穿戴健康数据表
- wearable_notifications: 可穿戴通知表
- wearable_settings: 可穿戴设备配置表
"""

__migration_name__ = "wearable_tables"
__description__ = "创建可穿戴设备相关表（设备、健康数据、通知、配置）及索引"


def up(conn):
    """
    升级迁移 - 创建可穿戴设备相关表

    Args:
        conn: 数据库连接对象（sqlite3.Connection）
    """
    cursor = conn.cursor()

    # 可穿戴设备表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wearable_devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL DEFAULT '',
            device_type TEXT NOT NULL DEFAULT 'watch',
            brand TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            mac_address TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'offline',
            battery_level REAL,
            firmware_version TEXT NOT NULL DEFAULT '',
            last_sync_at DATETIME,
            paired_at DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)

    # 可穿戴健康数据表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wearable_health_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default',
            data_type TEXT NOT NULL,
            value REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT '',
            recorded_at DATETIME NOT NULL,
            source TEXT NOT NULL DEFAULT 'device',
            quality TEXT NOT NULL DEFAULT 'good',
            created_at DATETIME NOT NULL
        )
    """)

    # 可穿戴通知表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wearable_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id TEXT NOT NULL UNIQUE,
            device_id TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'default',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'system',
            status TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'system',
            delivered_at DATETIME,
            created_at DATETIME NOT NULL
        )
    """)

    # 可穿戴设备配置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wearable_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL DEFAULT 'default',
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME NOT NULL
        )
    """)

    # 可穿戴设备索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_device_user
        ON wearable_devices(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_device_type
        ON wearable_devices(device_type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_device_status
        ON wearable_devices(status)
    """)

    # 健康数据索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_health_device_type_time
        ON wearable_health_data(device_id, data_type, recorded_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_health_user
        ON wearable_health_data(user_id)
    """)

    # 通知索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_notify_device
        ON wearable_notifications(device_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_notify_status
        ON wearable_notifications(status)
    """)

    # 设置表索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_wearable_settings_user
        ON wearable_settings(user_id)
    """)


def down(conn):
    """
    降级迁移 - 删除可穿戴设备相关表

    Args:
        conn: 数据库连接对象（sqlite3.Connection）
    """
    cursor = conn.cursor()

    # 删除索引
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_settings_user")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_notify_status")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_notify_device")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_health_user")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_health_device_type_time")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_device_status")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_device_type")
    cursor.execute("DROP INDEX IF EXISTS idx_wearable_device_user")

    # 删除表
    cursor.execute("DROP TABLE IF EXISTS wearable_settings")
    cursor.execute("DROP TABLE IF EXISTS wearable_notifications")
    cursor.execute("DROP TABLE IF EXISTS wearable_health_data")
    cursor.execute("DROP TABLE IF EXISTS wearable_devices")
