"""
SQLAlchemy 迁移适配器
====================

为使用 SQLAlchemy 的模块提供标准迁移管理器实现。
替代各模块自建的 migration_manager，统一迁移接口。

核心组件：
- SQLAlchemyMigrationHistoryStore: 基于 SQLAlchemy 的迁移历史存储
- SQLAlchemyMigrationManager: SQLAlchemy 版迁移管理器
- ModuleMigrationManager: 模块级迁移管理器（推荐使用）

使用方式：
    from shared.data_access.sqlalchemy_migration import ModuleMigrationManager

    mgr = ModuleMigrationManager(
        engine=sa_engine,
        db_name="m12_security_shield",
        migrations_dir="/path/to/migrations",
    )
    mgr.migrate()  # 迁移到最新版本
"""

from __future__ import annotations

import os
import sys
import importlib.util
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from sqlalchemy import Column, Float, String, Text, create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .migration import (
    Migration,
    MigrationContext,
    MigrationHistoryStore,
    MigrationManager,
    MigrationRecord,
    MigrationStatus,
)


# ============================================================
# SQLAlchemy 迁移历史存储
# ============================================================

class SQLAlchemyMigrationHistoryStore(MigrationHistoryStore):
    """
    基于 SQLAlchemy 的迁移历史存储。

    使用单独的表存储迁移历史记录，
    与各模块业务表隔离。
    """

    TABLE_NAME = "_yunxi_migration_history"

    def __init__(self, engine: Any):
        """
        Args:
            engine: SQLAlchemy Engine 对象
        """
        self._engine = engine
        self._Base = declarative_base()
        self._SessionLocal = sessionmaker(bind=engine)
        self._model = self._create_model()

    def _create_model(self) -> Any:
        """创建迁移历史 ORM 模型"""

        class MigrationHistoryModel(self._Base):  # type: ignore
            __tablename__ = self.TABLE_NAME

            version = Column(String(64), primary_key=True)
            description = Column(String(500), nullable=False)
            status = Column(String(32), nullable=False)
            applied_at = Column(Float, default=0.0)
            rolled_back_at = Column(Float, nullable=True)
            duration_ms = Column(Float, default=0.0)
            checksum = Column(String(64), default="")
            error_message = Column(Text, default="")

        return MigrationHistoryModel

    def initialize(self) -> None:
        """初始化存储（建表）"""
        self._Base.metadata.create_all(bind=self._engine)

    def get_all(self) -> List[MigrationRecord]:
        """获取所有迁移记录"""
        with Session(self._engine) as session:
            rows = session.query(self._model).order_by(self._model.version).all()
            return [self._row_to_record(row) for row in rows]

    def get_by_version(self, version: str) -> Optional[MigrationRecord]:
        """按版本获取迁移记录"""
        with Session(self._engine) as session:
            row = session.query(self._model).filter(
                self._model.version == version
            ).first()
            return self._row_to_record(row) if row else None

    def save(self, record: MigrationRecord) -> None:
        """保存迁移记录"""
        with Session(self._engine) as session:
            existing = session.query(self._model).filter(
                self._model.version == record.version
            ).first()

            if existing:
                existing.description = record.description
                existing.status = record.status.value
                existing.applied_at = record.applied_at
                existing.rolled_back_at = record.rolled_back_at
                existing.duration_ms = record.duration_ms
                existing.checksum = record.checksum
                existing.error_message = record.error_message
            else:
                new_row = self._model(
                    version=record.version,
                    description=record.description,
                    status=record.status.value,
                    applied_at=record.applied_at,
                    rolled_back_at=record.rolled_back_at,
                    duration_ms=record.duration_ms,
                    checksum=record.checksum,
                    error_message=record.error_message,
                )
                session.add(new_row)

            session.commit()

    def get_applied_versions(self) -> List[str]:
        """获取已应用的版本列表（按顺序）"""
        with Session(self._engine) as session:
            rows = session.query(self._model).filter(
                self._model.status == MigrationStatus.APPLIED.value
            ).order_by(self._model.version).all()
            return [row.version for row in rows]

    def _row_to_record(self, row: Any) -> MigrationRecord:
        return MigrationRecord(
            version=row.version,
            description=row.description,
            status=MigrationStatus(row.status),
            applied_at=row.applied_at or 0.0,
            rolled_back_at=row.rolled_back_at,
            duration_ms=row.duration_ms or 0.0,
            checksum=row.checksum or "",
            error_message=row.error_message or "",
        )


# ============================================================
# 模块迁移管理器
# ============================================================

