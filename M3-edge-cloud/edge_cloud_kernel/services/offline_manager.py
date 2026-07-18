"""离线数据管理器.

提供离线数据缓存、离线操作队列、在线检测与自动同步、
离线模式切换、数据过期清理等功能。

基于 SQLite 本地存储，与现有 OfflineShadowProxy 协同工作，
但提供更丰富的离线管理能力，包括：
- 多类型离线数据缓存（不只是同步操作队列）
- 在线状态检测与自动切换
- 离线操作优先级队列
- 数据过期策略与清理
- 离线模式统计与指标
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_CACHE_DB_NAME = "offline_cache.db"
DEFAULT_QUEUE_DB_NAME = "offline_queue.db"
DEFAULT_MAX_CACHE_SIZE = 100 * 1024 * 1024  # 100 MB
DEFAULT_CACHE_TTL = 7 * 24 * 3600  # 7 天
DEFAULT_HEARTBEAT_INTERVAL = 30.0  # 30 秒
MAX_BATCH_FLUSH_SIZE = 100


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class OfflineStatus(str, Enum):
    """离线状态枚举.

    Attributes:
        ONLINE: 在线模式.
        OFFLINE: 离线模式.
        RECONNECTING: 重连中.
        FLUSHING: 正在刷新离线队列.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    RECONNECTING = "reconnecting"
    FLUSHING = "flushing"


