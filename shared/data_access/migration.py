"""
数据迁移框架（Migration Framework）
==================================

提供版本化的数据迁移能力，支持：
- 版本化迁移管理
- 升级（upgrade）和回滚（rollback）
- 迁移历史记录
- 自动检测迁移状态
- 迁移脚本自动发现

设计原则：
- 与具体后端解耦，通过 adapter 适配不同存储
- 幂等迁移，重复执行不会出错
- 详细的迁移审计日志
"""

from __future__ import annotations

import time
import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# 迁移状态枚举
# ============================================================

class MigrationStatus(str, Enum):
    """迁移状态"""
    PENDING = "pending"       # 待执行
    APPLIED = "applied"       # 已应用
    FAILED = "failed"         # 失败
    ROLLED_BACK = "rolled_back"  # 已回滚


# ============================================================
# 迁移上下文
# ============================================================

@dataclass
class MigrationContext:
    """
    迁移执行上下文。

    传递给迁移脚本的 up/down 方法，
    包含后端连接、日志记录器等。
    """
    backend: Any = None
    logger: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str) -> None:
        """记录迁移日志"""
        if self.logger:
            self.logger.info(f"[Migration] {message}")
        else:
            logger.info(f"[Migration] {message}")


# ============================================================
# 迁移基类
# ============================================================

class Migration(ABC):
    """
    迁移脚本基类。

    每个迁移脚本都应继承此类，实现 up 和 down 方法。

    示例：
        class AddEmailToUserMigration(Migration):
            version = "002"
            description = "为用户表添加 email 字段"

            def up(self, ctx: MigrationContext) -> bool:
                # 升级逻辑
                return True

            def down(self, ctx: MigrationContext) -> bool:
                # 回滚逻辑
                return True
    """

    #: 迁移版本号（唯一标识）
    version: str = ""

    #: 迁移描述
    description: str = ""

    #: 依赖的迁移版本列表
    depends_on: List[str] = []

    def __init__(self):
        if not self.version:
            raise ValueError(f"Migration {type(self).__name__} must define a version")

    @abstractmethod
    def up(self, ctx: MigrationContext) -> bool:
        """
        升级操作。

        Args:
            ctx: 迁移上下文

        Returns:
            是否成功
        """
        ...

    @abstractmethod
    def down(self, ctx: MigrationContext) -> bool:
        """
        回滚操作。

        Args:
            ctx: 迁移上下文

        Returns:
            是否成功
        """
        ...

    @property
    def checksum(self) -> str:
        """计算迁移脚本的校验和（用于检测篡改）"""
        content = f"{self.version}:{self.description}:{self.depends_on}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


# ============================================================
# 迁移记录
# ============================================================

@dataclass
class MigrationRecord:
    """迁移执行记录"""
    version: str
    description: str
    status: MigrationStatus
    applied_at: float = 0.0
    rolled_back_at: Optional[float] = None
    duration_ms: float = 0.0
    checksum: str = ""
    error_message: str = ""


# ============================================================
# 迁移历史存储（抽象）
# ============================================================

class MigrationHistoryStore(ABC):
    """
    迁移历史存储抽象。

    负责持久化迁移历史记录。
    """

    @abstractmethod
    def initialize(self) -> None:
        """初始化存储（建表等）"""
        ...

    @abstractmethod
    def get_all(self) -> List[MigrationRecord]:
        """获取所有迁移记录"""
        ...

    @abstractmethod
    def get_by_version(self, version: str) -> Optional[MigrationRecord]:
        """按版本获取迁移记录"""
        ...

    @abstractmethod
    def save(self, record: MigrationRecord) -> None:
        """保存迁移记录"""
        ...

    @abstractmethod
    def get_applied_versions(self) -> List[str]:
        """获取已应用的版本列表（按顺序）"""
        ...


# ============================================================
# 内存迁移历史存储
# ============================================================

class MemoryMigrationHistoryStore(MigrationHistoryStore):
    """内存实现的迁移历史存储（用于测试）"""

    def __init__(self):
        self._records: Dict[str, MigrationRecord] = {}

    def initialize(self) -> None:
        pass  # 内存存储无需初始化

    def get_all(self) -> List[MigrationRecord]:
        return sorted(self._records.values(), key=lambda r: r.version)

    def get_by_version(self, version: str) -> Optional[MigrationRecord]:
        return self._records.get(version)

    def save(self, record: MigrationRecord) -> None:
        self._records[record.version] = record

    def get_applied_versions(self) -> List[str]:
        return [
            r.version
            for r in self._records.values()
            if r.status == MigrationStatus.APPLIED
        ]


# ============================================================
# SQLite 迁移历史存储
# ============================================================

