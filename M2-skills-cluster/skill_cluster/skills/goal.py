from __future__ import annotations

"""目标管理技能."""

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class GoalSkill(ISkill):
    """目标管理技能，支持目标创建、进度追踪、里程碑管理."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.goal",
            name="目标管理",
            version="1.0.0",
            description="管理个人目标，支持进度追踪、里程碑管理、分类归档",
            author="yunxi",
            tags=["goal", "productivity", "planning"],
            capabilities=["list", "create", "update", "delete", "progress", "milestones"],
            permissions=["read_file", "write"],
            entrypoint="GoalSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/goal.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            # 目标表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS goals (
                    goal_id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    category TEXT,
                    status TEXT,
                    priority INTEGER,
                    deadline TEXT,
                    progress REAL,
                    created_at TEXT,
                    completed_at TEXT
                )
                """
            )
            # 里程碑表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS milestones (
                    milestone_id TEXT PRIMARY KEY,
                    goal_id TEXT,
                    title TEXT,
                    target_date TEXT,
                    completed INTEGER,
                    completed_at TEXT,
                    order_index INTEGER
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
            elif action == "progress":
                data = self._progress(params)
            elif action == "milestones":
                data = self._milestones(params)
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

    # ------------------------------ 动作：目标列表 ------------------------------

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取目标列表，支持按分类和状态筛选.

        Args:
            params:
                - category: 分类筛选（career/health/learning/finance/relationship/personal）
                - status: 状态筛选（planning/in_progress/completed/abandoned）
                - limit: 返回数量限制（可选，默认 50）
                - offset: 偏移量（可选，默认 0）
                - sort_by: 排序字段（可选，默认 created_at）
                - sort_order: 排序方向 asc/desc（可选，默认 desc）

        Returns:
            目标列表及总数
        """
        category = params.get("category")
        status = params.get("status")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        sort_by = params.get("sort_by", "created_at")
        sort_order = params.get("sort_order", "desc")

        # 允许的排序字段白名单
        allowed_sort = {"created_at", "deadline", "priority", "progress", "title"}
        if sort_by not in allowed_sort:
            sort_by = "created_at"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"

        query = """
            SELECT goal_id, title, description, category, status, priority,
                   deadline, progress, created_at, completed_at
            FROM goals
            WHERE 1=1
        """
        count_query = "SELECT COUNT(*) FROM goals WHERE 1=1"
        args: list[Any] = []
        count_args: list[Any] = []

        if category:
            query += " AND category = ?"
            count_query += " AND category = ?"
            args.append(category)
            count_args.append(category)

        if status:
            query += " AND status = ?"
            count_query += " AND status = ?"
            args.append(status)
            count_args.append(status)

        query += f" ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()
            total = conn.execute(count_query, count_args).fetchone()[0]

        goals = [
            {
                "goal_id": r[0],
                "title": r[1],
                "description": r[2] or "",
                "category": r[3],
                "status": r[4],
                "priority": r[5],
                "deadline": r[6] or "",
                "progress": r[7],
                "created_at": r[8],
                "completed_at": r[9] or "",
            }
            for r in rows
        ]

        return {"goals": goals, "total": total, "limit": limit, "offset": offset}

    # ------------------------------ 动作：创建目标 ------------------------------

    def _create(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建新目标，可选同时创建里程碑.

        Args:
            params:
                - title: 目标标题
                - description: 目标描述（可选）
                - category: 分类（career/health/learning/finance/relationship/personal）
                - priority: 优先级 0-3（可选，默认 1）
                - deadline: 截止日期 ISO 格式（可选）
                - milestones: 里程碑列表 [{title, target_date}, ...]（可选）

        Returns:
            创建结果及目标信息
        """
        goal_id = str(uuid.uuid4())
        title = params.get("title", "")
        description = params.get("description", "")
        category = params.get("category", "personal")
        priority = int(params.get("priority", 1))
        priority = max(0, min(3, priority))
        deadline = params.get("deadline", "")
        milestones_data = params.get("milestones", [])
        now = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO goals (goal_id, title, description, category, status,
                                   priority, deadline, progress, created_at, completed_at)
                VALUES (?, ?, ?, ?, 'planning', ?, ?, 0, ?, NULL)
                """,
                (goal_id, title, description, category, priority, deadline, now),
            )

            # 创建里程碑
            if milestones_data and isinstance(milestones_data, list):
                for idx, ms in enumerate(milestones_data):
                    ms_id = str(uuid.uuid4())
                    ms_title = ms.get("title", "") if isinstance(ms, dict) else str(ms)
                    ms_target = ms.get("target_date", "") if isinstance(ms, dict) else ""
                    conn.execute(
                        """
                        INSERT INTO milestones (milestone_id, goal_id, title, target_date,
                                                completed, completed_at, order_index)
                        VALUES (?, ?, ?, ?, 0, NULL, ?)
                        """,
                        (ms_id, goal_id, ms_title, ms_target, idx),
                    )

            conn.commit()

        return {"goal_id": goal_id, "created": True, "title": title}

    # ------------------------------ 动作：更新目标 ------------------------------

    def _update(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新目标信息.

        Args:
            params:
                - goal_id: 目标 ID
                - title: 标题（可选）
                - description: 描述（可选）
                - category: 分类（可选）
                - status: 状态（可选：planning/in_progress/completed/abandoned）
                - priority: 优先级（可选）
                - deadline: 截止日期（可选）

        Returns:
            更新结果
        """
        goal_id = params.get("goal_id", "")
        if not goal_id:
            raise ValueError("goal_id is required")

        # 收集可更新字段
        updates: list[str] = []
        args: list[Any] = []

        if "title" in params:
            updates.append("title = ?")
            args.append(params["title"])

        if "description" in params:
            updates.append("description = ?")
            args.append(params["description"])

        if "category" in params:
            updates.append("category = ?")
            args.append(params["category"])

        if "status" in params:
            status = params["status"]
            updates.append("status = ?")
            args.append(status)
            # 如果状态变为 completed，设置完成时间
            if status == "completed":
                updates.append("completed_at = ?")
                args.append(datetime.now().isoformat())
            elif status in ("planning", "in_progress", "abandoned"):
                updates.append("completed_at = NULL")
                args.append(None)

        if "priority" in params:
            priority = int(params["priority"])
            priority = max(0, min(3, priority))
            updates.append("priority = ?")
            args.append(priority)

        if "deadline" in params:
            updates.append("deadline = ?")
            args.append(params["deadline"])

        if not updates:
            return {"updated": False, "goal_id": goal_id, "message": "no fields to update"}

        args.append(goal_id)
        query = f"UPDATE goals SET {', '.join(updates)} WHERE goal_id = ?"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(query, args)
            conn.commit()

        return {"updated": True, "goal_id": goal_id}

    # ------------------------------ 动作：删除目标 ------------------------------

    def _delete(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除目标及其所有里程碑.

        Args:
            params:
                - goal_id: 目标 ID

        Returns:
            删除结果
        """
        goal_id = params.get("goal_id", "")
        if not goal_id:
            raise ValueError("goal_id is required")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM milestones WHERE goal_id = ?", (goal_id,))
            conn.execute("DELETE FROM goals WHERE goal_id = ?", (goal_id,))
            conn.commit()

        return {"deleted": True, "goal_id": goal_id}

    # ------------------------------ 动作：更新进度 ------------------------------

    def _progress(self, params: dict[str, Any]) -> dict[str, Any]:
        """更新目标进度.

        Args:
            params:
                - goal_id: 目标 ID
                - progress: 进度值 0-100
                - auto_status: 是否自动根据进度调整状态（可选，默认 True）

        Returns:
            更新后的进度信息
        """
        goal_id = params.get("goal_id", "")
        progress = float(params.get("progress", 0))
        progress = max(0.0, min(100.0, progress))
        auto_status = bool(params.get("auto_status", True))

        with sqlite3.connect(self._db_path) as conn:
            if auto_status:
                if progress >= 100:
                    status = "completed"
                    completed_at = datetime.now().isoformat()
                    conn.execute(
                        "UPDATE goals SET progress = ?, status = ?, completed_at = ? WHERE goal_id = ?",
                        (progress, status, completed_at, goal_id),
                    )
                elif progress > 0:
                    conn.execute(
                        "UPDATE goals SET progress = ?, status = 'in_progress', completed_at = NULL WHERE goal_id = ?",
                        (progress, goal_id),
                    )
                else:
                    conn.execute(
                        "UPDATE goals SET progress = 0, completed_at = NULL WHERE goal_id = ?",
                        (goal_id,),
                    )
            else:
                conn.execute(
                    "UPDATE goals SET progress = ? WHERE goal_id = ?",
                    (progress, goal_id),
                )
            conn.commit()

            # 获取更新后的目标
            row = conn.execute(
                "SELECT goal_id, title, progress, status FROM goals WHERE goal_id = ?",
                (goal_id,),
            ).fetchone()

        if not row:
            raise ValueError(f"Goal not found: {goal_id}")

        return {
            "goal_id": row[0],
            "title": row[1],
            "progress": row[2],
            "status": row[3],
            "updated": True,
        }

    # ------------------------------ 动作：里程碑管理 ------------------------------

    def _milestones(self, params: dict[str, Any]) -> dict[str, Any]:
        """里程碑管理：列表/创建/标记完成/删除.

        Args:
            params:
                - action: "list" / "create" / "complete" / "delete"
                - goal_id: 目标 ID（list/create 必填）
                - milestone_id: 里程碑 ID（complete/delete 必填）
                - title: 里程碑标题（create 必填）
                - target_date: 目标日期（create 可选）
                - completed: 是否完成（complete 可选，默认 True）

        Returns:
            里程碑列表或操作结果
        """
        sub_action = params.get("action", "list")

        if sub_action == "create":
            return self._create_milestone(params)
        elif sub_action == "complete":
            return self._complete_milestone(params)
        elif sub_action == "delete":
            return self._delete_milestone(params)

        # list 模式
        goal_id = params.get("goal_id", "")
        if not goal_id:
            raise ValueError("goal_id is required for list action")

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT milestone_id, goal_id, title, target_date, completed,
                       completed_at, order_index
                FROM milestones
                WHERE goal_id = ?
                ORDER BY order_index ASC
                """,
                (goal_id,),
            ).fetchall()

        milestones = [
            {
                "milestone_id": r[0],
                "goal_id": r[1],
                "title": r[2],
                "target_date": r[3] or "",
                "completed": bool(r[4]),
                "completed_at": r[5] or "",
                "order_index": r[6],
            }
            for r in rows
        ]

        # 计算里程碑完成进度
        total = len(milestones)
        completed_count = sum(1 for m in milestones if m["completed"])
        ms_progress = round(completed_count / total * 100, 1) if total > 0 else 0.0

        return {
            "milestones": milestones,
            "total": total,
            "completed_count": completed_count,
            "progress": ms_progress,
            "goal_id": goal_id,
        }

    def _create_milestone(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建里程碑."""
        goal_id = params.get("goal_id", "")
        title = params.get("title", "")
        target_date = params.get("target_date", "")

        if not goal_id:
            raise ValueError("goal_id is required")

        milestone_id = str(uuid.uuid4())

        with sqlite3.connect(self._db_path) as conn:
            # 计算下一个 order_index
            row = conn.execute(
                "SELECT COALESCE(MAX(order_index), -1) FROM milestones WHERE goal_id = ?",
                (goal_id,),
            ).fetchone()
            order_index = row[0] + 1

            conn.execute(
                """
                INSERT INTO milestones (milestone_id, goal_id, title, target_date,
                                        completed, completed_at, order_index)
                VALUES (?, ?, ?, ?, 0, NULL, ?)
                """,
                (milestone_id, goal_id, title, target_date, order_index),
            )
            conn.commit()

        return {"milestone_id": milestone_id, "created": True, "goal_id": goal_id}

    def _complete_milestone(self, params: dict[str, Any]) -> dict[str, Any]:
        """标记里程碑完成/未完成."""
        milestone_id = params.get("milestone_id", "")
        completed = bool(params.get("completed", True))

        if not milestone_id:
            raise ValueError("milestone_id is required")

        completed_at = datetime.now().isoformat() if completed else None

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE milestones SET completed = ?, completed_at = ? WHERE milestone_id = ?",
                (1 if completed else 0, completed_at, milestone_id),
            )
            conn.commit()

            # 自动更新目标进度（基于里程碑完成率）
            row = conn.execute(
                "SELECT goal_id FROM milestones WHERE milestone_id = ?",
                (milestone_id,),
            ).fetchone()

            if row:
                goal_id = row[0]
                ms_row = conn.execute(
                    """
                    SELECT COUNT(*), SUM(completed)
                    FROM milestones
                    WHERE goal_id = ?
                    """,
                    (goal_id,),
                ).fetchone()
                total_ms = ms_row[0] or 0
                completed_ms = ms_row[1] or 0
                new_progress = round(completed_ms / total_ms * 100, 1) if total_ms > 0 else 0.0

                if new_progress >= 100:
                    conn.execute(
                        "UPDATE goals SET progress = ?, status = 'completed', completed_at = ? WHERE goal_id = ?",
                        (new_progress, datetime.now().isoformat(), goal_id),
                    )
                elif new_progress > 0:
                    conn.execute(
                        "UPDATE goals SET progress = ?, status = 'in_progress' WHERE goal_id = ?",
                        (new_progress, goal_id),
                    )
                conn.commit()

        return {
            "milestone_id": milestone_id,
            "completed": completed,
            "updated": True,
        }

    def _delete_milestone(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除里程碑."""
        milestone_id = params.get("milestone_id", "")

        if not milestone_id:
            raise ValueError("milestone_id is required")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM milestones WHERE milestone_id = ?", (milestone_id,))
            conn.commit()

        return {"deleted": True, "milestone_id": milestone_id}

    # ------------------------------ 工具方法 ------------------------------

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("goal_error", action=request.action, error=error, trace_id=request.trace_id)
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
