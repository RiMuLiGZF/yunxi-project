"""端云消息总线.

提供端云之间的消息队列服务，支持：
- 端云消息队列
- 消息持久化
- 消息确认机制
- 消息优先级
- 离线消息缓存

与现有 OfflineShadowProxy 协同工作，提供更通用的消息总线能力。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_DB_NAME = "message_bus.db"
DEFAULT_MAX_QUEUE_SIZE = 10000
DEFAULT_MAX_RETRIES = 5
DEFAULT_ACK_TIMEOUT = 60  # 秒


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class MessagePriority(int, Enum):
    """消息优先级枚举.

    Attributes:
        LOW: 低优先级（0）.
        NORMAL: 普通优先级（5）.
        HIGH: 高优先级（8）.
        CRITICAL: 关键优先级（10）.
    """

    LOW = 0
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


class MessageStatus(str, Enum):
    """消息状态枚举.

    Attributes:
        PENDING: 待发送.
        SENDING: 发送中.
        SENT: 已发送.
        ACKED: 已确认.
        FAILED: 发送失败.
        EXPIRED: 已过期.
    """

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    ACKED = "acked"
    FAILED = "failed"
    EXPIRED = "expired"


class MessageAckStatus(str, Enum):
    """消息确认状态.

    Attributes:
        ACK: 确认接收.
        NACK: 拒绝接收.
        RETRY: 请求重试.
    """

    ACK = "ack"
    NACK = "nack"
    RETRY = "retry"


class MessageDirection(str, Enum):
    """消息方向.

    Attributes:
        EDGE_TO_CLOUD: 端 -> 云.
        CLOUD_TO_EDGE: 云 -> 端.
    """

    EDGE_TO_CLOUD = "edge_to_cloud"
    CLOUD_TO_EDGE = "cloud_to_edge"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """消息对象.

    Attributes:
        message_id: 消息唯一标识.
        topic: 消息主题.
        direction: 消息方向.
        payload: 消息负载.
        priority: 优先级（0-10）.
        status: 消息状态.
        device_id: 目标/源设备 ID.
        correlation_id: 关联消息 ID（用于请求-响应模式）.
        created_at: 创建时间.
        sent_at: 发送时间.
        acked_at: 确认时间.
        expires_at: 过期时间.
        retry_count: 重试次数.
        last_error: 最后错误信息.
        headers: 自定义消息头.
    """

    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = "default"
    direction: MessageDirection = MessageDirection.EDGE_TO_CLOUD
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = MessagePriority.NORMAL
    status: MessageStatus = MessageStatus.PENDING
    device_id: str = ""
    correlation_id: str = ""
    created_at: float = field(default_factory=time.time)
    sent_at: float = 0.0
    acked_at: float = 0.0
    expires_at: float = 0.0
    retry_count: int = 0
    last_error: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """是否已过期."""
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at

    @property
    def size_bytes(self) -> int:
        """消息大小（字节）."""
        try:
            return len(json.dumps(self.payload, default=str).encode("utf-8"))
        except Exception:
            return 0


@dataclass
class MessageBusStats:
    """消息总线统计.

    Attributes:
        total_sent: 总发送数.
        total_acked: 总确认数.
        total_failed: 总失败数.
        total_expired: 总过期数.
        pending_count: 待发送数.
        in_flight_count: 发送中数.
        retry_count: 重试总数.
    """

    total_sent: int = 0
    total_acked: int = 0
    total_failed: int = 0
    total_expired: int = 0
    pending_count: int = 0
    in_flight_count: int = 0
    retry_count: int = 0


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------


class MessageBus:
    """端云消息总线.

    提供持久化的消息队列服务，支持：
    - 多主题消息队列
    - 消息优先级
    - 消息确认机制 (ACK/NACK)
    - 消息持久化（SQLite）
    - 离线消息缓存
    - 订阅/发布模式
    - 请求/响应模式

    Attributes:
        _db_path: 数据库路径.
        _db: 数据库连接.
        _max_queue_size: 最大队列大小.
        _max_retries: 最大重试次数.
        _ack_timeout: 确认超时时间（秒）.
        _subscribers: 订阅者字典 {topic: [callback, ...]}.
        _stats: 统计信息.
        _initialized: 是否已初始化.
        _send_loop_task: 发送循环任务.
        _send_callback: 发送回调（实际发送消息的函数）.
    """

    def __init__(
        self,
        data_dir: str | None = None,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        ack_timeout: int = DEFAULT_ACK_TIMEOUT,
    ) -> None:
        """初始化消息总线.

        Args:
            data_dir: 数据目录，默认 ~/.yunxi/message_bus/.
            max_queue_size: 最大队列大小.
            max_retries: 最大重试次数.
            ack_timeout: 确认超时时间（秒）.
        """
        base_dir = Path(data_dir) if data_dir else Path(
            os.path.expanduser("~/.yunxi/message_bus")
        )
        base_dir.mkdir(parents=True, exist_ok=True)

        self._db_path = str(base_dir / DEFAULT_DB_NAME)
        self._max_queue_size = max_queue_size
        self._max_retries = max_retries
        self._ack_timeout = ack_timeout

        self._db: aiosqlite.Connection | None = None
        self._subscribers: dict[str, list[Callable[[Message], Any]]] = {}
        self._stats = MessageBusStats()
        self._initialized = False
        self._send_loop_task: asyncio.Task[None] | None = None
        self._send_callback: Callable[[Message], bool] | None = None
        self._is_running = False
        self._queue_lock = asyncio.Lock()

        logger.info(
            "message_bus.init",
            db_path=self._db_path,
            max_queue_size=max_queue_size,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化消息总线.

        创建数据库表，启动发送循环。
        """
        if self._initialized:
            return

        await self._init_db()
        self._initialized = True
        self._is_running = True

        # 启动发送循环
        self._send_loop_task = asyncio.create_task(self._send_loop())

        logger.info("message_bus.initialized")

    async def shutdown(self) -> None:
        """关闭消息总线."""
        self._is_running = False

        if self._send_loop_task:
            self._send_loop_task.cancel()
            try:
                await self._send_loop_task
            except asyncio.CancelledError:
                pass
            self._send_loop_task = None

        if self._db:
            await self._db.close()
            self._db = None

        self._initialized = False
        logger.info("message_bus.shutdown")

    async def _init_db(self) -> None:
        """初始化数据库."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row

        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id      TEXT PRIMARY KEY,
                topic           TEXT DEFAULT 'default',
                direction       TEXT DEFAULT 'edge_to_cloud',
                payload_json    TEXT NOT NULL,
                priority        INTEGER DEFAULT 5,
                status          TEXT DEFAULT 'pending',
                device_id       TEXT DEFAULT '',
                correlation_id  TEXT DEFAULT '',
                created_at      REAL,
                sent_at         REAL,
                acked_at        REAL,
                expires_at      REAL,
                retry_count     INTEGER DEFAULT 0,
                last_error      TEXT DEFAULT '',
                headers_json    TEXT DEFAULT '{}'
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_status "
            "ON messages(status)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_topic "
            "ON messages(topic)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_priority "
            "ON messages(priority DESC)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_created "
            "ON messages(created_at)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_correlation "
            "ON messages(correlation_id)"
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # 发送回调注册
    # ------------------------------------------------------------------

    def register_send_callback(self, callback: Callable[[Message], bool]) -> None:
        """注册消息发送回调.

        Args:
            callback: 接收 Message，返回是否发送成功.
        """
        self._send_callback = callback
        logger.debug("message_bus.send_callback_registered")

    # ------------------------------------------------------------------
    # 发布/订阅
    # ------------------------------------------------------------------

    async def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        direction: MessageDirection = MessageDirection.EDGE_TO_CLOUD,
        priority: MessagePriority = MessagePriority.NORMAL,
        device_id: str = "",
        correlation_id: str = "",
        ttl_seconds: int = 3600,
        headers: dict[str, str] | None = None,
    ) -> str:
        """发布消息.

        Args:
            topic: 消息主题.
            payload: 消息负载.
            direction: 消息方向.
            priority: 优先级.
            device_id: 目标/源设备 ID.
            correlation_id: 关联消息 ID.
            ttl_seconds: 过期时间（秒）.
            headers: 自定义消息头.

        Returns:
            消息 ID.
        """
        assert self._db is not None

        msg = Message(
            topic=topic,
            direction=direction,
            payload=payload,
            priority=priority.value if isinstance(priority, MessagePriority) else priority,
            device_id=device_id,
            correlation_id=correlation_id,
            expires_at=time.time() + ttl_seconds if ttl_seconds > 0 else 0,
            headers=headers or {},
        )

        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        headers_json = json.dumps(msg.headers, ensure_ascii=False, default=str)

        await self._db.execute(
            """
            INSERT INTO messages
                (message_id, topic, direction, payload_json, priority, status,
                 device_id, correlation_id, created_at, expires_at, headers_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.message_id, topic, direction.value, payload_json,
                msg.priority, msg.status.value, device_id, correlation_id,
                msg.created_at, msg.expires_at, headers_json,
            ),
        )
        await self._db.commit()

        self._stats.pending_count += 1

        logger.debug(
            "message_bus.published",
            message_id=msg.message_id,
            topic=topic,
            priority=msg.priority,
        )

        return msg.message_id

    def subscribe(
        self,
        topic: str,
        callback: Callable[[Message], Any],
    ) -> None:
        """订阅主题.

        Args:
            topic: 主题名称.
            callback: 消息回调函数.
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)
        logger.debug("message_bus.subscribed", topic=topic)

    def unsubscribe(
        self,
        topic: str,
        callback: Callable[[Message], Any],
    ) -> bool:
        """取消订阅.

        Args:
            topic: 主题名称.
            callback: 要移除的回调函数.

        Returns:
            是否成功移除.
        """
        if topic not in self._subscribers:
            return False
        try:
            self._subscribers[topic].remove(callback)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # 消息确认
    # ------------------------------------------------------------------

    async def ack_message(self, message_id: str) -> bool:
        """确认消息已接收.

        Args:
            message_id: 消息 ID.

        Returns:
            是否成功.
        """
        assert self._db is not None

        now = time.time()
        await self._db.execute(
            """
            UPDATE messages
            SET status = 'acked', acked_at = ?
            WHERE message_id = ? AND status != 'acked'
            """,
            (now, message_id),
        )
        await self._db.commit()

        cursor = await self._db.execute(
            "SELECT changes() as cnt"
        )
        row = await cursor.fetchone()
        success = row["cnt"] > 0 if row else False

        if success:
            self._stats.total_acked += 1

        logger.debug(
            "message_bus.acked",
            message_id=message_id,
            success=success,
        )
        return success

    async def nack_message(
        self,
        message_id: str,
        reason: str = "",
        retry: bool = True,
    ) -> bool:
        """拒绝消息.

        Args:
            message_id: 消息 ID.
            reason: 拒绝原因.
            retry: 是否重试.

        Returns:
            是否成功.
        """
        assert self._db is not None

        now = time.time()

        if retry:
            await self._db.execute(
                """
                UPDATE messages
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    last_error = ?
                WHERE message_id = ?
                """,
                (reason, message_id),
            )
        else:
            await self._db.execute(
                """
                UPDATE messages
                SET status = 'failed',
                    last_error = ?
                WHERE message_id = ?
                """,
                (reason, message_id),
            )

        await self._db.commit()

        cursor = await self._db.execute(
            "SELECT changes() as cnt"
        )
        row = await cursor.fetchone()
        success = row["cnt"] > 0 if row else False

        if success and not retry:
            self._stats.total_failed += 1
        if success and retry:
            self._stats.retry_count += 1

        logger.debug(
            "message_bus.nacked",
            message_id=message_id,
            retry=retry,
            reason=reason,
        )
        return success

    # ------------------------------------------------------------------
    # 消息查询
    # ------------------------------------------------------------------

    async def get_message(self, message_id: str) -> Message | None:
        """获取消息详情.

        Args:
            message_id: 消息 ID.

        Returns:
            消息对象，不存在返回 None.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            "SELECT * FROM messages WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_message(row)

    async def list_messages(
        self,
        topic: str | None = None,
        status: MessageStatus | None = None,
        direction: MessageDirection | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Message]:
        """列出消息.

        Args:
            topic: 按主题过滤.
            status: 按状态过滤.
            direction: 按方向过滤.
            limit: 返回数量限制.
            offset: 偏移量.

        Returns:
            消息列表（按优先级降序 + 创建时间升序）.
        """
        assert self._db is not None

        conditions: list[str] = []
        params: list[Any] = []

        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if direction:
            conditions.append("direction = ?")
            params.append(direction.value)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT * FROM messages
            {where_clause}
            ORDER BY priority DESC, created_at ASC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def get_pending_messages(
        self,
        direction: MessageDirection = MessageDirection.EDGE_TO_CLOUD,
        limit: int = 100,
    ) -> list[Message]:
        """获取待发送消息.

        Args:
            direction: 消息方向.
            limit: 最大数量.

        Returns:
            待发送消息列表.
        """
        return await self.list_messages(
            status=MessageStatus.PENDING,
            direction=direction,
            limit=limit,
        )

    async def get_queue_size(self, status: MessageStatus | None = None) -> int:
        """获取队列大小.

        Args:
            status: 按状态过滤，None 返回总数.

        Returns:
            队列大小.
        """
        assert self._db is not None

        if status:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM messages WHERE status = ?",
                (status.value,),
            )
        else:
            cursor = await self._db.execute("SELECT COUNT(*) FROM messages")

        row = await cursor.fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # 请求/响应模式
    # ------------------------------------------------------------------

    async def request(
        self,
        topic: str,
        payload: dict[str, Any],
        device_id: str = "",
        timeout_seconds: int = 30,
    ) -> Message | None:
        """发送请求并等待响应.

        Args:
            topic: 请求主题.
            payload: 请求负载.
            device_id: 目标设备 ID.
            timeout_seconds: 超时时间（秒）.

        Returns:
            响应消息，超时返回 None.
        """
        request_id = await self.publish(
            topic=topic,
            payload=payload,
            device_id=device_id,
            ttl_seconds=timeout_seconds,
        )

        # 轮询等待响应
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            responses = await self.list_messages(
                topic=topic,
                status=MessageStatus.ACKED,
                limit=1,
            )
            for resp in responses:
                if resp.correlation_id == request_id:
                    return resp
            await asyncio.sleep(0.1)

        logger.warning(
            "message_bus.request_timeout",
            request_id=request_id,
            timeout=timeout_seconds,
        )
        return None

    # ------------------------------------------------------------------
    # 发送循环
    # ------------------------------------------------------------------

    async def _send_loop(self) -> None:
        """后台发送循环.

        周期性地从队列中取出待发送消息，调用发送回调。
        """
        while self._is_running:
            try:
                await asyncio.sleep(0.5)  # 每 500ms 检查一次

                if not self._send_callback:
                    continue

                # 获取待发送消息
                pending = await self.get_pending_messages(limit=10)
                if not pending:
                    continue

                for msg in pending:
                    # 检查过期
                    if msg.is_expired:
                        await self._mark_expired(msg.message_id)
                        continue

                    # 检查重试次数
                    if msg.retry_count >= self._max_retries:
                        await self._mark_failed(
                            msg.message_id,
                            "Max retries exceeded",
                        )
                        continue

                    # 发送消息
                    await self._send_message(msg)

                # 更新统计
                await self._update_stats()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("message_bus.send_loop_error")

    async def _send_message(self, msg: Message) -> None:
        """发送单条消息."""
        assert self._db is not None

        # 标记为发送中
        await self._db.execute(
            """
            UPDATE messages
            SET status = 'sending', sent_at = ?
            WHERE message_id = ?
            """,
            (time.time(), msg.message_id),
        )
        await self._db.commit()

        msg.status = MessageStatus.SENDING

        try:
            if self._send_callback:
                success = self._send_callback(msg)
                if asyncio.iscoroutine(success):
                    success = await success
            else:
                success = True  # 无回调时视为成功（模拟）

            if success:
                await self._db.execute(
                    "UPDATE messages SET status = 'sent' WHERE message_id = ?",
                    (msg.message_id,),
                )
                await self._db.commit()
                self._stats.total_sent += 1
                msg.status = MessageStatus.SENT

                # 通知订阅者
                await self._notify_subscribers(msg)
            else:
                raise Exception("Send callback returned False")

        except Exception as e:
            await self._db.execute(
                """
                UPDATE messages
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    last_error = ?
                WHERE message_id = ?
                """,
                (str(e), msg.message_id),
            )
            await self._db.commit()
            self._stats.retry_count += 1
            msg.status = MessageStatus.PENDING
            logger.warning(
                "message_bus.send_failed",
                message_id=msg.message_id,
                error=str(e),
                retry=msg.retry_count,
            )

    async def _notify_subscribers(self, msg: Message) -> None:
        """通知主题订阅者."""
        callbacks = self._subscribers.get(msg.topic, [])
        for callback in callbacks:
            try:
                result = callback(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "message_bus.subscriber_error",
                    topic=msg.topic,
                )

    async def _mark_expired(self, message_id: str) -> None:
        """标记消息为已过期."""
        assert self._db is not None
        await self._db.execute(
            "UPDATE messages SET status = 'expired' WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()
        self._stats.total_expired += 1
        logger.debug("message_bus.expired", message_id=message_id)

    async def _mark_failed(self, message_id: str, reason: str) -> None:
        """标记消息为失败."""
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE messages
            SET status = 'failed', last_error = ?
            WHERE message_id = ?
            """,
            (reason, message_id),
        )
        await self._db.commit()
        self._stats.total_failed += 1
        logger.warning(
            "message_bus.failed",
            message_id=message_id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # 清理与维护
    # ------------------------------------------------------------------

    async def cleanup(self, max_age_days: int = 7) -> int:
        """清理历史消息.

        Args:
            max_age_days: 最大保留天数.

        Returns:
            清理的消息数.
        """
        assert self._db is not None

        cutoff = time.time() - max_age_days * 24 * 3600

        cursor = await self._db.execute(
            "DELETE FROM messages WHERE created_at < ? AND status IN ('acked', 'failed', 'expired')",
            (cutoff,),
        )
        await self._db.commit()

        count = cursor.rowcount
        if count:
            logger.info("message_bus.cleanup", count=count)
        return count

    async def _update_stats(self) -> None:
        """更新统计信息."""
        pending = await self.get_queue_size(MessageStatus.PENDING)
        in_flight = await self.get_queue_size(MessageStatus.SENDING)
        self._stats.pending_count = pending
        self._stats.in_flight_count = in_flight

    def get_stats(self) -> MessageBusStats:
        """获取统计信息."""
        return self._stats

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_message(row: Any) -> Message:
        """将数据库行转换为 Message 对象."""
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            payload = {}

        try:
            headers = json.loads(row["headers_json"])
        except (json.JSONDecodeError, TypeError):
            headers = {}

        return Message(
            message_id=row["message_id"],
            topic=row["topic"],
            direction=MessageDirection(row["direction"]),
            payload=payload,
            priority=row["priority"],
            status=MessageStatus(row["status"]),
            device_id=row["device_id"],
            correlation_id=row["correlation_id"],
            created_at=row["created_at"],
            sent_at=row["sent_at"] or 0.0,
            acked_at=row["acked_at"] or 0.0,
            expires_at=row["expires_at"] or 0.0,
            retry_count=row["retry_count"],
            last_error=row["last_error"] or "",
            headers=headers,
        )
