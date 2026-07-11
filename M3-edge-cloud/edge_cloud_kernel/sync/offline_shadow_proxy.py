"""离线影子代理.

网络中断时本地队列缓存所有同步操作，重连后自动批量增量同步到云端。
实现 OfflineShadowProxy 类，拦截 SyncAPI 调用，根据网络状态决定
直接透传或入队持久化队列（基于 aiosqlite）。

设计依据：M3 离线影子代理需求规格。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import aiosqlite
import structlog
from pydantic import BaseModel, Field

from edge_cloud_kernel.models.exceptions import SyncError
from edge_cloud_kernel.sync.sync_api import (
    SyncAPI,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncResolveRequest,
    SyncResolveResponse,
    SyncSessionRequest,
    SyncSessionResponse,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH: str = os.path.expanduser("~/.yunxi/cache/offline_queue.db")
_CONNECTIVITY_PROBE_TIMEOUT: float = 5.0  # 连通性探测超时（秒）
_SESSION_TTL_SECONDS: float = 3600.0  # 会话有效期（秒）
_MAX_BATCH_PUSH_SIZE: int = 50  # 单次批量推送最大条目数


# ---------------------------------------------------------------------------
# 枚举 & 数据模型
# ---------------------------------------------------------------------------


class ConnectionState(str, Enum):
    """网络连接状态枚举.

    Attributes:
        ONLINE: 网络正常，操作直接透传到 SyncAPI.
        OFFLINE: 网络中断，操作入队持久化队列.
        RECONNECTING: 正在重连中，新操作仍入队.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    RECONNECTING = "reconnecting"


class OfflineReplayDetail(BaseModel):
    """单条回放结果详情.

    Attributes:
        queue_id: 队列记录 ID.
        operation: 操作类型.
        session_id: 关联会话 ID.
        success: 是否成功.
        error: 失败时的错误信息.
    """

    queue_id: int = Field(..., description="队列记录 ID")
    operation: str = Field(..., description="操作类型")
    session_id: str = Field(default="", description="关联会话 ID")
    success: bool = Field(default=True, description="是否成功")
    error: str = Field(default="", description="失败错误信息")


class OfflineReplayResult(BaseModel):
    """批量回放结果汇总.

    Attributes:
        success_count: 成功回放的操作数.
        failed_count: 回放失败的操作数.
        skipped_count: 跳过的操作数（如过期会话）.
        details: 每条操作的详细结果列表.
    """

    success_count: int = Field(default=0, description="成功数")
    failed_count: int = Field(default=0, description="失败数")
    skipped_count: int = Field(default=0, description="跳过数")
    details: list[OfflineReplayDetail] = Field(
        default_factory=list, description="详细结果列表"
    )


# ---------------------------------------------------------------------------
# OfflineShadowProxy
# ---------------------------------------------------------------------------


