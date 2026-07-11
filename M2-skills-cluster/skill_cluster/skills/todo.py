from __future__ import annotations

"""待办事项管理技能."""

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


class TodoSkill(ISkill):
    """待办事项管理技能，支持增删改查、完成标记和统计."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.todo",
            name="待办事项",
            version="1.0.0",
            description="管理本地待办事项，支持优先级、标签、统计",
            author="yunxi",
            tags=["todo", "task", "productivity"],
            capabilities=["list", "create", "update", "delete", "complete", "stats"],
            permissions=["read_file", "write"],
            entrypoint="TodoSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/todo.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    todo_id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    status TEXT,
                    priority INTEGER,
                    due_date TEXT,
                    tags TEXT,
                    created_at TEXT,
                    completed_at TEXT
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
            if action == "list":
                data = self._list(params)
            elif action == "create":
                data = self._create(params)
            elif action == "update":
                data = self._update(params)
            elif action == "delete":
                data = self._delete(params)
            elif action == "complete":
                data = self._complete(params)
            elif action == "stats":
                data = self._stats(params)
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

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """待办列表，支持按状态/优先级/标签筛选和分页."""
        status = params.get("status")
        priority = params.get("priority")
        tag = params.get("tag")
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 20))
        offset = (page - 1) * page_size

        # 构建查询条件
        conditions: list[str] = []
        args: list[Any] = []

        if status:
            conditions.append("status = ?")
            args.append(status)
        if priority is not None:
            conditions.append("priority = ?")
            args.append(priority)
        if tag:
            conditions.append("tags LIKE ?")
            args.append(f"%{tag}%")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with sqlite3.connect(self._db_path) as conn:
            # 查询总数
            total = conn.execute(
                f"SELECT COUNT(*) FROM todos{where_clause}", args
            ).fetchone()[0]

            # 查询分页数据，按优先级降序、创建时间降序
            rows = conn.execute(
                f"""
                SELECT todo_id, title, description, status, priority, due_date, tags, created_at, completed_at
                FROM todos{where_clause}
                ORDER BY priority DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                args + [page_size, offset],
            ).fetchall()

        todos = [
            {
                "todo_id": r[0],
                "title": r[1],
                "description": r[2],
                "status": r[3],
                "priority": r[4],
                "due_date": r[5],
                "tags": r[6].split(",") if r[6] else [],
                "created_at": r[7],
                "completed_at": r[8],
            }
            for r in rows
        ]
        return {
            "todos": todos,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        }

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建待办事项."""
        todo_id = str(uuid.uuid4())
        title = params.get("title", "")
        description = params.get("description", "")
        status = params.get("status", "pending")
        priority = int(params.get("priority", 0))
        due_date = params.get("due_date", "")
        tags = params.get("tags", [])
        tags_str = ",".join(tags) if isinstance(tags, list) else tags
        created_at = datetime.now().isoformat()

        if not title:
            raise ValueError("待办标题不能为空")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO todos (todo_id, title, description, status, priority, due_date, tags, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (todo_id, title, description, status, priority, due_date, tags_str, created_at, ""),
            )
            conn.commit()

        return {"todo_id": todo_id, "created": True, "title": title}

    def _update(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新待办事项."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        # 构建更新字段
        updates: list[str] = []
        args: list[Any] = []

        if "title" in params:
            updates.append("title = ?")
            args.append(params["title"])
        if "description" in params:
            updates.append("description = ?")
            args.append(params["description"])
        if "status" in params:
            updates.append("status = ?")
            args.append(params["status"])
        if "priority" in params:
            updates.append("priority = ?")
            args.append(int(params["priority"]))
        if "due_date" in params:
            updates.append("due_date = ?")
            args.append(params["due_date"])
        if "tags" in params:
            tags = params["tags"]
            tags_str = ",".join(tags) if isinstance(tags, list) else tags
            updates.append("tags = ?")
            args.append(tags_str)

        if not updates:
            raise ValueError("没有需要更新的字段")

        args.append(todo_id)

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE todos SET {', '.join(updates)} WHERE todo_id = ?", args
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"待办事项不存在: {todo_id}")

        return {"todo_id": todo_id, "updated": True}

    def _delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除待办事项."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM todos WHERE todo_id = ?", (todo_id,))
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"待办事项不存在: {todo_id}")

        return {"deleted": True, "todo_id": todo_id}

    def _complete(self, params: dict[str, Any]) -> dict[str, Any]:
        """标记待办事项为已完成."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        completed_at = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "UPDATE todos SET status = ?, completed_at = ? WHERE todo_id = ?",
                ("completed", completed_at, todo_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"待办事项不存在: {todo_id}")

        return {"todo_id": todo_id, "completed": True, "completed_at": completed_at}

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """统计信息：今日完成、本周完成、待处理、逾期."""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # 本周开始（周一）
        week_start = today_start - timedelta(days=today_start.weekday())
        week_end = week_start + timedelta(days=7)

        today_str = today_start.isoformat()
        today_end_str = today_end.isoformat()
        week_start_str = week_start.isoformat()
        week_end_str = week_end.isoformat()
        now_str = now.isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # 今日完成
            today_completed = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?",
                (today_str, today_end_str),
            ).fetchone()[0]

            # 本周完成
            week_completed = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?",
                (week_start_str, week_end_str),
            ).fetchone()[0]

            # 待处理总数
            pending = conn.execute(
                "SELECT COUNT(*) FROM todos WHERE status != 'completed'"
            ).fetchone()[0]

            # 逾期（有截止日期且已过截止日期且未完成）
            overdue = conn.execute(
                """
                SELECT COUNT(*) FROM todos
                WHERE status != 'completed'
                  AND due_date != ''
                  AND due_date < ?
                """,
                (now_str,),
            ).fetchone()[0]

            # 各状态数量
            status_rows = conn.execute(
                "SELECT status, COUNT(*) FROM todos GROUP BY status"
            ).fetchall()

            # 各优先级数量
            priority_rows = conn.execute(
                "SELECT priority, COUNT(*) FROM todos WHERE status != 'completed' GROUP BY priority ORDER BY priority DESC"
            ).fetchall()

        status_distribution = {r[0]: r[1] for r in status_rows}
        priority_distribution = {r[0]: r[1] for r in priority_rows}

        return {
            "today_completed": today_completed,
            "week_completed": week_completed,
            "pending": pending,
            "overdue": overdue,
            "status_distribution": status_distribution,
            "priority_distribution": priority_distribution,
            "today": today_str,
            "week_start": week_start_str,
        }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("todo_error", action=request.action, error=error, trace_id=request.trace_id)
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
