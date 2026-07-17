"""
云汐数据库迁移引擎

提供数据库版本管理和迁移能力：
- 版本追踪
- 增量迁移
- 回滚支持
- 迁移状态查询
- 迁移文件自动扫描
- 迁移审计统计（耗时、校验和）
- SQLAlchemy / sqlite3 适配层
- 迁移前完整性检查与备份
- 迁移脚本模板生成
"""
import os
import re
import sys
import time
import hashlib
import shutil
import sqlite3
import importlib.util
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Tuple, ContextManager
from contextlib import contextmanager
from pathlib import Path


# ============================================================
#  适配器层 - 统一不同数据库连接方式的接口
# ============================================================

class BaseMigrationAdapter(ABC):
    """迁移适配器抽象基类

    定义 MigrationEngine 所需的最小数据库操作接口。
    所有适配器都需要实现这些方法，以便 MigrationEngine
    能够在不感知底层连接类型的情况下工作。
    """

    @abstractmethod
    def get_connection(self, db_name: str, write: bool = False) -> ContextManager[Any]:
        """获取数据库连接（上下文管理器）

        Args:
            db_name: 数据库标识（名称或路径）
            write: 是否为写操作

        Yields:
            数据库连接对象（适配器内部统一为 sqlite3.Connection 风格）
        """
        ...

    @abstractmethod
    def transaction(self, db_name: str) -> ContextManager[Any]:
        """事务上下文管理器

        Args:
            db_name: 数据库标识

        Yields:
            数据库连接对象
        """
        ...

    @abstractmethod
    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        """查询单行数据

        Args:
            db_name: 数据库标识
            sql: SQL 查询语句
            params: 查询参数

        Returns:
            行字典或 None
        """
        ...

    @abstractmethod
    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """查询多行数据

        Args:
            db_name: 数据库标识
            sql: SQL 查询语句
            params: 查询参数

        Returns:
            行字典列表
        """
        ...

    def get_db_path(self, db_name: str) -> Optional[str]:
        """获取数据库文件路径（用于备份等文件操作）

        部分适配器（如内存数据库）可能没有物理文件，返回 None。

        Args:
            db_name: 数据库标识

        Returns:
            数据库文件绝对路径，或 None（不支持文件操作时）
        """
        return None


class SQLiteMigrationAdapter(BaseMigrationAdapter):
    """原生 sqlite3.Connection 适配器

    允许直接传入 sqlite3.Connection 对象使用迁移引擎，
    让不使用 DatabaseManager 的模块也能接入统一迁移能力。

    用法::

        import sqlite3
        conn = sqlite3.connect("mydb.db")
        adapter = SQLiteMigrationAdapter(conn)
        engine = MigrationEngine(db_manager=adapter)
        engine.migrate("default", migrations)
    """

    def __init__(self, connection: sqlite3.Connection, db_path: Optional[str] = None):
        """
        Args:
            connection: 原生 sqlite3.Connection 对象
            db_path: 数据库文件路径（用于备份等文件操作），
                     不传则尝试从 connection 中推断
        """
        self._conn = connection
        # 确保 row_factory 已设置，便于字典访问
        if self._conn.row_factory is None:
            self._conn.row_factory = sqlite3.Row
        # 尝试获取数据库文件路径
        self._db_path = db_path
        if self._db_path is None:
            try:
                # SQLite PRAGMA database_list 返回: (seq, name, file)
                row = self._conn.execute("PRAGMA database_list").fetchone()
                if row and len(row) > 2 and row[2]:
                    self._db_path = row[2]
            except Exception:
                pass

    @contextmanager
    def get_connection(self, db_name: str, write: bool = False):
        """获取数据库连接（直接返回内部连接）

        注意：单连接模式下不做读写锁管理，由调用方保证线程安全。
        """
        yield self._conn

    @contextmanager
    def transaction(self, db_name: str):
        """事务上下文管理器"""
        try:
            self._conn.execute("BEGIN")
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        cursor = self._conn.execute(sql, params or ())
        row = cursor.fetchone()
        return dict(row) if row else None

    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[Dict[str, Any]]:
        cursor = self._conn.execute(sql, params or ())
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_db_path(self, db_name: str) -> Optional[str]:
        return self._db_path


