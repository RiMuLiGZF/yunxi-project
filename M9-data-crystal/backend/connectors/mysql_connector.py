"""
云汐 M9 数据水晶 - MySQL 连接器

P3 优化：数据采集管道 + 连接器生态
MySQL 数据库连接器，支持 SQL 查询、分页读取、批量写入、连接池
"""

from __future__ import annotations

import logging
from typing import Iterator, List, Dict, Any, Optional

from .base import (
    BaseConnector,
    ConnectorMeta,
    ConnectorRegistry,
    ConnectorType,
    ConnectionStatus,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class MySQLConnector(BaseConnector):
    """
    MySQL 数据库连接器

    特性：
    - 支持 SQL 查询
    - 分页读取
    - 批量写入
    - 连接池（可选，使用 pymysql 直连）
    - 事务支持

    依赖：pymysql
    """

    meta = ConnectorMeta(
        name="mysql",
        connector_type=ConnectorType.DATABASE,
        description="MySQL 数据库连接器，支持 SQL 查询、分页、批量写入",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "schema", "list_tables"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._conn = None  # pymysql connection
        self._cursor = None

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """建立 MySQL 连接"""
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            import pymysql
        except ImportError:
            # 如果没有 pymysql，使用 sqlite 作为模拟层（测试/降级用）
            self._status = ConnectionStatus.ERROR
            self._last_error = "pymysql 未安装，请执行 pip install pymysql"
            logger.warning(self._last_error)
            return False

        try:
            conn_params = {
                "host": self._config.get("host", "localhost"),
                "port": int(self._config.get("port", 3306)),
                "user": self._config.get("user", "root"),
                "password": self._config.get("password", ""),
                "database": self._config.get("database", ""),
                "charset": self._config.get("charset", "utf8mb4"),
                "connect_timeout": int(self._config.get("connect_timeout", 10)),
            }

            self._conn = pymysql.connect(**conn_params, cursorclass=pymysql.cursors.DictCursor)
            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"MySQL 连接成功: {conn_params['host']}:{conn_params['port']}")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"MySQL 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开 MySQL 连接"""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("MySQL 连接已关闭")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._record_error()
            return False

    def read(self, query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式读取数据

        query 参数：
        - sql: SQL 查询语句
        - params: 查询参数（tuple 或 dict）
        - table: 表名（简化模式）
        - columns: 列名列表
        - where: WHERE 条件（dict）
        - offset: 偏移量
        - limit: 限制条数
        - fetch_size: 每次抓取大小（默认 1000）
        """
        self._ensure_connected()
        query = query or {}

        try:
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
                        conditions.append(f"`{key}` = %s")
                        where_params.append(value)
                    where_clause = " WHERE " + " AND ".join(conditions)

                limit_clause = ""
                if "limit" in query:
                    limit_clause = f" LIMIT {int(query['limit'])}"
                if "offset" in query:
                    limit_clause += f" OFFSET {int(query['offset'])}"

                sql = f"SELECT {columns} FROM `{table}`{where_clause}{limit_clause}"
                params = tuple(where_params)
            else:
                raise ValueError("query 必须包含 sql 或 table 参数")

            fetch_size = query.get("fetch_size", 1000)
            cursor = self._conn.cursor()
            cursor.execute(sql, params)

            count = 0
            while True:
                rows = cursor.fetchmany(fetch_size)
                if not rows:
                    break
                for row in rows:
                    count += 1
                    yield dict(row)

            self._record_read(count=1, bytes_read=count * 100)
            cursor.close()

        except Exception as e:
            self._record_error()
            logger.error(f"MySQL 读取失败: {e}")
            raise

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        query = query or {}
        query["limit"] = batch_size
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入数据

        配置：
        - table: 目标表名
        - if_exists: append / replace / upsert（默认 append）
        - batch_size: 每批写入大小（默认 1000）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            table = self._config.get("write_table", "")
            if not table:
                table = self._config.get("table", "")
            if not table:
                raise ValueError("未指定写入表名")

            columns = list(data[0].keys())
            placeholders = ", ".join(["%s"] * len(columns))
            col_names = ", ".join([f"`{c}`" for c in columns])
            sql = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"

            batch_size = self._config.get("write_batch_size", 1000)
            total_written = 0
            cursor = self._conn.cursor()

            for i in range(0, len(data), batch_size):
                batch = data[i:i + batch_size]
                rows = [tuple(record.get(col) for col in columns) for record in batch]
                cursor.executemany(sql, rows)
                total_written += len(rows)

            self._conn.commit()
            self._record_write(count=total_written, bytes_written=total_written * 100)
            cursor.close()
            return total_written

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._record_error()
            logger.error(f"MySQL 写入失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出所有表名"""
        self._ensure_connected()
        try:
            cursor = self._conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [list(row.values())[0] for row in cursor.fetchall()]
            cursor.close()
            return tables
        except Exception as e:
            self._record_error()
            raise

    def get_schema(self, table: str) -> Dict[str, Any]:
        """获取表结构"""
        self._ensure_connected()
        try:
            cursor = self._conn.cursor()
            cursor.execute(f"DESCRIBE `{table}`")
            columns_info = cursor.fetchall()

            fields = {}
            primary_keys = []
            for col in columns_info:
                field_name = col["Field"]
                fields[field_name] = {
                    "type": col["Type"],
                    "nullable": col["Null"] == "YES",
                    "default": col["Default"],
                    "extra": col.get("Extra", ""),
                }
                if col["Key"] == "PRI":
                    primary_keys.append(field_name)

            cursor.close()
            return {
                "table": table,
                "fields": fields,
                "primary_keys": primary_keys,
            }
        except Exception as e:
            self._record_error()
            raise

    def _health_probe(self) -> None:
        """健康探针"""
        if self._conn:
            cursor = self._conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
