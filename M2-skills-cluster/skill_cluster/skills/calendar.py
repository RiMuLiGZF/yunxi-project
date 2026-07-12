from __future__ import annotations

"""日历管理技能."""

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


class CalendarSkill(ISkill):
    """日历管理技能，支持事件增删查、空闲时段查询."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.calendar",
            name="日历管理",
            version="1.0.0",
            description="管理本地日历事件、查询空闲时段",
            author="yunxi",
            tags=["calendar", "time"],
            capabilities=["list_events", "create_event", "delete_event", "get_free_slots"],
            permissions=["read_file", "write"],
            entrypoint="CalendarSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/calendar.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    title TEXT,
                    start TEXT,
                    end TEXT,
                    description TEXT,
                    calendar_id TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "list_events":
                data = self._list_events(params)
            elif action == "create_event":
                data = self._create_event(params)
            elif action == "delete_event":
                data = self._delete_event(params)
            elif action == "get_free_slots":
                data = self._get_free_slots(params)
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

    def _list_events(self, params: dict[str, Any]) -> dict[str, Any]:
        start = params.get("start", "")
        end = params.get("end", "")
        calendar_id = params.get("calendar_id")
        with sqlite3.connect(self._db_path) as conn:
            if calendar_id:
                rows = conn.execute(
                    "SELECT event_id, title, start, end, description FROM events WHERE calendar_id = ? AND start >= ? AND end <= ?",
                    (calendar_id, start, end),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT event_id, title, start, end, description FROM events WHERE start >= ? AND end <= ?",
                    (start, end),
                ).fetchall()
        events = [
            {"event_id": r[0], "title": r[1], "start": r[2], "end": r[3], "description": r[4]}
            for r in rows
        ]
        return {"events": events}

    def _create_event(self, params: dict[str, Any]) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        title = params.get("title", "")
        start = params.get("start", "")
        end = params.get("end", "")
        description = params.get("description", "")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO events (event_id, title, start, end, description) VALUES (?, ?, ?, ?, ?)",
                (event_id, title, start, end, description),
            )
            conn.commit()
        return {"event_id": event_id, "created": True}

    def _delete_event(self, params: dict[str, Any]) -> dict[str, Any]:
        event_id = params.get("event_id", "")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            conn.commit()
        return {"deleted": True, "event_id": event_id}

    def _get_free_slots(self, params: dict[str, Any]) -> dict[str, Any]:
        date_str = params.get("date", "")
        duration_minutes = params.get("duration_minutes", 30)
        day_start = datetime.fromisoformat(date_str).replace(hour=0, minute=0, second=0)
        day_end = day_start + timedelta(days=1)
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT start, end FROM events WHERE start >= ? AND end <= ?",
                (day_start.isoformat(), day_end.isoformat()),
            ).fetchall()
        busy = []
        for r in rows:
            s = datetime.fromisoformat(r[0])
            e = datetime.fromisoformat(r[1])
            busy.append((s, e))
        busy.sort()
        free: list[dict[str, str]] = []
        current = day_start
        for s, e in busy:
            if (s - current).total_seconds() >= duration_minutes * 60:
                free.append({"start": current.isoformat(), "end": s.isoformat()})
            current = max(current, e)
        if (day_end - current).total_seconds() >= duration_minutes * 60:
            free.append({"start": current.isoformat(), "end": day_end.isoformat()})
        return {"free_slots": free}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("calendar_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
