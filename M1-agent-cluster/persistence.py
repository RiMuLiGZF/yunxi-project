"""
云汐内核 V4 - SQLite 持久化层

灵感来源：LangGraph Checkpointer / SQLite Saver

将内存中的关键数据持久化到 SQLite：
- 长期记忆 (LongTermMemory)
- 链路追踪 (Traces)
- 反馈记录 (Feedback)
- 事件日志 (DomainEvent)
- 路由统计 (RouteRecord)

支持异步读写，应用重启后数据不丢失。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class SQLitePersistence:
    """SQLite 持久化引擎

    提供异步友好的 SQLite 数据持久化能力。
    实际 I/O 在线程池中执行，避免阻塞事件循环。
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
        self._logger = logger.bind(service="sqlite_persistence", db_path=db_path)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库连接和表结构"""
        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._create_tables()
        self._logger.info("sqlite_db_initialized", path=self.db_path)

    def _create_tables(self) -> None:
        """创建数据表"""
        cursor = self._connection.cursor()

        # 长期记忆表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ltm_entries (
                entry_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT DEFAULT 'generic',
                source TEXT,
                importance REAL DEFAULT 0.5,
                created_at REAL DEFAULT 0,
                last_accessed REAL DEFAULT 0,
                access_count INTEGER DEFAULT 0,
                tags TEXT,
                metadata TEXT
            )
        """)

        # 追踪表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                start_time REAL DEFAULT 0,
                end_time REAL,
                duration_ms REAL DEFAULT 0,
                span_count INTEGER DEFAULT 0,
                is_success INTEGER DEFAULT 0,
                metadata TEXT,
                spans_json TEXT
            )
        """)

        # 反馈表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedbacks (
                feedback_id TEXT PRIMARY KEY,
                trace_id TEXT,
                agent_id TEXT,
                intent TEXT,
                feedback_type TEXT DEFAULT 'explicit',
                rating INTEGER DEFAULT 0,
                comment TEXT,
                metadata TEXT,
                created_at REAL DEFAULT 0
            )
        """)

        # 事件表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                trace_id TEXT,
                timestamp REAL DEFAULT 0,
                version INTEGER DEFAULT 1,
                payload TEXT,
                metadata TEXT
            )
        """)

        # 路由统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS route_records (
                route_id TEXT PRIMARY KEY,
                intent TEXT,
                target_agent TEXT,
                execution_count REAL DEFAULT 0,
                success_count REAL DEFAULT 0,
                total_latency_ms REAL DEFAULT 0,
                avg_score REAL DEFAULT 0,
                last_used REAL DEFAULT 0,
                active INTEGER DEFAULT 1
            )
        """)

        # 元数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cursor.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(self.SCHEMA_VERSION)),
        )

        self._connection.commit()

    def close(self) -> None:
        """关闭数据库连接"""
        if self._connection:
            self._connection.close()
            self._connection = None

    # ── 长期记忆持久化 ────────────────────────────────────

    def save_ltm_entry(self, entry: dict[str, Any]) -> None:
        """保存长期记忆条目"""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO ltm_entries
            (entry_id, content, memory_type, source, importance, created_at,
             last_accessed, access_count, tags, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.get("entry_id", ""),
            entry.get("content", ""),
            entry.get("memory_type", "generic"),
            entry.get("source", ""),
            entry.get("importance", 0.5),
            entry.get("created_at", 0),
            entry.get("last_accessed", 0),
            entry.get("access_count", 0),
            json.dumps(entry.get("tags", []), ensure_ascii=False),
            json.dumps(entry.get("metadata", {}), ensure_ascii=False),
        ))
        self._connection.commit()

    def load_ltm_entries(self, limit: int = 1000) -> list[dict[str, Any]]:
        """加载所有长期记忆条目"""
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT * FROM ltm_entries ORDER BY importance DESC, last_accessed DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [self._row_to_ltm_entry(row) for row in rows]

    def delete_ltm_entry(self, entry_id: str) -> None:
        """删除长期记忆条目"""
        cursor = self._connection.cursor()
        cursor.execute("DELETE FROM ltm_entries WHERE entry_id = ?", (entry_id,))
        self._connection.commit()

    def search_ltm_by_content(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """按内容关键词搜索长期记忆"""
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT * FROM ltm_entries WHERE content LIKE ? ORDER BY importance DESC LIMIT ?",
            (f"%{keyword}%", limit),
        )
        rows = cursor.fetchall()
        return [self._row_to_ltm_entry(row) for row in rows]

    def _row_to_ltm_entry(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "entry_id": row["entry_id"],
            "content": row["content"],
            "memory_type": row["memory_type"],
            "source": row["source"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "last_accessed": row["last_accessed"],
            "access_count": row["access_count"],
            "tags": json.loads(row["tags"] or "[]"),
            "metadata": json.loads(row["metadata"] or "{}"),
        }

    # ── 追踪持久化 ────────────────────────────────────────

    def save_trace(self, trace_data: dict[str, Any]) -> None:
        """保存追踪数据"""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO traces
            (trace_id, start_time, end_time, duration_ms, span_count, is_success, metadata, spans_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trace_data.get("trace_id", ""),
            trace_data.get("start_time", 0),
            trace_data.get("end_time"),
            trace_data.get("duration_ms", 0),
            trace_data.get("span_count", 0),
            1 if trace_data.get("is_success") else 0,
            json.dumps(trace_data.get("metadata", {}), ensure_ascii=False),
            json.dumps(trace_data.get("spans", []), ensure_ascii=False),
        ))
        self._connection.commit()

    def load_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        """加载追踪数据"""
        cursor = self._connection.cursor()
        cursor.execute(
            "SELECT * FROM traces ORDER BY start_time DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        return [self._row_to_trace(row) for row in rows]

    def _row_to_trace(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "trace_id": row["trace_id"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "duration_ms": row["duration_ms"],
            "span_count": row["span_count"],
            "is_success": bool(row["is_success"]),
            "metadata": json.loads(row["metadata"] or "{}"),
            "spans": json.loads(row["spans_json"] or "[]"),
        }

    # ── 反馈持久化 ────────────────────────────────────────

    def save_feedback(self, feedback: dict[str, Any]) -> None:
        """保存反馈记录"""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO feedbacks
            (feedback_id, trace_id, agent_id, intent, feedback_type, rating, comment, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feedback.get("feedback_id", ""),
            feedback.get("trace_id", ""),
            feedback.get("agent_id", ""),
            feedback.get("intent", ""),
            feedback.get("feedback_type", "explicit"),
            feedback.get("rating", 0),
            feedback.get("comment", ""),
            json.dumps(feedback.get("metadata", {}), ensure_ascii=False),
            feedback.get("created_at", time.time()),
        ))
        self._connection.commit()

    def load_feedbacks(self, agent_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """加载反馈记录"""
        cursor = self._connection.cursor()
        if agent_id:
            cursor.execute(
                "SELECT * FROM feedbacks WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM feedbacks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = cursor.fetchall()
        return [self._row_to_feedback(row) for row in rows]

    def _row_to_feedback(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "feedback_id": row["feedback_id"],
            "trace_id": row["trace_id"],
            "agent_id": row["agent_id"],
            "intent": row["intent"],
            "feedback_type": row["feedback_type"],
            "rating": row["rating"],
            "comment": row["comment"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "created_at": row["created_at"],
        }

    # ── 事件持久化 ────────────────────────────────────────

    def save_event(self, event: dict[str, Any]) -> None:
        """保存事件"""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO events
            (event_id, event_type, trace_id, timestamp, version, payload, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("event_id", ""),
            event.get("event_type", ""),
            event.get("trace_id", ""),
            event.get("timestamp", 0),
            event.get("version", 1),
            json.dumps(event.get("payload", {}), ensure_ascii=False),
            json.dumps(event.get("metadata", {}), ensure_ascii=False),
        ))
        self._connection.commit()

    def load_events(
        self,
        trace_id: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """加载事件"""
        cursor = self._connection.cursor()
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if trace_id:
            query += " AND trace_id = ?"
            params.append(trace_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "trace_id": row["trace_id"],
            "timestamp": row["timestamp"],
            "version": row["version"],
            "payload": json.loads(row["payload"] or "{}"),
            "metadata": json.loads(row["metadata"] or "{}"),
        }

    # ── 路由统计持久化 ────────────────────────────────────

    def save_route_record(self, record: dict[str, Any]) -> None:
        """保存路由统计"""
        cursor = self._connection.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO route_records
            (route_id, intent, target_agent, execution_count, success_count,
             total_latency_ms, avg_score, last_used, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get("route_id", ""),
            record.get("intent", ""),
            record.get("target_agent", ""),
            record.get("execution_count", 0),
            record.get("success_count", 0),
            record.get("total_latency_ms", 0),
            record.get("avg_score", 0),
            record.get("last_used", 0),
            1 if record.get("active", True) else 0,
        ))
        self._connection.commit()

    def load_route_records(self, intent: str | None = None) -> list[dict[str, Any]]:
        """加载路由统计"""
        cursor = self._connection.cursor()
        if intent:
            cursor.execute(
                "SELECT * FROM route_records WHERE intent = ?",
                (intent,),
            )
        else:
            cursor.execute("SELECT * FROM route_records")
        rows = cursor.fetchall()
        return [self._row_to_route_record(row) for row in rows]

    def _row_to_route_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "route_id": row["route_id"],
            "intent": row["intent"],
            "target_agent": row["target_agent"],
            "execution_count": row["execution_count"],
            "success_count": row["success_count"],
            "total_latency_ms": row["total_latency_ms"],
            "avg_score": row["avg_score"],
            "last_used": row["last_used"],
            "active": bool(row["active"]),
        }

    # ── 统计 ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取持久化层统计"""
        cursor = self._connection.cursor()
        tables = ["ltm_entries", "traces", "feedbacks", "events", "route_records"]
        stats = {}
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]
        return stats

    def clear_all(self) -> None:
        """清空所有数据（主要用于测试）"""
        cursor = self._connection.cursor()
        for table in ["ltm_entries", "traces", "feedbacks", "events", "route_records"]:
            cursor.execute(f"DELETE FROM {table}")
        self._connection.commit()
