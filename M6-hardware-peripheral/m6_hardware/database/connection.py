"""
M6 硬件外设 - 数据库连接管理

P1-5 改造：提供上下文管理器封装的事务连接，
支持自动建表与连接复用。
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """SQLite 数据库连接上下文管理器

    支持事务自动提交/回滚，配合 ``with`` 语句使用：

        with DatabaseConnection("/path/to/db") as conn:
            SensorDataRepository.insert_batch(..., conn)
            conn.commit()
    """

    def __init__(
        self,
        db_path: str,
        *,
        timeout: float = 5.0,
        isolation_level: Optional[str] = None,
    ):
        self.db_path = db_path
        self.timeout = timeout
        self.isolation_level = isolation_level  # None 表示由调用方控制事务
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            isolation_level=self.isolation_level,
        )
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn is None:
            return
        try:
            if exc_type is not None:
                self._conn.rollback()
            self._conn.close()
        except Exception:
            logger.exception("[DatabaseConnection] 关闭连接时异常")
        finally:
            self._conn = None


def _init_tables(conn: sqlite3.Connection) -> None:
    """初始化数据库表结构（幂等）"""
    cursor = conn.cursor()

    # 传感器数据表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            value REAL,
            value_text TEXT,
            unit TEXT,
            quality INTEGER,
            timestamp DATETIME NOT NULL
        )
    """)

    # 设备状态历史表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS device_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            status TEXT NOT NULL,
            battery REAL,
            signal_strength INTEGER,
            timestamp DATETIME NOT NULL
        )
    """)

    # 索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sensor_device_time
        ON sensor_data(device_id, timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sensor_type_time
        ON sensor_data(sensor_type, timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status_device_time
        ON device_status_history(device_id, timestamp)
    """)

    # ====================================================================
    # 可穿戴设备表（P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6）
    # ====================================================================

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

    conn.commit()


def get_db(db_path: str, auto_init: bool = True) -> DatabaseConnection:
    """获取数据库连接工厂

    Args:
        db_path: SQLite 文件路径
        auto_init: 是否自动建表（默认 True）

    Returns:
        DatabaseConnection 实例（尚未打开连接，需配合 with 使用）
    """
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    if auto_init:
        # 使用独立连接完成建表，避免污染主连接的事务状态
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            _init_tables(conn)

    return DatabaseConnection(db_path)
