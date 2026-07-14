"""
SQLite 数据库版本化迁移管理器

参考 M4 migration.py 实现风格，基于 schema_version 表实现轻量级数据库版本管理，
支持增量迁移、版本追踪和迁移历史记录。

与 M4 的区别：
- 使用原生 sqlite3 而非 sqlalchemy，与 M5 现有代码风格一致
- 使用 schema_version 表跟踪版本（而非 PRAGMA user_version）
- 每个数据库有独立的版本表

使用方式::

    from tide_memory.db.migration import DatabaseMigrator, Migration

    migrator = DatabaseMigrator(db_path="./data/memory/l1_shallow.db")
    migrator.register_migration(Migration(
        version=1,
        name="initial_schema",
        up_sql=["CREATE TABLE ..."],
    ))
    migrator.migrate()
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

from .connection import get_connection

logger = structlog.get_logger(__name__)


# ============================================================
# 迁移记录数据类
# ============================================================

@dataclass
class Migration:
    """
    单个迁移定义

    Attributes:
        version: 目标版本号（正整数，从 1 开始）
        name: 迁移名称，用于日志和记录
        up_sql: 升级 SQL 语句列表
        down_sql: 降级 SQL 语句列表（可选）
        up_func: 升级时执行的 Python 函数（可选），参数为 sqlite3.Connection
        down_func: 降级时执行的 Python 函数（可选）
    """
    version: int
    name: str
    up_sql: List[str] = field(default_factory=list)
    down_sql: List[str] = field(default_factory=list)
    up_func: Optional[Callable[[sqlite3.Connection], Any]] = None
    down_func: Optional[Callable[[sqlite3.Connection], Any]] = None


# ============================================================
# 迁移管理器
# ============================================================

class DatabaseMigrator:
    """
    SQLite 数据库版本化迁移管理器

    使用 schema_version 表跟踪当前数据库版本，
    按版本号顺序执行增量迁移。

    每个数据库文件有独立的版本表和迁移日志，互不干扰。

    Args:
        db_path: 数据库文件路径
        migrations: 预注册的迁移列表
    """

    # 版本表名
    VERSION_TABLE = "schema_version"
    # 迁移日志表名
    LOG_TABLE = "_migration_log"

    def __init__(
        self,
        db_path: str,
        migrations: Optional[List[Migration]] = None,
    ):
        self.db_path = db_path
        self._migrations: Dict[int, Migration] = {}

        if migrations:
            for m in migrations:
                self.register_migration(m)

    # ============================================================
    # 迁移注册
    # ============================================================

    def register_migration(self, migration: Migration) -> None:
        """
        注册一个迁移

        Args:
            migration: 迁移定义

        Raises:
            ValueError: 版本号已存在或无效
        """
        if migration.version in self._migrations:
            raise ValueError(
                f"Migration version {migration.version} already exists"
            )
        if migration.version <= 0:
            raise ValueError(
                f"Migration version must be positive, got {migration.version}"
            )
        self._migrations[migration.version] = migration
        logger.debug(
            "migration.registered",
            db_path=self.db_path,
            version=migration.version,
            name=migration.name,
        )

    def register(
        self,
        version: int,
        name: str,
        up_sql: Optional[List[str]] = None,
        down_sql: Optional[List[str]] = None,
        up_func: Optional[Callable[[sqlite3.Connection], Any]] = None,
        down_func: Optional[Callable[[sqlite3.Connection], Any]] = None,
    ) -> None:
        """
        便捷注册迁移的方法

        Args:
            version: 目标版本号
            name: 迁移名称
            up_sql: 升级 SQL 语句列表
            down_sql: 降级 SQL 语句列表
            up_func: 升级时执行的 Python 函数
            down_func: 降级时执行的 Python 函数
        """
        self.register_migration(Migration(
            version=version,
            name=name,
            up_sql=up_sql or [],
            down_sql=down_sql or [],
            up_func=up_func,
            down_func=down_func,
        ))

    # ============================================================
    # 版本查询
    # ============================================================

    @property
    def latest_version(self) -> int:
        """
        获取最新已注册的版本号

        Returns:
            最新版本号，无迁移则返回 0
        """
        if not self._migrations:
            return 0
        return max(self._migrations.keys())

    def get_current_version(self) -> int:
        """
        获取当前数据库版本

        Returns:
            当前版本号，新数据库或版本表不存在时返回 0
        """
        try:
            with get_connection(self.db_path, apply_pragmas=False) as conn:
                # 检查表是否存在
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (self.VERSION_TABLE,),
                )
                if not cursor.fetchone():
                    return 0

                cursor = conn.execute(
                    f"SELECT version FROM {self.VERSION_TABLE} LIMIT 1"
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except sqlite3.Error as e:
            logger.warning(
                "migration.get_version_failed",
                db_path=self.db_path,
                error=str(e),
            )
            return 0

    def _set_version(self, conn: sqlite3.Connection, version: int) -> None:
        """
        设置数据库版本

        Args:
            conn: 数据库连接
            version: 新版本号
        """
        conn.execute(
            f"INSERT OR REPLACE INTO {self.VERSION_TABLE} (id, version) VALUES (1, ?)",
            (version,),
        )

    # ============================================================
    # 版本表与日志表
    # ============================================================

    def _ensure_version_table(self, conn: sqlite3.Connection) -> None:
        """
        确保版本表存在

        Args:
            conn: 数据库连接
        """
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.VERSION_TABLE} (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL DEFAULT 0
            )
        """)
        # 确保有一行记录
        cursor = conn.execute(
            f"SELECT COUNT(*) FROM {self.VERSION_TABLE}"
        )
        if cursor.fetchone()[0] == 0:
            conn.execute(
                f"INSERT INTO {self.VERSION_TABLE} (id, version) VALUES (1, 0)"
            )

    def _ensure_migration_log_table(self, conn: sqlite3.Connection) -> None:
        """
        确保迁移日志表存在

        Args:
            conn: 数据库连接
        """
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.LOG_TABLE} (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  REAL NOT NULL,
                duration_ms REAL DEFAULT 0
            )
        """)

    def _log_migration(
        self,
        conn: sqlite3.Connection,
        version: int,
        name: str,
        duration_ms: float,
    ) -> None:
        """
        记录迁移执行日志

        Args:
            conn: 数据库连接
            version: 版本号
            name: 迁移名称
            duration_ms: 执行耗时（毫秒）
        """
        conn.execute(
            f"INSERT OR REPLACE INTO {self.LOG_TABLE} "
            f"(version, name, applied_at, duration_ms) "
            f"VALUES (?, ?, ?, ?)",
            (version, name, time.time(), duration_ms),
        )

    # ============================================================
    # 迁移执行
    # ============================================================

    def migrate(self, target_version: Optional[int] = None) -> Dict[str, Any]:
        """
        执行迁移到指定版本

        如果当前版本低于目标版本，执行升级迁移。
        默认升级到最新已注册版本。

        Args:
            target_version: 目标版本号，None 表示升级到最新

        Returns:
            迁移结果字典，包含 from_version, to_version, applied 列表

        Raises:
            ValueError: 目标版本不存在
            RuntimeError: 迁移执行失败
        """
        target = target_version or self.latest_version

        if target > self.latest_version:
            raise ValueError(
                f"Target version {target} exceeds latest registered "
                f"version {self.latest_version}"
            )

        # 确保数据库目录存在
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        current_version = self.get_current_version()

        if current_version == target:
            logger.info(
                "migration.already_at_target",
                db_path=self.db_path,
                version=target,
            )
            return {
                "from_version": current_version,
                "to_version": target,
                "applied": [],
                "status": "already_at_target",
            }

        if current_version > target:
            raise RuntimeError(
                f"Downgrade not supported. "
                f"Current={current_version}, target={target}"
            )

        # 按版本号升序执行迁移
        applied: List[Dict[str, Any]] = []
        with get_connection(self.db_path, apply_pragmas=False) as conn:
            self._ensure_version_table(conn)
            self._ensure_migration_log_table(conn)

            for version in sorted(self._migrations.keys()):
                if version <= current_version:
                    continue
                if version > target:
                    break

                migration = self._migrations[version]
                start_time = time.time()

                try:
                    # 执行 SQL 升级
                    for sql in migration.up_sql:
                        conn.execute(sql)

                    # 执行 Python 升级函数
                    if migration.up_func:
                        migration.up_func(conn)

                    # 更新版本号
                    self._set_version(conn, version)

                    duration_ms = (time.time() - start_time) * 1000

                    # 记录迁移日志
                    self._log_migration(conn, version, migration.name, duration_ms)

                    conn.commit()

                    applied.append({
                        "version": version,
                        "name": migration.name,
                        "duration_ms": round(duration_ms, 2),
                    })

                    logger.info(
                        "migration.applied",
                        db_path=self.db_path,
                        version=version,
                        name=migration.name,
                        duration_ms=round(duration_ms, 2),
                    )

                except Exception as e:
                    conn.rollback()
                    logger.error(
                        "migration.failed",
                        db_path=self.db_path,
                        version=version,
                        name=migration.name,
                        error=str(e),
                    )
                    raise RuntimeError(
                        f"Migration {version} ({migration.name}) failed: {e}"
                    ) from e

            logger.info(
                "migration.complete",
                from_version=current_version,
                to_version=target,
                applied_count=len(applied),
                db_path=self.db_path,
            )

            return {
                "from_version": current_version,
                "to_version": target,
                "applied": applied,
                "status": "success",
            }

    # ============================================================
    # 迁移历史
    # ============================================================

    def get_migration_history(self) -> List[Dict[str, Any]]:
        """
        获取迁移历史记录

        Returns:
            迁移历史列表，按版本号升序排列
        """
        try:
            with get_connection(self.db_path, apply_pragmas=False) as conn:
                # 检查表是否存在
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (self.LOG_TABLE,),
                )
                if not cursor.fetchone():
                    return []

                cursor = conn.execute(
                    f"SELECT version, name, applied_at, duration_ms "
                    f"FROM {self.LOG_TABLE} ORDER BY version ASC"
                )
                rows = cursor.fetchall()
                return [
                    {
                        "version": row[0],
                        "name": row[1],
                        "applied_at": row[2],
                        "duration_ms": row[3],
                    }
                    for row in rows
                ]
        except sqlite3.Error:
            return []

    # ============================================================
    # 状态验证
    # ============================================================

    def validate(self) -> Dict[str, Any]:
        """
        验证数据库状态

        Returns:
            验证结果字典
        """
        current = self.get_current_version()
        latest = self.latest_version
        history = self.get_migration_history()

        return {
            "current_version": current,
            "latest_registered_version": latest,
            "is_up_to_date": current == latest,
            "needs_migration": current < latest,
            "migration_history_count": len(history),
            "db_path": self.db_path,
        }

    # ============================================================
    # 初始化检测
    # ============================================================

    def is_initialized(self) -> bool:
        """
        检查迁移系统是否已初始化

        Returns:
            如果版本表存在则返回 True，否则返回 False
        """
        try:
            with get_connection(self.db_path, apply_pragmas=False) as conn:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (self.VERSION_TABLE,),
                )
                return cursor.fetchone() is not None
        except sqlite3.Error:
            return False


# vim: set et ts=4 sw=4:
