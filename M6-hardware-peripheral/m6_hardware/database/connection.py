"""
M6 硬件外设 - 数据库连接管理

P1-5 改造：提供上下文管理器封装的事务连接，
支持自动建表与连接复用。

P1-08 优化：SQLite 性能增强
- WAL 模式提升读写并发
- 合理 cache_size 减少磁盘 IO
- busy_timeout 避免 database is locked
- 定期过期数据清理（TTL）

P2-6 改造：接入统一迁移框架
- 使用 shared.data_layer.migration.MigrationEngine 管理版本
- 使用 SQLiteMigrationAdapter 适配原生 sqlite3 连接
- 迁移脚本存放于 m6_hardware/database/migrations/
"""

import sqlite3
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# ============================================================================
# P1-08: SQLite 性能 PRAGMA 默认配置
# ============================================================================

DEFAULT_PRAGMAS = {
    "journal_mode": "WAL",          # WAL 模式：读写并发，读不阻塞写
    "synchronous": "NORMAL",        # 平衡安全与性能（WAL 模式下 NORMAL 足够安全）
    "cache_size": "-20000",         # 约 20MB 页缓存（负数表示 KB）
    "busy_timeout": "5000",         # 5 秒忙等待，避免 database is locked
    "foreign_keys": "ON",           # 外键约束
    "temp_store": "MEMORY",         # 临时表放内存
}

# 健康数据默认保留天数（TTL）
DEFAULT_HEALTH_TTL_DAYS = 90
# 通知数据默认保留天数
DEFAULT_NOTIFICATION_TTL_DAYS = 30


# ============================================================================
# 共享模块导入辅助
# ============================================================================

def _ensure_shared_path() -> None:
    """确保 shared 模块在 sys.path 中"""
    current = Path(__file__).resolve().parent
    # 向上查找 shared 目录
    for _ in range(5):
        shared_dir = current / "shared"
        if shared_dir.exists():
            project_root = str(current)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            return
        current = current.parent


def _import_migration_engine():
    """延迟导入迁移引擎，避免循环依赖"""
    _ensure_shared_path()
    from shared.data_layer.migration import (
        MigrationEngine,
        SQLiteMigrationAdapter,
    )
    return MigrationEngine, SQLiteMigrationAdapter


# ============================================================================
# 数据库连接上下文管理器
# ============================================================================

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
        # P1-08: 应用性能 PRAGMA
        _apply_pragmas(self._conn)
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


# ============================================================================
# 工具函数
# ============================================================================

def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """P1-08: 应用 SQLite 性能优化 PRAGMA"""
    cursor = conn.cursor()
    for key, value in DEFAULT_PRAGMAS.items():
        try:
            cursor.execute(f"PRAGMA {key} = {value}")
        except Exception as e:
            logger.warning(f"设置 PRAGMA {key} 失败: {e}")


def cleanup_expired_data(
    conn: sqlite3.Connection,
    *,
    health_ttl_days: int = DEFAULT_HEALTH_TTL_DAYS,
    notification_ttl_days: int = DEFAULT_NOTIFICATION_TTL_DAYS,
) -> Dict[str, int]:
    """P1-08 / P1-6-1: 清理过期数据（TTL）

    Args:
        conn: 数据库连接
        health_ttl_days: 健康数据保留天数
        notification_ttl_days: 通知数据保留天数

    Returns:
        各表删除的行数
    """
    cursor = conn.cursor()
    result = {}
    now = datetime.now()

    # 清理过期健康数据
    if health_ttl_days > 0:
        cutoff = (now - timedelta(days=health_ttl_days)).isoformat()
        cursor.execute(
            "DELETE FROM wearable_health_data WHERE recorded_at < ?",
            (cutoff,),
        )
        result["health_data_deleted"] = cursor.rowcount
        if cursor.rowcount > 0:
            logger.info(f"清理过期健康数据: {cursor.rowcount} 条 (保留 {health_ttl_days} 天)")

    # 清理过期通知
    if notification_ttl_days > 0:
        cutoff = (now - timedelta(days=notification_ttl_days)).isoformat()
        cursor.execute(
            "DELETE FROM wearable_notifications WHERE created_at < ?",
            (cutoff,),
        )
        result["notifications_deleted"] = cursor.rowcount
        if cursor.rowcount > 0:
            logger.info(f"清理过期通知: {cursor.rowcount} 条 (保留 {notification_ttl_days} 天)")

    conn.commit()
    return result


# ============================================================================
# P2-6: 统一迁移引擎接入
# ============================================================================

