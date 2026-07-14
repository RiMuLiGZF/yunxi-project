"""
统一 SQLite 连接管理

提供上下文管理器 get_connection() 和便捷函数 execute_sql()，
统一管理所有模块散落的 sqlite3.connect() 调用。

特性：
- 上下文管理器自动关闭连接
- WAL 模式 + busy_timeout 等统一 PRAGMA 配置
- 基于 threading.local 的简单连接池（按 db_path 隔离）
- 与 DatabaseMigrator 完全兼容

使用方式::

    from tide_memory.db import get_connection, execute_sql

    # 上下文管理器
    with get_connection("/path/to/db.sqlite3") as conn:
        conn.execute("SELECT 1")

    # 便捷函数
    rows = execute_sql("SELECT * FROM memories WHERE domain = ?", ("private",))
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, List, Optional, Tuple, Union

import structlog

logger = structlog.get_logger(__name__)

# ============================================================
# 默认连接参数
# ============================================================

_DEFAULT_JOURNAL_MODE = "WAL"
_DEFAULT_BUSY_TIMEOUT = 30.0
_DEFAULT_SYNCHRONOUS = "NORMAL"
_DEFAULT_CACHE_SIZE_KB = -20000
_DEFAULT_TEMP_STORE = "MEMORY"
_DEFAULT_MMAP_SIZE = 268435456  # 256MB


# ============================================================
# 线程本地连接池（按 db_path 隔离）
# ============================================================

_thread_local = threading.local()


def _get_pool_key(db_path: str) -> str:
    """获取连接池的规范化 key"""
    return os.path.abspath(db_path)


def _get_thread_conn(db_path: str) -> Optional[sqlite3.Connection]:
    """从线程本地存储获取已有连接"""
    key = _get_pool_key(db_path)
    pool: dict = getattr(_thread_local, "_conn_pool", {})
    return pool.get(key)


def _set_thread_conn(db_path: str, conn: Optional[sqlite3.Connection]) -> None:
    """设置线程本地连接"""
    key = _get_pool_key(db_path)
    if not hasattr(_thread_local, "_conn_pool"):
        _thread_local._conn_pool = {}
    if conn is not None:
        _thread_local._conn_pool[key] = conn
    else:
        _thread_local._conn_pool.pop(key, None)


def _apply_pragmas(
    conn: sqlite3.Connection,
    journal_mode: Optional[str] = None,
    busy_timeout: Optional[float] = None,
    synchronous: Optional[str] = None,
    cache_size_kb: Optional[int] = None,
    temp_store: Optional[str] = None,
    mmap_size: Optional[int] = None,
) -> None:
    """
    应用 SQLite PRAGMA 配置

    Args:
        conn: 数据库连接
        journal_mode: 日志模式（默认 WAL）
        busy_timeout: 忙等待超时（秒）
        synchronous: 同步级别
        cache_size_kb: 页缓存大小（KB，负数）
        temp_store: 临时存储位置
        mmap_size: 内存映射大小（字节）
    """
    journal_mode = journal_mode or _DEFAULT_JOURNAL_MODE
    busy_timeout = busy_timeout if busy_timeout is not None else _DEFAULT_BUSY_TIMEOUT
    synchronous = synchronous or _DEFAULT_SYNCHRONOUS
    cache_size_kb = cache_size_kb if cache_size_kb is not None else _DEFAULT_CACHE_SIZE_KB
    temp_store = temp_store or _DEFAULT_TEMP_STORE
    mmap_size = mmap_size if mmap_size is not None else _DEFAULT_MMAP_SIZE

    conn.execute(f"PRAGMA journal_mode={journal_mode};")
    conn.execute(f"PRAGMA synchronous={synchronous};")
    conn.execute(f"PRAGMA cache_size={cache_size_kb};")
    conn.execute(f"PRAGMA temp_store={temp_store};")
    conn.execute(f"PRAGMA mmap_size={mmap_size};")


# ============================================================
# 核心上下文管理器
# ============================================================

@contextmanager
def get_connection(
    db_path: str,
    *,
    check_same_thread: bool = False,
    timeout: Optional[float] = None,
    row_factory: Optional[type] = None,
    journal_mode: Optional[str] = None,
    busy_timeout: Optional[float] = None,
    synchronous: Optional[str] = None,
    cache_size_kb: Optional[int] = None,
    temp_store: Optional[str] = None,
    mmap_size: Optional[int] = None,
    apply_pragmas: bool = True,
):
    """
    获取 SQLite 连接的上下文管理器

    自动管理连接的打开和关闭。支持可选的 threading.local 连接池复用。

    Args:
        db_path: 数据库文件路径
        check_same_thread: 是否检查同一线程（默认 False）
        timeout: 连接超时秒数（默认 30）
        row_factory: 行工厂（如 sqlite3.Row）
        journal_mode: 日志模式
        busy_timeout: 忙等待超时
        synchronous: 同步级别
        cache_size_kb: 页缓存大小
        temp_store: 临时存储位置
        mmap_size: 内存映射大小
        apply_pragmas: 是否应用默认 PRAGMA 配置

    Yields:
        sqlite3.Connection: 数据库连接

    Example::

        with get_connection("/path/to/db.sqlite3") as conn:
            rows = conn.execute("SELECT * FROM t").fetchall()
        # 连接已自动关闭
    """
    timeout = timeout if timeout is not None else _DEFAULT_BUSY_TIMEOUT
    conn = None
    try:
        # 确保数据库目录存在
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(
            db_path,
            check_same_thread=check_same_thread,
            timeout=timeout,
        )

        # 设置行工厂
        if row_factory is not None:
            conn.row_factory = row_factory

        # 应用 PRAGMA 配置
        if apply_pragmas:
            _apply_pragmas(
                conn,
                journal_mode=journal_mode,
                busy_timeout=busy_timeout,
                synchronous=synchronous,
                cache_size_kb=cache_size_kb,
                temp_store=temp_store,
                mmap_size=mmap_size,
            )

        logger.debug(
            "db.connection.opened",
            db_path=db_path,
        )

        yield conn

    except sqlite3.Error as e:
        logger.error(
            "db.connection.error",
            db_path=db_path,
            error=str(e),
        )
        raise
    finally:
        if conn is not None:
            conn.close()
            logger.debug(
                "db.connection.closed",
                db_path=db_path,
            )


# ============================================================
# 连接池辅助（供需要长连接的场景使用）
# ============================================================

def get_pooled_connection(
    db_path: str,
    *,
    check_same_thread: bool = False,
    timeout: Optional[float] = None,
    row_factory: Optional[type] = None,
    apply_pragmas: bool = True,
) -> sqlite3.Connection:
    """
    获取线程本地的池化连接（不自动关闭）

    返回当前线程的连接（如已存在则复用），否则创建新连接。
    调用方负责在不再需要时调用 release_pooled_connection() 关闭连接。

    Args:
        db_path: 数据库文件路径
        check_same_thread: 是否检查同一线程
        timeout: 连接超时
        row_factory: 行工厂
        apply_pragmas: 是否应用 PRAGMA

    Returns:
        sqlite3.Connection: 池化的数据库连接
    """
    conn = _get_thread_conn(db_path)
    if conn is not None:
        # 检查缓存连接是否仍然有效
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            _set_thread_conn(db_path, None)
            # 连接已失效，继续创建新连接

    timeout = timeout if timeout is not None else _DEFAULT_BUSY_TIMEOUT
    conn = sqlite3.connect(
        db_path,
        check_same_thread=check_same_thread,
        timeout=timeout,
    )

    if row_factory is not None:
        conn.row_factory = row_factory

    if apply_pragmas:
        _apply_pragmas(conn)

    _set_thread_conn(db_path, conn)

    logger.debug(
        "db.connection.pooled_opened",
        db_path=db_path,
    )

    return conn


def release_pooled_connection(db_path: str) -> None:
    """
    释放线程本地的池化连接

    Args:
        db_path: 数据库文件路径
    """
    conn = _get_thread_conn(db_path)
    if conn is not None:
        conn.close()
        _set_thread_conn(db_path, None)
        logger.debug(
            "db.connection.pooled_released",
            db_path=db_path,
        )


def close_all_pooled_connections() -> None:
    """关闭当前线程的所有池化连接"""
    pool: dict = getattr(_thread_local, "_conn_pool", {})
    for key, conn in list(pool.items()):
        try:
            conn.close()
        except Exception:
            pass
    _thread_local._conn_pool = {}
    logger.debug("db.connection.all_pooled_closed")


# ============================================================
# 便捷函数
# ============================================================

def execute_sql(
    sql: str,
    params: Union[tuple, list] = (),
    *,
    db_path: str,
    fetch: str = "all",
    commit: bool = False,
) -> Any:
    """
    便捷执行 SQL 的函数

    自动获取连接、执行、返回结果、关闭连接。

    Args:
        sql: SQL 语句
        params: 参数元组/列表
        db_path: 数据库文件路径
        fetch: 返回模式：
            - "all": 返回所有行（默认）
            - "one": 返回单行
            - "none": 不获取结果，返回 None
        commit: 是否自动提交（写操作时设为 True）

    Returns:
        fetch="all" → List[Tuple]
        fetch="one" → Optional[Tuple]
        fetch="none" → None

    Example::

        rows = execute_sql(
            "SELECT * FROM memories WHERE domain = ?",
            ("private",),
            db_path="/path/to/db.sqlite3",
        )

        execute_sql(
            "INSERT INTO memories (id) VALUES (?)",
            ("mem_001",),
            db_path="/path/to/db.sqlite3",
            commit=True,
        )
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(sql, params)
        if commit:
            conn.commit()

        if fetch == "all":
            return cursor.fetchall()
        elif fetch == "one":
            return cursor.fetchone()
        return None