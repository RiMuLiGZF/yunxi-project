from __future__ import annotations

"""通知提醒技能."""

import os
import sqlite3
import time
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class NotifySkill(ISkill):
    """通知提醒技能，支持发送通知、定时提醒、取消提醒."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.notify",
            name="通知提醒",
            version="1.0.0",
            description="发送通知、定时提醒、取消提醒",
            author="yunxi",
            tags=["notification", "system"],
            capabilities=["send_notification", "schedule_reminder", "cancel_reminder"],
            permissions=["write"],
            entrypoint="NotifySkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/notify.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    reminder_id TEXT PRIMARY KEY,
                    trigger_at REAL,
                    payload TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "send_notification":
                data = await self._send_notification(params)
            elif action == "schedule_reminder":
                data = self._schedule_reminder(params)
            elif action == "cancel_reminder":
                data = self._cancel_reminder(params)
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

    async def _send_notification(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title", "")
        body = params.get("body", "")
        level = params.get("level", "info")
        # 写入通知队列（简化：写入本地文件）
        queue_path = os.path.expanduser("~/.yunxi/data/notification_queue.txt")
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(f"[{level}] {title}: {body}\n")
        # 通过消息总线 publish（预留接口，实际由上层消费）
        logger.info(
            "notification_sent",
            title=title,
            level=level,
            topic="system.events",
        )
        return {"sent": True, "title": title, "level": level}

    def _schedule_reminder(self, params: dict[str, Any]) -> dict[str, Any]:
        reminder_id = params.get("reminder_id", "")
        trigger_at = params.get("trigger_at", 0.0)
        payload = params.get("payload", {})
        import json

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reminders (reminder_id, trigger_at, payload) VALUES (?, ?, ?)",
                (reminder_id, trigger_at, json.dumps(payload)),
            )
            conn.commit()
        return {"scheduled": True, "reminder_id": reminder_id}

    def _cancel_reminder(self, params: dict[str, Any]) -> dict[str, Any]:
        reminder_id = params.get("reminder_id", "")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM reminders WHERE reminder_id = ?", (reminder_id,))
            conn.commit()
        return {"cancelled": True, "reminder_id": reminder_id}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("notify_error", action=request.action, error=error, trace_id=request.trace_id)
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