def get_migrations_dir() -> str:
    """获取 M6 迁移脚本目录的绝对路径"""
    return str(Path(__file__).parent / "migrations")


def run_migrations(db_path: str, *, skip_integrity_check: bool = True) -> Dict[str, Any]:
    """执行 M6 数据库迁移

    使用统一的 MigrationEngine + SQLiteMigrationAdapter 执行迁移，
    自动扫描 migrations/ 目录下的所有迁移脚本并按版本号顺序执行。

    Args:
        db_path: 数据库文件路径
        skip_integrity_check: 是否跳过迁移前完整性检查（SQLite 一般不需要）

    Returns:
        迁移结果字典，包含 success、from_version、to_version、applied_count 等
    """
    MigrationEngine, SQLiteMigrationAdapter = _import_migration_engine()

    # 确保目录存在
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    # 创建原生连接（用于适配器）
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        _apply_pragmas(conn)

        # 使用 SQLiteMigrationAdapter 适配原生连接
        adapter = SQLiteMigrationAdapter(conn, db_path=db_path)

        # 创建迁移引擎
        engine = MigrationEngine(db_manager=adapter)

        # 扫描迁移文件
        migrations_dir = get_migrations_dir()
        migrations = engine.scan_migrations(migrations_dir)

        if not migrations:
            logger.warning("未找到任何迁移脚本")
            return {
                "success": True,
                "from_version": 0,
                "to_version": 0,
                "applied_count": 0,
                "applied_versions": [],
                "message": "no migrations found",
            }

        # 执行迁移
        result = engine.migrate(
            db_name="m6_sensors",
            migrations=migrations,
            skip_integrity_check=skip_integrity_check,
        )

        if result.get("success"):
            logger.info(
                f"M6 数据库迁移完成: v{result.get('from_version', 0)} "
                f"-> v{result.get('to_version', 0)} "
                f"(应用 {result.get('applied_count', 0)} 个迁移)"
            )
        else:
            logger.error(
                f"M6 数据库迁移失败: {result.get('error', 'unknown error')}"
            )

        return result

    finally:
        conn.close()


def get_current_schema_version(db_path: str) -> int:
    """获取当前数据库 schema 版本号

    Args:
        db_path: 数据库文件路径

    Returns:
        当前版本号，未初始化返回 0
    """
    MigrationEngine, SQLiteMigrationAdapter = _import_migration_engine()

    if not Path(db_path).exists():
        return 0

    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        adapter = SQLiteMigrationAdapter(conn, db_path=db_path)
        engine = MigrationEngine(db_manager=adapter)
        return engine.get_current_version("m6_sensors")
    except Exception:
        return 0
    finally:
        conn.close()


def get_migration_stats(db_path: str) -> Dict[str, Any]:
    """获取 M6 数据库迁移审计统计信息

    Args:
        db_path: 数据库文件路径

    Returns:
        迁移统计信息字典
    """
    MigrationEngine, SQLiteMigrationAdapter = _import_migration_engine()

    if not Path(db_path).exists():
        return {
            "total_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "current_version": 0,
            "migrations": [],
        }

    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        adapter = SQLiteMigrationAdapter(conn, db_path=db_path)
        engine = MigrationEngine(db_manager=adapter)
        return engine.get_migration_stats("m6_sensors")
    finally:
        conn.close()


# ============================================================================
# 向后兼容：保留 _init_tables 作为 fallback
# ============================================================================

def _init_tables(conn: sqlite3.Connection) -> None:
    """初始化数据库表结构（幂等）

    .. deprecated:: P2-6
        推荐使用 run_migrations() 统一管理数据库 schema。
        本函数作为向后兼容层保留，在迁移引擎不可用时作为 fallback。
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


# ============================================================================
# 工厂函数
# ============================================================================

def get_db(db_path: str, auto_init: bool = True) -> DatabaseConnection:
    """获取数据库连接工厂

    P2-6 改造：优先使用统一 MigrationEngine 执行迁移；
    如果迁移引擎不可用，则回退到 _init_tables() 直接建表，
    确保向后兼容。

    Args:
        db_path: SQLite 文件路径
        auto_init: 是否自动建表（默认 True）

    Returns:
        DatabaseConnection 实例（尚未打开连接，需配合 with 使用）
    """
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)

    if auto_init:
        # 优先使用统一迁移引擎
        try:
            run_migrations(db_path)
        except Exception as e:
            logger.warning(
                f"统一迁移引擎执行失败，回退到直接建表: {e}"
            )
            # fallback: 使用原有方式直接建表
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                _apply_pragmas(conn)
                _init_tables(conn)

    return DatabaseConnection(db_path)
