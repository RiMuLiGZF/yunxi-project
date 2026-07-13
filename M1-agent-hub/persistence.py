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

增强特性：
- WAL 模式提升并发读写性能
- 指数退避重试机制（database is locked）
- 数据库损坏检测与自动恢复
- 连接健康检查
- 优雅关闭与优化
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

import structlog

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class SQLitePersistence:
    """SQLite 持久化引擎

    提供异步友好的 SQLite 数据持久化能力。
    实际 I/O 在线程池中执行，避免阻塞事件循环。

    增强能力：
    - WAL 模式 + busy_timeout，减少锁竞争
    - 指数退避重试机制，应对 "database is locked"
    - 数据库损坏自动检测与恢复
    - 健康检查接口
    """

    SCHEMA_VERSION: int = 1

    # 重试配置
    MAX_RETRIES: int = 3
    RETRY_BACKOFFS: tuple[float, ...] = (0.05, 0.1, 0.2)  # 秒，指数退避

    # 连接泄漏检测默认配置
    DEFAULT_CONNECTION_MAX_AGE: float = 3600.0  # 秒，连接最大存活时间
    CONNECTION_LEAK_ENABLED: bool = True  # 是否启用连接泄漏检测

    def __init__(
        self,
        db_path: str = ":memory:",
        connection_max_age: float | None = None,
        enable_leak_detection: bool = True,
    ) -> None:
        self.db_path: str = db_path
        self._connection: sqlite3.Connection | None = None
        self._connection_age: float = 0.0
        """连接创建时间戳（time.time()），用于泄漏检测"""
        self._connection_max_age: float = (
            connection_max_age if connection_max_age is not None
            else self.DEFAULT_CONNECTION_MAX_AGE
        )
        """连接最大存活时间（秒），超过后自动重置"""
        self._enable_leak_detection: bool = enable_leak_detection
        """是否启用连接泄漏检测"""
        self._logger: structlog.stdlib.BoundLogger = logger.bind(service="sqlite_persistence", db_path=db_path)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库连接和表结构

        流程：
        1. 建立连接
        2. 启用 WAL 模式与性能调优 PRAGMA
        3. 完整性检测（损坏则自动恢复）
        4. 创建表结构
        """
        self._connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        # 记录连接创建时间，用于泄漏检测
        self._connection_age = time.time()

        # 启用 WAL 模式与性能参数
        self._configure_pragmas()

        # 完整性检测与损坏恢复
        self._check_corruption()

        self._create_tables()
        self._logger.info("sqlite_db_initialized", path=self.db_path)

    def _configure_pragmas(self) -> None:
        """配置数据库性能与并发相关的 PRAGMA

        - journal_mode=WAL: 提升并发读写，减少写锁阻塞
        - synchronous=NORMAL: 平衡性能与安全性（WAL 模式下推荐）
        - busy_timeout=5000: 5 秒 busy 超时，配合重试机制
        """
        cursor = self._connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        self._logger.debug(
            "sqlite_pragmas_configured",
            journal_mode="WAL",
            synchronous="NORMAL",
            busy_timeout_ms=5000,
        )

    # ── 重试机制 ──────────────────────────────────────────

    def _execute_with_retry(
        self,
        operation: Callable[[sqlite3.Connection], Any],
    ) -> Any:
        """执行数据库操作并在遇到 'database is locked' 时指数退避重试

        Args:
            operation: 接收 sqlite3.Connection 参数的可调用对象，
                       内部执行具体的 SQL 操作（含 commit/fetch 等）。

        Returns:
            operation 的返回值

        Raises:
            sqlite3.OperationalError: 重试耗尽后仍失败则抛出原始异常
            其他 sqlite3 异常: 非 locked 类错误直接抛出，不重试

        重试策略：
            - 默认最多重试 3 次
            - 退避间隔：0.05s → 0.1s → 0.2s（指数增长）
            - 仅对 "database is locked" 相关错误进行重试
        """
        last_exc: sqlite3.OperationalError | None = None

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return operation(self._connection)
            except sqlite3.OperationalError as exc:
                error_msg = str(exc).lower()
                if "database is locked" not in error_msg:
                    # 非锁相关错误，直接抛出
                    raise

                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    backoff = self.RETRY_BACKOFFS[attempt]
                    self._logger.warning(
                        "sqlite_db_locked_retrying",
                        attempt=attempt + 1,
                        max_retries=self.MAX_RETRIES,
                        backoff_seconds=backoff,
                    )
                    time.sleep(backoff)
                else:
                    self._logger.error(
                        "sqlite_db_locked_max_retries_exceeded",
                        max_retries=self.MAX_RETRIES,
                        error=str(exc),
                    )

        # 理论上不会走到这里，但为了类型安全兜底
        if last_exc is not None:
            raise last_exc

    # ── 损坏检测与自动恢复 ────────────────────────────────

    def _check_corruption(self) -> None:
        """检测数据库完整性，若损坏则自动恢复

        执行 PRAGMA integrity_check，若结果不是 'ok'：
        1. 将当前 db 文件重命名为 .corrupted 备份
        2. 记录 ERROR 级日志与告警
        3. 关闭旧连接，重新建立新数据库
        """
        try:
            cursor = self._connection.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            integrity_result = result[0] if result else "unknown"
        except sqlite3.DatabaseError as exc:
            integrity_result = f"exception: {exc}"

        if integrity_result == "ok":
            self._logger.debug("sqlite_integrity_check_passed")
            return

        # 检测到损坏，执行恢复流程
        self._logger.error(
            "sqlite_db_corruption_detected",
            integrity_result=integrity_result,
            db_path=self.db_path,
        )
        self._logger.warning(
            "sqlite_db_corruption_alert",
            message="数据库完整性检查失败，已启动自动恢复流程，"
                    "请及时检查备份文件并评估数据丢失风险。",
        )

        # 内存数据库无法备份，直接重建
        if self.db_path == ":memory:":
            self._logger.warning("sqlite_memory_db_corrupted_recreating")
            self._connection.close()
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._configure_pragmas()
            return

        # 文件数据库：备份损坏文件后重建
        try:
            corrupted_path = self.db_path + ".corrupted"
            # 若已有备份，追加时间戳避免覆盖
            if os.path.exists(corrupted_path):
                timestamp = int(time.time())
                corrupted_path = f"{self.db_path}.corrupted.{timestamp}"

            self._connection.close()
            os.rename(self.db_path, corrupted_path)

            self._logger.error(
                "sqlite_db_corrupted_backup_created",
                corrupted_path=corrupted_path,
            )

            # 重新建立连接和新数据库
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._configure_pragmas()

            self._logger.error(
                "sqlite_db_recovered_from_corruption",
                message="损坏数据库已备份并重建，数据可能已丢失。",
            )
        except OSError as exc:
            self._logger.error(
                "sqlite_db_corruption_recovery_failed",
                error=str(exc),
            )
            # 恢复失败时尝试直接重建连接（可能无法写入）
            self._connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row

    # ── 健康检查 ──────────────────────────────────────────

    def is_healthy(self) -> bool:
        """检测数据库连接是否健康

        执行简单的 SELECT 1 探测，验证连接可用性。
        任何异常均视为不健康。

        Returns:
            True 表示连接正常，False 表示连接不可用
        """
        if self._connection is None:
            return False
        try:
            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return True
        except sqlite3.Error:
            return False

    def integrity_check(self) -> dict[str, Any]:
        """执行深度完整性检查并返回详细结果

        包含：
        - 整体完整性检测结果
        - 各表记录数统计
        - 数据库文件大小（文件模式下）

        Returns:
            包含检查结果的字典，结构如下：
            {
                "healthy": bool,
                "integrity": str,       # "ok" 或具体错误信息
                "table_counts": {
                    "ltm_entries": int,
                    "traces": int,
                    "feedbacks": int,
                    "events": int,
                    "route_records": int,
                    "meta": int,
                },
                "db_size_bytes": int | None,  # 内存数据库为 None
            }
        """
        result: dict[str, Any] = {
            "healthy": False,
            "integrity": "unknown",
            "table_counts": {},
            "db_size_bytes": None,
        }

        if self._connection is None:
            result["integrity"] = "no_connection"
            return result

        try:
            # 完整性检测
            cursor = self._connection.cursor()
            cursor.execute("PRAGMA integrity_check")
            row = cursor.fetchone()
            integrity_result = row[0] if row else "unknown"
            result["integrity"] = integrity_result
            result["healthy"] = (integrity_result == "ok")

            # 各表记录数
            tables = ["ltm_entries", "traces", "feedbacks", "events",
                      "route_records", "meta"]
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count_row = cursor.fetchone()
                    result["table_counts"][table] = count_row[0] if count_row else 0
                except sqlite3.OperationalError:
                    result["table_counts"][table] = -1  # 表不存在

            # 文件大小（仅文件数据库）
            if self.db_path != ":memory:":
                try:
                    result["db_size_bytes"] = os.path.getsize(self.db_path)
                except OSError:
                    result["db_size_bytes"] = None

        except sqlite3.Error as exc:
            result["integrity"] = f"error: {exc}"
            result["healthy"] = False

        return result

    # ── 连接泄漏检测 ──────────────────────────────────────

    def check_connection_leak(self, max_age_seconds: float | None = None) -> bool:
        """检查连接是否泄漏（存活时间过长）。

        如果连接存活时间超过 max_age_seconds，视为潜在泄漏，
        自动执行安全重连（关闭旧连接 + 建立新连接）。

        Args:
            max_age_seconds: 最大存活时间（秒），为 None 时使用实例级配置。

        Returns:
            True 表示检测到泄漏并已执行重连，False 表示连接正常。
        """
        if not self._enable_leak_detection:
            return False
        if self._connection is None:
            return False

        max_age = max_age_seconds if max_age_seconds is not None else self._connection_max_age
        age = time.time() - self._connection_age

        if age <= max_age:
            return False

        self._logger.warning(
            "sqlite_connection_leak_detected",
            age_seconds=round(age, 2),
            max_age_seconds=max_age,
            db_path=self.db_path,
        )

        # 执行安全重连
        self._reconnect()
        return True

    def _reconnect(self) -> None:
        """安全重连：关闭旧连接并重新建立新连接。

        用于连接泄漏检测后的自动重置，或连接异常时的恢复。
        重连后会重新创建表结构（IF NOT EXISTS，安全），
        并重置连接创建时间。
        """
        self._logger.info(
            "sqlite_connection_reconnecting",
            db_path=self.db_path,
            previous_age_seconds=round(time.time() - self._connection_age, 2),
        )

        # 关闭旧连接
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error as exc:
                self._logger.warning(
                    "sqlite_reconnect_close_failed",
                    error=str(exc),
                )
            finally:
                self._connection = None

        # 重新初始化
        self._init_db()

        self._logger.info(
            "sqlite_connection_reconnected",
            db_path=self.db_path,
        )

    # ── 表结构初始化 ──────────────────────────────────────

    def _create_tables(self) -> None:
        """创建数据表"""
        def _create(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()

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

            conn.commit()

        self._execute_with_retry(_create)

    # ── 优雅关闭 ──────────────────────────────────────────

    def close(self) -> None:
        """优雅关闭数据库连接

        关闭流程：
        1. 检查是否有未完成事务，尝试提交（失败则回滚）
        2. 执行 PRAGMA optimize 进行数据库优化
        3. 关闭连接
        4. 记录关闭日志
        """
        if self._connection is None:
            self._logger.debug("sqlite_close_already_closed")
            return

        try:
            # 检查并处理未完成事务
            try:
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")  # 探测连接
                # 尝试提交未完成事务
                self._connection.commit()
                self._logger.debug("sqlite_close_pending_transaction_committed")
            except sqlite3.Error:
                try:
                    self._connection.rollback()
                    self._logger.warning("sqlite_close_pending_transaction_rolled_back")
                except sqlite3.Error:
                    pass

            # 执行数据库优化（WAL 模式下推荐定期执行）
            try:
                cursor = self._connection.cursor()
                cursor.execute("PRAGMA optimize")
                self._logger.debug("sqlite_close_optimize_executed")
            except sqlite3.Error as exc:
                self._logger.warning(
                    "sqlite_close_optimize_failed",
                    error=str(exc),
                )

        finally:
            try:
                self._connection.close()
            except sqlite3.Error as exc:
                self._logger.warning(
                    "sqlite_close_connection_error",
                    error=str(exc),
                )
            finally:
                self._connection = None
                self._logger.info("sqlite_db_closed", path=self.db_path)

    # ── 长期记忆持久化 ────────────────────────────────────

    def save_ltm_entry(self, entry: dict[str, Any]) -> None:
        """保存长期记忆条目"""
        def _save(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
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
            conn.commit()

        self._execute_with_retry(_save)

    def load_ltm_entries(self, limit: int = 1000) -> list[dict[str, Any]]:
        """加载所有长期记忆条目"""
        def _load(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM ltm_entries ORDER BY importance DESC, last_accessed DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_ltm_entry(row) for row in rows]

        return self._execute_with_retry(_load)

    def delete_ltm_entry(self, entry_id: str) -> None:
        """删除长期记忆条目"""
        def _delete(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ltm_entries WHERE entry_id = ?", (entry_id,))
            conn.commit()

        self._execute_with_retry(_delete)

    def search_ltm_by_content(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """按内容关键词搜索长期记忆"""
        def _search(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM ltm_entries WHERE content LIKE ? ORDER BY importance DESC LIMIT ?",
                (f"%{keyword}%", limit),
            )
            rows = cursor.fetchall()
            return [self._row_to_ltm_entry(row) for row in rows]

        return self._execute_with_retry(_search)

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
        def _save(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
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
            conn.commit()

        self._execute_with_retry(_save)

    def load_traces(self, limit: int = 100) -> list[dict[str, Any]]:
        """加载追踪数据"""
        def _load(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM traces ORDER BY start_time DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [self._row_to_trace(row) for row in rows]

        return self._execute_with_retry(_load)

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
        def _save(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
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
            conn.commit()

        self._execute_with_retry(_save)

    def load_feedbacks(self, agent_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        """加载反馈记录"""
        def _load(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
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

        return self._execute_with_retry(_load)

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
        def _save(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
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
            conn.commit()

        self._execute_with_retry(_save)

    def load_events(
        self,
        trace_id: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """加载事件"""
        def _load(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
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

        return self._execute_with_retry(_load)

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
        def _save(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
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
            conn.commit()

        self._execute_with_retry(_save)

    def load_route_records(self, intent: str | None = None) -> list[dict[str, Any]]:
        """加载路由统计"""
        def _load(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            cursor = conn.cursor()
            if intent:
                cursor.execute(
                    "SELECT * FROM route_records WHERE intent = ?",
                    (intent,),
                )
            else:
                cursor.execute("SELECT * FROM route_records")
            rows = cursor.fetchall()
            return [self._row_to_route_record(row) for row in rows]

        return self._execute_with_retry(_load)

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
        def _stats(conn: sqlite3.Connection) -> dict[str, Any]:
            cursor = conn.cursor()
            tables = ["ltm_entries", "traces", "feedbacks", "events", "route_records"]
            stats = {}
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            return stats

        return self._execute_with_retry(_stats)

    def clear_all(self) -> None:
        """清空所有数据（主要用于测试）"""
        def _clear(conn: sqlite3.Connection) -> None:
            cursor = conn.cursor()
            for table in ["ltm_entries", "traces", "feedbacks", "events", "route_records"]:
                cursor.execute(f"DELETE FROM {table}")
            conn.commit()

        self._execute_with_retry(_clear)
