"""
PostgreSQL 迁移适配器
====================

为 MigrationEngine 提供 PostgreSQL 后端支持。
基于 psycopg2 或 psycopg (psycopg3) 实现。

设计原则：
- 与 SQLiteMigrationAdapter / SQLAlchemyMigrationAdapter 保持接口一致
- 支持标准的 PostgreSQL 连接方式（DSN / 参数）
- 事务、查询、执行等操作完全兼容 MigrationEngine 接口
- 自动创建 schema_migrations 表（PostgreSQL 方言）
- 支持 ON CONFLICT (PostgreSQL 原生 UPSERT)

使用方式::

    from shared.data.data_layer.postgres_adapter import PostgreSQLMigrationAdapter
    from shared.data.data_layer.migration import MigrationEngine

    adapter = PostgreSQLMigrationAdapter(
        host="localhost",
        port=5432,
        dbname="yunxi",
        user="postgres",
        password="secret",
    )
    engine = MigrationEngine(db_manager=adapter)
    engine.migrate("default", migrations)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, ContextManager, Dict, List, Optional, Tuple

from .migration import BaseMigrationAdapter


class PostgreSQLMigrationAdapter(BaseMigrationAdapter):
    """PostgreSQL 迁移适配器

    使用 psycopg2 或 psycopg (v3) 连接 PostgreSQL 数据库，
    适配到 MigrationEngine 所需的统一接口。

    支持两种初始化方式：
    1. DSN 字符串: ``PostgreSQLMigrationAdapter(dsn="postgresql://...")``
    2. 连接参数: ``PostgreSQLMigrationAdapter(host=..., port=..., dbname=..., ...)``

    Attributes:
        _dsn: 连接 DSN 字符串
        _conn: 缓存的数据库连接
        _autocommit: 是否自动提交模式
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        schema: str = "public",
        connection=None,
    ):
        """
        初始化 PostgreSQL 适配器

        Args:
            dsn: PostgreSQL DSN 连接字符串，如 "host=... dbname=..." 或 "postgresql://..."
            host: 数据库主机地址
            port: 数据库端口
            dbname: 数据库名称
            user: 用户名
            password: 密码
            schema: 默认 schema（迁移记录表所在 schema）
            connection: 外部传入的现有连接（可选）
        """
        self._psycopg = self._import_psycopg()
        self._schema = schema
        self._dsn = dsn
        self._conn_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }
        # 过滤掉 None 值
        self._conn_params = {k: v for k, v in self._conn_params.items() if v is not None}

        self._external_conn = connection
        self._conn = None

    # --------------------------------------------------------
    #  内部工具方法
    # --------------------------------------------------------

    @staticmethod
    def _import_psycopg():
        """导入 psycopg 库（优先 psycopg3，回退 psycopg2）"""
        try:
            import psycopg  # psycopg3
            return psycopg
        except ImportError:
            pass

        try:
            import psycopg2 as psycopg  # psycopg2
            return psycopg
        except ImportError as e:
            raise ImportError(
                "PostgreSQL 适配器需要 psycopg 或 psycopg2 库，"
                "请先安装: pip install psycopg[binary] 或 pip install psycopg2-binary"
            ) from e

    def _build_dsn(self) -> str:
        """构建 DSN 连接字符串"""
        if self._dsn:
            return self._dsn

        parts = []
        for key, value in self._conn_params.items():
            if value is not None:
                parts.append(f"{key}={value}")
        return " ".join(parts)

    def _get_connection_raw(self):
        """获取原生 psycopg 连接"""
        if self._external_conn is not None:
            return self._external_conn

        if self._conn is None:
            dsn = self._build_dsn()
            self._conn = self._psycopg.connect(dsn)

        return self._conn

    def _is_psycopg3(self) -> bool:
        """判断是否为 psycopg3"""
        # psycopg3 有 Connection.cursor 但返回不同类型
        # 通过版本号判断
        try:
            return hasattr(self._psycopg, "__version__") and self._psycopg.__version__.startswith("3.")
        except Exception:
            return False

    def _execute(
        self,
        conn: Any,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Any:
        """执行 SQL，返回 cursor"""
        # PostgreSQL 使用 %s 占位符，需要将 ? 转换
        pg_sql = self._convert_placeholders(sql)
        cursor = conn.cursor()
        cursor.execute(pg_sql, params or ())
        return cursor

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        """将 SQLite 风格的 ? 占位符转换为 PostgreSQL 风格的 %s"""
        # 简单替换：假设 ? 只用作参数占位符
        # 注意：如果 SQL 字符串字面量中包含 ?，此方法会出错
        # 但迁移 SQL 中通常不会出现这种情况
        result = []
        i = 0
        in_string = False
        string_char = None

        while i < len(sql):
            char = sql[i]

            if not in_string:
                if char in ("'", '"'):
                    in_string = True
                    string_char = char
                    result.append(char)
                elif char == "?":
                    result.append("%s")
                else:
                    result.append(char)
            else:
                result.append(char)
                if char == string_char and (i + 1 >= len(sql) or sql[i + 1] != string_char):
                    # 检查是否为转义（连续两个相同引号）
                    if i + 1 < len(sql) and sql[i + 1] == string_char:
                        result.append(string_char)
                        i += 1
                    else:
                        in_string = False
                        string_char = None
            i += 1

        return "".join(result)

    @staticmethod
    def _row_to_dict(cursor: Any, row: Any) -> Dict[str, Any]:
        """将 cursor 行转换为字典"""
        if row is None:
            return {}
        # psycopg2/3 的 cursor.description 包含列名
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    # --------------------------------------------------------
    #  BaseMigrationAdapter 接口实现
    # --------------------------------------------------------

    @contextmanager
    def get_connection(self, db_name: str, write: bool = False):
        """获取数据库连接（上下文管理器）

        Args:
            db_name: 数据库标识（PostgreSQL 适配器中用于 schema 选择）
            write: 是否为写操作
        """
        conn = self._get_connection_raw()
        try:
            # 设置 search_path
            if self._schema and self._schema != "public":
                try:
                    cur = conn.cursor()
                    cur.execute(f"SET search_path TO {self._schema}")
                except Exception:
                    pass
            yield conn
        finally:
            # 外部连接不关闭
            if self._external_conn is None and self._conn is None:
                # 临时连接才关闭
                pass

    @contextmanager
    def transaction(self, db_name: str):
        """事务上下文管理器

        使用 PostgreSQL 的标准事务机制。
        对于外部传入的连接，使用 SAVEPOINT 嵌套事务。
        """
        conn = self._get_connection_raw()

        if self._external_conn is not None:
            # 外部连接可能已有事务，使用 savepoint
            savepoint_name = f"sp_migration_{int(time.time() * 1000)}"
            try:
                cur = conn.cursor()
                cur.execute(f"SAVEPOINT {savepoint_name}")
                yield conn
                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            except Exception:
                try:
                    cur = conn.cursor()
                    cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                except Exception:
                    pass
                raise
        else:
            # 自有连接：使用完整事务
            try:
                conn.rollback()  # 确保没有未完成的事务
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        """查询单行数据"""
        with self.get_connection(db_name) as conn:
            cursor = self._execute(conn, sql, params)
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_dict(cursor, row)

    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """查询多行数据"""
        with self.get_connection(db_name) as conn:
            cursor = self._execute(conn, sql, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]

    def get_db_path(self, db_name: str) -> Optional[str]:
        """PostgreSQL 无本地文件路径，返回 None"""
        return None

    # --------------------------------------------------------
    #  PostgreSQL 特有方法
    # --------------------------------------------------------

    def list_tables(self, db_name: str) -> List[str]:
        """列出当前 schema 下的所有表"""
        sql = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
        """
        rows = self.query_all(db_name, sql, (self._schema,))
        return [r["table_name"] for r in rows]

    def table_exists(self, db_name: str, table_name: str) -> bool:
        """检查表是否存在"""
        sql = """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """
        result = self.query_one(db_name, sql, (self._schema, table_name))
        return result is not None

    def get_table_row_count(self, db_name: str, table_name: str) -> int:
        """获取表的行数（安全版本）"""
        # 白名单校验：表名只允许字母数字下划线
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        sql = f"SELECT COUNT(*) as cnt FROM {self._schema}.{table_name}"
        result = self.query_one(db_name, sql)
        return int(result["cnt"]) if result else 0

    def close(self):
        """关闭数据库连接（仅自有连接）"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self):
        """析构时关闭连接"""
        try:
            self.close()
        except Exception:
            pass
