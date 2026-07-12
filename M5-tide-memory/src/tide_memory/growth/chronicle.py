"""
地球Online编年史模块

记录人生中的重大事件、成就、关键决策等，如同游戏中的任务日志。
支持分类、难度、标签等多维度管理，可与 Git 提交关联。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase, json_to_list, list_to_json

# 分类映射
CATEGORY_MAP: Dict[str, str] = {
    "main-quest": "主线任务",
    "side-quest": "支线任务",
    "achievement": "成就达成",
    "critical-decision": "关键决策",
}

# 难度列表
VALID_DIFFICULTIES = ["入门", "普通", "困难", "史诗"]


def _gen_id() -> str:
    """生成纪事ID"""
    return f"chr_{uuid.uuid4().hex[:16]}"


def _row_to_chronicle(row: Dict[str, Any]) -> Dict[str, Any]:
    """将数据库行转为纪事字典"""
    return {
        "id": row["id"],
        "date": row["date"],
        "title": row["title"],
        "category": row["category"],
        "category_text": row["category_text"],
        "difficulty": row["difficulty"],
        "content": row["content"],
        "tags": json_to_list(row["tags"]),
        "has_git": bool(row["has_git"]),
        "git_commits": json_to_list(row["git_commits"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _resolve_category_text(category: str, category_text: Optional[str] = None) -> str:
    """根据分类代码解析中文名称"""
    if category_text:
        return category_text
    return CATEGORY_MAP.get(category, "其他")


class ChronicleManager:
    """
    编年史管理器

    负责纪事的增删改查、分页查询、分类筛选等功能。
    """

    def __init__(self, db: GrowthDatabase = None):
        """
        初始化编年史管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
        """
        self._db = db or GrowthDatabase.get_instance()

    # ============================================================
    # 查询操作
    # ============================================================

    def list_chronicles(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        year: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分页查询纪事列表。

        Args:
            page: 页码，从1开始
            size: 每页数量
            category: 分类筛选
            year: 年份筛选（格式：YYYY）

        Returns:
            包含 items、total、page、size、total_pages 的分页结果
        """
        conditions = []
        params: List[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if year:
            conditions.append("date LIKE ?")
            params.append(f"{year}.%")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # 查询总数
        count_sql = f"SELECT COUNT(*) as cnt FROM growth_chronicle {where_clause}"
        count_row = self._db.query_one(count_sql, tuple(params))
        total = count_row["cnt"] if count_row else 0

        # 查询分页数据
        offset = (page - 1) * size
        query_sql = f"""
            SELECT * FROM growth_chronicle
            {where_clause}
            ORDER BY date DESC, created_at DESC
            LIMIT {size} OFFSET {offset}
        """
        rows = self._db.query_all(query_sql, tuple(params))

        items = [_row_to_chronicle(row) for row in rows]
        total_pages = (total + size - 1) // size if size > 0 else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": total_pages,
        }

    def get_chronicle(self, chronicle_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单条纪事详情。

        Args:
            chronicle_id: 纪事ID

        Returns:
            纪事数据字典，不存在返回 None
        """
        row = self._db.query_one(
            "SELECT * FROM growth_chronicle WHERE id = ?",
            (chronicle_id,),
        )
        if not row:
            return None
        return _row_to_chronicle(row)

    # ============================================================
    # 写入操作
    # ============================================================

    def create_chronicle(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        创建新纪事。

        Args:
            data: 纪事数据

        Returns:
            创建后的纪事数据
        """
        now = datetime.now().isoformat()
        chronicle_id = _gen_id()

        category = data.get("category", "main-quest")
        category_text = _resolve_category_text(category, data.get("category_text"))
        difficulty = data.get("difficulty", "普通")
        if difficulty not in VALID_DIFFICULTIES:
            difficulty = "普通"

        tags = data.get("tags", [])
        git_commits = data.get("git_commits", [])
        has_git = data.get("has_git", len(git_commits) > 0)

        self._db.execute(
            """
            INSERT INTO growth_chronicle
            (id, date, title, category, category_text, difficulty, content,
             tags, has_git, git_commits, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chronicle_id,
                data.get("date", datetime.now().strftime("%Y.%m.%d")),
                data.get("title", ""),
                category,
                category_text,
                difficulty,
                data.get("content", ""),
                list_to_json(tags),
                1 if has_git else 0,
                list_to_json(git_commits),
                now,
                now,
            ),
        )

        return self.get_chronicle(chronicle_id) or {}

    def update_chronicle(self, chronicle_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        更新纪事。

        Args:
            chronicle_id: 纪事ID
            data: 要更新的字段数据

        Returns:
            更新后的纪事数据，不存在返回 None
        """
        existing = self.get_chronicle(chronicle_id)
        if not existing:
            return None

        now = datetime.now().isoformat()

        # 收集要更新的字段
        update_fields: Dict[str, Any] = {}

        for key in ["date", "title", "difficulty", "content"]:
            if key in data and data[key] is not None:
                update_fields[key] = data[key]

        if "category" in data and data["category"] is not None:
            update_fields["category"] = data["category"]
            update_fields["category_text"] = _resolve_category_text(
                data["category"], data.get("category_text")
            )
        elif "category_text" in data and data["category_text"] is not None:
            update_fields["category_text"] = data["category_text"]

        if "tags" in data and data["tags"] is not None:
            update_fields["tags"] = list_to_json(data["tags"])

        if "has_git" in data and data["has_git"] is not None:
            update_fields["has_git"] = 1 if data["has_git"] else 0

        if "git_commits" in data and data["git_commits"] is not None:
            update_fields["git_commits"] = list_to_json(data["git_commits"])
            if "has_git" not in update_fields:
                update_fields["has_git"] = 1 if len(data["git_commits"]) > 0 else 0

        if not update_fields:
            return existing

        update_fields["updated_at"] = now

        # 构建 SQL
        set_clause = ", ".join(f"{k} = ?" for k in update_fields.keys())
        values = list(update_fields.values())
        values.append(chronicle_id)

        self._db.execute(
            f"UPDATE growth_chronicle SET {set_clause} WHERE id = ?",
            tuple(values),
        )

        return self.get_chronicle(chronicle_id)

    def delete_chronicle(self, chronicle_id: str) -> bool:
        """
        删除纪事。

        Args:
            chronicle_id: 纪事ID

        Returns:
            是否删除成功
        """
        existing = self.get_chronicle(chronicle_id)
        if not existing:
            return False

        self._db.execute(
            "DELETE FROM growth_chronicle WHERE id = ?",
            (chronicle_id,),
        )
        return True


# vim: set et ts=4 sw=4:
