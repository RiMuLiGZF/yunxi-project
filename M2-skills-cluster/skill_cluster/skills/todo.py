from __future__ import annotations

"""待办事项管理技能.

【重构说明】
已迁移到 Repository 模式，数据库操作委托给 TodoRepository。
原有 API 完全保留，仅内部实现变化。
"""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog

from skill_cluster.db.base import SQLiteDatabase
from skill_cluster.db.skill_repository_base import SkillBaseRepository
from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


# ----------------------------------------------------------------------
# Repository 层
# ----------------------------------------------------------------------


class TodoRepository(SkillBaseRepository):
    """待办事项 Repository.

    封装 todos 表的所有数据库操作。

    Args:
        db_path: 数据库文件路径
    """

    table_name = "todos"
    primary_key = "todo_id"

    def _create_tables(self) -> None:
        """创建 todos 表."""
        self._db.execute(
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

    def _create_indexes(self) -> None:
        """创建索引."""
        self._ensure_index("status")
        self._ensure_index("priority")
        self._ensure_index("due_date")
        self._ensure_index("created_at")

    # ------------------------------------------------------------------
    # 增删改查
    # ------------------------------------------------------------------

    def create_todo(
        self,
        title: str,
        description: str,
        status: str,
        priority: int,
        due_date: str,
        tags_str: str,
        created_at: str,
    ) -> str:
        """创建待办事项.

        Args:
            title: 标题
            description: 描述
            status: 状态
            priority: 优先级
            due_date: 截止日期
            tags_str: 标签（逗号分隔）
            created_at: 创建时间

        Returns:
            新创建的 todo_id
        """
        todo_id = str(uuid.uuid4())
        self._db.execute(
            """
            INSERT INTO todos (todo_id, title, description, status, priority,
                               due_date, tags, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (todo_id, title, description, status, priority,
             due_date, tags_str, created_at, ""),
        )
        return todo_id

    def get_todo(self, todo_id: str) -> dict[str, Any] | None:
        """获取单个待办事项.

        Args:
            todo_id: 待办 ID

        Returns:
            待办字典或 None
        """
        row = self.get_by_id(todo_id)
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_todos(
        self,
        status: str | None = None,
        priority: int | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """查询待办列表（支持筛选和分页.

        Args:
            status: 按状态筛选
            priority: 按优先级筛选
            tag: 按标签筛选（LIKE）
            page: 页码
            page_size: 每页数量

        Returns:
            (todos_list, total) 元组
        """
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
        offset = (page - 1) * page_size

        # 总数
        total_row = self._db.fetchone(
            f"SELECT COUNT(*) FROM todos{where_clause}", args
        )
        total = total_row[0] if total_row else 0

        # 分页数据
        rows = self._db.fetchall(
            f"""
            SELECT todo_id, title, description, status, priority,
                   due_date, tags, created_at, completed_at
            FROM todos{where_clause}
            ORDER BY priority DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            args + [page_size, offset],
        )

        todos = [self._row_to_dict(r) for r in rows]
        return todos, total

    def update_todo(self, todo_id: str, updates: dict[str, Any]) -> bool:
        """更新待办事项（动态字段）.

        Args:
            todo_id: 待办 ID
            updates: {字段名: 新值} 字典

        Returns:
            True 表示更新成功

        Raises:
            ValueError: 待办不存在
        """
        rowcount = self.update_fields(todo_id, updates)
        if rowcount == 0:
            raise ValueError(f"待办事项不存在: {todo_id}")
        return True

    def delete_todo(self, todo_id: str) -> bool:
        """删除待办事项.

        Args:
            todo_id: 待办 ID

        Returns:
            True 表示删除成功

        Raises:
            ValueError: 待办不存在
        """
        rowcount = self.delete_by_id(todo_id)
        if rowcount == 0:
            raise ValueError(f"待办事项不存在: {todo_id}")
        return True

    def complete_todo(self, todo_id: str, completed_at: str) -> bool:
        """标记待办为已完成.

        Args:
            todo_id: 待办 ID
            completed_at: 完成时间

        Returns:
            True 表示成功

        Raises:
            ValueError: 待办不存在
        """
        cursor = self._db.execute(
            "UPDATE todos SET status = ?, completed_at = ? WHERE todo_id = ?",
            ("completed", completed_at, todo_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"待办事项不存在: {todo_id}")
        return True

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息.

        Returns:
            统计字典
        """
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

        # 今日完成
        today_completed_row = self._db.fetchone(
            """
            SELECT COUNT(*) FROM todos
            WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?
            """,
            (today_str, today_end_str),
        )
        today_completed = today_completed_row[0] if today_completed_row else 0

        # 本周完成
        week_completed_row = self._db.fetchone(
            """
            SELECT COUNT(*) FROM todos
            WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?
            """,
            (week_start_str, week_end_str),
        )
        week_completed = week_completed_row[0] if week_completed_row else 0

        # 待处理总数
        pending_row = self._db.fetchone(
            "SELECT COUNT(*) FROM todos WHERE status != 'completed'"
        )
        pending = pending_row[0] if pending_row else 0

        # 逾期
        overdue_row = self._db.fetchone(
            """
            SELECT COUNT(*) FROM todos
            WHERE status != 'completed'
              AND due_date != ''
              AND due_date < ?
            """,
            (now_str,),
        )
        overdue = overdue_row[0] if overdue_row else 0

        # 各状态数量
        status_rows = self._db.fetchall(
            "SELECT status, COUNT(*) as cnt FROM todos GROUP BY status"
        )
        status_distribution = {r["status"]: r["cnt"] for r in status_rows}

        # 各优先级数量
        priority_rows = self._db.fetchall(
            """
            SELECT priority, COUNT(*) as cnt FROM todos
            WHERE status != 'completed'
            GROUP BY priority
            ORDER BY priority DESC
            """
        )
        priority_distribution = {r["priority"]: r["cnt"] for r in priority_rows}

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

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """将行转为字典."""
        return {
            "todo_id": row["todo_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "priority": row["priority"],
            "due_date": row["due_date"],
            "tags": row["tags"].split(",") if row["tags"] else [],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }


# ----------------------------------------------------------------------
# Skill 层（保留原有 API，内部委托给 Repository）
# ----------------------------------------------------------------------


class TodoSkill(ISkill):
    """待办事项管理技能，支持增删改查、完成标记和统计.

    【重构后】数据库操作全部委托给 TodoRepository，
    外部 API 完全不变。
    """

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
        db_path = os.path.expanduser("~/.yunxi/data/todo.db")
        self._repo = TodoRepository(db_path=db_path)

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

        todos, total = self._repo.list_todos(
            status=status,
            priority=priority,
            tag=tag,
            page=page,
            page_size=page_size,
        )
        return {
            "todos": todos,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        }

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建待办事项."""
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

        todo_id = self._repo.create_todo(
            title=title,
            description=description,
            status=status,
            priority=priority,
            due_date=due_date,
            tags_str=tags_str,
            created_at=created_at,
        )
        return {"todo_id": todo_id, "created": True, "title": title}

    def _update(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新待办事项."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        # 构建更新字段
        updates: dict[str, Any] = {}

        if "title" in params:
            updates["title"] = params["title"]
        if "description" in params:
            updates["description"] = params["description"]
        if "status" in params:
            updates["status"] = params["status"]
        if "priority" in params:
            updates["priority"] = int(params["priority"])
        if "due_date" in params:
            updates["due_date"] = params["due_date"]
        if "tags" in params:
            tags = params["tags"]
            updates["tags"] = ",".join(tags) if isinstance(tags, list) else tags

        if not updates:
            raise ValueError("没有需要更新的字段")

        self._repo.update_todo(todo_id, updates)
        return {"todo_id": todo_id, "updated": True}

    def _delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除待办事项."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        self._repo.delete_todo(todo_id)
        return {"deleted": True, "todo_id": todo_id}

    def _complete(self, params: dict[str, Any]) -> dict[str, Any]:
        """标记待办事项为已完成."""
        todo_id = params.get("todo_id", "")
        if not todo_id:
            raise ValueError("todo_id 不能为空")

        completed_at = datetime.now().isoformat()
        self._repo.complete_todo(todo_id, completed_at)
        return {"todo_id": todo_id, "completed": True, "completed_at": completed_at}

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """统计信息：今日完成、本周完成、待处理、逾期."""
        return self._repo.get_stats()

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
        return {
            "healthy": self._repo.is_healthy(),
            "skill_id": self.manifest.skill_id,
        }

    async def configure(self, config: dict[str, Any]) -> None:
        """配置更新."""
        self._config.update(config)

    # ------------------------------------------------------------------
    # 新增：Repository 访问属性
    # ------------------------------------------------------------------

    @property
    def repository(self) -> TodoRepository:
        """获取底层 TodoRepository 实例."""
        return self._repo

    def close(self) -> None:
        """关闭数据库连接."""
        self._repo.close()
