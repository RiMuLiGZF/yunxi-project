"""
SQLite 存储后端（SQLite Backend）
================================

基于 SQLite 的仓库实现，支持事务和复杂查询。

与现有 DatabaseManager 兼容，可直接复用连接池。
"""

from __future__ import annotations

import json
import time
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Type, Tuple
from pathlib import Path
from contextlib import contextmanager

from ..base import (
    BaseModel,
    BaseRepository,
    OrderBy,
    PaginationResult,
    QueryFilter,
    UnitOfWork,
    BackendFactory,
    T,
)


# ============================================================
# 安全标识符校验
# ============================================================

import re

_SAFE_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _safe_identifier(name: str, kind: str = "identifier") -> str:
    """校验 SQL 标识符安全性"""
    if not _SAFE_IDENT_RE.match(name):
        raise ValueError(f"Invalid {kind}: {repr(name)}")
    return name


# ============================================================
# SQLite 仓库实现
# ============================================================

class SQLiteRepository(BaseRepository[T]):
    """SQLite 仓库实现"""

    def __init__(self, backend: "SQLiteBackend", model_class: Type[BaseModel]):
        super().__init__(backend=backend)
        self._model_class = model_class
        self._table_name = _safe_identifier(model_class.__table_name__, "table name")
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保表存在（自动建表）"""
        columns = []
        pk_field = None

        for field_name, field_def in self._model_class.__fields__.items():
            _safe_identifier(field_name, "column name")
            col_type = self._map_type(field_def.get("type", str))
            col_def = f'"{field_name}" {col_type}'

            if field_def.get("primary_key"):
                pk_field = field_name
                col_def += " PRIMARY KEY"
                if field_def.get("auto_increment") and field_def.get("type") in (int, "int", "integer"):
                    col_def += " AUTOINCREMENT"

            if field_def.get("required") and not field_def.get("primary_key"):
                col_def += " NOT NULL"

            if "default" in field_def and not callable(field_def["default"]):
                default_val = field_def["default"]
                if isinstance(default_val, str):
                    col_def += f" DEFAULT '{default_val}'"
                elif default_val is not None:
                    col_def += f" DEFAULT {default_val}"

            if field_def.get("unique") and not field_def.get("primary_key"):
                col_def += " UNIQUE"

            columns.append(col_def)

        sql = f'CREATE TABLE IF NOT EXISTS "{self._table_name}" ({", ".join(columns)})'

        with self._backend.get_connection(write=True) as conn:
            conn.execute(sql)

    def _map_type(self, py_type: Any) -> str:
        """Python 类型到 SQLite 类型映射"""
        if py_type in (int, "int", "integer"):
            return "INTEGER"
        elif py_type in (float, "float", "real"):
            return "REAL"
        elif py_type in (bool, "bool"):
            return "INTEGER"
        elif py_type in (dict, list, "json"):
            return "TEXT"
        else:
            return "TEXT"

    def _row_to_model(self, row: sqlite3.Row) -> T:
        """将行转换为模型实例"""
        data = {}
        for field_name in self._model_class.__fields__:
            if field_name in row.keys():
                val = row[field_name]
                field_type = self._model_class.__fields__[field_name].get("type", str)
                if field_type in (dict, list, "json") and isinstance(val, str):
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif field_type is bool and isinstance(val, int):
                    val = bool(val)
                data[field_name] = val
        return self._model_class.from_dict(data)  # type: ignore

    def _serialize_value(self, field_name: str, value: Any) -> Any:
        """序列化值以存储"""
        if field_name not in self._model_class.__fields__:
            return value
        field_type = self._model_class.__fields__[field_name].get("type", str)
        if field_type in (dict, list, "json") and isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        elif field_type is bool and isinstance(value, bool):
            return 1 if value else 0
        return value

    def _do_create(self, data: Dict[str, Any]) -> T:
        # 过滤有效字段
        valid_data = {}
        for k, v in data.items():
            if k in self._model_class.__fields__:
                valid_data[k] = self._serialize_value(k, v)

        # 时间戳
        for ts_field in ["created_at", "updated_at"]:
            if ts_field in self._model_class.__fields__ and ts_field not in valid_data:
                valid_data[ts_field] = time.time()

        # 版本号
        if "version" in self._model_class.__fields__ and "version" not in valid_data:
            valid_data["version"] = 1

        columns = list(valid_data.keys())
        placeholders = ", ".join("?" for _ in columns)
        columns_str = ", ".join(f'"{c}"' for c in columns)
        values = tuple(valid_data[c] for c in columns)

        sql = f'INSERT INTO "{self._table_name}" ({columns_str}) VALUES ({placeholders})'

        with self._backend.get_connection(write=True) as conn:
            cursor = conn.execute(sql, values)
            pk = cursor.lastrowid

        # 读取刚创建的记录
        result = self._do_get_by_id(pk)
        if result:
            return result

        # 如果主键不是自增的，用传入的主键值
        pk_field = self._model_class.get_primary_key_field()
        if pk_field and pk_field in valid_data:
            result = self._do_get_by_id(valid_data[pk_field])
            if result:
                return result

        return self._model_class.from_dict(data)  # type: ignore

    def _do_get_by_id(self, pk: Any) -> Optional[T]:
        pk_field = self._model_class.get_primary_key_field() or "id"
        _safe_identifier(pk_field, "column name")

        sql = f'SELECT * FROM "{self._table_name}" WHERE "{pk_field}" = ? LIMIT 1'

        with self._backend.get_connection(write=False) as conn:
            cursor = conn.execute(sql, (pk,))
            row = cursor.fetchone()
            if row:
                return self._row_to_model(row)
        return None

    def _do_update(self, pk: Any, data: Dict[str, Any]) -> Optional[T]:
        pk_field = self._model_class.get_primary_key_field() or "id"
        _safe_identifier(pk_field, "column name")

        # 过滤有效字段
        valid_data = {}
        for k, v in data.items():
            if k in self._model_class.__fields__ and k != pk_field:
                valid_data[k] = self._serialize_value(k, v)

        if not valid_data:
            return self._do_get_by_id(pk)

        # 更新时间戳
        if "updated_at" in self._model_class.__fields__:
            valid_data["updated_at"] = time.time()

        # 版本号递增
        if "version" in self._model_class.__fields__:
            valid_data["version"] = self._get_version(pk) + 1

        set_clause = ", ".join(f'"{col}" = ?' for col in valid_data.keys())
        values = tuple(valid_data.values()) + (pk,)

        sql = f'UPDATE "{self._table_name}" SET {set_clause} WHERE "{pk_field}" = ?'

        with self._backend.get_connection(write=True) as conn:
            cursor = conn.execute(sql, values)
            if cursor.rowcount == 0:
                return None

        return self._do_get_by_id(pk)

    def _get_version(self, pk: Any) -> int:
        """获取当前版本号"""
        pk_field = self._model_class.get_primary_key_field() or "id"
        sql = f'SELECT version FROM "{self._table_name}" WHERE "{pk_field}" = ? LIMIT 1'
        with self._backend.get_connection(write=False) as conn:
            cursor = conn.execute(sql, (pk,))
            row = cursor.fetchone()
            if row and row["version"] is not None:
                return int(row["version"])
        return 0

    def _do_delete(self, pk: Any) -> bool:
        pk_field = self._model_class.get_primary_key_field() or "id"
        _safe_identifier(pk_field, "column name")

        sql = f'DELETE FROM "{self._table_name}" WHERE "{pk_field}" = ?'

        with self._backend.get_connection(write=True) as conn:
            cursor = conn.execute(sql, (pk,))
            return cursor.rowcount > 0

    def _build_where_clause(self, filters: List[QueryFilter]) -> Tuple[str, List[Any]]:
        """构建 WHERE 子句"""
        if not filters:
            return "", []

        conditions = []
        params: List[Any] = []

        for f in filters:
            _safe_identifier(f.field, "column name")
            col = f'"{f.field}"'

            if f.operator == "eq":
                conditions.append(f"{col} = ?")
                params.append(f.value)
            elif f.operator == "ne":
                conditions.append(f"{col} != ?")
                params.append(f.value)
            elif f.operator == "gt":
                conditions.append(f"{col} > ?")
                params.append(f.value)
            elif f.operator == "gte":
                conditions.append(f"{col} >= ?")
                params.append(f.value)
            elif f.operator == "lt":
                conditions.append(f"{col} < ?")
                params.append(f.value)
            elif f.operator == "lte":
                conditions.append(f"{col} <= ?")
                params.append(f.value)
            elif f.operator == "in":
                placeholders = ", ".join("?" for _ in (f.value or []))
                conditions.append(f"{col} IN ({placeholders})")
                params.extend(f.value or [])
            elif f.operator == "not_in":
                placeholders = ", ".join("?" for _ in (f.value or []))
                conditions.append(f"{col} NOT IN ({placeholders})")
                params.extend(f.value or [])
            elif f.operator == "like":
                conditions.append(f"{col} LIKE ?")
                params.append(f.value)
            elif f.operator == "contains":
                conditions.append(f"{col} LIKE ?")
                params.append(f"%{f.value}%")
            elif f.operator == "between":
                conditions.append(f"{col} BETWEEN ? AND ?")
                if isinstance(f.value, (list, tuple)) and len(f.value) == 2:
                    params.extend(f.value)
                else:
                    params.extend([None, None])
            elif f.operator == "is_null":
                conditions.append(f"{col} IS NULL")
            elif f.operator == "is_not_null":
                conditions.append(f"{col} IS NOT NULL")
            else:
                conditions.append(f"{col} = ?")
                params.append(f.value)

        return " WHERE " + " AND ".join(conditions), params

    def _build_order_clause(self, order_by: List[OrderBy]) -> str:
        """构建 ORDER BY 子句"""
        if not order_by:
            return ""

        parts = []
        for ob in order_by:
            _safe_identifier(ob.field, "column name")
            direction = "ASC" if ob.ascending else "DESC"
            parts.append(f'"{ob.field}" {direction}')

        return " ORDER BY " + ", ".join(parts)

    def _execute_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        limit: Optional[int],
        offset: Optional[int],
    ) -> List[T]:
        where_sql, params = self._build_where_clause(filters)
        order_sql = self._build_order_clause(order_by)

        sql = f'SELECT * FROM "{self._table_name}"{where_sql}{order_sql}'

        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset is not None:
            sql += f" OFFSET {int(offset)}"

        with self._backend.get_connection(write=False) as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = cursor.fetchall()
            return [self._row_to_model(row) for row in rows]

    def _execute_paginated_query(
        self,
        filters: List[QueryFilter],
        order_by: List[OrderBy],
        page: int,
        page_size: int,
    ) -> PaginationResult[T]:
        total = self._count_query(filters)
        items = self._execute_query(
            filters=filters,
            order_by=order_by,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return PaginationResult(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def _count_query(self, filters: List[QueryFilter]) -> int:
        where_sql, params = self._build_where_clause(filters)
        sql = f'SELECT COUNT(*) as cnt FROM "{self._table_name}"{where_sql}'

        with self._backend.get_connection(write=False) as conn:
            cursor = conn.execute(sql, tuple(params))
            row = cursor.fetchone()
            return int(row["cnt"]) if row else 0


# ============================================================
# SQLite 工作单元
# ============================================================

class SQLiteUnitOfWork(UnitOfWork):
    """SQLite 工作单元（基于数据库事务）"""

    def __init__(self, backend: "SQLiteBackend"):
        super().__init__(backend=backend)
        self._conn: Optional[sqlite3.Connection] = None

    def begin(self) -> None:
        if self._active:
            return
        self._conn = self._backend._get_raw_connection()
        self._conn.execute("BEGIN")
        self._active = True

    def commit(self) -> None:
        if not self._active or not self._conn:
            return
        self._conn.execute("COMMIT")
        self._active = False
        self._conn = None

    def rollback(self) -> None:
        if not self._active or not self._conn:
            return
        self._conn.execute("ROLLBACK")
        self._active = False
        self._conn = None


# ============================================================
# SQLite 后端
# ============================================================

class SQLiteBackend(BackendFactory):
    """
    SQLite 存储后端。

    提供基于 SQLite 的仓库和工作单元实现，
    支持连接池和 WAL 模式优化。
    """

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._init_connection()

    def _init_connection(self) -> None:
        """初始化数据库连接"""
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # 自动提交模式，手动管理事务
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 30000")

    def _get_raw_connection(self) -> sqlite3.Connection:
        """获取原始连接"""
        assert self._conn is not None
        return self._conn

    @contextmanager
    def get_connection(self, write: bool = False):
        """获取连接（上下文管理器）"""
        # SQLite 单连接，写操作加锁
        if write:
            with self._lock:
                yield self._conn
        else:
            yield self._conn

    def create_repository(self, model_class: Type[BaseModel]) -> SQLiteRepository:
        """创建仓库实例"""
        return SQLiteRepository(self, model_class)

    def create_unit_of_work(self) -> SQLiteUnitOfWork:
        """创建工作单元"""
        return SQLiteUnitOfWork(self)

    def get_backend_type(self) -> str:
        return "sqlite"

    def close(self) -> None:
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
