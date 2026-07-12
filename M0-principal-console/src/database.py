"""
M0 主理人管控台 - SQLite 数据库连接

MVP 版本仅用于存储审计日志等本地数据，
主要数据通过 M8 接口获取。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .config import settings


def get_db_path() -> Path:
    """
    获取数据库文件路径

    Returns:
        Path: 数据库文件绝对路径
    """
    db_dir = settings.data_dir
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "m0.db"


def get_connection() -> sqlite3.Connection:
    """
    获取数据库连接

    Returns:
        sqlite3.Connection: 数据库连接对象
    """
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    # 启用外键约束
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """
    初始化数据库，创建所需表结构

    MVP 版本创建以下表：
    - audit_logs: 审计日志
    - config_store: 配置存储
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 审计日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                operator TEXT NOT NULL,
                module TEXT DEFAULT 'system',
                detail TEXT DEFAULT '',
                ip TEXT,
                success INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        # 配置存储表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                description TEXT,
                updated_at TEXT NOT NULL
            )
        """)

        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
            ON audit_logs(created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_logs_action
            ON audit_logs(action)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config_store_category
            ON config_store(category)
        """)

        conn.commit()
    finally:
        conn.close()


def execute_query(sql: str, params: Optional[tuple] = None) -> list:
    """
    执行查询语句并返回结果列表

    Args:
        sql: SQL 语句
        params: 参数元组

    Returns:
        list: 查询结果行列表
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def execute_update(sql: str, params: Optional[tuple] = None) -> int:
    """
    执行更新语句（INSERT/UPDATE/DELETE）

    Args:
        sql: SQL 语句
        params: 参数元组

    Returns:
        int: 受影响的行数
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
