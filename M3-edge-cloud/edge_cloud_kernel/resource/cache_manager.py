"""缓存管理器.

LRU + TTL 混合缓存管理。
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Generic, TypeVar

import structlog

logger = structlog.get_logger(__name__)

V = TypeVar("V")


class CacheEntry(Generic[V]):
    """缓存条目.

    Attributes:
        key: 缓存键.
        value: 缓存值.
        created_at: 创建时间戳.
        expires_at: 过期时间戳.
        access_count: 访问次数.
    """

    __slots__ = ("key", "value", "created_at", "expires_at", "access_count")

    def __init__(
        self,
        key: str,
        value: V,
        ttl_s: float | None = None,
    ) -> None:
        """初始化 CacheEntry.

        Args:
            key: 缓存键.
            value: 缓存值.
            ttl_s: 生存时间（秒），None 表示永不过期.
        """
        self.key = key
        self.value = value
        self.created_at = time.time()
        self.expires_at = (
            self.created_at + ttl_s if ttl_s is not None else float("inf")
        )
        self.access_count = 0

    @property
    def is_expired(self) -> bool:
        """是否已过期.

        Returns:
            True 表示已过期.
        """
        return time.time() > self.expires_at


class CacheManager:
    """LRU + TTL 混合缓存管理器.

    基于双向链表（OrderedDict）实现 LRU 淘汰策略，
    结合 TTL 机制实现过期清理。
    使用 asyncio.Lock 保护关键操作，保证并发安全。

    Attributes:
        _max_size: 最大缓存条目数.
        _default_ttl_s: 默认 TTL（秒），None 表示永不过期.
        _store: 缓存存储（OrderedDict 实现LRU）.
        _cleanup_interval_s: 过期清理间隔（秒）.
        _running: 是否正在运行.
        _lock: asyncio.Lock 并发保护锁.
        _total_hits: 缓存命中总次数.
        _total_misses: 缓存未命中总次数.
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl_s: float | None = 300.0,
        cleanup_interval_s: float = 60.0,
    ) -> None:
        """初始化 CacheManager.

        Args:
            max_size: 最大缓存条目数.
            default_ttl_s: 默认 TTL（秒）.
            cleanup_interval_s: 过期清理间隔（秒）.
        """
        self._max_size = max_size
        self._default_ttl_s = default_ttl_s
        self._cleanup_interval_s = cleanup_interval_s
        self._store: OrderedDict[str, CacheEntry[Any]] = OrderedDict()
        self._running = False
        self._cleanup_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._total_hits: int = 0
        self._total_misses: int = 0
        logger.info(
            "cache_manager.init",
            max_size=max_size,
            default_ttl=default_ttl_s,
        )

    async def start(self) -> None:
        """启动定时清理任务."""
        if self._running:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("cache_manager.started")

    async def stop(self) -> None:
        """停止定时清理任务."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("cache_manager.stopped")

    async def get(self, key: str) -> Any | None:
        """获取缓存值（并发安全）.

        Args:
            key: 缓存键.

        Returns:
            缓存值，如果不存在或已过期则返回 None.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._total_misses += 1
                return None

            if entry.is_expired:
                del self._store[key]
                self._total_misses += 1
                return None

            # LRU: 移动到末尾（最近访问）
            self._store.move_to_end(key)
            entry.access_count += 1
            self._total_hits += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl_s: float | None = None,
    ) -> None:
        """设置缓存值（并发安全）.

        Args:
            key: 缓存键.
            value: 缓存值.
            ttl_s: 生存时间（秒），None 使用默认 TTL.
        """
        async with self._lock:
            if key in self._store:
                del self._store[key]
            elif len(self._store) >= self._max_size:
                # 淘汰最久未使用的条目
                self._store.popitem(last=False)

            ttl = ttl_s if ttl_s is not None else self._default_ttl_s
            self._store[key] = CacheEntry(key=key, value=value, ttl_s=ttl)
        logger.debug("cache_manager.set", key=key, ttl=ttl)

    async def delete(self, key: str) -> bool:
        """删除缓存条目（并发安全）.

        Args:
            key: 缓存键.

        Returns:
            是否成功删除.
        """
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear(self) -> int:
        """清空所有缓存（并发安全）.

        Returns:
            清除的条目数.
        """
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    async def has(self, key: str) -> bool:
        """检查缓存键是否存在且未过期（并发安全）.

        Args:
            key: 缓存键.

        Returns:
            是否存在.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            if entry.is_expired:
                del self._store[key]
                return False
            return True

    async def _cleanup_loop(self) -> None:
        """定时过期清理循环."""
        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval_s)
                self._evict_expired()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("cache_manager.cleanup_error")

    def _evict_expired(self) -> int:
        """清理所有过期条目.

        注意：此方法由 _cleanup_loop 调用，在清理循环内部运行，
        无需额外加锁（清理循环是单线程定时任务）。

        Returns:
            清理的条目数.
        """
        expired_keys: list[str] = [
            key for key, entry in self._store.items() if entry.is_expired
        ]
        for key in expired_keys:
            del self._store[key]
        if expired_keys:
            logger.debug("cache_manager.evicted", count=len(expired_keys))
        return len(expired_keys)

    @property
    def size(self) -> int:
        """当前缓存条目数.

        Returns:
            缓存条目数量.
        """
        return len(self._store)

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息.

        Returns:
            包含大小、命中率、hit_rate等信息的字典.
        """
        total_access = sum(e.access_count for e in self._store.values())
        total_requests = self._total_hits + self._total_misses
        hit_rate = self._total_hits / total_requests if total_requests > 0 else 0.0
        return {
            "size": len(self._store),
            "max_size": self._max_size,
            "total_access": total_access,
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "hit_rate": round(hit_rate, 4),
        }
