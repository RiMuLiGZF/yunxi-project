from __future__ import annotations

"""Skill Repository 基类 - 为技能级数据库操作提供统一封装（SEC-005 修复：防 SQL 注入）.

12 个技能（todo, journal, flashcard, contact 等）各自使用独立的 SQLite 数据库，
本模块提供 SkillBaseRepository 作为这些技能 Repository 的基类，
封装通用的增删改查、分页查询、动态条件构建等模式。

安全修复（SEC-005）：
- 对 order_by 列名进行白名单校验
- 对所有动态列名进行安全校验（只允许字母数字下划线）
- 对 select_columns 进行安全校验
- 所有动态 SQL 部分禁止字符串拼接用户输入
- 参考 shared.data.data_layer.database_manager._validate_identifier 模式

迁移指南：
1. 为每个技能创建 XxxRepository(SkillBaseRepository)
2. 实现 _create_tables() 和 _create_indexes()
3. 在技能类中实例化 Repository，替换 sqlite3.connect() 调用
4. 原有 API 保持不变，内部委托给 Repository
"""

import os
import re
from typing import Any, Sequence

import structlog

from skill_cluster.db.base import BaseRepository, SQLiteDatabase

logger = structlog.get_logger()


# ===========================================================================
# SQL 标识符安全校验（SEC-005 防 SQL 注入）
# ===========================================================================

# 安全的列名/表名正则（只允许字母、数字、下划线，且必须以字母或下划线开头）
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# 安全的 order_by 子句正则：允许 "column" 或 "column ASC" 或 "column DESC"
# 多列排序用逗号分隔，每列都必须符合安全格式
_SAFE_ORDER_BY_RE = re.compile(
    r'^[a-zA-Z_][a-zA-Z0-9_]*(\s+(ASC|DESC))?'
    r'(\s*,\s*[a-zA-Z_][a-zA-Z0-9_]*(\s+(ASC|DESC))?)*$',
    re.IGNORECASE,
)


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """校验 SQL 标识符（表名、列名）是否安全.

    SQLite 参数化查询不能绑定表名和列名，
    因此需要白名单校验确保安全。

    参考 shared.data.data_layer.database_manager._validate_identifier 模式。

    Args:
        name: 标识符名称
        kind: 标识符类型（用于错误消息）

    Returns:
        原始名称（如果安全）

    Raises:
        ValueError: 标识符包含不安全字符
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid {kind}: empty or non-string value")
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {kind}: {repr(name)} - only alphanumeric and underscore allowed, "
            f"must start with letter or underscore"
        )
    return name


def validate_order_by(order_by: str, allowed_columns: set[str] | None = None) -> str:
    """校验 ORDER BY 子句是否安全.

    校验规则：
    1. 只允许字母、数字、下划线、逗号、空格、ASC、DESC
    2. 每列必须符合安全标识符规则
    3. 如果提供了 allowed_columns 白名单，列名必须在白名单中

    Args:
        order_by: ORDER BY 子句（不含 ORDER BY 关键字）
        allowed_columns: 允许的列名白名单集合，None 表示只做格式校验

    Returns:
        原始 order_by 字符串（如果安全）

    Raises:
        ValueError: order_by 包含不安全内容
    """
    if not order_by or not isinstance(order_by, str):
        raise ValueError("Invalid order_by: empty or non-string value")

    # 格式校验
    if not _SAFE_ORDER_BY_RE.match(order_by.strip()):
        raise ValueError(
            f"Invalid order_by: {repr(order_by)} - "
            f"only column names with optional ASC/DESC, comma-separated"
        )

    # 如果有白名单，逐列检查
    if allowed_columns is not None:
        # 解析每一列
        parts = [p.strip() for p in order_by.split(",")]
        for part in parts:
            # 提取列名（去掉 ASC/DESC）
            col = part.split()[0].strip()
            if col.lower() not in {c.lower() for c in allowed_columns}:
                raise ValueError(
                    f"Invalid order_by column: {repr(col)} - "
                    f"not in allowed columns: {sorted(allowed_columns)}"
                )

    return order_by


def validate_select_columns(
    select_columns: str, allowed_columns: set[str] | None = None
) -> str:
    """校验 SELECT 列名是否安全.

    Args:
        select_columns: 列名字符串（逗号分隔，或 "*"）
        allowed_columns: 允许的列名白名单集合，None 表示只做格式校验

    Returns:
        原始 select_columns 字符串（如果安全）

    Raises:
        ValueError: 包含不安全内容
    """
    if not select_columns or not isinstance(select_columns, str):
        raise ValueError("Invalid select_columns: empty or non-string value")

    # 允许 "*"
    if select_columns.strip() == "*":
        return select_columns

    # 逐列校验
    columns = [c.strip() for c in select_columns.split(",")]
    for col in columns:
        validate_identifier(col, "select column")
        # 白名单校验
        if allowed_columns is not None:
            if col.lower() not in {c.lower() for c in allowed_columns}:
                raise ValueError(
                    f"Invalid select column: {repr(col)} - "
                    f"not in allowed columns: {sorted(allowed_columns)}"
                )

    return select_columns


def validate_conditions_keys(
    conditions: dict[str, Any], allowed_columns: set[str] | None = None
) -> dict[str, Any]:
    """校验 conditions 字典中的列名是否安全.

    Args:
        conditions: {列名: 值} 字典
        allowed_columns: 允许的列名白名单集合

    Returns:
        原始 conditions 字典（如果安全）

    Raises:
        ValueError: 包含不安全的列名
    """
    if not conditions:
        return conditions

    for col in conditions.keys():
        validate_identifier(col, "condition column")
        if allowed_columns is not None:
            if col.lower() not in {c.lower() for c in allowed_columns}:
                raise ValueError(
                    f"Invalid condition column: {repr(col)} - "
                    f"not in allowed columns: {sorted(allowed_columns)}"
                )

    return conditions


class SkillBaseRepository(BaseRepository):
    """技能级 Repository 基类.

    在 BaseRepository 基础上增加：
    - 便捷的分页查询方法（带 SQL 注入防护）
    - 动态条件构建辅助（带列名校验）
    - 动态更新字段辅助（带列名校验）
    - 常见的列表/详情/统计模式

    安全特性（SEC-005）：
    - 所有动态列名、表名均经过格式校验
    - order_by 支持白名单校验
    - 默认排序列通过子类的 allowed_sort_columns 属性配置

    Args:
        db_path: 数据库文件路径
        table_name: 主表名（子类必须设置）
        primary_key: 主键列名
        allowed_sort_columns: 允许排序的列名白名单
        allowed_columns: 允许查询/更新的列名白名单（None 表示不限制列，仅格式校验）
    """

    # 子类可覆盖：允许排序的列名白名单
    # 例如: {"id", "created_at", "updated_at", "title"}
    allowed_sort_columns: set[str] | None = None

    # 子类可覆盖：允许查询/更新的列名白名单
    # None 表示只做格式校验，不限制具体列名
    allowed_columns: set[str] | None = None

    def __init__(
        self,
        db_path: str,
        table_name: str = "",
        primary_key: str = "",
        allowed_sort_columns: set[str] | None = None,
        allowed_columns: set[str] | None = None,
    ) -> None:
        # 支持子类设置类属性，也支持构造参数传入
        # 只有传入非空值时才覆盖子类的类属性
        if table_name:
            self.table_name = table_name
        if primary_key:
            self.primary_key = primary_key
        if allowed_sort_columns is not None:
            self.allowed_sort_columns = allowed_sort_columns
        if allowed_columns is not None:
            self.allowed_columns = allowed_columns

        if not self.table_name:
            raise ValueError("table_name must be set by subclass or constructor")

        # 安全校验：表名
        validate_identifier(self.table_name, "table name")

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = SQLiteDatabase(db_path)
        super().__init__(db)

    # ------------------------------------------------------------------
    # 分页查询辅助（SEC-005 安全加固）
    # ------------------------------------------------------------------

    def paginated_query(
        self,
        conditions: dict[str, Any] | None = None,
        order_by: str = "created_at DESC",
        page: int = 1,
        page_size: int = 20,
        select_columns: str = "*",
    ) -> tuple[list[Any], int]:
        """通用分页查询（带 SQL 注入防护）.

        构建 WHERE 条件（使用 AND 连接所有条件，= 比较），返回分页结果和总数。

        安全特性（SEC-005）：
        - order_by 列名经过白名单/格式校验
        - conditions 中的列名经过格式校验
        - select_columns 经过安全校验
        - 所有值参数使用参数化查询

        Args:
            conditions: {列名: 值} 字典，所有条件使用 = 比较并 AND 连接
            order_by: 排序子句（经过安全校验）
            page: 页码（从 1 开始）
            page_size: 每页数量
            select_columns: SELECT 后面的列名（默认 *，经过安全校验）

        Returns:
            (rows, total) 元组

        Raises:
            ValueError: order_by 或列名不安全
        """
        conditions = conditions or {}

        # SEC-005: 安全校验
        validate_conditions_keys(conditions, self.allowed_columns)
        validate_order_by(order_by, self.allowed_sort_columns)
        validate_select_columns(select_columns, self.allowed_columns)

        where_clauses: list[str] = []
        params: list[Any] = []

        for col, val in conditions.items():
            where_clauses.append(f'"{col}" = ?')
            params.append(val)

        where = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        offset = max(0, (page - 1) * page_size)
        page_size = max(1, page_size)

        # 总数
        total_row = self._db.fetchone(
            f'SELECT COUNT(*) FROM "{self.table_name}"{where}',
            params,
        )
        total = total_row[0] if total_row else 0

        # 分页数据
        rows = self._db.fetchall(
            f"""
            SELECT {select_columns} FROM "{self.table_name}"{where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        )

        return rows, total

    # ------------------------------------------------------------------
    # 动态更新辅助（SEC-005 安全加固）
    # ------------------------------------------------------------------

    def update_fields(
        self,
        record_id: str,
        field_map: dict[str, Any],
    ) -> int:
        """动态更新指定字段（带 SQL 注入防护）.

        安全特性（SEC-005）：
        - field_map 中的列名经过格式/白名单校验
        - 所有值参数使用参数化查询

        Args:
            record_id: 主键值
            field_map: {列名: 新值} 字典，只更新传入的字段

        Returns:
            受影响行数

        Raises:
            ValueError: field_map 为空或列名不安全
        """
        if not field_map:
            raise ValueError("No fields to update")

        # SEC-005: 安全校验列名
        validate_conditions_keys(field_map, self.allowed_columns)

        set_clauses = [f'"{col}" = ?' for col in field_map.keys()]
        params = list(field_map.values())
        params.append(record_id)

        cursor = self._db.execute(
            f'UPDATE "{self.table_name}" SET {", ".join(set_clauses)} '
            f'WHERE "{self.primary_key}" = ?',
            params,
        )
        return cursor.rowcount

    # ------------------------------------------------------------------
    # LIKE 查询辅助（SEC-005 安全加固）
    # ------------------------------------------------------------------

    def like_search(
        self,
        keyword: str,
        search_columns: Sequence[str],
        conditions: dict[str, Any] | None = None,
        order_by: str = "created_at DESC",
        limit: int = 50,
        select_columns: str = "*",
    ) -> list[Any]:
        """多列模糊搜索（OR 连接，带 SQL 注入防护）.

        安全特性（SEC-005）：
        - search_columns 经过格式/白名单校验
        - order_by 经过白名单/格式校验
        - conditions 列名经过格式校验
        - 所有值参数使用参数化查询

        Args:
            keyword: 搜索关键词
            search_columns: 要搜索的列名列表（经过安全校验）
            conditions: 额外的等值条件（AND 连接）
            order_by: 排序（经过安全校验）
            limit: 最大返回数
            select_columns: SELECT 列（经过安全校验）

        Returns:
            匹配的行列表

        Raises:
            ValueError: 列名或排序不安全
        """
        if not search_columns:
            return []

        # SEC-005: 安全校验
        for col in search_columns:
            validate_identifier(col, "search column")
            if self.allowed_columns is not None:
                if col.lower() not in {c.lower() for c in self.allowed_columns}:
                    raise ValueError(
                        f"Invalid search column: {repr(col)} - "
                        f"not in allowed columns: {sorted(self.allowed_columns)}"
                    )

        conditions = conditions or {}
        validate_conditions_keys(conditions, self.allowed_columns)
        validate_order_by(order_by, self.allowed_sort_columns)
        validate_select_columns(select_columns, self.allowed_columns)

        like_pattern = f"%{keyword}%"
        like_clauses = [f'"{col}" LIKE ?' for col in search_columns]
        like_params = [like_pattern] * len(search_columns)

        where_clauses: list[str] = []
        where_params: list[Any] = []

        for col, val in conditions.items():
            where_clauses.append(f'"{col}" = ?')
            where_params.append(val)

        # 组合：WHERE (col1 LIKE ? OR col2 LIKE ?) [AND other_conds]
        like_part = f"({' OR '.join(like_clauses)})"
        if where_clauses:
            where = f" WHERE {like_part} AND {' AND '.join(where_clauses)}"
            all_params = like_params + where_params
        else:
            where = f" WHERE {like_part}"
            all_params = like_params

        limit = max(1, limit)

        rows = self._db.fetchall(
            f"""
            SELECT {select_columns} FROM "{self.table_name}"{where}
            ORDER BY {order_by}
            LIMIT ?
            """,
            all_params + [limit],
        )
        return rows

    # ------------------------------------------------------------------
    # 快捷属性
    # ------------------------------------------------------------------

    @property
    def db_path(self) -> str:
        """数据库文件路径."""
        return self._db.db_path

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭数据库连接."""
        self._db.close()

    def __enter__(self) -> "SkillBaseRepository":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# ----------------------------------------------------------------------
# 迁移辅助函数
# ----------------------------------------------------------------------


def create_skill_repo(
    skill_name: str,
    repo_class: type[SkillBaseRepository],
    default_db_name: str = "",
) -> SkillBaseRepository:
    """便捷创建技能 Repository 实例.

    Args:
        skill_name: 技能名称（用于日志）
        repo_class: Repository 类
        default_db_name: 默认数据库文件名（如 "todo.db"）

    Returns:
        Repository 实例
    """
    db_name = default_db_name or f"{skill_name}.db"
    db_path = os.path.expanduser(f"~/.yunxi/data/{db_name}")
    logger.debug("skill_repo_created", skill=skill_name, db_path=db_path)
    return repo_class(db_path=db_path)
