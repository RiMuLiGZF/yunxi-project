from __future__ import annotations

"""Skill Repository 基类 - 为技能级数据库操作提供统一封装.

12 个技能（todo, journal, flashcard, contact 等）各自使用独立的 SQLite 数据库，
本模块提供 SkillBaseRepository 作为这些技能 Repository 的基类，
封装通用的增删改查、分页查询、动态条件构建等模式。

迁移指南：
1. 为每个技能创建 XxxRepository(SkillBaseRepository)
2. 实现 _create_tables() 和 _create_indexes()
3. 在技能类中实例化 Repository，替换 sqlite3.connect() 调用
4. 原有 API 保持不变，内部委托给 Repository
"""

import os
from typing import Any, Sequence

import structlog

from skill_cluster.db.base import BaseRepository, SQLiteDatabase

logger = structlog.get_logger()


class SkillBaseRepository(BaseRepository):
    """技能级 Repository 基类.

    在 BaseRepository 基础上增加：
    - 便捷的分页查询方法
    - 动态条件构建辅助
    - 动态更新字段辅助
    - 常见的列表/详情/统计模式

    Args:
        db_path: 数据库文件路径
        table_name: 主表名（子类必须设置）
        primary_key: 主键列名
    """

    def __init__(
        self,
        db_path: str,
        table_name: str = "",
        primary_key: str = "",
    ) -> None:
        # 支持子类设置类属性，也支持构造参数传入
        # 只有传入非空值时才覆盖子类的类属性
        if table_name:
            self.table_name = table_name
        if primary_key:
            self.primary_key = primary_key

        if not self.table_name:
            raise ValueError("table_name must be set by subclass or constructor")

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = SQLiteDatabase(db_path)
        super().__init__(db)

    # ------------------------------------------------------------------
    # 分页查询辅助
    # ------------------------------------------------------------------

    def paginated_query(
        self,
        conditions: dict[str, Any] | None = None,
        order_by: str = "created_at DESC",
        page: int = 1,
        page_size: int = 20,
        select_columns: str = "*",
    ) -> tuple[list[Any], int]:
        """通用分页查询.

        构建 WHERE 条件（使用 AND 连接所有条件，= 比较），返回分页结果和总数。

        Args:
            conditions: {列名: 值} 字典，所有条件使用 = 比较并 AND 连接
            order_by: 排序子句
            page: 页码（从 1 开始）
            page_size: 每页数量
            select_columns: SELECT 后面的列名（默认 *）

        Returns:
            (rows, total) 元组
        """
        conditions = conditions or {}
        where_clauses: list[str] = []
        params: list[Any] = []

        for col, val in conditions.items():
            where_clauses.append(f"{col} = ?")
            params.append(val)

        where = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        offset = (page - 1) * page_size

        # 总数
        total_row = self._db.fetchone(
            f"SELECT COUNT(*) FROM {self.table_name}{where}",
            params,
        )
        total = total_row[0] if total_row else 0

        # 分页数据
        rows = self._db.fetchall(
            f"""
            SELECT {select_columns} FROM {self.table_name}{where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        )

        return rows, total

    # ------------------------------------------------------------------
    # 动态更新辅助
    # ------------------------------------------------------------------

    def update_fields(
        self,
        record_id: str,
        field_map: dict[str, Any],
    ) -> int:
        """动态更新指定字段.

        Args:
            record_id: 主键值
            field_map: {列名: 新值} 字典，只更新传入的字段

        Returns:
            受影响行数

        Raises:
            ValueError: field_map 为空
        """
        if not field_map:
            raise ValueError("No fields to update")

        set_clauses = [f"{col} = ?" for col in field_map.keys()]
        params = list(field_map.values())
        params.append(record_id)

        cursor = self._db.execute(
            f"UPDATE {self.table_name} SET {', '.join(set_clauses)} "
            f"WHERE {self.primary_key} = ?",
            params,
        )
        return cursor.rowcount

    # ------------------------------------------------------------------
    # LIKE 查询辅助
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
        """多列模糊搜索（OR 连接）.

        Args:
            keyword: 搜索关键词
            search_columns: 要搜索的列名列表
            conditions: 额外的等值条件（AND 连接）
            order_by: 排序
            limit: 最大返回数
            select_columns: SELECT 列

        Returns:
            匹配的行列表
        """
        if not search_columns:
            return []

        like_pattern = f"%{keyword}%"
        like_clauses = [f"{col} LIKE ?" for col in search_columns]
        like_params = [like_pattern] * len(search_columns)

        conditions = conditions or {}
        where_clauses: list[str] = []
        where_params: list[Any] = []

        for col, val in conditions.items():
            where_clauses.append(f"{col} = ?")
            where_params.append(val)

        # 组合：WHERE (col1 LIKE ? OR col2 LIKE ?) [AND other_conds]
        like_part = f"({' OR '.join(like_clauses)})"
        if where_clauses:
            where = f" WHERE {like_part} AND {' AND '.join(where_clauses)}"
            all_params = like_params + where_params
        else:
            where = f" WHERE {like_part}"
            all_params = like_params

        rows = self._db.fetchall(
            f"""
            SELECT {select_columns} FROM {self.table_name}{where}
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