class CachePriority(str, Enum):
    """缓存优先级枚举.

    Attributes:
        CRITICAL: 关键数据（永不自动清理）.
        HIGH: 高优先级.
        NORMAL: 普通优先级.
        LOW: 低优先级（优先清理）.
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class OfflineQueueEntry:
    """离线队列条目.

    Attributes:
        id: 队列记录 ID.
        operation: 操作类型.
        entity_type: 实体类型.
        entity_id: 实体 ID.
        payload: 操作负载.
        priority: 优先级（0-10，越高越优先）.
        status: 状态（pending / processing / failed / done）.
        queued_at: 入队时间.
        retry_count: 重试次数.
        last_error: 上次错误信息.
    """

    id: int = 0
    operation: str = ""
    entity_type: str = ""
    entity_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    status: str = "pending"
    queued_at: float = 0.0
    retry_count: int = 0
    last_error: str = ""


@dataclass
class OfflineCacheEntry:
    """离线缓存条目.

    Attributes:
        cache_key: 缓存键.
        category: 数据分类.
        value: 缓存值.
        priority: 优先级.
        size_bytes: 数据大小（字节）.
        created_at: 创建时间.
        expires_at: 过期时间.
        last_accessed: 最后访问时间.
        access_count: 访问次数.
    """

    cache_key: str = ""
    category: str = "default"
    value: Any = None
    priority: CachePriority = CachePriority.NORMAL
    size_bytes: int = 0
    created_at: float = 0.0
    expires_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0


@dataclass
class OfflineMetrics:
    """离线管理指标.

    Attributes:
        total_queued: 总入队操作数.
        total_flushed: 总刷新成功数.
        total_failed: 总失败数.
        cache_hits: 缓存命中数.
        cache_misses: 缓存未命中数.
        offline_duration: 累计离线时长（秒）.
        current_queue_size: 当前队列大小.
        current_cache_size: 当前缓存大小（字节）.
    """

    total_queued: int = 0
    total_flushed: int = 0
    total_failed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    offline_duration: float = 0.0
    current_queue_size: int = 0
    current_cache_size: int = 0


# ---------------------------------------------------------------------------
# OfflineManager
# ---------------------------------------------------------------------------


class OfflineManager:
    """离线数据管理器.

    提供完整的离线数据管理能力：
    - 离线数据缓存（SQLite 持久化）
    - 离线操作队列（优先级队列）
    - 在线检测与自动同步
    - 离线模式切换
    - 数据过期清理

    向后兼容：不修改现有 OfflineShadowProxy，作为增强层叠加使用。

    Attributes:
        _cache_db_path: 缓存数据库路径.
        _queue_db_path: 队列数据库路径.
        _status: 当前离线状态.
        _max_cache_size: 最大缓存大小（字节）.
        _default_cache_ttl: 默认缓存 TTL（秒）.
        _heartbeat_interval: 心跳检测间隔（秒）.
        _metrics: 离线管理指标.
    """

    def __init__(
        self,
        data_dir: str | None = None,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
        default_cache_ttl: int = DEFAULT_CACHE_TTL,
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        """初始化离线管理器.

        Args:
            data_dir: 数据目录路径，默认 ~/.yunxi/cache/.
            max_cache_size: 最大缓存大小（字节）.
            default_cache_ttl: 默认缓存过期时间（秒）.
            heartbeat_interval: 心跳检测间隔（秒）.
        """
        base_dir = Path(data_dir) if data_dir else Path(
            os.path.expanduser("~/.yunxi/cache")
        )
        base_dir.mkdir(parents=True, exist_ok=True)

        self._cache_db_path = str(base_dir / DEFAULT_CACHE_DB_NAME)
        self._queue_db_path = str(base_dir / DEFAULT_QUEUE_DB_NAME)
        self._max_cache_size = max_cache_size
        self._default_cache_ttl = default_cache_ttl
        self._heartbeat_interval = heartbeat_interval

        self._status = OfflineStatus.ONLINE
        self._cache_db: aiosqlite.Connection | None = None
        self._queue_db: aiosqlite.Connection | None = None
        self._metrics = OfflineMetrics()
        self._initialized = False
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._status_callbacks: list[Any] = []
        self._last_online_at = time.time()
        self._offline_start_at: float | None = None

        # 在线检测回调（返回 True 表示在线）
        self._connectivity_check: Any = None

        # 刷新回调（处理离线队列中的操作）
        self._flush_callback: Any = None

        logger.info(
            "offline_manager.init",
            cache_db=self._cache_db_path,
            queue_db=self._queue_db_path,
            max_cache_size=max_cache_size,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化离线管理器.

        创建数据库表、启动心跳检测。
        """
        if self._initialized:
            return

        await self._init_cache_db()
        await self._init_queue_db()
        self._initialized = True

        # 启动心跳检测
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("offline_manager.initialized")

    async def shutdown(self) -> None:
        """关闭离线管理器."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._cache_db:
            await self._cache_db.close()
            self._cache_db = None

        if self._queue_db:
            await self._queue_db.close()
            self._queue_db = None

        self._initialized = False
        logger.info("offline_manager.shutdown")

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------

    async def _init_cache_db(self) -> None:
        """初始化缓存数据库."""
        self._cache_db = await aiosqlite.connect(self._cache_db_path)
        self._cache_db.row_factory = aiosqlite.Row

        await self._cache_db.execute(
            """
            CREATE TABLE IF NOT EXISTS offline_cache (
                cache_key      TEXT PRIMARY KEY,
                category       TEXT DEFAULT 'default',
                value_json     TEXT NOT NULL,
                priority       TEXT DEFAULT 'normal',
                size_bytes     INTEGER DEFAULT 0,
                created_at     REAL,
                expires_at     REAL,
                last_accessed  REAL,
                access_count   INTEGER DEFAULT 0
            )
            """
        )
        await self._cache_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_category "
            "ON offline_cache(category)"
        )
        await self._cache_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expires "
            "ON offline_cache(expires_at)"
        )
        await self._cache_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_priority "
            "ON offline_cache(priority)"
        )
        await self._cache_db.commit()

    async def _init_queue_db(self) -> None:
        """初始化队列数据库."""
        self._queue_db = await aiosqlite.connect(self._queue_db_path)
        self._queue_db.row_factory = aiosqlite.Row

        await self._queue_db.execute(
            """
            CREATE TABLE IF NOT EXISTS offline_ops_queue (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                operation     TEXT NOT NULL,
                entity_type   TEXT DEFAULT '',
                entity_id     TEXT DEFAULT '',
                payload_json  TEXT NOT NULL,
                priority      INTEGER DEFAULT 5,
                status        TEXT DEFAULT 'pending',
                queued_at     REAL,
                retry_count   INTEGER DEFAULT 0,
                last_error    TEXT DEFAULT ''
            )
            """
        )
        await self._queue_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_queue_status "
            "ON offline_ops_queue(status)"
        )
        await self._queue_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_queue_priority "
            "ON offline_ops_queue(priority DESC)"
        )
        await self._queue_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_queue_entity "
            "ON offline_ops_queue(entity_type, entity_id)"
        )
        await self._queue_db.commit()

    # ------------------------------------------------------------------
    # 回调注册
    # ------------------------------------------------------------------

    def register_connectivity_check(self, callback: Any) -> None:
        """注册连通性检测回调.

        Args:
            callback: 异步函数，返回 bool 表示是否在线.
        """
        self._connectivity_check = callback

    def register_flush_callback(self, callback: Any) -> None:
        """注册队列刷新回调.

        Args:
            callback: 异步函数，接收操作列表，返回成功列表.
        """
        self._flush_callback = callback

    def register_status_callback(self, callback: Any) -> None:
        """注册状态变更回调.

        Args:
            callback: 接收 OfflineStatus 参数的回调函数.
        """
        self._status_callbacks.append(callback)

    # ------------------------------------------------------------------
    # 在线状态管理
    # ------------------------------------------------------------------

    @property
    def status(self) -> OfflineStatus:
        """当前离线状态."""
        return self._status

    @property
    def is_online(self) -> bool:
        """是否在线."""
        return self._status == OfflineStatus.ONLINE

    @property
    def is_offline(self) -> bool:
        """是否离线."""
        return self._status in (OfflineStatus.OFFLINE, OfflineStatus.RECONNECTING)

    async def set_offline_mode(self) -> None:
        """手动切换到离线模式."""
        await self._transition_status(OfflineStatus.OFFLINE)

    async def set_online_mode(self) -> None:
        """手动切换到在线模式并刷新队列."""
        await self._transition_status(OfflineStatus.ONLINE)
        # 自动刷新离线队列
        asyncio.create_task(self.flush_queue())

    async def check_connectivity(self) -> bool:
        """检查网络连通性.

        Returns:
            True 表示在线.
        """
        if self._connectivity_check:
            try:
                result = self._connectivity_check()
                if asyncio.iscoroutine(result):
                    result = await result
                return bool(result)
            except Exception as e:
                logger.debug("offline_manager.connectivity_check_failed", error=str(e))
                return False
        # 没有检测回调时，默认视为在线
        return True

    async def _transition_status(self, new_status: OfflineStatus) -> None:
        """切换状态并通知回调."""
        if new_status == self._status:
            return

        old_status = self._status
        self._status = new_status

        # 统计离线时长
        if old_status == OfflineStatus.OFFLINE and new_status == OfflineStatus.ONLINE:
            if self._offline_start_at:
                self._metrics.offline_duration += time.time() - self._offline_start_at
                self._offline_start_at = None
            self._last_online_at = time.time()

        if old_status == OfflineStatus.ONLINE and new_status == OfflineStatus.OFFLINE:
            self._offline_start_at = time.time()

        logger.info(
            "offline_manager.status_changed",
            old=old_status.value,
            new=new_status.value,
        )

        # 通知回调
        for callback in self._status_callbacks:
            try:
                result = callback(new_status)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("offline_manager.status_callback_error")

    async def _heartbeat_loop(self) -> None:
        """心跳检测循环."""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                is_online = await self.check_connectivity()

                if is_online and self._status == OfflineStatus.OFFLINE:
                    await self._transition_status(OfflineStatus.RECONNECTING)
                    try:
                        await self.flush_queue()
                        await self._transition_status(OfflineStatus.ONLINE)
                    except Exception:
                        logger.exception("offline_manager.reconnect_flush_failed")
                        await self._transition_status(OfflineStatus.OFFLINE)

                elif not is_online and self._status == OfflineStatus.ONLINE:
                    await self._transition_status(OfflineStatus.OFFLINE)

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("offline_manager.heartbeat_error")

    # ------------------------------------------------------------------
    # 离线数据缓存
    # ------------------------------------------------------------------

    async def cache_set(
        self,
        key: str,
        value: Any,
        category: str = "default",
        priority: CachePriority = CachePriority.NORMAL,
        ttl_seconds: int | None = None,
    ) -> None:
        """设置缓存项.

        Args:
            key: 缓存键.
            value: 缓存值（可 JSON 序列化）.
            category: 数据分类.
            priority: 缓存优先级.
            ttl_seconds: 过期时间（秒），None 使用默认 TTL.
        """
        assert self._cache_db is not None

        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self._default_cache_ttl
        expires_at = now + ttl
        value_json = json.dumps(value, ensure_ascii=False, default=str)
        size_bytes = len(value_json.encode("utf-8"))

        await self._cache_db.execute(
            """
            INSERT INTO offline_cache
                (cache_key, category, value_json, priority, size_bytes,
                 created_at, expires_at, last_accessed, access_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(cache_key) DO UPDATE SET
                category = excluded.category,
                value_json = excluded.value_json,
                priority = excluded.priority,
                size_bytes = excluded.size_bytes,
                expires_at = excluded.expires_at,
                last_accessed = excluded.last_accessed
            """,
            (
                key, category, value_json, priority.value, size_bytes,
                now, expires_at, now,
            ),
        )
        await self._cache_db.commit()
        self._metrics.current_cache_size = await self._get_total_cache_size()

        # 如果超出缓存上限，触发清理
        if self._metrics.current_cache_size > self._max_cache_size:
            asyncio.create_task(self._evict_cache())

        logger.debug("offline_manager.cache_set", key=key, size=size_bytes)

    async def cache_get(self, key: str) -> Any | None:
        """获取缓存项.

        Args:
            key: 缓存键.

        Returns:
            缓存值，不存在或已过期返回 None.
        """
        assert self._cache_db is not None

        now = time.time()
        cursor = await self._cache_db.execute(
            "SELECT * FROM offline_cache WHERE cache_key = ? AND expires_at > ?",
            (key, now),
        )
        row = await cursor.fetchone()

        if row is None:
            self._metrics.cache_misses += 1
            return None

        # 更新访问统计
        await self._cache_db.execute(
            "UPDATE offline_cache SET last_accessed = ?, access_count = access_count + 1 "
            "WHERE cache_key = ?",
            (now, key),
        )
        await self._cache_db.commit()

        self._metrics.cache_hits += 1
        return json.loads(row["value_json"])

    async def cache_delete(self, key: str) -> bool:
        """删除缓存项.

        Args:
            key: 缓存键.

        Returns:
            是否删除成功.
        """
        assert self._cache_db is not None

        cursor = await self._cache_db.execute(
            "DELETE FROM offline_cache WHERE cache_key = ?", (key,)
        )
        await self._cache_db.commit()

        deleted = cursor.rowcount > 0
        if deleted:
            self._metrics.current_cache_size = await self._get_total_cache_size()
        return deleted

    async def cache_clear(self, category: str | None = None) -> int:
        """清空缓存.

        Args:
            category: 指定分类，None 清空全部.

        Returns:
            删除的条目数.
        """
        assert self._cache_db is not None

        if category:
            cursor = await self._cache_db.execute(
                "DELETE FROM offline_cache WHERE category = ?", (category,)
            )
        else:
            cursor = await self._cache_db.execute("DELETE FROM offline_cache")

        await self._cache_db.commit()
        count = cursor.rowcount
        self._metrics.current_cache_size = await self._get_total_cache_size()
        logger.info("offline_manager.cache_cleared", count=count, category=category)
        return count

    async def cache_list(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[OfflineCacheEntry]:
        """列出缓存条目.

        Args:
            category: 按分类过滤.
            limit: 最大返回数.

        Returns:
            缓存条目列表.
        """
        assert self._cache_db is not None

        if category:
            cursor = await self._cache_db.execute(
                "SELECT * FROM offline_cache WHERE category = ? "
                "ORDER BY last_accessed DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor = await self._cache_db.execute(
                "SELECT * FROM offline_cache "
                "ORDER BY last_accessed DESC LIMIT ?",
                (limit,),
            )

        rows = await cursor.fetchall()
        return [self._row_to_cache_entry(row) for row in rows]

    async def _get_total_cache_size(self) -> int:
        """获取缓存总大小."""
        assert self._cache_db is not None
        cursor = await self._cache_db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM offline_cache"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _evict_cache(self) -> int:
        """缓存驱逐：清理低优先级和最久未访问的条目.

        Returns:
            驱逐的条目数.
        """
        assert self._cache_db is not None

        evicted = 0
        # 先清理过期的
        now = time.time()
        cursor = await self._cache_db.execute(
            "DELETE FROM offline_cache WHERE expires_at <= ?", (now,)
        )
        evicted += cursor.rowcount

        # 如果还不够，按优先级 + LRU 清理
        current_size = await self._get_total_cache_size()
        if current_size > self._max_cache_size:
            # 删除 low 优先级的最久未访问条目
            cursor = await self._cache_db.execute(
                "DELETE FROM offline_cache WHERE priority = 'low' "
                "ORDER BY last_accessed ASC LIMIT 100"
            )
            evicted += cursor.rowcount

        await self._cache_db.commit()
        self._metrics.current_cache_size = await self._get_total_cache_size()

        if evicted:
            logger.info("offline_manager.cache_evicted", count=evicted)
        return evicted

    @staticmethod
    def _row_to_cache_entry(row: Any) -> OfflineCacheEntry:
        """将数据库行转换为缓存条目."""
        return OfflineCacheEntry(
            cache_key=row["cache_key"],
            category=row["category"],
            value=json.loads(row["value_json"]),
            priority=CachePriority(row["priority"]),
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
        )

    # ------------------------------------------------------------------
    # 离线操作队列
    # ------------------------------------------------------------------

    async def enqueue_operation(
        self,
        operation: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        priority: int = 5,
    ) -> int:
        """将操作加入离线队列.

        Args:
            operation: 操作类型（CREATE / UPDATE / DELETE 等）.
            entity_type: 实体类型.
            entity_id: 实体 ID.
            payload: 操作负载.
            priority: 优先级（0-10，越高越优先）.

        Returns:
            队列条目 ID.
        """
        assert self._queue_db is not None

        now = time.time()
        priority = max(0, min(10, priority))
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)

        cursor = await self._queue_db.execute(
            """
            INSERT INTO offline_ops_queue
                (operation, entity_type, entity_id, payload_json,
                 priority, status, queued_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (operation, entity_type, entity_id, payload_json, priority, now),
        )
        await self._queue_db.commit()

        queue_id = cursor.lastrowid or 0
        self._metrics.total_queued += 1
        self._metrics.current_queue_size = await self._get_queue_size()

        logger.debug(
            "offline_manager.enqueued",
            queue_id=queue_id,
            operation=operation,
            entity_id=entity_id,
            priority=priority,
        )
        return queue_id

    async def get_queue_size(self, status: str = "pending") -> int:
        """获取队列大小.

        Args:
            status: 按状态过滤.

        Returns:
            队列条目数.
        """
        return await self._get_queue_size(status)

    async def _get_queue_size(self, status: str = "pending") -> int:
        """内部实现：获取队列大小."""
        assert self._queue_db is not None
        cursor = await self._queue_db.execute(
            "SELECT COUNT(*) FROM offline_ops_queue WHERE status = ?",
            (status,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_queue_items(
        self,
        status: str = "pending",
        limit: int = 50,
        entity_type: str | None = None,
    ) -> list[OfflineQueueEntry]:
        """获取队列条目.

        Args:
            status: 状态过滤.
            limit: 最大返回数.
            entity_type: 实体类型过滤.

        Returns:
            队列条目列表（按优先级降序 + 入队时间升序）.
        """
        assert self._queue_db is not None

        if entity_type:
            cursor = await self._queue_db.execute(
                "SELECT * FROM offline_ops_queue WHERE status = ? AND entity_type = ? "
                "ORDER BY priority DESC, queued_at ASC LIMIT ?",
                (status, entity_type, limit),
            )
        else:
            cursor = await self._queue_db.execute(
                "SELECT * FROM offline_ops_queue WHERE status = ? "
                "ORDER BY priority DESC, queued_at ASC LIMIT ?",
                (status, limit),
            )

        rows = await cursor.fetchall()
        return [self._row_to_queue_entry(row) for row in rows]

    async def flush_queue(self, max_items: int = MAX_BATCH_FLUSH_SIZE) -> dict[str, int]:
        """刷新离线队列（将队列中的操作发送出去）.

        Args:
            max_items: 最大刷新条目数.

        Returns:
            刷新统计 {success, failed, remaining}.
        """
        assert self._queue_db is not None

        if self._status != OfflineStatus.ONLINE and self._status != OfflineStatus.FLUSHING:
            # 非在线模式不刷新
            return {"success": 0, "failed": 0, "remaining": await self._get_queue_size()}

        await self._transition_status(OfflineStatus.FLUSHING)

        try:
            # 获取待处理条目
            items = await self.get_queue_items(status="pending", limit=max_items)
            if not items:
                await self._transition_status(OfflineStatus.ONLINE)
                return {"success": 0, "failed": 0, "remaining": 0}

            success_count = 0
            failed_count = 0

            if self._flush_callback:
                # 使用回调处理
                try:
                    payloads = [
                        {
                            "id": item.id,
                            "operation": item.operation,
                            "entity_type": item.entity_type,
                            "entity_id": item.entity_id,
                            "payload": item.payload,
                        }
                        for item in items
                    ]
                    result = self._flush_callback(payloads)
                    if asyncio.iscoroutine(result):
                        result = await result

                    successful_ids = result if isinstance(result, list) else result.get("success", [])

                    for item in items:
                        if item.id in successful_ids or str(item.id) in successful_ids:
                            await self._mark_done(item.id)
                            success_count += 1
                        else:
                            await self._mark_failed(item.id, "flush_callback_failed")
                            failed_count += 1
                except Exception as e:
                    logger.exception("offline_manager.flush_callback_error")
                    for item in items:
                        await self._mark_failed(item.id, str(e))
                    failed_count = len(items)
            else:
                # 无回调时视为全部成功（模拟模式）
                for item in items:
                    await self._mark_done(item.id)
                    success_count += 1

            self._metrics.total_flushed += success_count
            self._metrics.total_failed += failed_count
            self._metrics.current_queue_size = await self._get_queue_size()

            remaining = self._metrics.current_queue_size

            logger.info(
                "offline_manager.queue_flushed",
                success=success_count,
                failed=failed_count,
                remaining=remaining,
            )

            await self._transition_status(OfflineStatus.ONLINE)
            return {
                "success": success_count,
                "failed": failed_count,
                "remaining": remaining,
            }

        except Exception as e:
            logger.exception("offline_manager.flush_error")
            await self._transition_status(OfflineStatus.ONLINE)
            raise e

    async def _mark_done(self, queue_id: int) -> None:
        """标记队列条目为已完成."""
        assert self._queue_db is not None
        await self._queue_db.execute(
            "DELETE FROM offline_ops_queue WHERE id = ?", (queue_id,)
        )
        await self._queue_db.commit()

    async def _mark_failed(self, queue_id: int, error: str) -> None:
        """标记队列条目为失败并递增重试计数."""
        assert self._queue_db is not None
        await self._queue_db.execute(
            """
            UPDATE offline_ops_queue
            SET status = 'pending',
                retry_count = retry_count + 1,
                last_error = ?
            WHERE id = ?
            """,
            (error, queue_id),
        )
        await self._queue_db.commit()

    async def purge_failed(self, max_retries: int = 5) -> int:
        """清理超过最大重试次数的失败条目.

        Args:
            max_retries: 最大重试次数.

        Returns:
            清理的条目数.
        """
        assert self._queue_db is not None

        cursor = await self._queue_db.execute(
            "DELETE FROM offline_ops_queue WHERE retry_count >= ?",
            (max_retries,),
        )
        await self._queue_db.commit()

        count = cursor.rowcount
        if count:
            logger.info("offline_manager.purged_failed", count=count)
        self._metrics.current_queue_size = await self._get_queue_size()
        return count

    @staticmethod
    def _row_to_queue_entry(row: Any) -> OfflineQueueEntry:
        """将数据库行转换为队列条目."""
        return OfflineQueueEntry(
            id=row["id"],
            operation=row["operation"],
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            payload=json.loads(row["payload_json"]),
            priority=row["priority"],
            status=row["status"],
            queued_at=row["queued_at"],
            retry_count=row["retry_count"],
            last_error=row["last_error"],
        )

    # ------------------------------------------------------------------
    # 过期清理
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> dict[str, int]:
        """清理所有过期数据.

        Returns:
            清理统计 {cache_expired, queue_failed, freed_bytes}.
        """
        cache_count = 0
        freed_bytes = 0

        # 清理过期缓存
        if self._cache_db:
            now = time.time()
            # 先计算将被清理的大小
            cursor = await self._cache_db.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM offline_cache "
                "WHERE expires_at <= ? AND priority != 'critical'",
                (now,),
            )
            row = await cursor.fetchone()
            freed_bytes = row[0] if row else 0

            cursor = await self._cache_db.execute(
                "DELETE FROM offline_cache WHERE expires_at <= ? AND priority != 'critical'",
                (now,),
            )
            cache_count = cursor.rowcount
            await self._cache_db.commit()

        # 清理超限重试的队列条目
        queue_count = await self.purge_failed(max_retries=5)

        self._metrics.current_cache_size = await self._get_total_cache_size()

        logger.info(
            "offline_manager.cleanup_done",
            cache_expired=cache_count,
            queue_failed=queue_count,
            freed_bytes=freed_bytes,
        )
        return {
            "cache_expired": cache_count,
            "queue_failed": queue_count,
            "freed_bytes": freed_bytes,
        }

    # ------------------------------------------------------------------
    # 指标获取
    # ------------------------------------------------------------------

    async def get_metrics(self) -> OfflineMetrics:
        """获取离线管理指标.

        Returns:
            离线指标对象.
        """
        if self._queue_db:
            self._metrics.current_queue_size = await self._get_queue_size()
        if self._cache_db:
            self._metrics.current_cache_size = await self._get_total_cache_size()
        return self._metrics

    async def get_cache_hit_rate(self) -> float:
        """获取缓存命中率.

        Returns:
            命中率（0.0 - 1.0）.
        """
        total = self._metrics.cache_hits + self._metrics.cache_misses
        if total == 0:
            return 0.0
        return self._metrics.cache_hits / total
