from __future__ import annotations

"""联系人管理技能."""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class ContactSkill(ISkill):
    """联系人管理技能，支持联系人增删查改、分组管理、重要日期提醒."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.contact",
            name="联系人",
            version="1.0.0",
            description="管理联系人信息，支持分组、搜索、重要日期提醒",
            author="yunxi",
            tags=["contact", "relationship", "social"],
            capabilities=["list", "create", "update", "delete", "search", "groups", "important_dates"],
            permissions=["read_file", "write"],
            entrypoint="ContactSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/contact.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    contact_id TEXT PRIMARY KEY,
                    name TEXT,
                    nickname TEXT,
                    relationship TEXT,
                    phone TEXT,
                    email TEXT,
                    birthday TEXT,
                    group_name TEXT,
                    notes TEXT,
                    last_contact TEXT,
                    contact_frequency TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用分发入口."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "list":
                data = self._list(params)
            elif action == "create":
                data = self._create(params)
            elif action == "update":
                data = self._update(params)
            elif action == "delete":
                data = self._delete(params)
            elif action == "search":
                data = self._search(params)
            elif action == "groups":
                data = self._groups(params)
            elif action == "important_dates":
                data = self._important_dates(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    # ------------------------------ 动作：联系人列表 ------------------------------

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取联系人列表，支持按分组和关系筛选.

        Args:
            params:
                - group_name: 分组筛选（可选）
                - relationship: 关系筛选（可选）
                - limit: 返回数量限制（可选，默认 50）
                - offset: 偏移量（可选，默认 0）
                - sort_by: 排序字段（可选，默认 name）
                - sort_order: 排序方向 asc/desc（可选，默认 asc）

        Returns:
            联系人列表及总数
        """
        group_name = params.get("group_name")
        relationship = params.get("relationship")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        sort_by = params.get("sort_by", "name")
        sort_order = params.get("sort_order", "asc")

        # 允许的排序字段白名单
        allowed_sort = {"name", "created_at", "birthday", "last_contact", "group_name"}
        if sort_by not in allowed_sort:
            sort_by = "name"
        if sort_order not in ("asc", "desc"):
            sort_order = "asc"

        query = """
            SELECT contact_id, name, nickname, relationship, phone, email,
                   birthday, group_name, notes, last_contact, contact_frequency, created_at
            FROM contacts
            WHERE 1=1
        """
        count_query = "SELECT COUNT(*) FROM contacts WHERE 1=1"
        args: list[Any] = []
        count_args: list[Any] = []

        if group_name:
            query += " AND group_name = ?"
            count_query += " AND group_name = ?"
            args.append(group_name)
            count_args.append(group_name)

        if relationship:
            query += " AND relationship = ?"
            count_query += " AND relationship = ?"
            args.append(relationship)
            count_args.append(relationship)

        query += f" ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()
            total = conn.execute(count_query, count_args).fetchone()[0]

        contacts = [
            {
                "contact_id": r[0],
                "name": r[1],
                "nickname": r[2] or "",
                "relationship": r[3] or "",
                "phone": r[4] or "",
                "email": r[5] or "",
                "birthday": r[6] or "",
                "group_name": r[7] or "",
                "notes": r[8] or "",
                "last_contact": r[9] or "",
                "contact_frequency": r[10] or "",
                "created_at": r[11],
            }
            for r in rows
        ]

        return {"contacts": contacts, "total": total, "limit": limit, "offset": offset}

    # ------------------------------ 动作：创建联系人 ------------------------------

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建新联系人.

        Args:
            params:
                - name: 姓名
                - nickname: 昵称（可选）
                - relationship: 关系（可选）
                - phone: 电话（可选）
                - email: 邮箱（可选）
                - birthday: 生日 ISO 格式（可选）
                - group_name: 分组（可选）
                - notes: 备注（可选）
                - last_contact: 上次联系时间（可选）
                - contact_frequency: 联系频率（可选，如 weekly/monthly）

        Returns:
            创建结果及联系人信息
        """
        contact_id = str(uuid.uuid4())
        name = params.get("name", "")
        nickname = params.get("nickname", "")
        relationship = params.get("relationship", "")
        phone = params.get("phone", "")
        email = params.get("email", "")
        birthday = params.get("birthday", "")
        group_name = params.get("group_name", "")
        notes = params.get("notes", "")
        last_contact = params.get("last_contact", "")
        contact_frequency = params.get("contact_frequency", "")
        now = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO contacts (contact_id, name, nickname, relationship, phone,
                                      email, birthday, group_name, notes, last_contact,
                                      contact_frequency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (contact_id, name, nickname, relationship, phone, email,
                 birthday, group_name, notes, last_contact, contact_frequency, now),
            )
            conn.commit()

        return {"contact_id": contact_id, "created": True, "name": name}

    # ------------------------------ 动作：更新联系人 ------------------------------

    def _update(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新联系人信息.

        Args:
            params:
                - contact_id: 联系人 ID
                - name: 姓名（可选）
                - nickname: 昵称（可选）
                - relationship: 关系（可选）
                - phone: 电话（可选）
                - email: 邮箱（可选）
                - birthday: 生日（可选）
                - group_name: 分组（可选）
                - notes: 备注（可选）
                - last_contact: 上次联系时间（可选）
                - contact_frequency: 联系频率（可选）

        Returns:
            更新结果
        """
        contact_id = params.get("contact_id", "")
        if not contact_id:
            raise ValueError("contact_id is required")

        # 可更新字段
        field_map = {
            "name": "name",
            "nickname": "nickname",
            "relationship": "relationship",
            "phone": "phone",
            "email": "email",
            "birthday": "birthday",
            "group_name": "group_name",
            "notes": "notes",
            "last_contact": "last_contact",
            "contact_frequency": "contact_frequency",
        }

        updates: list[str] = []
        args: list[Any] = []

        for param_key, col_name in field_map.items():
            if param_key in params:
                updates.append(f"{col_name} = ?")
                args.append(params[param_key])

        if not updates:
            return {"updated": False, "contact_id": contact_id, "message": "no fields to update"}

        args.append(contact_id)
        query = f"UPDATE contacts SET {', '.join(updates)} WHERE contact_id = ?"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(query, args)
            conn.commit()

        return {"updated": True, "contact_id": contact_id}

    # ------------------------------ 动作：删除联系人 ------------------------------

    def _delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除联系人.

        Args:
            params:
                - contact_id: 联系人 ID

        Returns:
            删除结果
        """
        contact_id = params.get("contact_id", "")
        if not contact_id:
            raise ValueError("contact_id is required")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM contacts WHERE contact_id = ?", (contact_id,))
            conn.commit()

        return {"deleted": True, "contact_id": contact_id}

    # ------------------------------ 动作：搜索联系人 ------------------------------

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        """搜索联系人（姓名/昵称/备注模糊匹配）.

        Args:
            params:
                - keyword: 搜索关键词
                - limit: 返回数量限制（可选，默认 50）

        Returns:
            匹配的联系人列表
        """
        keyword = params.get("keyword", "")
        limit = int(params.get("limit", 50))

        if not keyword:
            return {"contacts": [], "total": 0}

        like_keyword = f"%{keyword}%"
        query = """
            SELECT contact_id, name, nickname, relationship, phone, email,
                   birthday, group_name, notes, last_contact, contact_frequency, created_at
            FROM contacts
            WHERE name LIKE ? OR nickname LIKE ? OR notes LIKE ? OR phone LIKE ?
            ORDER BY name ASC
            LIMIT ?
        """
        args: list[Any] = [like_keyword, like_keyword, like_keyword, like_keyword, limit]

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()

        contacts = [
            {
                "contact_id": r[0],
                "name": r[1],
                "nickname": r[2] or "",
                "relationship": r[3] or "",
                "phone": r[4] or "",
                "email": r[5] or "",
                "birthday": r[6] or "",
                "group_name": r[7] or "",
                "notes": r[8] or "",
                "last_contact": r[9] or "",
                "contact_frequency": r[10] or "",
                "created_at": r[11],
            }
            for r in rows
        ]

        return {"contacts": contacts, "total": len(contacts), "keyword": keyword}

    # ------------------------------ 动作：分组列表 ------------------------------

    def _groups(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取分组列表及各分组人数.

        Args:
            params: 无

        Returns:
            分组统计信息
        """
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT group_name, COUNT(*) as cnt
                FROM contacts
                WHERE group_name IS NOT NULL AND group_name != ''
                GROUP BY group_name
                ORDER BY cnt DESC
                """
            ).fetchall()

            # 未分组的人数
            no_group_row = conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE group_name IS NULL OR group_name = ''"
            ).fetchone()

        groups = [
            {"group_name": r[0], "count": r[1]}
            for r in rows
        ]

        total = sum(g["count"] for g in groups) + (no_group_row[0] if no_group_row else 0)

        return {
            "groups": groups,
            "ungrouped_count": no_group_row[0] if no_group_row else 0,
            "total_contacts": total,
            "group_count": len(groups),
        }

    # ------------------------------ 动作：重要日期提醒 ------------------------------

    def _important_dates(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取近期重要日期（生日、纪念日等）.

        计算未来 N 天内的生日提醒。生日按 MM-DD 比较，不考虑年份。

        Args:
            params:
                - days: 未来天数（可选，默认 30 天）

        Returns:
            近期重要日期列表
        """
        days = int(params.get("days", 30))
        now = datetime.now()

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT contact_id, name, nickname, birthday, relationship, group_name
                FROM contacts
                WHERE birthday IS NOT NULL AND birthday != ''
                """
            ).fetchall()

        upcoming: list[dict[str, Any]] = []

        for r in rows:
            birthday_str = r[3]
            if not birthday_str:
                continue

            try:
                # 尝试解析生日（支持 YYYY-MM-DD 格式）
                bday = datetime.fromisoformat(birthday_str)
                # 构造今年的生日
                this_year_bday = bday.replace(year=now.year)

                # 如果今年生日已过，计算明年的
                if this_year_bday < now:
                    next_bday = bday.replace(year=now.year + 1)
                else:
                    next_bday = this_year_bday

                days_until = (next_bday - now).days

                if 0 <= days_until <= days:
                    # 计算年龄（今年生日时的年龄）
                    age = next_bday.year - bday.year

                    upcoming.append({
                        "contact_id": r[0],
                        "name": r[1],
                        "nickname": r[2] or "",
                        "type": "birthday",
                        "date": next_bday.strftime("%Y-%m-%d"),
                        "days_until": days_until,
                        "age": age,
                        "relationship": r[4] or "",
                        "group_name": r[5] or "",
                    })
            except (ValueError, TypeError):
                continue

        # 按距离天数排序
        upcoming.sort(key=lambda x: x["days_until"])

        return {
            "upcoming": upcoming,
            "total": len(upcoming),
            "days_range": days,
            "today": now.strftime("%Y-%m-%d"),
        }

    # ------------------------------ 工具方法 ------------------------------

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("contact_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查."""
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        """配置技能."""
        self._config.update(config)
