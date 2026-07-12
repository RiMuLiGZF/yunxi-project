from __future__ import annotations

"""日记随笔技能."""

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


class JournalSkill(ISkill):
    """日记随笔技能，支持写日记、列表、搜索、周报、标签管理."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.journal",
            name="日记随笔",
            version="1.0.0",
            description="记录日记随笔，支持全文搜索、周报生成、标签管理",
            author="yunxi",
            tags=["journal", "diary", "writing"],
            capabilities=["write", "list", "read", "search", "weekly_summary", "tags"],
            permissions=["read_file", "write"],
            entrypoint="JournalSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/journal.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS journals (
                    journal_id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    mood TEXT,
                    tags TEXT,
                    created_date TEXT,
                    updated_at TEXT,
                    word_count INTEGER
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用入口，根据 action 分发到对应处理方法."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "write":
                data = self._write(params)
            elif action == "list":
                data = self._list(params)
            elif action == "read":
                data = self._read(params)
            elif action == "search":
                data = self._search(params)
            elif action == "weekly_summary":
                data = self._weekly_summary(params)
            elif action == "tags":
                data = self._tags(params)
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

    def _write(self, params: dict[str, Any]) -> dict[str, Any]:
        """写日记/随笔，支持新建和更新."""
        journal_id = params.get("journal_id", "")
        title = params.get("title", "")
        content = params.get("content", "")
        mood = params.get("mood", "")
        tags = params.get("tags", [])
        tags_str = ",".join(tags) if isinstance(tags, list) else tags
        now = datetime.now().isoformat()
        word_count = len(content)

        if not content:
            raise ValueError("日记内容不能为空")

        with sqlite3.connect(self._db_path) as conn:
            if journal_id:
                # 更新已有日记
                cursor = conn.execute(
                    """
                    UPDATE journals
                    SET title = ?, content = ?, mood = ?, tags = ?, updated_at = ?, word_count = ?
                    WHERE journal_id = ?
                    """,
                    (title, content, mood, tags_str, now, word_count, journal_id),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    raise ValueError(f"日记不存在: {journal_id}")
                is_new = False
            else:
                # 新建日记
                journal_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO journals (journal_id, title, content, mood, tags, created_date, updated_at, word_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (journal_id, title, content, mood, tags_str, now, now, word_count),
                )
                conn.commit()
                is_new = True

        return {
            "journal_id": journal_id,
            "created": is_new,
            "updated": not is_new,
            "word_count": word_count,
        }

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """日记列表，按日期范围/标签筛选."""
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        tag = params.get("tag", "")
        mood = params.get("mood", "")
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 20))
        offset = (page - 1) * page_size

        conditions: list[str] = []
        args: list[Any] = []

        if start_date:
            conditions.append("created_date >= ?")
            args.append(start_date)
        if end_date:
            conditions.append("created_date <= ?")
            args.append(end_date + "T23:59:59.999999")
        if tag:
            conditions.append("tags LIKE ?")
            args.append(f"%{tag}%")
        if mood:
            conditions.append("mood = ?")
            args.append(mood)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM journals{where_clause}", args
            ).fetchone()[0]

            rows = conn.execute(
                f"""
                SELECT journal_id, title, content, mood, tags, created_date, updated_at, word_count
                FROM journals{where_clause}
                ORDER BY created_date DESC
                LIMIT ? OFFSET ?
                """,
                args + [page_size, offset],
            ).fetchall()

        journals = [
            {
                "journal_id": r[0],
                "title": r[1],
                "content_preview": r[2][:100] if r[2] else "",
                "mood": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "created_date": r[5],
                "updated_at": r[6],
                "word_count": r[7],
            }
            for r in rows
        ]

        return {
            "journals": journals,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        }

    def _read(self, params: dict[str, Any]) -> dict[str, Any]:
        """读取单篇日记详情."""
        journal_id = params.get("journal_id", "")
        if not journal_id:
            raise ValueError("journal_id 不能为空")

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT journal_id, title, content, mood, tags, created_date, updated_at, word_count
                FROM journals WHERE journal_id = ?
                """,
                (journal_id,),
            ).fetchone()

        if not row:
            raise ValueError(f"日记不存在: {journal_id}")

        return {
            "journal_id": row[0],
            "title": row[1],
            "content": row[2],
            "mood": row[3],
            "tags": row[4].split(",") if row[4] else [],
            "created_date": row[5],
            "updated_at": row[6],
            "word_count": row[7],
        }

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        """全文搜索（使用 SQLite LIKE）."""
        keyword = params.get("keyword", "")
        if not keyword:
            raise ValueError("搜索关键词不能为空")

        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 20))
        offset = (page - 1) * page_size
        like_pattern = f"%{keyword}%"

        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute(
                """
                SELECT COUNT(*) FROM journals
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                """,
                (like_pattern, like_pattern, like_pattern),
            ).fetchone()[0]

            rows = conn.execute(
                """
                SELECT journal_id, title, content, mood, tags, created_date, updated_at, word_count
                FROM journals
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                ORDER BY created_date DESC
                LIMIT ? OFFSET ?
                """,
                (like_pattern, like_pattern, like_pattern, page_size, offset),
            ).fetchall()

        results = [
            {
                "journal_id": r[0],
                "title": r[1],
                "content_preview": r[2][:150] if r[2] else "",
                "mood": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "created_date": r[5],
                "updated_at": r[6],
                "word_count": r[7],
            }
            for r in rows
        ]

        return {
            "results": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "keyword": keyword,
        }

    def _weekly_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        """生成周报结构：本周日记列表、字数统计、情绪分布."""
        # 计算本周起止日期（周一为一周开始）
        week_offset = int(params.get("week_offset", 0))
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday() + week_offset * 7)
        week_end = week_start + timedelta(days=7)

        week_start_str = week_start.isoformat()
        week_end_str = week_end.isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # 本周日记列表
            rows = conn.execute(
                """
                SELECT journal_id, title, content, mood, tags, created_date, updated_at, word_count
                FROM journals
                WHERE created_date >= ? AND created_date < ?
                ORDER BY created_date ASC
                """,
                (week_start_str, week_end_str),
            ).fetchall()

            # 总字数
            total_words = conn.execute(
                "SELECT COALESCE(SUM(word_count), 0) FROM journals WHERE created_date >= ? AND created_date < ?",
                (week_start_str, week_end_str),
            ).fetchone()[0]

            # 情绪分布
            mood_rows = conn.execute(
                "SELECT mood, COUNT(*) FROM journals WHERE created_date >= ? AND created_date < ? AND mood != '' GROUP BY mood",
                (week_start_str, week_end_str),
            ).fetchall()

            # 每日统计
            daily_rows = conn.execute(
                """
                SELECT SUBSTR(created_date, 1, 10) as day, COUNT(*), COALESCE(SUM(word_count), 0)
                FROM journals
                WHERE created_date >= ? AND created_date < ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (week_start_str, week_end_str),
            ).fetchall()

        journals = [
            {
                "journal_id": r[0],
                "title": r[1],
                "content_preview": r[2][:100] if r[2] else "",
                "mood": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "created_date": r[5],
                "word_count": r[7],
            }
            for r in rows
        ]

        mood_distribution = {r[0]: r[1] for r in mood_rows}
        daily_stats = [
            {"date": r[0], "count": r[1], "total_words": r[2]}
            for r in daily_rows
        ]

        return {
            "week_start": week_start_str,
            "week_end": week_end_str,
            "total_entries": len(rows),
            "total_words": total_words,
            "avg_words_per_entry": round(total_words / len(rows), 1) if rows else 0,
            "journals": journals,
            "mood_distribution": mood_distribution,
            "daily_stats": daily_stats,
        }

    def _tags(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取所有标签及使用次数."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT tags FROM journals WHERE tags != '' AND tags IS NOT NULL"
            ).fetchall()

        tag_counts: dict[str, int] = {}
        for row in rows:
            if row[0]:
                for tag in row[0].split(","):
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # 按使用次数排序
        sorted_tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        return {
            "tags": sorted_tags,
            "total_tags": len(sorted_tags),
        }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("journal_error", action=request.action, error=error, trace_id=request.trace_id)
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
        """配置更新."""
        self._config.update(config)
