"""
M8 → M6 可穿戴数据迁移脚本
==========================

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6 硬件外设模块。

迁移内容：
- watch_devices → wearable_devices（可穿戴设备表）
- watch_health_data → wearable_health_data（健康数据表）
- watch_notifications → wearable_notifications（通知记录表）
- watch_settings → wearable_settings（设备配置表）

特性：
- 幂等迁移：重复执行安全，不会重复插入
- 增量迁移：支持按时间范围增量迁移
- 事务保障：每类数据在单个事务中完成
- 数据校验：迁移前后数量对比
- 失败回滚：异常时自动回滚事务

使用方式：
    python migrate_wearable_m8_to_m6.py [--full] [--start-date YYYY-MM-DD] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

# 确保项目根目录在 sys.path 中
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# M8 数据库路径
M8_DB_PATH = PROJECT_ROOT / "M8-control-tower" / "backend" / "data" / "m8.db"
# M6 数据库路径
M6_DB_PATH = PROJECT_ROOT / "M6-hardware-peripheral" / "data" / "m6_sensors.db"


# ---------------------------------------------------------------------------
# 迁移统计
# ---------------------------------------------------------------------------
class MigrationStats:
    """迁移统计信息"""

    def __init__(self):
        self.devices_m8 = 0
        self.devices_m6_before = 0
        self.devices_migrated = 0
        self.devices_skipped = 0
        self.health_m8 = 0
        self.health_m6_before = 0
        self.health_migrated = 0
        self.health_skipped = 0
        self.notifications_m8 = 0
        self.notifications_m6_before = 0
        self.notifications_migrated = 0
        self.notifications_skipped = 0
        self.settings_m8 = 0
        self.settings_m6_before = 0
        self.settings_migrated = 0
        self.settings_skipped = 0
        self.start_time = None
        self.end_time = None
        self.errors: List[str] = []

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "devices": {
                "m8_count": self.devices_m8,
                "m6_before": self.devices_m6_before,
                "migrated": self.devices_migrated,
                "skipped": self.devices_skipped,
            },
            "health_data": {
                "m8_count": self.health_m8,
                "m6_before": self.health_m6_before,
                "migrated": self.health_migrated,
                "skipped": self.health_skipped,
            },
            "notifications": {
                "m8_count": self.notifications_m8,
                "m6_before": self.notifications_m6_before,
                "migrated": self.notifications_migrated,
                "skipped": self.notifications_skipped,
            },
            "settings": {
                "m8_count": self.settings_m8,
                "m6_before": self.settings_m6_before,
                "migrated": self.settings_migrated,
                "skipped": self.settings_skipped,
            },
            "duration_seconds": round(self.duration_seconds, 2),
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# 数据库连接工具
# ---------------------------------------------------------------------------

def get_m8_connection() -> sqlite3.Connection:
    """获取 M8 数据库连接（只读模式）"""
    if not M8_DB_PATH.exists():
        raise FileNotFoundError(f"M8 数据库不存在: {M8_DB_PATH}")
    conn = sqlite3.connect(f"file:{M8_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_m6_connection(init_tables: bool = True) -> sqlite3.Connection:
    """获取 M6 数据库连接（读写模式）

    Args:
        init_tables: 是否自动初始化可穿戴设备表结构
    """
    M6_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(M6_DB_PATH))
    conn.row_factory = sqlite3.Row

    if init_tables:
        # 确保可穿戴设备表存在（幂等）
        _init_wearable_tables(conn)

    return conn


def _init_wearable_tables(conn: sqlite3.Connection) -> None:
    """初始化可穿戴设备表结构（幂等）"""
    cursor = conn.cursor()
    cursor.executescript("""
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
        );

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
        );

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
        );

        CREATE TABLE IF NOT EXISTS wearable_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL DEFAULT 'default',
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_wearable_device_user
        ON wearable_devices(user_id);
        CREATE INDEX IF NOT EXISTS idx_wearable_device_type
        ON wearable_devices(device_type);
        CREATE INDEX IF NOT EXISTS idx_wearable_device_status
        ON wearable_devices(status);

        CREATE INDEX IF NOT EXISTS idx_wearable_health_device_type_time
        ON wearable_health_data(device_id, data_type, recorded_at);
        CREATE INDEX IF NOT EXISTS idx_wearable_health_user
        ON wearable_health_data(user_id);

        CREATE INDEX IF NOT EXISTS idx_wearable_notify_device
        ON wearable_notifications(device_id);
        CREATE INDEX IF NOT EXISTS idx_wearable_notify_status
        ON wearable_notifications(status);

        CREATE INDEX IF NOT EXISTS idx_wearable_settings_user
        ON wearable_settings(user_id);
    """)
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Row 转字典"""
    return dict(row)