class SQLAlchemyMigrationAdapter(BaseMigrationAdapter):
    """SQLAlchemy 适配层

    将 SQLAlchemy 的 Engine / Connection 适配到 MigrationEngine
    所需的接口，让使用 SQLAlchemy 的模块（M4/M7/M8/M9/M10）
    也能使用统一迁移引擎。

    用法::

        from sqlalchemy import create_engine
        engine = create_engine("sqlite:///mydb.db")
        adapter = SQLAlchemyMigrationAdapter(engine)
        mig_engine = MigrationEngine(db_manager=adapter)
        mig_engine.migrate("default", migrations)

    注意：
        - 底层必须是 SQLite 方言的 SQLAlchemy 引擎
        - 迁移脚本中的 up(conn) / down(conn) 接收到的是
          SQLAlchemy Connection 对象，需使用 SQLAlchemy API
          执行数据库操作
    """

    def __init__(self, engine_or_connection, db_path: Optional[str] = None):
        """
        Args:
            engine_or_connection: SQLAlchemy Engine 或 Connection 对象
            db_path: 数据库文件路径（用于备份），不传则尝试从 URL 推断
        """
        try:
            from sqlalchemy import create_engine, Connection, Engine
        except ImportError as e:
            raise ImportError(
                "SQLAlchemy 未安装，请先安装: pip install sqlalchemy"
            ) from e

        self._engine = None
        self._external_conn = None

        if isinstance(engine_or_connection, Engine):
            self._engine = engine_or_connection
        elif isinstance(engine_or_connection, Connection):
            self._external_conn = engine_or_connection
            self._engine = engine_or_connection.engine
        else:
            raise TypeError(
                f"期望 SQLAlchemy Engine 或 Connection，实际得到: "
                f"{type(engine_or_connection).__name__}"
            )

        # 推断数据库文件路径
        self._db_path = db_path
        if self._db_path is None:
            try:
                url = str(self._engine.url)
                if url.startswith("sqlite:///"):
                    self._db_path = url[len("sqlite:///"):]
                elif url.startswith("sqlite://") and not url == "sqlite://":
                    # sqlite:///relative/path vs sqlite:////absolute/path
                    rest = url[len("sqlite://"):]
                    if rest.startswith("/"):
                        self._db_path = rest
                    else:
                        self._db_path = rest
            except Exception:
                pass

    @contextmanager
    def get_connection(self, db_name: str, write: bool = False):
        """获取 SQLAlchemy 连接

        如果外部传入了 Connection，则直接使用它；
        否则从 Engine 创建新连接。
        """
        if self._external_conn is not None:
            yield self._external_conn
        else:
            conn = self._engine.connect()
            try:
                yield conn
            finally:
                conn.close()

    @contextmanager
    def transaction(self, db_name: str):
        """事务上下文管理器

        使用 SQLAlchemy 的事务机制。
        对于外部传入的 Connection，使用 savepoint 嵌套事务，
        避免与外部已有的事务冲突。
        """
        if self._external_conn is not None:
            # 外部连接可能已有事务，使用嵌套事务 (savepoint)
            trans = self._external_conn.begin_nested()
            try:
                yield self._external_conn
                trans.commit()
            except Exception:
                trans.rollback()
                raise
        else:
            conn = self._engine.connect()
            trans = conn.begin()
            try:
                yield conn
                trans.commit()
            except Exception:
                trans.rollback()
                raise
            finally:
                conn.close()

    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        from sqlalchemy import text

        with self.get_connection(db_name) as conn:
            result = conn.execute(text(sql), params or {})
            row = result.fetchone()
            if row is None:
                return None
            # SQLAlchemy Row -> dict
            return dict(row._mapping)

    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[Dict[str, Any]]:
        from sqlalchemy import text

        with self.get_connection(db_name) as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(row._mapping) for row in result.fetchall()]

    def get_db_path(self, db_name: str) -> Optional[str]:
        return self._db_path


# ============================================================
#  迁移引擎核心
# ============================================================

# 迁移文件名正则：v{版本号}_{名称}.py
_MIGRATION_FILE_RE = re.compile(r'^v(\d+)_(.+)\.py$')


