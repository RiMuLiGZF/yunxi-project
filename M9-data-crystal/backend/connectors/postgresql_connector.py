"""
云汐 M9 数据水晶 - PostgreSQL 连接器

P3 优化：数据采集管道 + 连接器生态
PostgreSQL 数据库连接器，支持 SQL 查询、JSONB、分页、批量写入
"""

from __future__ import annotations

import logging
import json
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
class PostgreSQLConnector(BaseConnector):
    """
    PostgreSQL 数据库连接器

    特性：
    - 支持 SQL 查询
    - 支持 JSONB 字段
    - 分页读取
    - 批量写入
    - 事务支持
    - 连接池（可选）

    依赖：psycopg2-binary
    """

    meta = ConnectorMeta(
        name="postgresql",
        connector_type=ConnectorType.DATABASE,
        description="PostgreSQL 数据库连接器，支持 JSONB、SQL 查询、批量写入",
        version="1.0.0",
        supported_operations=["read", "write", "batch_read", "batch_write", "schema", "list_tables"],
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._conn = None  # psycopg2 connection
        self._schema = config.get("schema", "public") if config else "public"

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """建立 PostgreSQL 连接"""
        if config:
            self._config.update(config)

        self._status = ConnectionStatus.CONNECTING
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            self._status = ConnectionStatus.ERROR
            self._last_error = "psycopg2 未安装，请执行 pip install psycopg2-binary"
            logger.warning(self._last_error)
            return False

        try:
            conn_params = {
                "host": self._config.get("host", "localhost"),
                "port": int(self._config.get("port", 5432)),
                "user": self._config.get("user", "postgres"),
                "password": self._config.get("password", ""),
                "dbname": self._config.get("database", "postgres"),
                "connect_timeout": int(self._config.get("connect_timeout", 10)),
            }

            self._conn = psycopg2.connect(**conn_params)
            self._conn.autocommit = False
            self._schema = self._config.get("schema", "public")

            # 设置搜索路径
            with self._conn.cursor() as cur:
                cur.execute(f"SET search_path TO {self._schema}")

            self._status = ConnectionStatus.CONNECTED
            self._stats.connection_count += 1
            logger.info(f"PostgreSQL 连接成功: {conn_params['host']}:{conn_params['port']}")
            return True

        except Exception as e:
            self._status = ConnectionStatus.ERROR
            self._last_error = str(e)
            self._record_error()
            logger.error(f"PostgreSQL 连接失败: {e}")
            return False

    def disconnect(self) -> bool:
        """断开 PostgreSQL 连接"""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("PostgreSQL 连接已关闭")
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
        - params: 查询参数
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
            import psycopg2.extras

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
                    idx = 1
                    for key, value in query["where"].items():
                        conditions.append(f'"{key}" = %s')
                        where_params.append(value)
                        idx += 1
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

            fetch_size = query.get("fetch_size", 1000)
            cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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
            logger.error(f"PostgreSQL 读取失败: {e}")
            raise

    def read_batch(self, batch_size: int = 100, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """批量读取"""
        query = query or {}
        query["limit"] = batch_size
        return super().read_batch(batch_size, query)

    def write(self, data: List[Dict[str, Any]]) -> int:
        """
        批量写入数据，支持 JSONB 字段

        配置：
        - table: 目标表名
        - if_exists: append / upsert（默认 append）
        - batch_size: 每批大小（默认 1000）
        - jsonb_fields: JSONB 字段列表（自动序列化 dict 值）
        """
        self._ensure_connected()

        if not data:
            return 0

        try:
            import psycopg2.extras

            table = self._config.get("write_table", "")
            if not table:
                table = self._config.get("table", "")
            if not table:
                raise ValueError("未指定写入表名")

            jsonb_fields = set(self._config.get("jsonb_fields", []))
            columns = list(data[0].keys())
            col_names = ", ".join([f'"{c}"' for c in columns])

            # 处理 JSONB 字段
            processed_data = []
            for record in data:
                processed = {}
                for col in columns:
                    val = record.get(col)
                    if col in jsonb_fields and isinstance(val, (dict, list)):
                        processed[col] = json.dumps(val, ensure_ascii=False)
                    else:
                        processed[col] = val
                processed_data.append(processed)

            batch_size = self._config.get("write_batch_size", 1000)
            total_written = 0

            for i in range(0, len(processed_data), batch_size):
                batch = processed_data[i:i + batch_size]
                values_template = f"({', '.join(['%s'] * len(columns))})"

                # 构建 VALUES
                values_list = []
                for record in batch:
                    values_list.append(tuple(record.get(col) for col in columns))

                # 使用 mogrify 提升性能
                cursor = self._conn.cursor()
                args_str = ",".join(
                    cursor.mogrify(values_template, v).decode("utf-8")
                    for v in values_list
                )
                cursor.execute(f'INSERT INTO "{table}" ({col_names}) VALUES ' + args_str)
                total_written += len(batch)
                cursor.close()

            self._conn.commit()
            self._record_write(count=total_written, bytes_written=total_written * 100)
            return total_written

        except Exception as e:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._record_error()
            logger.error(f"PostgreSQL 写入失败: {e}")
            raise

    def list_tables(self) -> List[str]:
        """列出当前 schema 下的所有表"""
        self._ensure_connected()
        try:
            cursor = self._conn.cursor()
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = %s
                ORDER BY table_name
            """, (self._schema,))
            tables = [row[0] for row in cursor.fetchall()]
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
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default,
                       character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (self._schema, table))
            columns_info = cursor.fetchall()

            fields = {}
            for col_name, data_type, is_nullable, default_val, char_max_len in columns_info:
                fields[col_name] = {
                    "type": data_type,
                    "nullable": is_nullable == "YES",
                    "default": default_val,
                    "max_length": char_max_len,
                }

            # 获取主键信息
            cursor.execute("""
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = %s AND tc.table_name = %s
                    AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
            """, (self._schema, table))
            primary_keys = [row[0] for row in cursor.fetchall()]

            cursor.close()
            return {
                "table": table,
                "schema": self._schema,
                "fields": fields,
                "primary_keys": primary_keys,
            }
        except Exception as e:
            self._record_error()
            raise

    def _health_probe(self) -> None:
        """健康探针"""
        if self._conn:
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
