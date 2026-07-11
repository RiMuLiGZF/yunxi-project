from __future__ import annotations

"""习惯打卡技能."""

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


class HabitSkill(ISkill):
    """习惯打卡技能，支持习惯管理、打卡、连续天数和统计."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.habit",
            name="习惯打卡",
            version="1.0.0",
            description="习惯养成打卡，支持连续天数、完成率统计",
            author="yunxi",
            tags=["habit", "checkin", "productivity"],
            capabilities=["list_habits", "create_habit", "delete_habit", "check_in", "streak", "stats"],
            permissions=["read_file", "write"],
            entrypoint="HabitSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/habit.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS habits (
                    habit_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    frequency TEXT,
                    target_count INTEGER,
                    unit TEXT,
                    color TEXT,
                    created_at TEXT,
                    archived INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS habit_checkins (
                    checkin_id TEXT PRIMARY KEY,
                    habit_id TEXT,
                    checkin_date TEXT,
                    value REAL,
                    note TEXT,
                    created_at TEXT
                )
                """
            )
            # 创建索引加速查询
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_checkins_habit_date ON habit_checkins(habit_id, checkin_date)"
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用入口，根据 action 分发到对应处理方法."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "list_habits":
                data = self._list_habits(params)
            elif action == "create_habit":
                data = self._create_habit(params)
            elif action == "delete_habit":
                data = self._delete_habit(params)
            elif action == "check_in":
                data = self._check_in(params)
            elif action == "streak":
                data = self._streak(params)
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

    def _list_habits(self, params: dict[str, Any]) -> dict[str, Any]:
        """习惯列表，包含今日打卡状态."""
        include_archived = bool(params.get("include_archived", False))
        today_str = datetime.now().strftime("%Y-%m-%d")

        with sqlite3.connect(self._db_path) as conn:
            # 查询习惯列表
            if include_archived:
                rows = conn.execute(
                    """
                    SELECT habit_id, name, description, frequency, target_count, unit, color, created_at, archived
                    FROM habits ORDER BY created_at DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT habit_id, name, description, frequency, target_count, unit, color, created_at, archived
                    FROM habits WHERE archived = 0 ORDER BY created_at DESC
                    """
                ).fetchall()

            # 构建习惯列表并查询今日打卡状态
            habits: list[dict[str, Any]] = []
            for r in rows:
                habit_id = r[0]
                # 查询今日打卡记录
                checkin_rows = conn.execute(
                    """
                    SELECT checkin_id, value, note, created_at
                    FROM habit_checkins
                    WHERE habit_id = ? AND checkin_date = ?
                    ORDER BY created_at DESC
                    """,
                    (habit_id, today_str),
                ).fetchall()

                today_checkins = [
                    {
                        "checkin_id": c[0],
                        "value": c[1],
                        "note": c[2],
                        "created_at": c[3],
                    }
                    for c in checkin_rows
                ]
                today_total = sum(c[1] for c in checkin_rows)

                habit = {
                    "habit_id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "frequency": r[3],
                    "target_count": r[4],
                    "unit": r[5],
                    "color": r[6],
                    "created_at": r[7],
                    "archived": bool(r[8]),
                    "today_checkins": today_checkins,
                    "today_total": today_total,
                    "today_completed": today_total >= r[4] if r[4] else len(today_checkins) > 0,
                }
                habits.append(habit)

        return {"habits": habits, "total": len(habits)}

    def _create_habit(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建习惯."""
        habit_id = str(uuid.uuid4())
        name = params.get("name", "")
        description = params.get("description", "")
        frequency = params.get("frequency", "daily")
        target_count = int(params.get("target_count", 1))
        unit = params.get("unit", "次")
        color = params.get("color", "#4CAF50")
        created_at = datetime.now().isoformat()

        if not name:
            raise ValueError("习惯名称不能为空")

        if frequency not in ("daily", "weekly"):
            raise ValueError("频率只能是 daily 或 weekly")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO habits (habit_id, name, description, frequency, target_count, unit, color, created_at, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (habit_id, name, description, frequency, target_count, unit, color, created_at),
            )
            conn.commit()

        return {"habit_id": habit_id, "created": True, "name": name}

    def _delete_habit(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除/归档习惯，默认归档而非物理删除."""
        habit_id = params.get("habit_id", "")
        hard_delete = bool(params.get("hard_delete", False))

        if not habit_id:
            raise ValueError("habit_id 不能为空")

        with sqlite3.connect(self._db_path) as conn:
            if hard_delete:
                # 物理删除习惯及打卡记录
                conn.execute("DELETE FROM habit_checkins WHERE habit_id = ?", (habit_id,))
                cursor = conn.execute("DELETE FROM habits WHERE habit_id = ?", (habit_id,))
            else:
                # 归档
                cursor = conn.execute(
                    "UPDATE habits SET archived = 1 WHERE habit_id = ?", (habit_id,)
                )
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(f"习惯不存在: {habit_id}")

        return {"habit_id": habit_id, "deleted": True, "hard_delete": hard_delete}

    def _check_in(self, params: dict[str, Any]) -> dict[str, Any]:
        """习惯打卡."""
        habit_id = params.get("habit_id", "")
        value = float(params.get("value", 1))
        note = params.get("note", "")
        checkin_date = params.get("checkin_date", "")

        if not habit_id:
            raise ValueError("habit_id 不能为空")

        # 如果没有指定日期，使用今天
        if not checkin_date:
            checkin_date = datetime.now().strftime("%Y-%m-%d")

        checkin_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # 验证习惯存在且未归档
            habit_row = conn.execute(
                "SELECT habit_id, name, target_count, unit, frequency FROM habits WHERE habit_id = ? AND archived = 0",
                (habit_id,),
            ).fetchone()

            if not habit_row:
                raise ValueError(f"习惯不存在或已归档: {habit_id}")

            conn.execute(
                """
                INSERT INTO habit_checkins (checkin_id, habit_id, checkin_date, value, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (checkin_id, habit_id, checkin_date, value, note, created_at),
            )
            conn.commit()

            # 查询今日累计打卡值
            today_total_row = conn.execute(
                "SELECT COALESCE(SUM(value), 0) FROM habit_checkins WHERE habit_id = ? AND checkin_date = ?",
                (habit_id, checkin_date),
            ).fetchone()

        today_total = today_total_row[0]
        target = habit_row[2]
        is_target_reached = today_total >= target if target else False

        return {
            "checkin_id": checkin_id,
            "habit_id": habit_id,
            "checkin_date": checkin_date,
            "value": value,
            "today_total": today_total,
            "target": target,
            "target_reached": is_target_reached,
            "unit": habit_row[3],
        }

    def _streak(self, params: dict[str, Any]) -> dict[str, Any]:
        """计算连续打卡天数."""
        habit_id = params.get("habit_id", "")
        if not habit_id:
            raise ValueError("habit_id 不能为空")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today.strftime("%Y-%m-%d")

        with sqlite3.connect(self._db_path) as conn:
            # 获取所有打卡日期（去重）
            rows = conn.execute(
                "SELECT DISTINCT checkin_date FROM habit_checkins WHERE habit_id = ? ORDER BY checkin_date DESC",
                (habit_id,),
            ).fetchall()

        checkin_dates = {r[0] for r in rows}

        # 计算当前连续天数（从今天或昨天开始往前数）
        current_streak = 0
        check_date = today

        # 如果今天没打卡，从昨天开始算
        if today_str not in checkin_dates:
            check_date = today - timedelta(days=1)

        while check_date.strftime("%Y-%m-%d") in checkin_dates:
            current_streak += 1
            check_date -= timedelta(days=1)

        # 计算最长连续天数
        max_streak = 0
        temp_streak = 0
        prev_date = None

        sorted_dates = sorted(checkin_dates)
        for date_str in sorted_dates:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if prev_date and (date - prev_date).days == 1:
                temp_streak += 1
            else:
                temp_streak = 1
            max_streak = max(max_streak, temp_streak)
            prev_date = date

        return {
            "habit_id": habit_id,
            "current_streak": current_streak,
            "max_streak": max_streak,
            "total_checkin_days": len(checkin_dates),
        }

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """习惯统计：本周完成率、总打卡次数、最长连续."""
        habit_id = params.get("habit_id", "")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        # 本周开始（周一）
        week_start = today - timedelta(days=today.weekday())
        week_start_str = week_start.strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")

        with sqlite3.connect(self._db_path) as conn:
            if habit_id:
                # 单个习惯统计
                habit_row = conn.execute(
                    "SELECT habit_id, name, frequency, target_count, unit FROM habits WHERE habit_id = ?",
                    (habit_id,),
                ).fetchone()
                if not habit_row:
                    raise ValueError(f"习惯不存在: {habit_id}")

                # 总打卡次数
                total_checkins = conn.execute(
                    "SELECT COUNT(*) FROM habit_checkins WHERE habit_id = ?",
                    (habit_id,),
                ).fetchone()[0]

                # 本周打卡天数
                week_days = conn.execute(
                    "SELECT DISTINCT checkin_date FROM habit_checkins WHERE habit_id = ? AND checkin_date >= ?",
                    (habit_id, week_start_str),
                ).fetchall()

                # 本周累计值
                week_total = conn.execute(
                    "SELECT COALESCE(SUM(value), 0) FROM habit_checkins WHERE habit_id = ? AND checkin_date >= ?",
                    (habit_id, week_start_str),
                ).fetchone()[0]

                # 总打卡天数
                total_days = conn.execute(
                    "SELECT COUNT(DISTINCT checkin_date) FROM habit_checkins WHERE habit_id = ?",
                    (habit_id,),
                ).fetchone()[0]

                # 计算连续天数
                streak_info = self._streak({"habit_id": habit_id})

                # 本周完成率
                days_passed = (today - week_start).days + 1
                target = habit_row[3] or 1
                completed_days = len(week_days)
                completion_rate = round(completed_days / days_passed * 100, 1) if days_passed > 0 else 0

                return {
                    "habit_id": habit_id,
                    "name": habit_row[1],
                    "frequency": habit_row[2],
                    "target_count": target,
                    "unit": habit_row[4],
                    "total_checkins": total_checkins,
                    "total_days": total_days,
                    "week_completed_days": completed_days,
                    "week_total_value": week_total,
                    "week_completion_rate": completion_rate,
                    "current_streak": streak_info["current_streak"],
                    "max_streak": streak_info["max_streak"],
                    "week_start": week_start_str,
                    "today": today_str,
                }
            else:
                # 所有习惯概览统计
                total_habits = conn.execute(
                    "SELECT COUNT(*) FROM habits WHERE archived = 0"
                ).fetchone()[0]

                # 今日完成的习惯数
                today_completed = 0
                habit_rows = conn.execute(
                    "SELECT habit_id, target_count FROM habits WHERE archived = 0"
                ).fetchall()

                for h_row in habit_rows:
                    hid = h_row[0]
                    target = h_row[1] or 1
                    today_val = conn.execute(
                        "SELECT COALESCE(SUM(value), 0) FROM habit_checkins WHERE habit_id = ? AND checkin_date = ?",
                        (hid, today_str),
                    ).fetchone()[0]
                    if today_val >= target:
                        today_completed += 1

                # 本周总打卡次数
                week_total_checkins = conn.execute(
                    "SELECT COUNT(*) FROM habit_checkins WHERE checkin_date >= ?",
                    (week_start_str,),
                ).fetchone()[0]

                return {
                    "total_habits": total_habits,
                    "today_completed": today_completed,
                    "today_completion_rate": round(today_completed / total_habits * 100, 1) if total_habits > 0 else 0,
                    "week_total_checkins": week_total_checkins,
                    "today": today_str,
                    "week_start": week_start_str,
                }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("habit_error", action=request.action, error=error, trace_id=request.trace_id)
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
