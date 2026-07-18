"""
云汐 M9 数据水晶 - SQLite 连接器

P3 优化：数据采集管道 + 连接器生态
轻量级文件数据库连接器，支持 SQL 查询、分页读取、批量写入
"""

from __future__ import annotations

import sqlite3
import logging
from typing import Iterator, List, Dict, Any, Optional
from pathlib import Path

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
    HealthStatus,
    HealthCheckResult,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class SQLiteConnector(BaseConnector):
    """
    SQLite 数据库连接器

    特性：
    - 轻量级文件数据库
    - 支持 SQL 查询
    - 分页读取
    - 批量写入
    - 内存数据库支持
    """

    meta = ConnectorMeta(
        name="sqlite",
        connector_type=ConnectorType.DATABASE,
        description="SQLite 轻量级文件数据库连接器",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "schema", "list_tables"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._conn: Optional[sqlite3.Connection] = None
        self._db_path: str = ""
        self._row_factory_enabled: bool = True

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """建立 SQLite 连接"""
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            db_path = self._config.get("db_path", "")
            if not db_path:
                db_path = self._config.get("path", ":memory:")

            self._db_path = db_path

            # 如果是文件路径，确保目录存在
            if db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(db_path)
            self._conn.row_factory = sqlite3.Row

            # 启用 WAL 模式提升并发性能
            if db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")

            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"SQLite 连接成功: {db_path}")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"SQLite 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开 SQLite 连接"""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("SQLite 连接已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            logger.error(f"SQLite 断开失败: {e}")
            return False

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取数据

        query 参数：
        - sql: SQL 查询语句
        - params: 查询参数
        - table: 表名（简化模式，不指定 sql 时使用）
        - columns: 列名列表
        - where: WHERE 条件（dict）
        - offset: 偏移量
        - limit: 限制条数
        """
        self._ensure_connected()
        query = query or {}

        try:
            # 构建 SQL
            if "sql" in query:
                sql = query["sql"]
                params = query.get("params", ())
            elif "table" in query:
                table = query["table"]
                columns = ", ".join(query.get("columns", ["*"]))
                where_clause = ""
                where_params = []
                if "where" in query and query["where"]:
                    conditions = []
                    for key, value in query["where"].items():
                        conditions.append(f'"{key}" = ?')
                        where_params.append(value)
                    where_clause = " WHERE " + " AND ".join(conditions)

                limit_clause = ""
                if "limit" in query:
                    limit_clause = f" LIMIT {int(query['limit'])}"
                if "offset" in query:
                    limit_clause += f" OFFSET {int(query['offset'])}"

                sql = f'SELECT {columns} FROM "{table}"{where_clause}{limit_clause}'
                params = tuple(where_params)
            else:
                raise ValueError("query 必须包含 sql 或 table 参数")

            cursor = self._conn.cursor()
            cursor.execute(sql, params)

            count = 0
            for row in cursor:
                record = dict(row)
                count += 1
                yield record

            self._record_read(count=1, bytes_read=count * 100)  # 估算字节数
            cursor.close()

        except Exception as e:
            self._record_error()
            logger.error(f"SQLite 读取失败: {e}")
            raise

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取数据"""
        query = query or {}
        query["limit"] = batch_size
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入数据

        query 参数（通过 data 中的配置传入，或使用 write_config）：
        - table: 目标表名
        - if_exists: append / replace / fail（默认 append）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            table = self._config.get("write_table", "")
            if not table:
                raise ValueError("未指定写入表名，请在配置中设置 write_table")

            columns = list(data[0].keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join([f'"{c}"' for c in columns])

            sql = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'

            cursor = self._conn.cursor()
            rows = [tuple(record.get(col) for col in columns) for record in data]
            cursor.executemany(sql, rows)
            self._conn.commit()

            count = len(rows)
            self._record_write(count=count, bytes_written=count * 100)
            cursor.close()
            return count

        except Exception as e:
            self._conn.rollback() if self._conn else None
            self._record_error()
            logger.error(f"SQLite 写入失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出所有表名"""
        self._ensure_connected()
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return tables
        except Exception as e:
            self._record_error()
            logger.error(f"SQLite list_tables 失败: {e}")
            raise

    def get_schema(self, table: str) -> Dict[str, Any]:
        """获取表结构"""
        self._ensure_connected()
        try:
            cursor = self._conn.cursor()
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns_info = cursor.fetchall()

            fields = {}
            for col_info in columns_info:
                cid, name, ctype, notnull, default, pk = col_info
                fields[name] = {
                    "type": ctype,
                    "nullable": not notnull,
                    "primary_key": bool(pk),
                    "default": default,
                }

            cursor.close()
            return {
                "table": table,
                "fields": fields,
                "primary_keys": [name for name, info in fields.items() if info["primary_key"]],
            }
        except Exception as e:
            self._record_error()
            logger.error(f"SQLite get_schema 失败: {e}")
            raise

    def _health_probe(self) -> None:
        """健康探针"""
        if self._conn:
            self._conn.execute("SELECT 1").fetchone()

    def create_table(self, table: str, schema: Dict[str, Any]) -> bool:
        """
        创建表

        Args:
            table: 表名
            schema: 表结构定义，格式：
                {
                    "fields": {
                        "id": {"type": "INTEGER", "primary_key": True, "autoincrement": True},
                        "name": {"type": "TEXT", "nullable": False},
                        ...
                    }
                }
        """
        self._ensure_connected()
        try:
            field_defs = []
            for field_name, field_info in schema.get("fields", {}).items():
                parts = [f'"{field_name}"', field_info.get("type", "TEXT")]
                if field_info.get("primary_key"):
                    parts.append("PRIMARY KEY")
                if field_info.get("autoincrement"):
                    parts.append("AUTOINCREMENT")
                if not field_info.get("nullable", True):
                    parts.append("NOT NULL")
                if "default" in field_info:
                    default_val = field_info["default"]
                    if isinstance(default_val, str):
                        parts.append(f"DEFAULT '{default_val}'")
                    else:
                        parts.append(f"DEFAULT {default_val}")
                field_defs.append(" ".join(parts))

            sql = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(field_defs)})'
            self._conn.execute(sql)
            self._conn.commit()
            return True
        except Exception as e:
            self._record_error()
            logger.error(f"SQLite 创建表失败: {e}")
            raise
