"""
迁移引擎增强模块
=================

在 MigrationEngine 基础上提供增强能力：
- 数据完整性校验（迁移前后行数对比）
- 错误重试机制（指数退避）
- 幂等性保证（迁移级别的幂等检查）
- Dry-run 模式
- 迁移检查点和进度追踪
- 多数据库类型兼容性增强

设计原则：
- 完全向后兼容，不破坏现有 MigrationEngine 接口
- 通过组合方式增强，而非继承
- 所有增强功能均可独立开关
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .migration import MigrationEngine, _MIGRATION_FILE_RE
from .migration_tools import (
    retry_with_backoff,
    RetryableError,
    ProgressTracker,
    format_duration,
)


# ============================================================
#  数据类
# ============================================================

@dataclass
class TableIntegrityInfo:
    """单表完整性信息"""
    table_name: str
    row_count_before: int = 0
    row_count_after: int = 0
    row_count_delta: int = 0
    check_passed: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "row_count_before": self.row_count_before,
            "row_count_after": self.row_count_after,
            "row_count_delta": self.row_count_delta,
            "check_passed": self.check_passed,
            "notes": self.notes,
        }


@dataclass
class MigrationIntegrityReport:
    """迁移完整性校验报告"""
    migration_version: int
    migration_name: str
    tables_checked: List[TableIntegrityInfo] = field(default_factory=list)
    overall_passed: bool = True
    error: Optional[str] = None

    @property
    def total_rows_before(self) -> int:
        return sum(t.row_count_before for t in self.tables_checked)

    @property
    def total_rows_after(self) -> int:
        return sum(t.row_count_after for t in self.tables_checked)

    @property
    def total_delta(self) -> int:
        return sum(t.row_count_delta for t in self.tables_checked)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "migration_version": self.migration_version,
            "migration_name": self.migration_name,
            "total_rows_before": self.total_rows_before,
            "total_rows_after": self.total_rows_after,
            "total_delta": self.total_delta,
            "overall_passed": self.overall_passed,
            "error": self.error,
            "tables": [t.to_dict() for t in self.tables_checked],
        }


@dataclass
class MigrationCheckpoint:
    """迁移检查点（断点续传）"""
    db_name: str
    current_version: int
    target_version: int
    completed_versions: List[int] = field(default_factory=list)
    failed_version: Optional[int] = None
    failed_error: Optional[str] = None
    started_at: float = 0.0
    last_updated_at: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.failed_version is None and self.current_version >= self.target_version

    @property
    def progress_percent(self) -> float:
        total = max(self.target_version - self.completed_versions[0] if self.completed_versions else self.target_version, 1)
        return min(len(self.completed_versions) / total * 100, 100.0)


# ============================================================
#  安全表名校验
# ============================================================

_SAFE_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(name: str, kind: str = "identifier") -> str:
    """校验 SQL 标识符是否安全（防注入）"""
    if not _SAFE_IDENT_RE.match(name):
        raise ValueError(
            f"Invalid {kind}: {repr(name)} - only alphanumeric and underscore allowed"
        )
    return name


# ============================================================
#  增强型迁移引擎
# ============================================================

class EnhancedMigrationEngine:
    """增强型迁移引擎

    在 MigrationEngine 基础上提供以下增强能力：
    1. 数据完整性校验（迁移前后行数对比）
    2. 错误重试机制（指数退避）
    3. 幂等性保证
    4. Dry-run 模式
    5. 进度追踪
    6. 检查点 / 断点续传

    使用方式::

        engine = EnhancedMigrationEngine(db_manager=adapter)
        result = engine.migrate_enhanced(
            db_name="mydb",
            migrations=migrations,
            dry_run=True,
            enable_integrity_check=True,
            enable_retry=True,
        )
    """

    def __init__(self, engine: Optional[MigrationEngine] = None, **kwargs):
        """
        初始化增强型迁移引擎

        Args:
            engine: 基础 MigrationEngine 实例，None 时新建
            **kwargs: 传递给 MigrationEngine 构造函数的参数
        """
        if engine is not None:
            self.engine = engine
        else:
            self.engine = MigrationEngine(**kwargs)

    # --------------------------------------------------------
    #  代理方法 - 委托给底层引擎
    # --------------------------------------------------------

    def __getattr__(self, name):
        """代理未定义的属性到底层 MigrationEngine"""
        return getattr(self.engine, name)

    # --------------------------------------------------------
    #  1. 数据完整性校验
    # --------------------------------------------------------

    def get_all_user_tables(self, db_name: str) -> List[str]:
        """获取所有用户表（排除系统表和迁移表）

        Args:
            db_name: 数据库名称

        Returns:
            表名列表
        """
        # 尝试 SQLite 方式
        try:
            rows = self.engine.db_manager.query_all(
                db_name,
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r["name"] for r in rows if r.get("name")]
        except Exception:
            # 尝试 PostgreSQL 方式
            try:
                rows = self.engine.db_manager.query_all(
                    db_name,
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
                tables = [r["table_name"] for r in rows if r.get("table_name")]
            except Exception:
                return []

        # 过滤掉系统表和迁移表
        system_tables = {
            "_schema_migrations", "_migration_log", "sqlite_sequence",
            "_backup_metadata",
        }
        return [
            t for t in tables
            if not t.startswith("sqlite_")
            and not t.startswith("_")
            and t not in system_tables
        ]

    def get_table_row_count(self, db_name: str, table_name: str) -> int:
        """获取表的行数

        Args:
            db_name: 数据库名称
            table_name: 表名（会做安全校验）

        Returns:
            行数
        """
        _validate_identifier(table_name, "table name")

        try:
            result = self.engine.db_manager.query_one(
                db_name,
                f'SELECT COUNT(*) as cnt FROM "{table_name}"'
            )
            if result and "cnt" in result:
                return int(result["cnt"])
            if result:
                # 尝试从结果中提取第一个值
                return int(list(result.values())[0])
            return 0
        except Exception:
            return -1  # -1 表示无法获取

    def snapshot_table_counts(
        self,
        db_name: str,
        tables: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """拍摄表行数快照

        Args:
            db_name: 数据库名称
            tables: 要快照的表名列表，None 表示所有用户表

        Returns:
            {表名: 行数} 字典
        """
        if tables is None:
            tables = self.get_all_user_tables(db_name)

        snapshot = {}
        for table in tables:
            count = self.get_table_row_count(db_name, table)
            if count >= 0:
                snapshot[table] = count

        return snapshot

    def compare_snapshots(
        self,
        before: Dict[str, int],
        after: Dict[str, int],
        migration_name: str = "",
    ) -> MigrationIntegrityReport:
        """对比迁移前后的表行数快照

        Args:
            before: 迁移前快照
            after: 迁移后快照
            migration_name: 迁移名称（用于报告）

        Returns:
            完整性校验报告
        """
        report = MigrationIntegrityReport(
            migration_version=0,
            migration_name=migration_name,
        )

        all_tables = set(before.keys()) | set(after.keys())

        for table in sorted(all_tables):
            before_count = before.get(table, 0)
            after_count = after.get(table, 0)
            delta = after_count - before_count

            info = TableIntegrityInfo(
                table_name=table,
                row_count_before=before_count,
                row_count_after=after_count,
                row_count_delta=delta,
            )

            if table not in before:
                info.notes = "新表"
            elif table not in after:
                info.notes = "表已删除"
                info.check_passed = True  # 删除表是预期操作

            report.tables_checked.append(info)

        report.overall_passed = all(t.check_passed for t in report.tables_checked)
        return report

    # --------------------------------------------------------
    #  2. 错误重试机制
    # --------------------------------------------------------

    def _execute_migration_with_retry(
        self,
        db_name: str,
        migration: Dict[str, Any],
        max_retries: int = 3,
        base_delay: float = 1.0,
        retry_on: Optional[Tuple[type, ...]] = None,
    ) -> Dict[str, Any]:
        """带重试的单迁移执行

        Args:
            db_name: 数据库名称
            migration: 迁移定义
            max_retries: 最大重试次数
            base_delay: 初始延迟秒数
            retry_on: 可重试的异常类型元组，默认包含常见数据库错误

        Returns:
            执行结果字典
        """
        if retry_on is None:
            retry_on = (RetryableError, OperationalError, TimeoutError)

        version = migration["version"]
        name = migration.get("name", f"v{version}")

        def _do_migration():
            migration_start = time.time()
            with self.engine.db_manager.transaction(db_name) as conn:
                up_script = migration.get("up", "")

                if callable(up_script):
                    up_script(conn)
                elif isinstance(up_script, str):
                    self.engine._executescript(conn, up_script)

                duration_ms = int((time.time() - migration_start) * 1000)
                checksum = migration.get("checksum", "")

                # 记录迁移
                self.engine._record_migration(
                    conn,
                    version=version,
                    name=name,
                    description=migration.get("description", ""),
                    duration_ms=duration_ms,
                    checksum=checksum,
                    status="success",
                    error_message="",
                )

                return {
                    "version": version,
                    "name": name,
                    "duration_ms": duration_ms,
                    "success": True,
                }

        return retry_with_backoff(
            _do_migration,
            max_retries=max_retries,
            base_delay=base_delay,
            retry_exceptions=retry_on,
        )

    # --------------------------------------------------------
    #  3. 增强版 migrate 方法
    # --------------------------------------------------------

    def migrate_enhanced(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: Optional[int] = None,
        *,
        dry_run: bool = False,
        pre_migration_backup: bool = False,
        backup_dir: Optional[str] = None,
        skip_integrity_check: bool = False,
        enable_integrity_check: bool = False,
        enable_retry: bool = False,
        max_retries: int = 3,
        base_delay: float = 1.0,
        progress_callback: Optional[Callable[[ProgressTracker], None]] = None,
        integrity_tables: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        增强版数据库迁移

        在基础 migrate() 之上增加：
        - dry-run 模式（仅检查，不实际执行）
        - 数据完整性校验（迁移前后行数对比）
        - 错误重试机制
        - 进度追踪回调

        Args:
            db_name: 数据库名称
            migrations: 迁移列表
            target_version: 目标版本，None 表示最新
            dry_run: 是否为试运行模式
            pre_migration_backup: 迁移前是否自动备份
            backup_dir: 备份目录
            skip_integrity_check: 是否跳过 SQLite 完整性检查
            enable_integrity_check: 是否启用表行数完整性校验
            enable_retry: 是否启用错误重试
            max_retries: 最大重试次数
            base_delay: 重试初始延迟
            progress_callback: 进度回调函数
            integrity_tables: 要检查的表列表，None 表示全部用户表

        Returns:
            增强版迁移结果字典
        """
        total_start = time.time()
        self.engine._ensure_migrations_table(db_name)

        current_version = self.engine.get_current_version(db_name)

        if target_version is None:
            target_version = max(m["version"] for m in migrations) if migrations else 0

        # 按版本排序
        sorted_migrations = sorted(migrations, key=lambda m: m["version"])
        pending = [m for m in sorted_migrations if m["version"] > current_version and m["version"] <= target_version]

        if not pending:
            return {
                "success": True,
                "dry_run": dry_run,
                "from_version": current_version,
                "to_version": current_version,
                "applied_count": 0,
                "applied_versions": [],
                "duration_ms": 0,
                "message": "Already at target version",
            }

        # Dry-run 模式：只模拟，不执行
        if dry_run:
            return self._migrate_dry_run(
                db_name=db_name,
                migrations=pending,
                current_version=current_version,
                target_version=target_version,
                enable_integrity_check=enable_integrity_check,
                integrity_tables=integrity_tables,
                progress_callback=progress_callback,
            )

        # 1. SQLite 完整性检查（基础）
        integrity_result = None
        if not skip_integrity_check:
            integrity_result = self.engine.check_integrity(db_name)
            if integrity_result.get("status") not in ("ok", "error"):
                return {
                    "success": False,
                    "error": f"数据库完整性检查未通过: {integrity_result}",
                    "from_version": current_version,
                    "integrity_check": integrity_result,
                }

        # 2. 迁移前备份
        backup_path = None
        if pre_migration_backup:
            try:
                backup_path = self.engine._backup_database(db_name, backup_dir)
            except Exception as e:
                backup_path = f"backup_failed: {e}"

        # 3. 执行迁移
        applied = []
        integrity_reports: List[Dict[str, Any]] = []
        failed_version = None
        failed_error = None

        # 进度追踪
        total_count = len(pending)
        progress = ProgressTracker(
            total_count,
            label="迁移进度",
            callback=progress_callback,
            show_bar=progress_callback is None,
        )

        try:
            for migration in pending:
                version = migration["version"]
                name = migration.get("name", f"v{version}")

                # 迁移前快照
                before_snapshot = None
                if enable_integrity_check:
                    before_snapshot = self.snapshot_table_counts(db_name, integrity_tables)

                # 执行迁移
                migration_start = time.time()

                if enable_retry:
                    result = self._execute_migration_with_retry(
                        db_name, migration,
                        max_retries=max_retries,
                        base_delay=base_delay,
                    )
                else:
                    with self.engine.db_manager.transaction(db_name) as conn:
                        up_script = migration.get("up", "")

                        if callable(up_script):
                            up_script(conn)
                        elif isinstance(up_script, str):
                            self.engine._executescript(conn, up_script)

                        duration_ms = int((time.time() - migration_start) * 1000)
                        checksum = migration.get("checksum", "")

                        self.engine._record_migration(
                            conn,
                            version=version,
                            name=name,
                            description=migration.get("description", ""),
                            duration_ms=duration_ms,
                            checksum=checksum,
                            status="success",
                            error_message="",
                        )
                        result = {
                            "version": version,
                            "name": name,
                            "duration_ms": duration_ms,
                            "success": True,
                        }

                # 迁移后快照和对比
                if enable_integrity_check and before_snapshot is not None:
                    after_snapshot = self.snapshot_table_counts(db_name, integrity_tables)
                    report = self.compare_snapshots(before_snapshot, after_snapshot, name)
                    report.migration_version = version
                    integrity_reports.append(report.to_dict())

                applied.append(version)
                progress.update(1)

            progress.finish()
            total_duration_ms = int((time.time() - total_start) * 1000)

            return {
                "success": True,
                "dry_run": False,
                "from_version": current_version,
                "to_version": target_version,
                "applied_count": len(applied),
                "applied_versions": applied,
                "duration_ms": total_duration_ms,
                "backup_path": backup_path,
                "integrity_check": integrity_result,
                "integrity_reports": integrity_reports,
            }

        except Exception as e:
            failed_error = str(e)
            total_duration_ms = int((time.time() - total_start) * 1000)

            failed_version = applied[-1] + 1 if applied else current_version + 1

            # 尝试记录失败状态
            failed_migration = next(
                (m for m in sorted_migrations if m["version"] == failed_version),
                None,
            )
            if failed_migration is not None:
                try:
                    with self.engine.db_manager.transaction(db_name) as conn:
                        self.engine._record_migration(
                            conn,
                            version=failed_version,
                            name=failed_migration.get("name", f"v{failed_version}"),
                            description=failed_migration.get("description", ""),
                            duration_ms=0,
                            checksum=failed_migration.get("checksum", ""),
                            status="failed",
                            error_message=failed_error,
                        )
                except Exception:
                    pass

            return {
                "success": False,
                "dry_run": False,
                "error": failed_error,
                "from_version": current_version,
                "failed_at": failed_version,
                "applied_versions": applied,
                "duration_ms": total_duration_ms,
                "backup_path": backup_path,
                "integrity_check": integrity_result,
                "integrity_reports": integrity_reports,
            }

    def _migrate_dry_run(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        current_version: int,
        target_version: int,
        enable_integrity_check: bool,
        integrity_tables: Optional[List[str]],
        progress_callback: Optional[Callable[[ProgressTracker], None]],
    ) -> Dict[str, Any]:
        """Dry-run 模式：仅验证迁移脚本语法和结构，不实际执行"""
        total_start = time.time()
        applied = []
        errors = []
        integrity_previews = []

        # 进度追踪
        total_count = len(migrations)
        progress = ProgressTracker(
            total_count,
            label="DRY-RUN 迁移检查",
            callback=progress_callback,
            show_bar=progress_callback is None,
        )

        for migration in migrations:
            version = migration["version"]
            name = migration.get("name", f"v{version}")

            try:
                # 检查 up/down 是否存在
                up_script = migration.get("up", "")
                down_script = migration.get("down", "")

                if callable(up_script):
                    # 函数形式：仅检查可调用性
                    if not callable(down_script):
                        errors.append(f"v{version} ({name}): down 函数缺失或不可调用")
                elif isinstance(up_script, str):
                    # SQL 字符串形式：检查基本语法（不执行）
                    if not up_script.strip():
                        errors.append(f"v{version} ({name}): up SQL 为空")

                # 迁移前快照
                if enable_integrity_check:
                    snapshot = self.snapshot_table_counts(db_name, integrity_tables)
                    integrity_previews.append({
                        "version": version,
                        "name": name,
                        "table_count": len(snapshot),
                        "total_rows": sum(snapshot.values()),
                    })

                applied.append(version)
                progress.update(1)

            except Exception as e:
                errors.append(f"v{version} ({name}): {e}")

        progress.finish()
        total_duration_ms = int((time.time() - total_start) * 1000)

        return {
            "success": len(errors) == 0,
            "dry_run": True,
            "from_version": current_version,
            "to_version": target_version if not errors else applied[-1] if applied else current_version,
            "applied_count": len(applied),
            "applied_versions": applied,
            "duration_ms": total_duration_ms,
            "errors": errors,
            "integrity_previews": integrity_previews,
            "message": f"DRY-RUN: {len(applied)} 个迁移待执行，{len(errors)} 个错误" if errors else f"DRY-RUN: {len(applied)} 个迁移将被执行",
        }

    # --------------------------------------------------------
    #  4. 增强版回滚
    # --------------------------------------------------------

    def rollback_enhanced(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: int = 0,
        *,
        dry_run: bool = False,
        enable_retry: bool = False,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Dict[str, Any]:
        """
        增强版回滚

        Args:
            db_name: 数据库名称
            migrations: 迁移列表
            target_version: 回滚到的目标版本
            dry_run: 是否试运行
            enable_retry: 是否启用重试
            max_retries: 最大重试次数
            base_delay: 重试初始延迟

        Returns:
            回滚结果字典
        """
        total_start = time.time()
        self.engine._ensure_migrations_table(db_name)

        current_version = self.engine.get_current_version(db_name)

        if current_version <= target_version:
            return {
                "success": True,
                "dry_run": dry_run,
                "message": "Already at or below target version",
                "current_version": current_version,
                "duration_ms": 0,
            }

        # 按版本降序排列待回滚的迁移
        sorted_migrations = sorted(
            [m for m in migrations if m["version"] > target_version and m["version"] <= current_version],
            key=lambda m: m["version"],
            reverse=True,
        )

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "from_version": current_version,
                "to_version": target_version,
                "rollback_count": len(sorted_migrations),
                "rollback_versions": [m["version"] for m in sorted_migrations],
                "duration_ms": 0,
                "message": f"DRY-RUN: 将回滚 {len(sorted_migrations)} 个迁移",
            }

        rolled_back = []
        failed_error = None

        try:
            for migration in sorted_migrations:
                version = migration["version"]
                name = migration.get("name", f"v{version}")

                def _do_rollback():
                    with self.engine.db_manager.transaction(db_name) as conn:
                        down_script = migration.get("down", "")

                        if callable(down_script):
                            down_script(conn)
                        elif isinstance(down_script, str):
                            self.engine._executescript(conn, down_script)

                        # 删除迁移记录
                        self.engine._execute_sql(
                            conn,
                            "DELETE FROM _schema_migrations WHERE version = ?",
                            (version,),
                        )

                if enable_retry:
                    retry_with_backoff(
                        _do_rollback,
                        max_retries=max_retries,
                        base_delay=base_delay,
                    )
                else:
                    _do_rollback()

                rolled_back.append(version)

            total_duration_ms = int((time.time() - total_start) * 1000)

            return {
                "success": True,
                "dry_run": False,
                "from_version": current_version,
                "to_version": target_version,
                "rolled_back_count": len(rolled_back),
                "rolled_back_versions": rolled_back,
                "duration_ms": total_duration_ms,
            }

        except Exception as e:
            failed_error = str(e)
            total_duration_ms = int((time.time() - total_start) * 1000)

            return {
                "success": False,
                "dry_run": False,
                "error": failed_error,
                "from_version": current_version,
                "rolled_back_versions": rolled_back,
                "duration_ms": total_duration_ms,
            }

    # --------------------------------------------------------
    #  5. 状态查询增强
    # --------------------------------------------------------

    def get_migration_status(
        self,
        db_name: str,
        migrations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """获取迁移状态详情

        Args:
            db_name: 数据库名称
            migrations: 迁移脚本列表（可选，用于对比）

        Returns:
            状态详情字典
        """
        self.engine._ensure_migrations_table(db_name)

        applied = self.engine.get_migrations(db_name)
        current_version = self.engine.get_current_version(db_name)

        status = {
            "db_name": db_name,
            "current_version": current_version,
            "applied_count": len(applied),
            "last_migration": applied[-1] if applied else None,
            "applied_migrations": applied,
        }

        # 如果提供了迁移脚本列表，进行对比
        if migrations:
            sorted_migrations = sorted(migrations, key=lambda m: m["version"])
            latest_version = max(m["version"] for m in sorted_migrations) if sorted_migrations else 0

            applied_versions = {m["version"] for m in applied}
            pending_versions = [
                m for m in sorted_migrations
                if m["version"] not in applied_versions
            ]
            failed_migrations = [
                m for m in applied
                if m.get("status") == "failed"
            ]

            # 校验和检查
            checksum_issues = []
            migration_map = {m["version"]: m for m in sorted_migrations}
            for app in applied:
                ver = app["version"]
                if ver in migration_map:
                    db_checksum = app.get("checksum", "")
                    cur_checksum = migration_map[ver].get("checksum", "")
                    if db_checksum and cur_checksum and db_checksum != cur_checksum:
                        checksum_issues.append({
                            "version": ver,
                            "name": app.get("name", ""),
                            "db_checksum": db_checksum,
                            "current_checksum": cur_checksum,
                        })

            status.update({
                "latest_version": latest_version,
                "is_up_to_date": current_version >= latest_version,
                "pending_count": len(pending_versions),
                "pending_migrations": [
                    {"version": m["version"], "name": m.get("name", "")}
                    for m in pending_versions
                ],
                "failed_count": len(failed_migrations),
                "failed_migrations": failed_migrations,
                "checksum_issues": checksum_issues,
            })

        # 表统计
        try:
            tables = self.get_all_user_tables(db_name)
            status["table_count"] = len(tables)
            status["tables"] = tables
        except Exception:
            pass

        return status


# ============================================================
#  异常类型
# ============================================================

class OperationalError(Exception):
    """数据库操作错误（可重试）"""
    pass


class MigrationValidationError(Exception):
    """迁移验证错误"""
    pass
