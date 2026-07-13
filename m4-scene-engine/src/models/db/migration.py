"""SQLite 数据库版本化迁移管理器.

基于 ``PRAGMA user_version`` 实现轻量级数据库版本管理，
支持增量迁移、版本回退检查和迁移历史记录。

使用方式::

    from src.models.db.migration import DatabaseMigrator, Migration

    migrator = DatabaseMigrator(db_path="./data/m4.db")
    migrator.register_migration(Migration(
        version=1,
        name="initial_schema",
        up_sql=["CREATE TABLE ..."],
    ))
    migrator.migrate()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 迁移记录数据类
# ---------------------------------------------------------------------------

@dataclass
class Migration:
    """单个迁移定义.

    Attributes:
        version: 目标版本号（正整数，从 1 开始）.
        name: 迁移名称，用于日志和记录.
        up_sql: 升级 SQL 语句列表.
        down_sql: 降级 SQL 语句列表（可选）.
        up_func: 升级时执行的 Python 函数（可选）.
        down_func: 降级时执行的 Python 函数（可选）.
    """
    version: int
    name: str
    up_sql: list[str] = field(default_factory=list)
    down_sql: list[str] = field(default_factory=list)
    up_func: Callable[[Any], Any] | None = None  # 参数为 sqlalchemy Connection
    down_func: Callable[[Any], Any] | None = None


# ---------------------------------------------------------------------------
# 迁移管理器
# ---------------------------------------------------------------------------

class DatabaseMigrator:
    """SQLite 数据库版本化迁移管理器.

    使用 ``PRAGMA user_version`` 跟踪当前数据库版本，
    按版本号顺序执行增量迁移。

    Args:
        db_path: 数据库文件路径.
        migrations: 预注册的迁移列表.
    """

    def __init__(
        self,
        db_path: str,
        migrations: list[Migration] | None = None,
    ):
        self.db_path = db_path
        self._migrations: dict[int, Migration] = {}

        if migrations:
            for m in migrations:
                self.register_migration(m)

    def register_migration(self, migration: Migration) -> None:
        """注册一个迁移.

        Args:
            migration: 迁移定义.

        Raises:
            ValueError: 版本号已存在或无效.
        """
        if migration.version in self._migrations:
            raise ValueError(f"Migration version {migration.version} already exists")
        if migration.version <= 0:
            raise ValueError(f"Migration version must be positive, got {migration.version}")
        self._migrations[migration.version] = migration

    def register(
        self,
        version: int,
        name: str,
        up_sql: list[str] | None = None,
        down_sql: list[str] | None = None,
        up_func: Callable[[Any], Any] | None = None,
        down_func: Callable[[Any], Any] | None = None,
    ) -> None:
        """便捷注册迁移的方法.

        Args:
            version: 目标版本号.
            name: 迁移名称.
            up_sql: 升级 SQL 语句列表.
            down_sql: 降级 SQL 语句列表.
            up_func: 升级时执行的 Python 函数.
            down_func: 降级时执行的 Python 函数.
        """
        self.register_migration(Migration(
            version=version,
            name=name,
            up_sql=up_sql or [],
            down_sql=down_sql or [],
            up_func=up_func,
            down_func=down_func,
        ))

    @property
    def latest_version(self) -> int:
        """获取最新已注册的版本号.

        Returns:
            最新版本号，无迁移则返回 0.
        """
        if not self._migrations:
            return 0
        return max(self._migrations.keys())

    def get_current_version(self) -> int:
        """获取当前数据库版本.

        Returns:
            当前版本号，新数据库返回 0.
        """
        from sqlalchemy import text
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{self.db_path}")
        try:
            with engine.connect() as conn:
                result = conn.execute(text("PRAGMA user_version"))
                row = result.fetchone()
                return row[0] if row else 0
        finally:
            engine.dispose()

    def _set_version(self, conn: Any, version: int) -> None:
        """设置数据库版本.

        Args:
            conn: 数据库连接.
            version: 新版本号.
        """
        from sqlalchemy import text
        conn.execute(text(f"PRAGMA user_version = {version}"))

    def _ensure_migration_log_table(self, conn: Any) -> None:
        """确保迁移日志表存在.

        Args:
            conn: 数据库连接.
        """
        from sqlalchemy import text
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS _migration_log (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  REAL NOT NULL,
                duration_ms REAL DEFAULT 0
            )
            """
        ))

    def _log_migration(
        self,
        conn: Any,
        version: int,
        name: str,
        duration_ms: float,
    ) -> None:
        """记录迁移执行日志.

        Args:
            conn: 数据库连接.
            version: 版本号.
            name: 迁移名称.
            duration_ms: 执行耗时（毫秒）.
        """
        from sqlalchemy import text
        conn.execute(
            text(
                "INSERT OR REPLACE INTO _migration_log "
                "(version, name, applied_at, duration_ms) "
                "VALUES (:version, :name, :applied_at, :duration_ms)"
            ),
            {
                "version": version,
                "name": name,
                "applied_at": time.time(),
                "duration_ms": duration_ms,
            },
        )

    def migrate(self, target_version: int | None = None) -> dict[str, Any]:
        """执行迁移到指定版本.

        如果当前版本低于目标版本，执行升级迁移。
        默认升级到最新已注册版本。

        Args:
            target_version: 目标版本号，None 表示升级到最新.

        Returns:
            迁移结果字典，包含 from_version, to_version, applied 列表.

        Raises:
            ValueError: 目标版本不存在.
            RuntimeError: 迁移执行失败.
        """
        from sqlalchemy import text
        from sqlalchemy import create_engine

        target = target_version or self.latest_version

        if target > self.latest_version:
            raise ValueError(
                f"Target version {target} exceeds latest registered version {self.latest_version}"
            )

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
                f"Downgrade not supported. Current={current_version}, target={target}"
            )

        # 按版本号升序执行迁移
        applied: list[dict[str, Any]] = []
        engine = create_engine(f"sqlite:///{self.db_path}")
        try:
            with engine.begin() as conn:
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
                            conn.execute(text(sql))

                        # 执行 Python 升级函数
                        if migration.up_func:
                            migration.up_func(conn)

                        # 更新版本号
                        self._set_version(conn, version)

                        duration_ms = (time.time() - start_time) * 1000

                        # 记录迁移日志
                        self._log_migration(conn, version, migration.name, duration_ms)

                        applied.append({
                            "version": version,
                            "name": migration.name,
                            "duration_ms": round(duration_ms, 2),
                        })

                        logger.info(
                            "migration.applied",
                            version=version,
                            name=migration.name,
                            duration_ms=round(duration_ms, 2),
                        )

                    except Exception as e:
                        logger.error(
                            "migration.failed",
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

        finally:
            engine.dispose()

    def get_migration_history(self) -> list[dict[str, Any]]:
        """获取迁移历史记录.

        Returns:
            迁移历史列表，按版本号升序排列.
        """
        from sqlalchemy import text
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{self.db_path}")
        try:
            with engine.connect() as conn:
                # 检查表是否存在
                result = conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='_migration_log'"
                ))
                if not result.fetchone():
                    return []

                result = conn.execute(text(
                    "SELECT version, name, applied_at, duration_ms "
                    "FROM _migration_log ORDER BY version ASC"
                ))
                rows = result.fetchall()
                return [
                    {
                        "version": row[0],
                        "name": row[1],
                        "applied_at": row[2],
                        "duration_ms": row[3],
                    }
                    for row in rows
                ]
        finally:
            engine.dispose()

    def validate(self) -> dict[str, Any]:
        """验证数据库状态.

        Returns:
            验证结果字典.
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