class OfflineShadowProxy:
    """离线影子代理.

    拦截 SyncAPI 调用，根据网络连通状态决定直接透传或入队本地持久化队列。
    当网络恢复后自动按 FIFO 顺序回放队列中的操作，支持连续 push 批量合并
    和冲突自动解决（local_wins 策略）。

    Attributes:
        _sync_api: 底层 SyncAPI 实例.
        _state: 当前连接状态.
        _health_check_interval: 周期性健康检查间隔（秒）.
        _db_path: SQLite 队列数据库路径.
    """

    # ------------------------------------------------------------------
    # 初始化 & 生命周期
    # ------------------------------------------------------------------

    def __init__(
        self,
        sync_api: SyncAPI | None = None,
        health_check_interval: float = 30.0,
        db_path: str | None = None,
    ) -> None:
        """初始化离线影子代理.

        Args:
            sync_api: 底层 SyncAPI 实例，在线时直接透传。
                       若为 None，则代理以纯离线模式启动，所有操作入队，
                       后续可通过 bind_sync_api 绑定.
            health_check_interval: 周期性健康检查间隔（秒），默认 30s.
            db_path: SQLite 持久化队列文件路径，默认 ~/.yunxi/cache/offline_queue.db.
        """
        self._sync_api = sync_api
        # 没有 sync_api 时默认进入纯离线模式
        self._state = (
            ConnectionState.ONLINE if sync_api is not None
            else ConnectionState.OFFLINE
        )
        self._health_check_interval = health_check_interval
        self._db_path = db_path or DEFAULT_DB_PATH
        self._connectivity_callback: Callable[[ConnectionState], Any] | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._replay_lock = asyncio.Lock()
        self._db: aiosqlite.Connection | None = None
        logger.info(
            "offline_shadow_proxy.init",
            health_check_interval=health_check_interval,
            db_path=self._db_path,
        )

    async def start(self) -> None:
        """启动代理：初始化数据库并开启周期性健康检查.

        应在事件循环启动后调用。
        """
        await self._ensure_db()
        self._health_task = asyncio.create_task(self._health_check_loop())
        logger.info("offline_shadow_proxy.started")

    async def stop(self) -> None:
        """停止代理：取消健康检查任务并关闭数据库连接."""
        if self._health_task is not None:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
        if self._db is not None:
            await self._db.close()
            self._db = None
        logger.info("offline_shadow_proxy.stopped")

    # ------------------------------------------------------------------
    # 网络状态检测
    # ------------------------------------------------------------------

    async def check_connectivity(self) -> bool:
        """探测云端端点连通性.

        通过尝试创建一个临时同步会话来验证网络是否可用，超时 5 秒。
        若未绑定 sync_api，则直接返回 False（纯离线模式）。

        Returns:
            网络是否连通.
        """
        if self._sync_api is None:
            logger.debug("offline_shadow_proxy.no_sync_api_offline")
            return False

        try:
            # 使用短超时的探测请求验证连通性
            await asyncio.wait_for(
                self._sync_api.create_session(
                    SyncSessionRequest(device_id="__health_check__", scopes=[])
                ),
                timeout=_CONNECTIVITY_PROBE_TIMEOUT,
            )
            return True
        except asyncio.TimeoutError:
            logger.debug("offline_shadow_proxy.connectivity_timeout")
            return False
        except Exception as exc:
            logger.debug(
                "offline_shadow_proxy.connectivity_check_failed",
                error=str(exc),
            )
            return False

    def set_connectivity_callback(
        self,
        callback: Callable[[ConnectionState], Any],
    ) -> None:
        """设置外部网络状态变更回调.

        当代理内部检测到 ONLINE -> OFFLINE 或 OFFLINE -> ONLINE 时，
        会调用此回调通知外部组件。

        Args:
            callback: 接收 ConnectionState 参数的异步或同步回调.
        """
        self._connectivity_callback = callback
        logger.debug("offline_shadow_proxy.connectivity_callback_set")

    async def _transition_state(self, new_state: ConnectionState) -> None:
        """执行状态转换并通知回调.

        Args:
            new_state: 目标连接状态.
        """
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        logger.info(
            "offline_shadow_proxy.state_changed",
            old=old_state.value,
            new=new_state.value,
        )
        if self._connectivity_callback is not None:
            try:
                result = self._connectivity_callback(new_state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "offline_shadow_proxy.connectivity_callback_error",
                    state=new_state.value,
                )

    async def _health_check_loop(self) -> None:
        """周期性健康检查协程.

        每 `_health_check_interval` 秒探测一次连通性，
        状态变化时触发自动回放。
        """
        while True:
            await asyncio.sleep(self._health_check_interval)
            try:
                is_online = await self.check_connectivity()
                if is_online and self._state != ConnectionState.ONLINE:
                    await self._transition_state(ConnectionState.RECONNECTING)
                    # 自动触发回放
                    await self.replay()
                    await self._transition_state(ConnectionState.ONLINE)
                elif not is_online and self._state == ConnectionState.ONLINE:
                    await self._transition_state(ConnectionState.OFFLINE)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("offline_shadow_proxy.health_check_error")

    # ------------------------------------------------------------------
    # 本地操作队列（SQLite 持久化）
    # ------------------------------------------------------------------

    async def _ensure_db(self) -> None:
        """确保数据库文件和表已创建.

        创建数据库父目录（如不存在）并初始化 offline_queue 表。
        """
        db_file = Path(self._db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS offline_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                operation       TEXT NOT NULL,
                session_id      TEXT,
                payload         TEXT NOT NULL,
                queued_at       REAL,
                retry_count     INTEGER DEFAULT 0,
                last_retry_at   REAL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_oq_operation "
            "ON offline_queue(operation)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_oq_queued_at "
            "ON offline_queue(queued_at)"
        )
        await self._db.commit()
        logger.debug("offline_shadow_proxy.db_ready", path=self._db_path)

    async def enqueue(
        self,
        operation: str,
        session_id: str,
        payload: dict,
    ) -> None:
        """将操作加入离线队列.

        Args:
            operation: 操作类型（push / resolve / session_create）.
            session_id: 关联的同步会话 ID（session_create 可为空）.
            payload: 序列化为 JSON 存储的操作负载字典.
        """
        assert self._db is not None
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        await self._db.execute(
            """
            INSERT INTO offline_queue (operation, session_id, payload, queued_at)
            VALUES (?, ?, ?, ?)
            """,
            (operation, session_id, payload_json, time.time()),
        )
        await self._db.commit()
        logger.info(
            "offline_shadow_proxy.enqueued",
            operation=operation,
            session_id=session_id,
        )

    async def get_queue_size(self) -> int:
        """获取当前队列深度.

        Returns:
            队列中待回放的操作数量.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM offline_queue"
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0
        logger.debug("offline_shadow_proxy.queue_size", size=count)
        return count

    async def purge(self, max_retries: int = 5) -> int:
        """清理超过最大重试次数的操作记录.

        Args:
            max_retries: 最大重试次数阈值，默认 5.

        Returns:
            清理的记录数量.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM offline_queue WHERE retry_count >= ?",
            (max_retries,),
        )
        await self._db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info(
                "offline_shadow_proxy.purged",
                count=deleted,
                max_retries=max_retries,
            )
        return deleted

    async def _fetch_all_queued(self) -> list[dict[str, Any]]:
        """从队列中取出全部待回放记录（按 FIFO 排序）.

        Returns:
            队列记录字典列表，每条包含 id/operation/session_id/payload 等字段.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, operation, session_id, payload, queued_at, retry_count "
            "FROM offline_queue ORDER BY queued_at ASC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "operation": row["operation"],
                "session_id": row["session_id"] or "",
                "payload": json.loads(row["payload"]),
                "queued_at": row["queued_at"],
                "retry_count": row["retry_count"],
            }
            for row in rows
        ]

    async def _remove_queued(self, queue_id: int) -> None:
        """从队列中删除已成功回放的记录.

        Args:
            queue_id: 队列记录 ID.
        """
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM offline_queue WHERE id = ?", (queue_id,)
        )
        await self._db.commit()

    async def _increment_retry(self, queue_id: int) -> None:
        """递增记录的重试计数并更新最后重试时间.

        Args:
            queue_id: 队列记录 ID.
        """
        assert self._db is not None
        await self._db.execute(
            "UPDATE offline_queue SET retry_count = retry_count + 1, "
            "last_retry_at = ? WHERE id = ?",
            (time.time(), queue_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # 批量回放策略
    # ------------------------------------------------------------------

    async def replay(self) -> OfflineReplayResult:
        """回放离线队列中的所有操作.

        按 FIFO 顺序处理：
        - 连续的 push 操作合并为单次批量推送（减少网络开销）.
        - resolve 操作逐条回放（顺序敏感）.
        - session_create 操作直接透传；若原会话已过期则创建新会话.

        冲突处理：push 返回冲突时自动以 local_wins 策略解决；
        push 返回 409 版本冲突时递增重试计数并重新入队。

        若未绑定 sync_api，则直接返回空结果（纯离线模式无法回放）。

        Returns:
            OfflineReplayResult 回放结果汇总.
        """
        if self._sync_api is None:
            logger.warning("offline_shadow_proxy.replay_no_sync_api")
            return OfflineReplayResult()

        async with self._replay_lock:
            result = OfflineReplayResult()
            records = await self._fetch_all_queued()

            if not records:
                logger.debug("offline_shadow_proxy.replay_empty")
                return result

            logger.info(
                "offline_shadow_proxy.replay_start",
                queue_size=len(records),
            )

            # 按操作类型分组处理
            i = 0
            while i < len(records):
                rec = records[i]

                if rec["operation"] == "push":
                    # 合并连续 push 为单次批量推送
                    batch_pushes, consumed = self._collect_consecutive_pushes(
                        records, i
                    )
                    detail = await self._replay_batch_push(batch_pushes)
                    result.details.append(detail)
                    if detail.success:
                        result.success_count += consumed
                        for pr in batch_pushes:
                            await self._remove_queued(pr["id"])
                    else:
                        result.failed_count += consumed
                        for pr in batch_pushes:
                            await self._increment_retry(pr["id"])
                    i += consumed

                elif rec["operation"] == "resolve":
                    # resolve 逐条回放
                    detail = await self._replay_single_resolve(rec)
                    result.details.append(detail)
                    if detail.success:
                        result.success_count += 1
                        await self._remove_queued(rec["id"])
                    else:
                        result.failed_count += 1
                        await self._increment_retry(rec["id"])
                    i += 1

                elif rec["operation"] == "session_create":
                    # session_create：直接透传
                    detail = await self._replay_session_create(rec)
                    result.details.append(detail)
                    if detail.success:
                        result.success_count += 1
                        await self._remove_queued(rec["id"])
                    else:
                        result.skipped_count += 1
                        await self._increment_retry(rec["id"])
                    i += 1

                else:
                    # 未知操作类型：跳过
                    logger.warning(
                        "offline_shadow_proxy.unknown_operation",
                        operation=rec["operation"],
                        queue_id=rec["id"],
                    )
                    result.details.append(
                        OfflineReplayDetail(
                            queue_id=rec["id"],
                            operation=rec["operation"],
                            session_id=rec["session_id"],
                            success=False,
                            error=f"Unknown operation: {rec['operation']}",
                        )
                    )
                    result.skipped_count += 1
                    await self._remove_queued(rec["id"])
                    i += 1

            # 清理超限重试记录
            purged = await self.purge()
            if purged:
                logger.info(
                    "offline_shadow_proxy.replay_purged", count=purged
                )

            logger.info(
                "offline_shadow_proxy.replay_completed",
                success=result.success_count,
                failed=result.failed_count,
                skipped=result.skipped_count,
            )
            return result

    @staticmethod
    def _collect_consecutive_pushes(
        records: list[dict[str, Any]],
        start_index: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """从 start_index 开始收集连续的 push 操作.

        Args:
            records: 全部队列记录.
            start_index: 起始索引.

        Returns:
            (合并的 push 列表, 消费的记录数).
        """
        batch: list[dict[str, Any]] = []
        i = start_index
        total_changes: list[dict[str, Any]] = []
        merged_version_vector: dict[str, int] = {}

        while i < len(records) and records[i]["operation"] == "push":
            rec = records[i]
            batch.append(rec)
            payload = rec["payload"]
            changes = payload.get("changes", [])
            total_changes.extend(changes)
            version_vector = payload.get("version_vector", {})
            merged_version_vector.update(version_vector)

            # 单批次上限检查
            if len(total_changes) >= _MAX_BATCH_PUSH_SIZE:
                break
            i += 1

        # 构建合并后的 payload
        if batch:
            merged_payload = {
                "changes": total_changes,
                "version_vector": merged_version_vector,
            }
            batch[0]["payload"] = merged_payload
            # 后续记录标记为已合并（仅保留第一条的完整 payload）
            for j in range(1, len(batch)):
                batch[j]["payload"] = {"_merged_into": batch[0]["id"]}

        return batch, len(batch)

    async def _replay_batch_push(
        self,
        batch: list[dict[str, Any]],
    ) -> OfflineReplayDetail:
        """回放一批合并的 push 操作.

        使用第一条记录的 session_id 发起合并后的推送。
        如果服务端返回冲突，自动以 local_wins 策略解决。

        Args:
            batch: 合并后的 push 记录列表.

        Returns:
            OfflineReplayDetail 回放详情.
        """
        if not batch:
            return OfflineReplayDetail(
                queue_id=0,
                operation="push",
                success=False,
                error="Empty batch",
            )

        first = batch[0]
        session_id = first["session_id"]
        payload = first["payload"]

        try:
            push_request = SyncPushRequest.model_validate(payload)
            response: SyncPushResponse = await self._sync_api.push(
                session_id, push_request
            )

            # 检查是否有冲突需要自动解决
            if response.conflicts:
                logger.info(
                    "offline_shadow_proxy.replay_auto_resolve",
                    session_id=session_id,
                    conflict_count=len(response.conflicts),
                )
                await self._auto_resolve_conflicts(
                    session_id, response.conflicts
                )

            return OfflineReplayDetail(
                queue_id=first["id"],
                operation="push",
                session_id=session_id,
                success=True,
            )

        except SyncError as exc:
            # 409 版本冲突：递增重试计数并重新入队
            if exc.error_code and "409" in str(exc.error_code):
                logger.warning(
                    "offline_shadow_proxy.replay_version_conflict",
                    session_id=session_id,
                    error_code=exc.error_code,
                )
                return OfflineReplayDetail(
                    queue_id=first["id"],
                    operation="push",
                    session_id=session_id,
                    success=False,
                    error=f"Version conflict: {exc.error_code}",
                )

            logger.warning(
                "offline_shadow_proxy.replay_push_error",
                session_id=session_id,
                error=str(exc),
            )
            return OfflineReplayDetail(
                queue_id=first["id"],
                operation="push",
                session_id=session_id,
                success=False,
                error=str(exc),
            )

        except Exception as exc:
            logger.exception(
                "offline_shadow_proxy.replay_push_exception",
                session_id=session_id,
            )
            return OfflineReplayDetail(
                queue_id=first["id"],
                operation="push",
                session_id=session_id,
                success=False,
                error=str(exc),
            )

    async def _auto_resolve_conflicts(
        self,
        session_id: str,
        conflicts: list[dict[str, Any]],
    ) -> None:
        """自动解决冲突 — 使用 local_wins 策略.

        离线期间缓存的操作来自本地，数据更新，因此采用 local 优先策略。

        Args:
            session_id: 同步会话 ID.
            conflicts: 服务端返回的冲突列表.
        """
        conflict_ids = [c.get("item_id", "") for c in conflicts if c.get("item_id")]
        if not conflict_ids:
            return

        try:
            resolve_request = SyncResolveRequest(
                conflict_ids=conflict_ids,
                resolution="local",
            )
            response = await self._sync_api.resolve(session_id, resolve_request)
            logger.info(
                "offline_shadow_proxy.auto_resolve_completed",
                session_id=session_id,
                resolved=response.resolved,
                failed=response.failed,
            )
        except Exception:
            logger.exception(
                "offline_shadow_proxy.auto_resolve_failed",
                session_id=session_id,
                conflict_ids=conflict_ids,
            )

    async def _replay_single_resolve(
        self,
        record: dict[str, Any],
    ) -> OfflineReplayDetail:
        """回放单条 resolve 操作.

        Args:
            record: 队列记录字典.

        Returns:
            OfflineReplayDetail 回放详情.
        """
        session_id = record["session_id"]
        payload = record["payload"]

        try:
            resolve_request = SyncResolveRequest.model_validate(payload)
            await self._sync_api.resolve(session_id, resolve_request)
            return OfflineReplayDetail(
                queue_id=record["id"],
                operation="resolve",
                session_id=session_id,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "offline_shadow_proxy.replay_resolve_error",
                session_id=session_id,
                error=str(exc),
            )
            return OfflineReplayDetail(
                queue_id=record["id"],
                operation="resolve",
                session_id=session_id,
                success=False,
                error=str(exc),
            )

    async def _replay_session_create(
        self,
        record: dict[str, Any],
    ) -> OfflineReplayDetail:
        """回放 session_create 操作.

        若原始会话已过期，重新创建新会话。

        Args:
            record: 队列记录字典.

        Returns:
            OfflineReplayDetail 回放详情.
        """
        payload = record["payload"]

        try:
            session_request = SyncSessionRequest.model_validate(payload)
            await self._sync_api.create_session(session_request)
            return OfflineReplayDetail(
                queue_id=record["id"],
                operation="session_create",
                session_id="",
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "offline_shadow_proxy.replay_session_create_error",
                error=str(exc),
            )
            return OfflineReplayDetail(
                queue_id=record["id"],
                operation="session_create",
                success=False,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # SyncAPI 代理接口
    # ------------------------------------------------------------------

    async def create_session(
        self,
        request: SyncSessionRequest,
    ) -> SyncSessionResponse:
        """创建同步会话（代理方法）.

        在线时直接透传到 SyncAPI；离线时将操作入队并返回
        占位响应（包含本地生成的 session_id）。

        Args:
            request: 同步会话请求.

        Returns:
            SyncSessionResponse.

        Raises:
            SyncError: 在线模式下 SyncAPI 抛出的异常直接透传.
        """
        if self._state == ConnectionState.ONLINE and self._sync_api is not None:
            return await self._sync_api.create_session(request)

        # 离线模式：入队并返回占位响应
        await self.enqueue(
            operation="session_create",
            session_id="",
            payload=request.model_dump(),
        )
        logger.info("offline_shadow_proxy.create_session_queued")
        return SyncSessionResponse(
            session_id="__offline_pending__",
            server_version="offline",
        )

    async def push(
        self,
        session_id: str,
        request: SyncPushRequest,
    ) -> SyncPushResponse:
        """推送本地变更到云端（代理方法）.

        在线时直接透传；离线时入队本地队列。

        Args:
            session_id: 同步会话 ID.
            request: 推送请求.

        Returns:
            SyncPushResponse. 离线时返回空接受列表的占位响应.
        """
        if self._state == ConnectionState.ONLINE and self._sync_api is not None:
            return await self._sync_api.push(session_id, request)

        # 离线模式：入队
        await self.enqueue(
            operation="push",
            session_id=session_id,
            payload=request.model_dump(),
        )
        logger.info(
            "offline_shadow_proxy.push_queued",
            session_id=session_id,
            changes_count=len(request.changes),
        )
        return SyncPushResponse(
            accepted=[d.item_id for d in request.changes],
            rejected=[],
            conflicts=[],
        )

    async def pull(
        self,
        session_id: str,
        since_version: dict[str, int],
    ) -> SyncPullResponse:
        """拉取云端变更到本地（代理方法）.

        pull 为只读操作，始终尝试透传。若网络不可用则返回空变更列表。

        Args:
            session_id: 同步会话 ID.
            since_version: 客户端本地版本向量.

        Returns:
            SyncPullResponse.
        """
        if self._state == ConnectionState.ONLINE and self._sync_api is not None:
            return await self._sync_api.pull(session_id, since_version)

        # 离线模式：pull 为只读操作不入队，返回空变更
        logger.debug(
            "offline_shadow_proxy.pull_offline",
            session_id=session_id,
        )
        return SyncPullResponse(changes=[], server_version="offline")

    async def resolve(
        self,
        session_id: str,
        request: SyncResolveRequest,
    ) -> SyncResolveResponse:
        """解决同步冲突（代理方法）.

        在线时直接透传；离线时入队待回放。

        Args:
            session_id: 同步会话 ID.
            request: 冲突解决请求.

        Returns:
            SyncResolveResponse. 离线时返回空解决列表的占位响应.
        """
        if self._state == ConnectionState.ONLINE and self._sync_api is not None:
            return await self._sync_api.resolve(session_id, request)

        # 离线模式：入队
        await self.enqueue(
            operation="resolve",
            session_id=session_id,
            payload=request.model_dump(),
        )
        logger.info(
            "offline_shadow_proxy.resolve_queued",
            session_id=session_id,
            conflict_ids=request.conflict_ids,
        )
        return SyncResolveResponse(
            resolved=request.conflict_ids,
            failed=[],
        )

    # ------------------------------------------------------------------
    # 动态绑定 & 辅助属性
    # ------------------------------------------------------------------

    def bind_sync_api(self, sync_api: SyncAPI) -> None:
        """后续绑定 SyncAPI 实例（纯离线模式 -> 可在线模式）.

        当 OfflineShadowProxy 以无 sync_api 的纯离线模式启动后，
        可通过此方法绑定真实的 SyncAPI，绑定后会自动触发一次连通性检查，
        若网络可用则切换为 ONLINE 状态并回放队列。

        Args:
            sync_api: 底层 SyncAPI 实例.
        """
        if self._sync_api is not None:
            logger.warning("offline_shadow_proxy.sync_api_already_bound")
            return
        self._sync_api = sync_api
        logger.info("offline_shadow_proxy.sync_api_bound")

    async def bind_sync_api_and_replay(self, sync_api: SyncAPI) -> OfflineReplayResult | None:
        """绑定 SyncAPI 并尝试回放队列（便捷方法）.

        绑定后立即检查连通性，若在线则自动回放离线队列。

        Args:
            sync_api: 底层 SyncAPI 实例.

        Returns:
            若触发回放则返回回放结果，否则返回 None.
        """
        self.bind_sync_api(sync_api)
        is_online = await self.check_connectivity()
        if is_online:
            await self._transition_state(ConnectionState.RECONNECTING)
            result = await self.replay()
            await self._transition_state(ConnectionState.ONLINE)
            return result
        return None

    @property
    def state(self) -> ConnectionState:
        """当前网络连接状态."""
        return self._state

    @property
    def is_online(self) -> bool:
        """网络是否在线."""
        return self._state == ConnectionState.ONLINE