class ModuleMigrationManager:
    """
    模块级迁移管理器。

    封装了迁移历史存储、迁移脚本自动发现和执行逻辑，
    为各模块提供统一的迁移管理接口。

    迁移脚本规范：
    - 放置在 migrations/ 目录下
    - 文件名格式：{version}_{name}.py
      例如：001_initial.py, 002_add_email.py
    - 每个脚本定义一个 Migration 子类，实现 up/down 方法

    使用方式::

        from shared.data_access.sqlalchemy_migration import ModuleMigrationManager

        mgr = ModuleMigrationManager(
            engine=sa_engine,
            db_name="m12_security_shield",
            migrations_dir="backend/migrations",
        )

        # 迁移到最新版本
        result = mgr.migrate()

        # 回滚到指定版本
        mgr.rollback(target_version=0)

        # 查看状态
        status = mgr.get_status()
    """

    def __init__(
        self,
        engine: Any,
        db_name: str = "default",
        migrations_dir: Optional[str] = None,
    ):
        """
        初始化模块迁移管理器。

        Args:
            engine: SQLAlchemy Engine 对象
            db_name: 数据库/模块名称（用于标识）
            migrations_dir: 迁移脚本目录路径
        """
        self._engine = engine
        self._db_name = db_name
        self._migrations_dir = migrations_dir
        self._history_store = SQLAlchemyMigrationHistoryStore(engine)
        self._history_store.initialize()

        # 创建迁移上下文
        self._ctx = MigrationContext(
            backend=engine,
            extra={"db_name": db_name},
        )

        # 创建迁移管理器
        self._manager = MigrationManager(
            backend=engine,
            history_store=self._history_store,
        )
        self._manager._ctx = self._ctx

        # 迁移脚本缓存
        self._migrations_loaded = False

    # ============================================================
    #  迁移脚本加载
    # ============================================================

    def load_migrations(self, force_reload: bool = False) -> None:
        """
        加载迁移脚本。

        Args:
            force_reload: 是否强制重新加载
        """
        if self._migrations_loaded and not force_reload:
            return

        if not self._migrations_dir:
            return

        migrations_path = Path(self._migrations_dir)
        if not migrations_path.exists():
            return

        # 扫描并加载迁移脚本
        for file in sorted(migrations_path.glob("*.py")):
            if file.name.startswith("_"):
                continue  # 跳过 __init__.py 等

            try:
                migration_class = self._load_migration_file(file)
                if migration_class:
                    self._manager.register(migration_class)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to load migration %s: %s", file.name, e
                )

        self._migrations_loaded = True

    def _load_migration_file(self, file_path: Path) -> Optional[Type[Migration]]:
        """
        从文件加载迁移类。

        查找文件中继承自 Migration 的类。

        Args:
            file_path: 迁移脚本文件路径

        Returns:
            迁移类或 None
        """
        spec = importlib.util.spec_from_file_location(
            f"migration_{file_path.stem}", str(file_path)
        )
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 查找 Migration 子类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Migration)
                and attr is not Migration
            ):
                return attr

        return None

    # ============================================================
    #  迁移执行
    # ============================================================

    def migrate(
        self,
        target_version: Optional[str] = None,
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        执行数据库迁移。

        Args:
            target_version: 目标版本，None 表示最新版本
            force_reload: 是否强制重新加载迁移脚本

        Returns:
            迁移结果字典
        """
        self.load_migrations(force_reload=force_reload)

        start_time = time.time()
        from_version = self.get_current_version() or "0"

        records = self._manager.upgrade(target_version=target_version)

        to_version = self.get_current_version() or "0"
        success = all(r.status == MigrationStatus.APPLIED for r in records)
        failed_at = None
        error = None

        for r in records:
            if r.status == MigrationStatus.FAILED:
                failed_at = r.version
                error = r.error_message
                break

        return {
            "success": success,
            "from_version": from_version,
            "to_version": to_version,
            "applied_count": len([r for r in records if r.status == MigrationStatus.APPLIED]),
            "total_migrations": len(records),
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "failed_at": failed_at,
            "error": error,
            "records": records,
        }

    def rollback(
        self,
        target_version: str = "0",
        force_reload: bool = False,
    ) -> Dict[str, Any]:
        """
        回滚迁移。

        Args:
            target_version: 回滚到的版本号，"0" 表示回滚所有
            force_reload: 是否强制重新加载迁移脚本

        Returns:
            回滚结果字典
        """
        self.load_migrations(force_reload=force_reload)

        start_time = time.time()
        from_version = self.get_current_version() or "0"

        records = self._manager.rollback(target_version=target_version)

        to_version = self.get_current_version() or "0"
        success = all(r.status == MigrationStatus.ROLLED_BACK for r in records)

        return {
            "success": success,
            "from_version": from_version,
            "to_version": to_version,
            "rolled_back_count": len(records),
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "records": records,
        }

    # ============================================================
    #  状态查询
    # ============================================================

    def get_current_version(self) -> Optional[str]:
        """获取当前数据库版本"""
        return self._manager.get_current_version()

    def get_latest_version(self) -> Optional[str]:
        """获取最新迁移版本"""
        self.load_migrations()
        return self._manager.get_latest_version()

    def get_status(self) -> Dict[str, Any]:
        """获取迁移状态"""
        self.load_migrations()
        return self._manager.get_status()

    def get_history(self) -> List[MigrationRecord]:
        """获取迁移历史"""
        return self._manager.get_history()

    def get_pending_migrations(self) -> List[Migration]:
        """获取待执行的迁移"""
        self.load_migrations()
        return self._manager.get_pending_migrations()

    # ============================================================
    #  属性
    # ============================================================

    @property
    def engine(self) -> Any:
        """SQLAlchemy Engine"""
        return self._engine

    @property
    def db_name(self) -> str:
        """数据库名称"""
        return self._db_name

    @property
    def migrations_dir(self) -> Optional[str]:
        """迁移脚本目录"""
        return self._migrations_dir

    @property
    def manager(self) -> MigrationManager:
        """底层 MigrationManager"""
        return self._manager


# ============================================================
# 导出
# ============================================================

__all__ = [
    "SQLAlchemyMigrationHistoryStore",
    "ModuleMigrationManager",
]
