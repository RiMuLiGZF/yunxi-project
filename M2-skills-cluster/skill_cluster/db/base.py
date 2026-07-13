from __future__ import annotations

"""基础数据库类 - 统一 SQLite 连接管理与 Repository 基类.

提供以下增强能力：
1. WAL 模式启用（高并发读写性能）
2. 连接重用（单连接 + 线程安全访问）
3. 自动重试：database is locked 时指数退避重试（默认 3 次）
4. SQL 注入防护：强制参数化查询
5. 事务管理：transaction() 上下文管理器
6. 健康检查：is_healthy() + integrity_check()
7. 损坏检测与恢复：检测到数据库损坏时备份并重建
8. 优雅关闭：close() 方法执行 PRAGMA optimize
"""

import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import structlog

logger = structlog.get_logger()


class DatabaseCorruptedError(Exception):
    """数据库文件损坏异常."""


class SQLiteDatabase:
    """统一的 SQLite 数据库连接管理器.

    特性：
    - WAL 模式 + 单连接重用，避免每次操作新建连接的开销
    - 线程安全（threading.Lock 保护连接访问）
    - database is locked 自动指数退避重试
    - 损坏检测与自动备份重建
    - 优雅关闭时执行 PRAGMA optimize

    Args:
        db_path: 数据库文件路径
        max_retries: 最大重试次数（默认 3 次）
        retry_base_delay: 重试基础延迟秒数（指数退避底数）
        timeout: 连接超时时间（秒）
    """

    def __init__(
        self,
        db_path: str,
        max_retries: int = 3,
        retry_base_delay: float = 0.1,
        timeout: float = 5.0,
    ) -> None:
        self._db_path = db_path
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._timeout = timeout
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._init_db()

    # ------------------------------------------------------------------
    # 初始化与连接管理
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """初始化数据库连接与 WAL 模式."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._connect()
        self._enable_wal()

    def _connect(self) -> None:
        """建立数据库连接."""
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=self._timeout,
            check_same_thread=False,
            isolation_level=None,  # 手动管理事务
        )
        self._conn.row_factory = sqlite3.Row

    def _enable_wal(self) -> None:
        """启用 WAL 模式以提升并发读写性能."""
        assert self._conn is not None
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=3000")

    @property
    def db_path(self) -> str:
        """数据库文件路径."""
        return self._db_path

    @property
    def closed(self) -> bool:
        """数据库是否已关闭."""
        return self._closed

    # ------------------------------------------------------------------
    # 核心执行方法（带重试）
    # ------------------------------------------------------------------

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> sqlite3.Cursor:
        """执行 SQL 语句（带自动重试）.

        全部使用参数化查询，禁止通过字符串拼接传入用户数据。

        Args:
            sql: SQL 语句（使用 ? 作为参数占位符）
            params: 参数元组/列表

        Returns:
            sqlite3.Cursor 游标对象

        Raises:
            DatabaseCorruptedError: 数据库文件损坏
            sqlite3.Error: 其他数据库错误（重试耗尽后）
        """
        self._ensure_open()
        params = params or ()
        last_error: sqlite3.Error | None = None

        for attempt in range(self._max_retries + 1):
            try:
                with self._lock:
                    assert self._conn is not None
                    cursor = self._conn.execute(sql, params)
                    return cursor
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()

                # 检测数据库损坏
                if "database disk image is malformed" in error_msg:
                    logger.error(
                        "db_corrupted_detected",
                        db_path=self._db_path,
                        error=str(e),
                    )
                    self._handle_corruption()
                    # 重建后再试一次
                    continue

                # database is locked -> 指数退避重试
                if "database is locked" in error_msg:
                    if attempt < self._max_retries:
                        delay = self._retry_base_delay * (2**attempt)
                        logger.warning(
                            "db_locked_retrying",
                            db_path=self._db_path,
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                            delay=round(delay, 3),
                        )
                        time.sleep(delay)
                        continue

                raise
            except sqlite3.DatabaseError as e:
                last_error = e
                error_msg = str(e).lower()
                if "malformed" in error_msg or "corrupt" in error_msg:
                    logger.error(
                        "db_corrupted_detected",
                        db_path=self._db_path,
                        error=str(e),
                    )
                    self._handle_corruption()
                    continue
                raise

        # 重试耗尽
        if last_error:
            raise last_error
        raise sqlite3.Error("Unknown database error")

    def executemany(
        self,
        sql: str,
        seq_of_params: Sequence[Sequence[Any]],
    ) -> sqlite3.Cursor:
        """批量执行 SQL 语句（带自动重试）.

        Args:
            sql: SQL 语句
            seq_of_params: 参数序列

        Returns:
            sqlite3.Cursor 游标对象
        """
        self._ensure_open()
        last_error: sqlite3.Error | None = None

        for attempt in range(self._max_retries + 1):
            try:
                with self._lock:
                    assert self._conn is not None
                    cursor = self._conn.executemany(sql, seq_of_params)
                    return cursor
            except sqlite3.OperationalError as e:
                last_error = e
                error_msg = str(e).lower()
                if "database disk image is malformed" in error_msg:
                    self._handle_corruption()
                    continue
                if "database is locked" in error_msg:
                    if attempt < self._max_retries:
                        delay = self._retry_base_delay * (2**attempt)
                        logger.warning(
                            "db_locked_retrying",
                            db_path=self._db_path,
                            attempt=attempt + 1,
                            max_retries=self._max_retries,
                            delay=round(delay, 3),
                        )
                        time.sleep(delay)
                        continue
                raise

        if last_error:
            raise last_error
        raise sqlite3.Error("Unknown database error")

    def fetchone(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> sqlite3.Row | None:
        """查询单行结果.

        Args:
            sql: SELECT 语句
            params: 参数

        Returns:
            sqlite3.Row 或 None
        """
        cursor = self.execute(sql, params)
        return cursor.fetchone()

    def fetchall(
        self, sql: str, params: Sequence[Any] | None = None
    ) -> list[sqlite3.Row]:
        """查询所有结果.

        Args:
            sql: SELECT 语句
            params: 参数

        Returns:
            sqlite3.Row 列表
        """
        cursor = self.execute(sql, params)
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # 事务管理
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文管理器.

        使用方式::

            with db.transaction() as conn:
                conn.execute(...)
                conn.execute(...)
            # 自动提交，异常时自动回滚

        Yields:
            sqlite3.Connection 连接对象（在事务内）
        """
        self._ensure_open()
        with self._lock:
            assert self._conn is not None
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """快速健康检查（执行一条简单 SQL）.

        Returns:
            True 表示数据库正常
        """
        try:
            self.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error("db_unhealthy", db_path=self._db_path, error=str(e))
            return False

    def integrity_check(self) -> dict[str, Any]:
        """执行数据库完整性检查.

        Returns:
            包含检查结果的字典：
            - ok: bool 是否通过
            - details: str 详细信息
        """
        try:
            cursor = self.execute("PRAGMA integrity_check")
            row = cursor.fetchone()
            result = row[0] if row else "unknown"
            ok = result == "ok"
            if not ok:
                logger.error(
                    "db_integrity_check_failed",
                    db_path=self._db_path,
                    result=result,
                )
            return {"ok": ok, "details": result}
        except Exception as e:
            logger.error(
                "db_integrity_check_error",
                db_path=self._db_path,
                error=str(e),
            )
            return {"ok": False, "details": str(e)}

    # ------------------------------------------------------------------
    # 损坏检测与恢复
    # ------------------------------------------------------------------

    def _handle_corruption(self) -> None:
        """处理数据库损坏：备份旧文件并重建.

        将损坏的数据库文件备份为 .corrupted-{timestamp}，
        然后重新建立连接（新的空数据库）。
        """
        if not os.path.exists(self._db_path):
            return

        # 关闭当前连接
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

        # 备份损坏文件
        timestamp = int(time.time())
        backup_path = f"{self._db_path}.corrupted-{timestamp}"
        try:
            shutil.copy2(self._db_path, backup_path)
            logger.critical(
                "db_corrupted_backup_created",
                db_path=self._db_path,
                backup_path=backup_path,
            )
        except Exception as e:
            logger.critical(
                "db_corrupted_backup_failed",
                db_path=self._db_path,
                error=str(e),
            )

        # 删除损坏文件，重建
        try:
            os.remove(self._db_path)
            # 同时删除 WAL 和 SHM 文件
            for suffix in ("-wal", "-shm"):
                sidecar = self._db_path + suffix
                if os.path.exists(sidecar):
                    os.remove(sidecar)
        except Exception as e:
            logger.critical(
                "db_corrupted_remove_failed",
                db_path=self._db_path,
                error=str(e),
            )
            raise DatabaseCorruptedError(
                f"Database corrupted and cannot be removed: {self._db_path}"
            ) from e

        # 重新建立连接与表结构
        try:
            self._connect()
            self._enable_wal()
            logger.info(
                "db_corrupted_rebuilt",
                db_path=self._db_path,
                backup_path=backup_path,
            )
        except Exception as e:
            logger.critical(
                "db_corrupted_rebuild_failed",
                db_path=self._db_path,
                error=str(e),
            )
            raise DatabaseCorruptedError(
                f"Database corrupted and rebuild failed: {self._db_path}"
            ) from e

    # ------------------------------------------------------------------
    # 索引管理
    # ------------------------------------------------------------------

    def ensure_index(self, table: str, column: str, unique: bool = False) -> None:
        """确保索引存在.

        Args:
            table: 表名
            column: 列名
            unique: 是否唯一索引
        """
        idx_name = f"idx_{table}_{column}"
        unique_keyword = "UNIQUE" if unique else ""
        self.execute(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"
            if not unique
            else f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"
        )

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在.

        Args:
            table_name: 表名

        Returns:
            True 表示存在
        """
        row = self.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        """确保数据库连接处于打开状态."""
        if self._closed:
            raise RuntimeError(f"Database is closed: {self._db_path}")
        if self._conn is None:
            self._connect()
            self._enable_wal()

    def close(self) -> None:
        """优雅关闭数据库连接.

        执行 PRAGMA optimize 优化查询计划，然后检查点 WAL 文件，
        最后关闭连接。
        """
        if self._closed:
            return
        self._closed = True

        try:
            if self._conn:
                with self._lock:
                    # 优化查询计划
                    self._conn.execute("PRAGMA optimize")
                    # 执行检查点，将 WAL 写入主文件
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._conn.close()
                    self._conn = None
                logger.info("db_closed_gracefully", db_path=self._db_path)
        except Exception as e:
            logger.warning(
                "db_close_error",
                db_path=self._db_path,
                error=str(e),
            )
            # 强制关闭
            try:
                if self._conn:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "SQLiteDatabase":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass


# 方便的全局函数别名
@contextmanager
def transaction(db: SQLiteDatabase) -> Iterator[sqlite3.Connection]:
    """全局事务上下文管理器（与 db.transaction() 等效）.

    Args:
        db: SQLiteDatabase 实例

    Yields:
        sqlite3.Connection 连接对象
    """
    with db.transaction() as conn:
        yield conn


class BaseRepository:
    """Repository 基类，提供通用 CRUD 与索引管理能力.

    所有具体 Repository 应继承此类，通过组合 SQLiteDatabase 实现
    数据访问逻辑。子类需实现 _create_tables() 方法定义表结构。

    Args:
        db: SQLiteDatabase 实例
    """

    #: 表名（子类必须设置）
    table_name: str = ""

    #: 主键列名（默认 id）
    primary_key: str = "id"

    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db
        self._create_tables()
        self._create_indexes()

    # ------------------------------------------------------------------
    # 子类需实现的方法
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        """创建表结构（子类必须实现）.

        使用 CREATE TABLE IF NOT EXISTS 语句。
        """
        raise NotImplementedError("Subclasses must implement _create_tables()")

    def _create_indexes(self) -> None:
        """创建索引（子类可选实现）.

        默认不创建任何索引。
        """

    # ------------------------------------------------------------------
    # 通用 CRUD 方法
    # ------------------------------------------------------------------

    @property
    def db(self) -> SQLiteDatabase:
        """获取底层数据库实例."""
        return self._db

    def get_by_id(self, record_id: str) -> sqlite3.Row | None:
        """按主键查询单条记录.

        Args:
            record_id: 主键值

        Returns:
            sqlite3.Row 或 None
        """
        return self._db.fetchone(
            f"SELECT * FROM {self.table_name} WHERE {self.primary_key} = ?",
            (record_id,),
        )

    def delete_by_id(self, record_id: str) -> int:
        """按主键删除记录.

        Args:
            record_id: 主键值

        Returns:
            受影响行数
        """
        cursor = self._db.execute(
            f"DELETE FROM {self.table_name} WHERE {self.primary_key} = ?",
            (record_id,),
        )
        return cursor.rowcount

    def count(self, where: str = "", params: Sequence[Any] | None = None) -> int:
        """统计记录数.

        Args:
            where: WHERE 子句（不含 WHERE 关键字，使用 ? 占位符）
            params: WHERE 参数

        Returns:
            记录总数
        """
        where_clause = f" WHERE {where}" if where else ""
        row = self._db.fetchone(
            f"SELECT COUNT(*) FROM {self.table_name}{where_clause}",
            params or (),
        )
        return row[0] if row else 0

    def exists(self, record_id: str) -> bool:
        """检查记录是否存在.

        Args:
            record_id: 主键值

        Returns:
            True 表示存在
        """
        row = self._db.fetchone(
            f"SELECT 1 FROM {self.table_name} WHERE {self.primary_key} = ? LIMIT 1",
            (record_id,),
        )
        return row is not None

    def list_all(
        self,
        order_by: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """查询所有记录（分页）.

        Args:
            order_by: 排序子句（如 "created_at DESC"）
            limit: 每页数量
            offset: 偏移量

        Returns:
            sqlite3.Row 列表
        """
        order_clause = f" ORDER BY {order_by}" if order_by else ""
        return self._db.fetchall(
            f"SELECT * FROM {self.table_name}{order_clause} LIMIT ? OFFSET ?",
            (limit, offset),
        )

    # ------------------------------------------------------------------
    # 索引管理辅助方法
    # ------------------------------------------------------------------

    def _ensure_index(self, column: str, unique: bool = False) -> None:
        """确保单列索引存在（子类在 _create_indexes 中调用）.

        Args:
            column: 列名
            unique: 是否唯一索引
        """
        self._db.ensure_index(self.table_name, column, unique=unique)

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def is_healthy(self) -> bool:
        """Repository 健康检查."""
        return self._db.is_healthy()

    def integrity_check(self) -> dict[str, Any]:
        """完整性检查."""
        return self._db.integrity_check()

    # ------------------------------------------------------------------
    # 事务快捷方式
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文管理器."""
        with self._db.transaction() as conn:
            yield conn