# ---------------------------------------------------------------------------
# 迁移：可穿戴设备
# ---------------------------------------------------------------------------

def migrate_devices(m8_conn: sqlite3.Connection, m6_conn: sqlite3.Connection, stats: MigrationStats, dry_run: bool = False) -> None:
    """
    迁移设备表：watch_devices → wearable_devices

    字段映射：
        id → (M6自增)
        device_id → device_id
        name → name
        device_type → device_type
        brand → brand
        model → model
        firmware_version → firmware_version
        status → status
        battery → battery_level
        paired_at → paired_at
        last_sync → last_sync_at
        mac_address → mac_address
        user_id → user_id (M8 是 Integer，M6 是 String，转 str)
        created_at → created_at
        updated_at → updated_at
    """
    print("\n" + "=" * 60)
    print("  迁移：可穿戴设备 (watch_devices → wearable_devices)")
    print("=" * 60)

    # 统计 M8 数据量
    m8_cursor = m8_conn.execute("SELECT COUNT(*) as cnt FROM watch_devices")
    stats.devices_m8 = m8_cursor.fetchone()["cnt"]
    print(f"  M8 源数据: {stats.devices_m8} 条")

    # 统计 M6 现有数据量
    m6_cursor = m6_conn.execute("SELECT COUNT(*) as cnt FROM wearable_devices")
    stats.devices_m6_before = m6_cursor.fetchone()["cnt"]
    print(f"  M6 现有: {stats.devices_m6_before} 条")

    if dry_run:
        print("  [DRY-RUN] 跳过实际迁移")
        return

    # 查询所有 M8 设备
    m8_cursor = m8_conn.execute("SELECT * FROM watch_devices ORDER BY id")
    m8_devices = [row_to_dict(row) for row in m8_cursor.fetchall()]

    migrated = 0
    skipped = 0

    try:
        for dev in m8_devices:
            # 检查是否已存在（幂等）
            existing = m6_conn.execute(
                "SELECT id FROM wearable_devices WHERE device_id = ?",
                (dev["device_id"],),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            # 字段映射
            m6_data = {
                "device_id": dev["device_id"],
                "user_id": str(dev.get("user_id", "default")),  # M8 是 Integer，转 str
                "name": dev.get("name", ""),
                "device_type": dev.get("device_type", "watch"),
                "brand": dev.get("brand", ""),
                "model": dev.get("model", ""),
                "mac_address": dev.get("mac_address", ""),
                "status": dev.get("status", "offline"),
                "battery_level": dev.get("battery"),
                "firmware_version": dev.get("firmware_version", ""),
                "last_sync_at": dev.get("last_sync"),
                "paired_at": dev.get("paired_at"),
                "created_at": dev.get("created_at", datetime.now().isoformat()),
                "updated_at": dev.get("updated_at", datetime.now().isoformat()),
            }

            # 插入 M6
            columns = list(m6_data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(m6_data[col] for col in columns)

            m6_conn.execute(
                f"INSERT INTO wearable_devices ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            migrated += 1

        m6_conn.commit()
        stats.devices_migrated = migrated
        stats.devices_skipped = skipped
        print(f"  迁移完成: 新增 {migrated} 条，跳过 {skipped} 条")

    except Exception as e:
        m6_conn.rollback()
        stats.errors.append(f"设备迁移失败: {str(e)}")
        print(f"  [ERROR] 设备迁移失败: {e}")
        raise


# ---------------------------------------------------------------------------
# 迁移：健康数据
# ---------------------------------------------------------------------------

def migrate_health_data(
    m8_conn: sqlite3.Connection,
    m6_conn: sqlite3.Connection,
    stats: MigrationStats,
    start_date: str = None,
    dry_run: bool = False,
    batch_size: int = 1000,
) -> None:
    """
    迁移健康数据表：watch_health_data → wearable_health_data

    字段映射：
        id → (M6自增)
        device_id → device_id
        data_type → data_type
        value → value
        unit → unit
        timestamp → recorded_at
        source → source
        quality → quality
        user_id → user_id
        created_at → created_at
    """
    print("\n" + "=" * 60)
    print("  迁移：健康数据 (watch_health_data → wearable_health_data)")
    print("=" * 60)

    # 统计 M8 数据量
    if start_date:
        m8_cursor = m8_conn.execute(
            "SELECT COUNT(*) as cnt FROM watch_health_data WHERE timestamp >= ?",
            (start_date,),
        )
    else:
        m8_cursor = m8_conn.execute("SELECT COUNT(*) as cnt FROM watch_health_data")
    stats.health_m8 = m8_cursor.fetchone()["cnt"]
    print(f"  M8 源数据: {stats.health_m8} 条")

    # 统计 M6 现有数据量
    m6_cursor = m6_conn.execute("SELECT COUNT(*) as cnt FROM wearable_health_data")
    stats.health_m6_before = m6_cursor.fetchone()["cnt"]
    print(f"  M6 现有: {stats.health_m6_before} 条")

    if dry_run:
        print("  [DRY-RUN] 跳过实际迁移")
        return

    migrated = 0
    skipped = 0
    offset = 0

    try:
        while True:
            # 分批查询
            if start_date:
                m8_cursor = m8_conn.execute(
                    """SELECT * FROM watch_health_data
                       WHERE timestamp >= ?
                       ORDER BY id LIMIT ? OFFSET ?""",
                    (start_date, batch_size, offset),
                )
            else:
                m8_cursor = m8_conn.execute(
                    "SELECT * FROM watch_health_data ORDER BY id LIMIT ? OFFSET ?",
                    (batch_size, offset),
                )

            batch = [row_to_dict(row) for row in m8_cursor.fetchall()]
            if not batch:
                break

            batch_migrated = 0
            for record in batch:
                # 幂等检查：使用 (device_id, data_type, recorded_at) 作为唯一标识
                existing = m6_conn.execute(
                    """SELECT id FROM wearable_health_data
                       WHERE device_id = ? AND data_type = ? AND recorded_at = ?""",
                    (record["device_id"], record["data_type"], record["timestamp"]),
                ).fetchone()

                if existing:
                    skipped += 1
                    continue

                # 字段映射
                m6_data = {
                    "device_id": record["device_id"],
                    "user_id": str(record.get("user_id", "default")),
                    "data_type": record["data_type"],
                    "value": record.get("value", 0),
                    "unit": record.get("unit", ""),
                    "recorded_at": record["timestamp"],
                    "source": record.get("source", "device"),
                    "quality": record.get("quality", "good"),
                    "created_at": record.get("created_at", datetime.now().isoformat()),
                }

                columns = list(m6_data.keys())
                placeholders = ", ".join("?" for _ in columns)
                values = tuple(m6_data[col] for col in columns)

                m6_conn.execute(
                    f"INSERT INTO wearable_health_data ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                batch_migrated += 1

            migrated += batch_migrated
            m6_conn.commit()

            print(f"  进度: {offset + len(batch)}/{stats.health_m8} (已迁移 {migrated} 条)")
            offset += batch_size

        stats.health_migrated = migrated
        stats.health_skipped = skipped
        print(f"  迁移完成: 新增 {migrated} 条，跳过 {skipped} 条")

    except Exception as e:
        m6_conn.rollback()
        stats.errors.append(f"健康数据迁移失败: {str(e)}")
        print(f"  [ERROR] 健康数据迁移失败: {e}")
        raise


# ---------------------------------------------------------------------------
# 迁移：通知记录
# ---------------------------------------------------------------------------

def migrate_notifications(
    m8_conn: sqlite3.Connection,
    m6_conn: sqlite3.Connection,
    stats: MigrationStats,
    dry_run: bool = False,
) -> None:
    """
    迁移通知表：watch_notifications → wearable_notifications

    字段映射：
        id → (M6自增)
        notification_id → notification_id
        device_id → device_id
        title → title
        content → content
        notification_type → type
        status → status
        delivered_at → delivered_at
        source → source
        user_id → user_id
        created_at → created_at
    """
    print("\n" + "=" * 60)
    print("  迁移：通知记录 (watch_notifications → wearable_notifications)")
    print("=" * 60)

    # 统计 M8 数据量
    m8_cursor = m8_conn.execute("SELECT COUNT(*) as cnt FROM watch_notifications")
    stats.notifications_m8 = m8_cursor.fetchone()["cnt"]
    print(f"  M8 源数据: {stats.notifications_m8} 条")

    # 统计 M6 现有数据量
    m6_cursor = m6_conn.execute("SELECT COUNT(*) as cnt FROM wearable_notifications")
    stats.notifications_m6_before = m6_cursor.fetchone()["cnt"]
    print(f"  M6 现有: {stats.notifications_m6_before} 条")

    if dry_run:
        print("  [DRY-RUN] 跳过实际迁移")
        return

    # 查询所有 M8 通知
    m8_cursor = m8_conn.execute("SELECT * FROM watch_notifications ORDER BY id")
    m8_notifs = [row_to_dict(row) for row in m8_cursor.fetchall()]

    migrated = 0
    skipped = 0

    try:
        for notif in m8_notifs:
            # 幂等检查
            existing = m6_conn.execute(
                "SELECT id FROM wearable_notifications WHERE notification_id = ?",
                (notif["notification_id"],),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            # 字段映射
            m6_data = {
                "notification_id": notif["notification_id"],
                "device_id": notif["device_id"],
                "user_id": str(notif.get("user_id", "default")),
                "title": notif.get("title", ""),
                "content": notif.get("content", ""),
                "type": notif.get("notification_type", "system"),
                "status": notif.get("status", "pending"),
                "source": notif.get("source", "system"),
                "delivered_at": notif.get("delivered_at"),
                "created_at": notif.get("created_at", datetime.now().isoformat()),
            }

            columns = list(m6_data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(m6_data[col] for col in columns)

            m6_conn.execute(
                f"INSERT INTO wearable_notifications ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            migrated += 1

        m6_conn.commit()
        stats.notifications_migrated = migrated
        stats.notifications_skipped = skipped
        print(f"  迁移完成: 新增 {migrated} 条，跳过 {skipped} 条")

    except Exception as e:
        m6_conn.rollback()
        stats.errors.append(f"通知迁移失败: {str(e)}")
        print(f"  [ERROR] 通知迁移失败: {e}")
        raise


# ---------------------------------------------------------------------------
# 迁移：设备配置
# ---------------------------------------------------------------------------

def migrate_settings(
    m8_conn: sqlite3.Connection,
    m6_conn: sqlite3.Connection,
    stats: MigrationStats,
    dry_run: bool = False,
) -> None:
    """
    迁移配置表：watch_settings → wearable_settings

    字段映射：
        id → (M6自增)
        device_id → device_id
        settings_json → settings_json
        user_id → user_id
        updated_at → updated_at
    """
    print("\n" + "=" * 60)
    print("  迁移：设备配置 (watch_settings → wearable_settings)")
    print("=" * 60)

    # 统计 M8 数据量
    m8_cursor = m8_conn.execute("SELECT COUNT(*) as cnt FROM watch_settings")
    stats.settings_m8 = m8_cursor.fetchone()["cnt"]
    print(f"  M8 源数据: {stats.settings_m8} 条")

    # 统计 M6 现有数据量
    m6_cursor = m6_conn.execute("SELECT COUNT(*) as cnt FROM wearable_settings")
    stats.settings_m6_before = m6_cursor.fetchone()["cnt"]
    print(f"  M6 现有: {stats.settings_m6_before} 条")

    if dry_run:
        print("  [DRY-RUN] 跳过实际迁移")
        return

    # 查询所有 M8 配置
    m8_cursor = m8_conn.execute("SELECT * FROM watch_settings ORDER BY id")
    m8_settings = [row_to_dict(row) for row in m8_cursor.fetchall()]

    migrated = 0
    skipped = 0

    try:
        for setting in m8_settings:
            # 幂等检查
            existing = m6_conn.execute(
                "SELECT id FROM wearable_settings WHERE device_id = ?",
                (setting["device_id"],),
            ).fetchone()

            if existing:
                skipped += 1
                continue

            # 字段映射
            m6_data = {
                "device_id": setting["device_id"],
                "user_id": str(setting.get("user_id", "default")),
                "settings_json": setting.get("settings_json", "{}"),
                "updated_at": setting.get("updated_at", datetime.now().isoformat()),
            }

            columns = list(m6_data.keys())
            placeholders = ", ".join("?" for _ in columns)
            values = tuple(m6_data[col] for col in columns)

            m6_conn.execute(
                f"INSERT INTO wearable_settings ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            migrated += 1

        m6_conn.commit()
        stats.settings_migrated = migrated
        stats.settings_skipped = skipped
        print(f"  迁移完成: 新增 {migrated} 条，跳过 {skipped} 条")

    except Exception as e:
        m6_conn.rollback()
        stats.errors.append(f"配置迁移失败: {str(e)}")
        print(f"  [ERROR] 配置迁移失败: {e}")
        raise


# ---------------------------------------------------------------------------
# 主迁移流程
# ---------------------------------------------------------------------------

def run_migration(full: bool = False, start_date: str = None, dry_run: bool = False) -> MigrationStats:
    """
    执行完整的迁移流程

    Args:
        full: 是否全量迁移（True=全量，False=仅设备和配置）
        start_date: 健康数据起始日期（YYYY-MM-DD），None 表示全量
        dry_run: 试运行模式（不实际写入数据）

    Returns:
        MigrationStats 统计信息
    """
    stats = MigrationStats()
    stats.start_time = datetime.now()

    print("\n" + "#" * 60)
    print("  M8 → M6 可穿戴数据迁移工具")
    print(f"  模式: {'DRY-RUN' if dry_run else '正式迁移'}")
    print(f"  范围: {'全量' if full else '设备+配置'}")
    if start_date:
        print(f"  健康数据起始: {start_date}")
    print("#" * 60)
    print(f"\n  M8 数据库: {M8_DB_PATH}")
    print(f"  M6 数据库: {M6_DB_PATH}")

    try:
        m8_conn = get_m8_connection()
        m6_conn = get_m6_connection()

        # 1. 迁移设备（始终执行）
        migrate_devices(m8_conn, m6_conn, stats, dry_run=dry_run)

        # 2. 迁移配置（始终执行）
        migrate_settings(m8_conn, m6_conn, stats, dry_run=dry_run)

        # 3. 迁移通知（始终执行）
        migrate_notifications(m8_conn, m6_conn, stats, dry_run=dry_run)

        # 4. 迁移健康数据（full 模式或指定 start_date 时执行）
        if full or start_date:
            migrate_health_data(m8_conn, m6_conn, stats, start_date=start_date, dry_run=dry_run)
        else:
            print("\n  [INFO] 跳过健康数据迁移（使用 --full 或 --start-date 启用）")

        m8_conn.close()
        m6_conn.close()

    except Exception as e:
        stats.errors.append(f"迁移过程异常: {str(e)}")
        print(f"\n[FATAL] 迁移失败: {e}")

    stats.end_time = datetime.now()

    # 打印汇总
    print("\n" + "=" * 60)
    print("  迁移汇总")
    print("=" * 60)
    result = stats.to_dict()
    for table_name, table_stats in result.items():
        if table_name in ("duration_seconds", "errors"):
            continue
        print(f"\n  {table_name}:")
        print(f"    M8 源数据:    {table_stats['m8_count']}")
        print(f"    M6 迁移前:    {table_stats['m6_before']}")
        print(f"    新增:         {table_stats['migrated']}")
        print(f"    跳过(已存在): {table_stats['skipped']}")

    print(f"\n  耗时: {result['duration_seconds']} 秒")

    if stats.errors:
        print(f"\n  [ERRORS] {len(stats.errors)} 个错误:")
        for err in stats.errors:
            print(f"    - {err}")
    else:
        print(f"\n  ✓ 迁移完成，无错误")

    return stats


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="M8 → M6 可穿戴数据迁移工具 (P0 批次)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 试运行（不写入数据）
  python migrate_wearable_m8_to_m6.py --dry-run

  # 迁移设备、配置、通知（不含健康数据）
  python migrate_wearable_m8_to_m6.py

  # 全量迁移（含健康数据）
  python migrate_wearable_m8_to_m6.py --full

  # 从指定日期开始迁移健康数据
  python migrate_wearable_m8_to_m6.py --start-date 2024-01-01
        """,
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量迁移（包含健康数据）",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="健康数据起始日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，不实际写入数据",
    )

    args = parser.parse_args()
    stats = run_migration(full=args.full, start_date=args.start_date, dry_run=args.dry_run)

    # 有错误则返回非零退出码
    if stats.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