class SQLiteMigrationHistoryStore(MigrationHistoryStore):
    """基于 SQLite 的迁移历史存储"""

    TABLE_NAME = "_yunxi_migration_history"

    def __init__(self, conn_provider: Any):
        """
        Args:
            conn_provider: 提供 SQLite 连接的对象（需有 get_connection 方法）
        """
        self._conn_provider = conn_provider

    def initialize(self) -> None:
        """创建迁移历史表"""
        sql = f"""
        CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            applied_at REAL,
            rolled_back_at REAL,
            duration_ms REAL,
            checksum TEXT,
            error_message TEXT
        )
        """
        with self._conn_provider.get_connection(write=True) as conn:
            conn.execute(sql)

    def get_all(self) -> List[MigrationRecord]:
        sql = f"SELECT * FROM {self.TABLE_NAME} ORDER BY version"
        with self._conn_provider.get_connection(write=False) as conn:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            return [self._row_to_record(dict(row)) for row in rows]

    def get_by_version(self, version: str) -> Optional[MigrationRecord]:
        sql = f"SELECT * FROM {self.TABLE_NAME} WHERE version = ?"
        with self._conn_provider.get_connection(write=False) as conn:
            cursor = conn.execute(sql, (version,))
            row = cursor.fetchone()
            if row:
                return self._row_to_record(dict(row))
        return None

    def save(self, record: MigrationRecord) -> None:
        sql = f"""
        INSERT OR REPLACE INTO {self.TABLE_NAME}
        (version, description, status, applied_at, rolled_back_at, duration_ms, checksum, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._conn_provider.get_connection(write=True) as conn:
            conn.execute(sql, (
                record.version,
                record.description,
                record.status.value,
                record.applied_at,
                record.rolled_back_at,
                record.duration_ms,
                record.checksum,
                record.error_message,
            ))

    def get_applied_versions(self) -> List[str]:
        sql = f"SELECT version FROM {self.TABLE_NAME} WHERE status = 'applied' ORDER BY version"
        with self._conn_provider.get_connection(write=False) as conn:
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            return [dict(row)["version"] for row in rows]

    def _row_to_record(self, row: Dict[str, Any]) -> MigrationRecord:
        return MigrationRecord(
            version=row["version"],
            description=row["description"],
            status=MigrationStatus(row["status"]),
            applied_at=row.get("applied_at") or 0.0,
            rolled_back_at=row.get("rolled_back_at"),
            duration_ms=row.get("duration_ms") or 0.0,
            checksum=row.get("checksum") or "",
            error_message=row.get("error_message") or "",
        )


# ============================================================
# 迁移管理器
# ============================================================

class MigrationManager:
    """
    迁移管理器。

    管理所有迁移脚本的注册、执行和回滚。

    使用方式：
        manager = MigrationManager(backend, history_store)
        manager.register(MyMigration)
        manager.upgrade()  # 升级到最新版本
        manager.rollback() # 回滚上一个版本
    """

    def __init__(
        self,
        backend: Any = None,
        history_store: Optional[MigrationHistoryStore] = None,
    ):
        self._backend = backend
        self._migrations: Dict[str, Migration] = {}
        self._history_store = history_store or MemoryMigrationHistoryStore()
        self._history_store.initialize()
        self._ctx = MigrationContext(backend=backend, logger=logger)

    def register(self, migration_class: Type[Migration]) -> None:
        """
        注册迁移类。

        Args:
            migration_class: 迁移类
        """
        migration = migration_class()
        if migration.version in self._migrations:
            raise ValueError(f"Migration version {migration.version} already registered")
        self._migrations[migration.version] = migration

    def register_many(self, migration_classes: List[Type[Migration]]) -> None:
        """批量注册迁移"""
        for mc in migration_classes:
            self.register(mc)

    def get_migration(self, version: str) -> Optional[Migration]:
        """获取指定版本的迁移"""
        return self._migrations.get(version)

    def get_all_migrations(self) -> List[Migration]:
        """获取所有已注册的迁移（按版本排序）"""
        return sorted(self._migrations.values(), key=lambda m: m.version)

    def get_pending_migrations(self) -> List[Migration]:
        """获取待执行的迁移列表"""
        applied = set(self._history_store.get_applied_versions())
        pending = [
            m for m in self.get_all_migrations()
            if m.version not in applied
        ]
        return pending

    def get_current_version(self) -> Optional[str]:
        """获取当前数据库版本（最新应用的版本）"""
        applied = self._history_store.get_applied_versions()
        return applied[-1] if applied else None

    def get_latest_version(self) -> Optional[str]:
        """获取最新的迁移版本"""
        all_migrations = self.get_all_migrations()
        return all_migrations[-1].version if all_migrations else None

    def upgrade(self, target_version: Optional[str] = None) -> List[MigrationRecord]:
        """
        升级数据库。

        Args:
            target_version: 目标版本，None 表示升级到最新

        Returns:
            执行的迁移记录列表
        """
        pending = self.get_pending_migrations()

        # 过滤到目标版本
        if target_version:
            pending = [m for m in pending if m.version <= target_version]

        executed: List[MigrationRecord] = []

        for migration in pending:
            record = self._apply_migration(migration)
            executed.append(record)

            if record.status == MigrationStatus.FAILED:
                logger.error(
                    f"Migration {migration.version} failed: {record.error_message}"
                )
                break

        return executed

    def rollback(self, target_version: Optional[str] = None) -> List[MigrationRecord]:
        """
        回滚数据库。

        Args:
            target_version: 回滚到的版本，None 表示回滚上一个版本

        Returns:
            回滚的迁移记录列表
        """
        applied = self._history_store.get_applied_versions()
        if not applied:
            return []

        # 确定要回滚的版本
        if target_version is None:
            # 回滚上一个版本
            versions_to_rollback = [applied[-1]]
        else:
            # 回滚到目标版本之后的所有版本
            versions_to_rollback = [
                v for v in applied if v > target_version
            ]
            versions_to_rollback.reverse()

        rolled_back: List[MigrationRecord] = []

        for version in versions_to_rollback:
            migration = self._migrations.get(version)
            if not migration:
                logger.warning(f"Migration {version} not found, skipping rollback")
                continue

            record = self._rollback_migration(migration)
            rolled_back.append(record)

            if record.status != MigrationStatus.ROLLED_BACK:
                logger.error(
                    f"Rollback of migration {version} failed: {record.error_message}"
                )
                break

        return rolled_back

    def _apply_migration(self, migration: Migration) -> MigrationRecord:
        """执行单个迁移"""
        start_time = time.time()
        record = MigrationRecord(
            version=migration.version,
            description=migration.description,
            status=MigrationStatus.PENDING,
            checksum=migration.checksum,
        )

        try:
            self._ctx.log(f"Applying migration {migration.version}: {migration.description}")
            success = migration.up(self._ctx)
            duration = (time.time() - start_time) * 1000

            if success:
                record.status = MigrationStatus.APPLIED
                record.applied_at = time.time()
                record.duration_ms = duration
                self._ctx.log(
                    f"Migration {migration.version} applied successfully ({duration:.1f}ms)"
                )
            else:
                record.status = MigrationStatus.FAILED
                record.error_message = "Migration returned False"

        except Exception as e:
            record.status = MigrationStatus.FAILED
            record.error_message = str(e)
            record.duration_ms = (time.time() - start_time) * 1000
            logger.exception(f"Migration {migration.version} failed with exception")

        self._history_store.save(record)
        return record

    def _rollback_migration(self, migration: Migration) -> MigrationRecord:
        """回滚单个迁移"""
        start_time = time.time()
        existing = self._history_store.get_by_version(migration.version)

        record = MigrationRecord(
            version=migration.version,
            description=migration.description,
            status=MigrationStatus.APPLIED,
            checksum=migration.checksum,
            applied_at=existing.applied_at if existing else 0.0,
        )

        try:
            self._ctx.log(f"Rolling back migration {migration.version}: {migration.description}")
            success = migration.down(self._ctx)
            duration = (time.time() - start_time) * 1000

            if success:
                record.status = MigrationStatus.ROLLED_BACK
                record.rolled_back_at = time.time()
                record.duration_ms = duration
                self._ctx.log(
                    f"Migration {migration.version} rolled back successfully ({duration:.1f}ms)"
                )
            else:
                record.status = MigrationStatus.FAILED
                record.error_message = "Rollback returned False"

        except Exception as e:
            record.status = MigrationStatus.FAILED
            record.error_message = f"Rollback error: {str(e)}"
            record.duration_ms = (time.time() - start_time) * 1000
            logger.exception(f"Rollback of migration {migration.version} failed")

        self._history_store.save(record)
        return record

    def get_history(self) -> List[MigrationRecord]:
        """获取完整迁移历史"""
        return self._history_store.get_all()

    def get_status(self) -> Dict[str, Any]:
        """获取迁移状态摘要"""
        all_migrations = self.get_all_migrations()
        applied = self._history_store.get_applied_versions()
        pending = self.get_pending_migrations()

        return {
            "total_migrations": len(all_migrations),
            "applied_count": len(applied),
            "pending_count": len(pending),
            "current_version": self.get_current_version(),
            "latest_version": self.get_latest_version(),
            "is_up_to_date": len(pending) == 0,
            "pending_versions": [m.version for m in pending],
            "applied_versions": applied,
        }


# ============================================================
# 全局单例
# ============================================================

_migration_manager: Optional[MigrationManager] = None


def get_migration_manager(
    backend: Any = None,
    history_store: Optional[MigrationHistoryStore] = None,
) -> MigrationManager:
    """获取迁移管理器单例"""
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = MigrationManager(backend=backend, history_store=history_store)
    return _migration_manager


def reset_migration_manager() -> None:
    """重置迁移管理器（测试用）"""
    global _migration_manager
    _migration_manager = None
