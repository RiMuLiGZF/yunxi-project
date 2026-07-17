"""
迁移脚本 v001 - initial_sensor_tables

M6 初始数据库建表迁移，包含传感器数据表和设备状态历史表。
这是从原有的 _init_tables() 函数中提取的第一部分基础表结构。

表清单：
- sensor_data: 传感器数据表
- device_status_history: 设备状态历史表
"""

__migration_name__ = "initial_sensor_tables"
__description__ = "创建传感器数据表和设备状态历史表及相关索引"


def up(conn):
    """
    升级迁移 - 创建初始表结构

    Args:
        conn: 数据库连接对象（sqlite3.Connection）
    """
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


def down(conn):
    """
    降级迁移 - 删除初始表结构

    Args:
        conn: 数据库连接对象（sqlite3.Connection）
    """
    cursor = conn.cursor()

    # 删除索引
    cursor.execute("DROP INDEX IF EXISTS idx_status_device_time")
    cursor.execute("DROP INDEX IF EXISTS idx_sensor_type_time")
    cursor.execute("DROP INDEX IF EXISTS idx_sensor_device_time")

    # 删除表
    cursor.execute("DROP TABLE IF EXISTS device_status_history")
    cursor.execute("DROP TABLE IF EXISTS sensor_data")