class MigrationEngine:
    """数据库迁移引擎

    支持多种数据库连接方式（DatabaseManager、原生 sqlite3、SQLAlchemy），
    提供版本管理、增量迁移、回滚、审计统计、完整性检查等能力。
    """

    def __init__(self, db_manager=None):
        """
        初始化迁移引擎

        Args:
            db_manager: 数据库管理器，可以是:
                - DatabaseManager 实例（默认，None 时使用全局实例）
                - BaseMigrationAdapter 子类实例
                - 任何实现了 get_connection / transaction / query_one / query_all 的对象
        """
        if db_manager is None:
            from .database_manager import get_db_manager
            db_manager = get_db_manager()
        self.db_manager = db_manager

    # --------------------------------------------------------
    #  内部工具方法
    # --------------------------------------------------------

    def _is_adapter(self) -> bool:
        """判断当前 db_manager 是否为适配器模式"""
        return isinstance(self.db_manager, BaseMigrationAdapter)

    def _get_db_path(self, db_name: str) -> Optional[str]:
        """获取数据库文件路径

        Returns:
            文件路径字符串，或 None（不支持文件操作时）
        """
        # 适配器模式
        if hasattr(self.db_manager, 'get_db_path'):
            path = self.db_manager.get_db_path(db_name)
            if path:
                return path

        # DatabaseManager 模式
        if hasattr(self.db_manager, '_get_db_path'):
            try:
                return str(self.db_manager._get_db_path(db_name))
            except Exception:
                pass

        return None

    # --------------------------------------------------------
    #  迁移表管理
    # --------------------------------------------------------

    def _ensure_migrations_table(self, db_name: str):
        """确保迁移记录表存在，并自动升级表结构

        每次调用时检查并补充缺失的列，保证向后兼容。
        """
        with self.db_manager.get_connection(db_name, write=True) as conn:
            self._execute_sql(conn, """
                CREATE TABLE IF NOT EXISTS _schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)

            # 自动添加新列（向后兼容：旧表可能缺少这些列）
            self._add_column_if_missing(conn, "duration_ms", "INTEGER DEFAULT 0")
            self._add_column_if_missing(conn, "checksum", "TEXT DEFAULT ''")
            self._add_column_if_missing(conn, "status", "TEXT DEFAULT 'success'")
            self._add_column_if_missing(conn, "error_message", "TEXT DEFAULT ''")

    def _add_column_if_missing(self, conn: Any, column_name: str, column_def: str):
        """如果列不存在则添加

        通过 PRAGMA table_info 检查列是否存在，避免重复添加。
        """
        try:
            rows = self._execute_fetchall(conn, "PRAGMA table_info(_schema_migrations)")
            existing_columns = set()
            for row in rows:
                row_dict = self._row_to_dict(row)
                if row_dict and "name" in row_dict:
                    existing_columns.add(row_dict["name"])
                elif isinstance(row, (list, tuple)) and len(row) > 1:
                    # 元组形式，name 是第 2 个字段（索引 1）
                    existing_columns.add(row[1])

            if column_name not in existing_columns:
                self._execute_sql(
                    conn,
                    f"ALTER TABLE _schema_migrations ADD COLUMN {column_name} {column_def}"
                )
        except Exception:
            # 某些情况下 PRAGMA 或 ALTER TABLE 可能失败（如 SQLAlchemy 适配）
            # 静默忽略，迁移引擎的核心功能不受影响
            pass

    @staticmethod
    def _is_sqlite3_conn(conn: Any) -> bool:
        """判断连接是否为原生 sqlite3.Connection"""
        return isinstance(conn, sqlite3.Connection)

    @staticmethod
    def _is_sqlalchemy_conn(conn: Any) -> bool:
        """判断连接是否为 SQLAlchemy Connection"""
        try:
            from sqlalchemy import Connection as SAConnection
            return isinstance(conn, SAConnection)
        except ImportError:
            return False

    def _execute_sql(self, conn: Any, sql: str, params: Optional[Tuple] = None):
        """统一执行 SQL 的工具方法，兼容多种连接类型

        Args:
            conn: 数据库连接（sqlite3.Connection 或 SQLAlchemy Connection）
            sql: SQL 语句（使用 ? 占位符）
            params: 参数元组
        """
        if self._is_sqlite3_conn(conn):
            conn.execute(sql, params or ())
        elif self._is_sqlalchemy_conn(conn):
            from sqlalchemy import text
            # SQLAlchemy 使用命名参数，需要将 ? 转换为 :param_0, :param_1 等
            if params and '?' in sql:
                sa_params = {}
                sa_sql = sql
                for i, val in enumerate(params):
                    placeholder = f":param_{i}"
                    # 逐个替换第一个 ?
                    sa_sql = sa_sql.replace('?', placeholder, 1)
                    sa_params[f"param_{i}"] = val
                conn.execute(text(sa_sql), sa_params)
            else:
                conn.execute(text(sql), params or {})
        elif hasattr(conn, 'execute'):
            # 兜底：尝试直接执行
            conn.execute(sql, params or ())
        else:
            raise TypeError(f"不支持的连接类型: {type(conn).__name__}")

    def _execute_fetchall(self, conn: Any, sql: str) -> List[Any]:
        """统一查询并获取所有结果"""
        if self._is_sqlite3_conn(conn):
            cursor = conn.execute(sql)
            return cursor.fetchall()
        elif self._is_sqlalchemy_conn(conn):
            from sqlalchemy import text
            result = conn.execute(text(sql))
            return result.fetchall()
        elif hasattr(conn, 'execute'):
            cursor = conn.execute(sql)
            return cursor.fetchall()
        raise TypeError(f"不支持的连接类型: {type(conn).__name__}")

    # --------------------------------------------------------
    #  基础查询
    # --------------------------------------------------------

    def get_current_version(self, db_name: str) -> int:
        """获取当前数据库版本"""
        self._ensure_migrations_table(db_name)
        result = self.db_manager.query_one(
            db_name,
            "SELECT MAX(version) as max_ver FROM _schema_migrations",
        )
        if result and result.get("max_ver"):
            return int(result["max_ver"])
        return 0

    def get_migrations(self, db_name: str) -> List[Dict[str, Any]]:
        """获取所有已应用的迁移"""
        self._ensure_migrations_table(db_name)
        return self.db_manager.query_all(
            db_name,
            "SELECT * FROM _schema_migrations ORDER BY version",
        )

    # --------------------------------------------------------
    #  迁移文件自动扫描
    # --------------------------------------------------------

    def scan_migrations(self, migrations_dir: str) -> List[Dict[str, Any]]:
        """扫描指定目录下的迁移文件并返回排序后的迁移列表

        迁移文件命名规范：``v{版本号}_{名称}.py``，例如
        ``v001_initial.py``、``v002_add_users.py``。

        每个迁移文件应包含：
            - ``up(conn)`` 函数：升级逻辑
            - ``down(conn)`` 函数：降级逻辑
            - ``__migration_name__`` 变量：迁移名称（可选，默认从文件名提取）
            - ``__description__`` 变量：迁移描述（可选）

        Args:
            migrations_dir: 迁移文件所在目录的路径

        Returns:
            按版本号升序排列的迁移列表，每个元素为字典，包含:
            - version: 版本号
            - name: 迁移名称
            - description: 描述
            - up: 升级函数
            - down: 降级函数
            - file_path: 文件路径
            - checksum: 文件内容 SHA256 校验和

        Raises:
            FileNotFoundError: 目录不存在
            ValueError: 迁移文件格式错误或版本号冲突
            ImportError: 迁移文件导入失败
        """
        dir_path = Path(migrations_dir)
        if not dir_path.exists():
            raise FileNotFoundError(f"迁移目录不存在: {migrations_dir}")
        if not dir_path.is_dir():
            raise NotADirectoryError(f"路径不是目录: {migrations_dir}")

        migrations: Dict[int, Dict[str, Any]] = {}

        for file_path in sorted(dir_path.glob("v*.py")):
            match = _MIGRATION_FILE_RE.match(file_path.name)
            if not match:
                continue

            version = int(match.group(1))
            name_from_file = match.group(2)

            # 版本号冲突检测
            if version in migrations:
                raise ValueError(
                    f"版本号冲突: v{version} 同时存在于 "
                    f"{migrations[version]['file_path']} 和 {file_path}"
                )

            # 计算文件校验和
            checksum = self._compute_file_checksum(str(file_path))

            # 动态加载模块
            try:
                module = self._load_migration_module(file_path, version)
            except Exception as e:
                raise ImportError(
                    f"加载迁移文件失败 {file_path}: {e}"
                ) from e

            # 验证必须的函数
            if not hasattr(module, 'up') or not callable(module.up):
                raise ValueError(
                    f"迁移文件 {file_path} 缺少 up(conn) 函数"
                )
            if not hasattr(module, 'down') or not callable(module.down):
                raise ValueError(
                    f"迁移文件 {file_path} 缺少 down(conn) 函数"
                )

            # 提取元数据
            migration_name = getattr(module, '__migration_name__', name_from_file)
            description = getattr(module, '__description__', '')

            migrations[version] = {
                "version": version,
                "name": migration_name,
                "description": description,
                "up": module.up,
                "down": module.down,
                "file_path": str(file_path),
                "checksum": checksum,
            }

        # 按版本号排序返回
        return [migrations[v] for v in sorted(migrations.keys())]

    def _load_migration_module(self, file_path: Path, version: int) -> Any:
        """动态加载迁移文件为 Python 模块

        使用 importlib.util 从文件路径加载模块，避免与其他模块冲突。
        """
        module_name = f"_migration_v{version}_{file_path.stem}_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建模块规格: {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            # 加载失败时清理 sys.modules
            sys.modules.pop(module_name, None)
            raise

        return module

    @staticmethod
    def _compute_file_checksum(file_path: str) -> str:
        """计算文件内容的 SHA256 校验和"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    # --------------------------------------------------------
    #  迁移执行（增强版）
    # --------------------------------------------------------

    def migrate(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: Optional[int] = None,
        pre_migration_backup: bool = False,
        backup_dir: Optional[str] = None,
        skip_integrity_check: bool = False,
    ) -> Dict[str, Any]:
        """
        执行数据库迁移（增强版）

        在原有迁移能力基础上增加：
        - 迁移前完整性检查（可跳过）
        - 迁移前自动备份（可选）
        - 迁移耗时统计
        - 迁移脚本校验和记录

        Args:
            db_name: 数据库名称
            migrations: 迁移列表，每个迁移包含:
                - version: 版本号（整数，递增）
                - name: 迁移名称
                - up: 升级SQL或函数
                - down: 降级SQL或函数（可选）
                - description: 描述（可选）
                - checksum: 校验和（可选，用于审计）
            target_version: 目标版本，None 表示最新
            pre_migration_backup: 是否在迁移前自动备份数据库
            backup_dir: 备份文件存放目录，None 时使用数据库同目录下的 backups/
            skip_integrity_check: 是否跳过迁移前完整性检查

        Returns:
            迁移结果字典，包含 success、from_version、to_version、
            applied_count、applied_versions、duration_ms、backup_path 等
        """
        total_start = time.time()
        self._ensure_migrations_table(db_name)

        # 1. 迁移前完整性检查
        integrity_result = None
        if not skip_integrity_check:
            integrity_result = self.check_integrity(db_name)
            if integrity_result.get("status") not in ("ok", "error"):
                # 完整性检查明确报告损坏时，阻止迁移
                return {
                    "success": False,
                    "error": f"数据库完整性检查未通过: {integrity_result}",
                    "from_version": self.get_current_version(db_name),
                    "integrity_check": integrity_result,
                }
            # 如果完整性检查本身报错（如不支持），不阻止迁移，但记录警告

        current_version = self.get_current_version(db_name)

        if target_version is None:
            target_version = max(m["version"] for m in migrations) if migrations else 0

        # 2. 迁移前备份
        backup_path = None
        if pre_migration_backup and target_version > current_version:
            try:
                backup_path = self._backup_database(db_name, backup_dir)
            except Exception as e:
                # 备份失败不阻止迁移，但返回警告
                backup_path = f"backup_failed: {e}"

        applied = []
        failed = None
        failed_error = None

        # 按版本排序
        sorted_migrations = sorted(migrations, key=lambda m: m["version"])

        try:
            for migration in sorted_migrations:
                version = migration["version"]

                if version <= current_version:
                    continue

                if version > target_version:
                    break

                # 执行升级（带耗时统计）
                migration_start = time.time()
                with self.db_manager.transaction(db_name) as conn:
                    up_script = migration.get("up", "")

                    if callable(up_script):
                        up_script(conn)
                    elif isinstance(up_script, str):
                        self._executescript(conn, up_script)

                    duration_ms = int((time.time() - migration_start) * 1000)
                    checksum = migration.get("checksum", "")

                    # 记录迁移（含耗时和校验和）
                    self._record_migration(
                        conn,
                        version=version,
                        name=migration.get("name", f"v{version}"),
                        description=migration.get("description", ""),
                        duration_ms=duration_ms,
                        checksum=checksum,
                        status="success",
                        error_message="",
                    )

                    applied.append(version)

            total_duration_ms = int((time.time() - total_start) * 1000)

            return {
                "success": True,
                "from_version": current_version,
                "to_version": target_version,
                "applied_count": len(applied),
                "applied_versions": applied,
                "duration_ms": total_duration_ms,
                "backup_path": backup_path,
                "integrity_check": integrity_result,
            }

        except Exception as e:
            failed_error = str(e)
            total_duration_ms = int((time.time() - total_start) * 1000)

            # 记录失败的迁移（如果已经执行到该版本）
            if applied:
                failed_version = applied[-1] + 1
            else:
                failed_version = current_version + 1

            # 尝试找到失败迁移的信息
            failed_migration = None
            for m in sorted_migrations:
                if m["version"] == failed_version:
                    failed_migration = m
                    break

            # 记录失败状态到迁移表（如果已部分执行）
            if failed_migration is not None:
                try:
                    with self.db_manager.transaction(db_name) as conn:
                        self._record_migration(
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
                    pass  # 记录失败不影响返回结果

            return {
                "success": False,
                "error": failed_error,
                "from_version": current_version,
                "failed_at": failed_version,
                "applied_versions": applied,
                "duration_ms": total_duration_ms,
                "backup_path": backup_path,
                "integrity_check": integrity_result,
            }

    def _record_migration(
        self,
        conn: Any,
        version: int,
        name: str,
        description: str,
        duration_ms: int,
        checksum: str,
        status: str,
        error_message: str,
    ):
        """记录一条迁移记录（兼容多种连接类型）

        使用 INSERT OR REPLACE 以支持失败记录的更新。
        """
        sql = (
            "INSERT OR REPLACE INTO _schema_migrations "
            "(version, name, description, duration_ms, checksum, status, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        params = (version, name, description, duration_ms, checksum, status, error_message)
        self._execute_sql(conn, sql, params)

    def _executescript(self, conn: Any, script: str):
        """执行 SQL 脚本（兼容多种连接类型）

        注意：不直接使用 sqlite3 的 executescript()，因为它会先隐式 COMMIT，
        破坏手动事务管理。改为逐条拆分执行，保持事务一致性。

        Args:
            conn: 数据库连接
            script: SQL 脚本字符串（可包含多条语句，以分号分隔）
        """
        statements = self._split_sql_script(script)
        if not statements:
            return

        if self._is_sqlite3_conn(conn):
            for stmt in statements:
                conn.execute(stmt)
        elif self._is_sqlalchemy_conn(conn):
            from sqlalchemy import text
            for stmt in statements:
                conn.execute(text(stmt))
        elif hasattr(conn, 'executescript'):
            conn.executescript(script)
        elif hasattr(conn, 'execute'):
            for stmt in statements:
                conn.execute(stmt)
        else:
            raise TypeError(f"不支持的连接类型: {type(conn).__name__}")

    @staticmethod
    def _split_sql_script(script: str) -> List[str]:
        """简单的 SQL 脚本拆分（按分号）"""
        statements = []
        current = []
        for line in script.split('\n'):
            stripped = line.strip()
            if not stripped or stripped.startswith('--'):
                continue
            current.append(line)
            if stripped.endswith(';'):
                stmt = '\n'.join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []
        # 处理最后一条不以分号结尾的语句
        if current:
            stmt = '\n'.join(current).strip()
            if stmt:
                statements.append(stmt)
        return statements

    # --------------------------------------------------------
    #  回滚
    # --------------------------------------------------------

    def rollback(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: int = 0,
    ) -> Dict[str, Any]:
        """
        回滚迁移

        Args:
            db_name: 数据库名称
            migrations: 迁移列表
            target_version: 回滚到的版本

        Returns:
            回滚结果字典
        """
        total_start = time.time()
        self._ensure_migrations_table(db_name)

        current_version = self.get_current_version(db_name)

        if current_version <= target_version:
            return {
                "success": True,
                "message": "Already at target version",
                "current_version": current_version,
                "duration_ms": 0,
            }

        # 按版本降序排序
        sorted_migrations = sorted(
            [m for m in migrations if m["version"] > target_version],
            key=lambda m: m["version"],
            reverse=True,
        )

        rolled_back = []

        try:
            for migration in sorted_migrations:
                version = migration["version"]

                if version <= target_version:
                    continue

                # 执行降级
                with self.db_manager.transaction(db_name) as conn:
                    down_script = migration.get("down", "")

                    if callable(down_script):
                        down_script(conn)
                    elif isinstance(down_script, str):
                        self._executescript(conn, down_script)

                    # 删除迁移记录
                    self._execute_sql(
                        conn,
                        "DELETE FROM _schema_migrations WHERE version = ?",
                        (version,),
                    )

                    rolled_back.append(version)

            total_duration_ms = int((time.time() - total_start) * 1000)

            return {
                "success": True,
                "from_version": current_version,
                "to_version": target_version,
                "rolled_back_count": len(rolled_back),
                "rolled_back_versions": rolled_back,
                "duration_ms": total_duration_ms,
            }

        except Exception as e:
            total_duration_ms = int((time.time() - total_start) * 1000)
            return {
                "success": False,
                "error": str(e),
                "from_version": current_version,
                "rolled_back_versions": rolled_back,
                "duration_ms": total_duration_ms,
            }

    # --------------------------------------------------------
    #  完整性检查
    # --------------------------------------------------------

    def check_integrity(self, db_name: str) -> Dict[str, Any]:
        """检查数据库完整性"""
        try:
            with self.db_manager.get_connection(db_name) as conn:
                result = self._execute_fetchone(conn, "PRAGMA integrity_check")
                quick_check = self._execute_fetchone(conn, "PRAGMA quick_check")

                # 获取表数量
                tables_row = self._execute_fetchone(
                    conn,
                    "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table'"
                )

                table_count = 0
                tables_dict = self._row_to_dict(tables_row)
                if tables_dict and "cnt" in tables_dict:
                    table_count = int(tables_dict["cnt"])
                elif isinstance(tables_row, (list, tuple)) and tables_row:
                    table_count = int(tables_row[0])

                result_val = self._extract_first_value(result)
                quick_val = self._extract_first_value(quick_check)

                return {
                    "status": "ok" if result_val == "ok" else "corrupted",
                    "integrity_check": result_val,
                    "quick_check": quick_val,
                    "table_count": table_count,
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def _execute_fetchone(self, conn: Any, sql: str) -> Any:
        """统一查询单行"""
        if self._is_sqlite3_conn(conn):
            cursor = conn.execute(sql)
            return cursor.fetchone()
        elif self._is_sqlalchemy_conn(conn):
            from sqlalchemy import text
            result = conn.execute(text(sql))
            return result.fetchone()
        elif hasattr(conn, 'execute'):
            cursor = conn.execute(sql)
            return cursor.fetchone()
        raise TypeError(f"不支持的连接类型: {type(conn).__name__}")

    @staticmethod
    def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
        """将各种行对象统一转换为字典

        支持 sqlite3.Row、SQLAlchemy Row、原生 dict、tuple。
        """
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        # SQLAlchemy Row
        if hasattr(row, '_mapping'):
            return dict(row._mapping)
        # sqlite3.Row 或其他有 keys() 的行对象
        if hasattr(row, 'keys') and callable(getattr(row, 'keys')):
            return dict(zip(row.keys(), row))
        # tuple/list - 无法转换为有名字段的字典
        if isinstance(row, (list, tuple)) and hasattr(row, '__len__'):
            # 返回数字索引字典
            return {str(i): v for i, v in enumerate(row)}
        return None

    @staticmethod
    def _extract_first_value(row: Any) -> Any:
        """从查询结果行中提取第一个值"""
        if row is None:
            return None
        if isinstance(row, dict):
            return list(row.values())[0] if row else None
        # SQLAlchemy Row
        if hasattr(row, '_mapping'):
            values = list(dict(row._mapping).values())
            return values[0] if values else None
        # sqlite3.Row 或其他有 keys() 的行对象
        if hasattr(row, 'keys') and callable(getattr(row, 'keys')):
            return row[0] if len(row) > 0 else None
        if isinstance(row, (list, tuple)):
            return row[0] if row else None
        return row

    # --------------------------------------------------------
    #  数据库备份
    # --------------------------------------------------------

    def _backup_database(
        self,
        db_name: str,
        backup_dir: Optional[str] = None,
    ) -> str:
        """创建数据库备份

        使用 SQLite 官方推荐的备份 API（sqlite3.Connection.backup），
        保证备份一致性。如果不支持备份 API，则回退到文件复制。

        Args:
            db_name: 数据库名称
            backup_dir: 备份目录，None 时使用数据库同目录下的 backups/

        Returns:
            备份文件的绝对路径

        Raises:
            RuntimeError: 无法获取数据库路径或备份失败
        """
        db_path = self._get_db_path(db_name)
        if not db_path:
            raise RuntimeError(
                f"无法获取数据库文件路径，无法创建备份: {db_name}"
            )

        # 确定备份目录
        if backup_dir:
            backup_path = Path(backup_dir)
        else:
            backup_path = Path(db_path).parent / "backups"

        backup_path.mkdir(parents=True, exist_ok=True)

        # 生成备份文件名：{db_name}_v{版本}_{时间戳}.db
        current_version = self.get_current_version(db_name)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        db_stem = Path(db_path).stem
        backup_file = backup_path / f"{db_stem}_v{current_version}_{timestamp}.db"

        # 尝试使用 SQLite 备份 API
        try:
            with self.db_manager.get_connection(db_name, write=False) as conn:
                # 获取原生 sqlite3.Connection
                native_conn = self._get_native_sqlite_conn(conn)
                if native_conn is not None:
                    backup_conn = sqlite3.connect(str(backup_file))
                    try:
                        native_conn.backup(backup_conn)
                    finally:
                        backup_conn.close()
                    return str(backup_file)
        except Exception:
            pass  # 回退到文件复制

        # 回退方案：直接复制文件（仅在数据库非 WAL 模式或静止时可靠）
        try:
            shutil.copy2(db_path, str(backup_file))
            # 同时复制 WAL 和 SHM 文件（如果存在）
            for suffix in ('.wal', '.shm'):
                src = db_path + suffix
                if os.path.exists(src):
                    shutil.copy2(src, str(backup_file) + suffix)
            return str(backup_file)
        except Exception as e:
            raise RuntimeError(f"数据库备份失败: {e}") from e

    def _get_native_sqlite_conn(self, conn: Any) -> Optional[sqlite3.Connection]:
        """尝试从连接对象中获取原生 sqlite3.Connection

        支持:
        - 原生 sqlite3.Connection（直接返回）
        - SQLAlchemy Connection（通过 .connection.driver_connection 获取）
        """
        if isinstance(conn, sqlite3.Connection):
            return conn

        # SQLAlchemy Connection
        try:
            if hasattr(conn, 'connection'):
                dbapi_conn = conn.connection
                if hasattr(dbapi_conn, 'driver_connection'):
                    return dbapi_conn.driver_connection
                if isinstance(dbapi_conn, sqlite3.Connection):
                    return dbapi_conn
        except Exception:
            pass

        return None

    # --------------------------------------------------------
    #  迁移审计统计
    # --------------------------------------------------------

    def get_migration_stats(self, db_name: str) -> Dict[str, Any]:
        """获取迁移审计统计信息

        返回迁移执行的完整统计数据，包括总数、成功/失败数、
        总耗时、最后迁移时间和各版本详情。

        Args:
            db_name: 数据库名称

        Returns:
            统计信息字典，包含:
            - total_count: 总迁移数
            - success_count: 成功迁移数
            - failed_count: 失败迁移数
            - total_duration_ms: 总耗时（毫秒）
            - avg_duration_ms: 平均耗时（毫秒）
            - last_migration_at: 最后迁移时间
            - last_version: 最后版本号
            - current_version: 当前版本号
            - checksum_mismatches: 校验和不匹配的迁移列表（需要传入 migrations 才会检查）
            - migrations: 各版本详情列表
        """
        self._ensure_migrations_table(db_name)

        all_migrations = self.get_migrations(db_name)

        if not all_migrations:
            return {
                "total_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "total_duration_ms": 0,
                "avg_duration_ms": 0,
                "last_migration_at": None,
                "last_version": 0,
                "current_version": 0,
                "migrations": [],
            }

        total_count = len(all_migrations)
        success_count = sum(
            1 for m in all_migrations
            if m.get("status", "success") == "success"
        )
        failed_count = total_count - success_count
        total_duration_ms = sum(
            int(m.get("duration_ms", 0) or 0) for m in all_migrations
        )
        avg_duration_ms = total_duration_ms // total_count if total_count > 0 else 0

        # 最后一条迁移记录
        last_migration = all_migrations[-1]
        last_migration_at = last_migration.get("applied_at")
        last_version = last_migration.get("version", 0)
        current_version = self.get_current_version(db_name)

        return {
            "total_count": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "total_duration_ms": total_duration_ms,
            "avg_duration_ms": avg_duration_ms,
            "last_migration_at": last_migration_at,
            "last_version": last_version,
            "current_version": current_version,
            "migrations": all_migrations,
        }

    def verify_checksums(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """验证已应用迁移的校验和

        对比数据库中记录的 checksum 与迁移脚本当前内容的 checksum，
        检测迁移脚本是否被篡改。

        Args:
            db_name: 数据库名称
            migrations: 迁移列表（需包含 checksum 字段）

        Returns:
            验证结果字典，包含:
            - all_valid: 是否全部匹配
            - mismatches: 不匹配列表，每项包含 version、name、db_checksum、current_checksum
            - missing: 数据库中有记录但迁移列表中不存在的版本
        """
        self._ensure_migrations_table(db_name)

        applied = self.get_migrations(db_name)
        applied_map = {m["version"]: m for m in applied}
        migration_map = {m["version"]: m for m in migrations}

        mismatches = []
        missing = []

        for version, db_record in applied_map.items():
            if version not in migration_map:
                missing.append({
                    "version": version,
                    "name": db_record.get("name", f"v{version}"),
                })
                continue

            current = migration_map[version]
            db_checksum = db_record.get("checksum", "")
            current_checksum = current.get("checksum", "")

            # 旧记录可能没有 checksum，跳过
            if not db_checksum or not current_checksum:
                continue

            if db_checksum != current_checksum:
                mismatches.append({
                    "version": version,
                    "name": db_record.get("name", current.get("name", f"v{version}")),
                    "db_checksum": db_checksum,
                    "current_checksum": current_checksum,
                })

        return {
            "all_valid": len(mismatches) == 0 and len(missing) == 0,
            "mismatches": mismatches,
            "missing": missing,
        }

    # --------------------------------------------------------
    #  迁移脚本模板生成
    # --------------------------------------------------------

    def generate_migration_template(
        self,
        name: str,
        version: int,
        output_dir: str,
        description: str = "",
    ) -> str:
        """生成标准格式的迁移脚本模板文件

        按照命名规范生成 ``v{版本号}_{名称}.py`` 文件，
        包含 up、down 函数和元数据变量的模板代码。

        Args:
            name: 迁移名称（会被清理为合法的文件名字符）
            version: 版本号（正整数）
            output_dir: 输出目录路径
            description: 迁移描述（可选）

        Returns:
            生成的迁移文件绝对路径

        Raises:
            ValueError: 参数不合法
            FileExistsError: 目标文件已存在
        """
        # 参数校验
        if not isinstance(version, int) or version <= 0:
            raise ValueError(f"版本号必须是正整数，得到: {version}")
        if not name or not name.strip():
            raise ValueError("迁移名称不能为空")

        # 清理名称：只保留字母、数字、下划线
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', name.strip())
        clean_name = re.sub(r'_+', '_', clean_name).strip('_')
        if not clean_name:
            raise ValueError(f"迁移名称清理后为空，原始名称: {name}")

        # 格式化版本号（至少 3 位，前导零）
        version_str = f"{version:03d}"

        # 构造文件名和路径
        filename = f"v{version_str}_{clean_name}.py"
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        file_path = output_path / filename

        # 检查文件是否已存在
        if file_path.exists():
            raise FileExistsError(f"迁移文件已存在: {file_path}")

        # 生成模板内容
        template = self._build_migration_template(
            version=version,
            name=clean_name,
            description=description,
        )

        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(template)

        return str(file_path)

    @staticmethod
    def _build_migration_template(
        version: int,
        name: str,
        description: str,
    ) -> str:
        """构建迁移脚本模板内容"""
        return f'''"""
迁移脚本 v{version:03d} - {name}

{description if description else "在此处描述本次迁移的内容和目的。"}
"""

# 迁移元数据
__migration_name__ = "{name}"
__description__ = "{description if description else f"v{version:03d} - {name}"}"


def up(conn):
    """
    升级迁移

    Args:
        conn: 数据库连接对象（sqlite3.Connection 或 SQLAlchemy Connection）
    """
    # TODO: 在此处编写升级逻辑
    # 示例：
    # conn.execute("""
    #     CREATE TABLE example (
    #         id INTEGER PRIMARY KEY AUTOINCREMENT,
    #         name TEXT NOT NULL,
    #         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    #     )
    # """)
    pass


def down(conn):
    """
    降级迁移（回滚）

    Args:
        conn: 数据库连接对象（sqlite3.Connection 或 SQLAlchemy Connection）
    """
    # TODO: 在此处编写降级逻辑，需与 up 对应
    # 示例：
    # conn.execute("DROP TABLE IF EXISTS example")
    pass
'''


# ============================================================
#  全局单例
# ============================================================

_migration_engine: Optional[MigrationEngine] = None


def get_migration_engine() -> MigrationEngine:
    """获取全局迁移引擎实例"""
    global _migration_engine
    if _migration_engine is None:
        _migration_engine = MigrationEngine()
    return _migration_engine
