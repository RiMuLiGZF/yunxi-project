"""
有界集合工具类 (Bounded Collections)
=====================================

提供内存安全的有界数据结构，防止无界增长导致的 OOM 风险。
适用于 event_store、feedback_loop、reflection_engine、metrics_collector、
缓存等所有可能使用 setdefault().append() 模式的场景。

核心类：
- BoundedList: 固定容量的列表，FIFO 淘汰
- LRUDict: 固定容量的字典，LRU 淘汰，支持 TTL
- BoundedSet: 固定容量的集合，FIFO 淘汰

设计原则：
- 线程安全（可选加锁，通过 thread_safe 参数控制）
- 高性能：O(1) 或 O(log n) 的基本操作
- 可观测：支持溢出回调、统计信息
- 兼容：尽量保持与内置类型一致的 API
"""

from __future__ import annotations

import time
import logging
import threading
from collections import OrderedDict
from typing import Any, Callable, Generic, Iterable, Iterator, Optional, TypeVar

T = TypeVar("T")
KT = TypeVar("KT")
VT = TypeVar("VT")

logger = logging.getLogger(__name__)

__all__ = [
    "BoundedList",
    "LRUDict",
    "BoundedSet",
    "EvictionReason",
]


class EvictionReason(str):
    """淘汰原因枚举"""
    CAPACITY = "capacity"       # 容量不足
    EXPIRED = "expired"         # TTL 过期


# ──────────────────────────────────────────────────────────
# BoundedList —— 有界列表（FIFO 淘汰）
# ──────────────────────────────────────────────────────────

class BoundedList(Generic[T]):
    """固定最大容量的列表，超出时自动丢弃最旧元素（FIFO）。

    特性：
    - 线程安全（可选）
    - 支持溢出回调（元素被丢弃时触发）
    - 支持 append / extend / clear / len / 索引访问 / 迭代
    - O(1) append（使用 deque 风格的环形缓冲思想，内部用 list 实现以保持兼容性）

    使用场景：
    - 事件存储 event_store
    - 反馈收集 feedback_loop
    - 反射历史 reflection_engine
    - 任何使用 list.append() 累积数据的地方

    示例::

        bl = BoundedList(max_size=1000)
        bl.append(item)
        bl.extend([item1, item2])
        print(len(bl))
        for item in bl:
            process(item)
    """

    def __init__(
        self,
        max_size: int,
        *,
        thread_safe: bool = False,
        on_evict: Optional[Callable[[T, str], None]] = None,
    ) -> None:
        """初始化有界列表。

        Args:
            max_size: 最大容量，必须大于 0
            thread_safe: 是否启用线程安全（加锁）
            on_evict: 元素被淘汰时的回调函数，签名为 (element, reason) -> None

        Raises:
            ValueError: max_size <= 0 时抛出
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")

        self._max_size = max_size
        self._items: list[T] = []
        self._evicted_count = 0
        self._on_evict = on_evict
        self._lock = threading.Lock() if thread_safe else None

    # ── 写入接口 ──────────────────────────────────────

    def append(self, item: T) -> Optional[T]:
        """追加元素。如果超出容量，淘汰最旧的元素。

        Args:
            item: 要追加的元素

        Returns:
            被淘汰的元素（如果有），否则返回 None
        """
        evicted: Optional[T] = None

        if self._lock:
            with self._lock:
                evicted = self._append_nolock(item)
        else:
            evicted = self._append_nolock(item)

        return evicted

    def _append_nolock(self, item: T) -> Optional[T]:
        """无锁版本的 append（内部使用）"""
        self._items.append(item)
        evicted: Optional[T] = None

        if len(self._items) > self._max_size:
            evicted = self._items.pop(0)
            self._evicted_count += 1
            if self._on_evict:
                try:
                    self._on_evict(evicted, EvictionReason.CAPACITY)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted

    def extend(self, iterable: Iterable[T]) -> list[T]:
        """批量追加元素。超出容量的最旧元素将被淘汰。

        Args:
            iterable: 可迭代的元素序列

        Returns:
            被淘汰的元素列表（可能为空）
        """
        evicted: list[T] = []

        if self._lock:
            with self._lock:
                evicted = self._extend_nolock(iterable)
        else:
            evicted = self._extend_nolock(iterable)

        return evicted

    def _extend_nolock(self, iterable: Iterable[T]) -> list[T]:
        """无锁版本的 extend（内部使用）"""
        evicted: list[T] = []
        items = list(iterable)

        if not items:
            return evicted

        self._items.extend(items)

        if len(self._items) > self._max_size:
            overflow = len(self._items) - self._max_size
            evicted = self._items[:overflow]
            self._items = self._items[overflow:]
            self._evicted_count += len(evicted)

            if self._on_evict:
                for item in evicted:
                    try:
                        self._on_evict(item, EvictionReason.CAPACITY)
                    except Exception:
                        # 回调异常不影响主流程，记录 debug 日志便于排查
                        logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted

    def clear(self) -> None:
        """清空所有元素。"""
        if self._lock:
            with self._lock:
                self._items.clear()
                self._evicted_count = 0
        else:
            self._items.clear()
            self._evicted_count = 0

    # ── 读取接口 ──────────────────────────────────────

    def __len__(self) -> int:
        if self._lock:
            with self._lock:
                return len(self._items)
        return len(self._items)

    def __getitem__(self, index: int) -> T:
        if self._lock:
            with self._lock:
                return self._items[index]
        return self._items[index]

    def __iter__(self) -> Iterator[T]:
        # 迭代时返回副本，避免迭代过程中修改导致的问题
        if self._lock:
            with self._lock:
                return iter(list(self._items))
        return iter(list(self._items))

    def __contains__(self, item: T) -> bool:
        if self._lock:
            with self._lock:
                return item in self._items
        return item in self._items

    def __repr__(self) -> str:
        return f"BoundedList(max_size={self._max_size}, current={len(self._items)})"

    def to_list(self) -> list[T]:
        """返回所有元素的列表副本。"""
        if self._lock:
            with self._lock:
                return list(self._items)
        return list(self._items)

    def first(self) -> Optional[T]:
        """获取最旧的元素（队首），空列表返回 None。"""
        if self._lock:
            with self._lock:
                return self._items[0] if self._items else None
        return self._items[0] if self._items else None

    def last(self) -> Optional[T]:
        """获取最新的元素（队尾），空列表返回 None。"""
        if self._lock:
            with self._lock:
                return self._items[-1] if self._items else None
        return self._items[-1] if self._items else None

    # ── 统计与配置 ────────────────────────────────────

    @property
    def max_size(self) -> int:
        """最大容量。"""
        return self._max_size

    @property
    def evicted_count(self) -> int:
        """累计被淘汰的元素数量。"""
        if self._lock:
            with self._lock:
                return self._evicted_count
        return self._evicted_count

    @property
    def is_full(self) -> bool:
        """是否已满。"""
        return len(self) >= self._max_size

    @property
    def utilization(self) -> float:
        """当前容量利用率（0.0 ~ 1.0）。"""
        return len(self) / self._max_size

    def stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        return {
            "max_size": self._max_size,
            "current_size": len(self),
            "evicted_count": self.evicted_count,
            "is_full": self.is_full,
            "utilization": round(self.utilization, 4),
            "thread_safe": self._lock is not None,
        }

    def resize(self, new_max_size: int) -> list[T]:
        """调整最大容量。如果新容量小于当前大小，最旧的元素将被淘汰。

        Args:
            new_max_size: 新的最大容量

        Returns:
            因缩容被淘汰的元素列表
        """
        if new_max_size <= 0:
            raise ValueError(f"new_max_size must be positive, got {new_max_size}")

        evicted: list[T] = []

        if self._lock:
            with self._lock:
                self._max_size = new_max_size
                if len(self._items) > new_max_size:
                    overflow = len(self._items) - new_max_size
                    evicted = self._items[:overflow]
                    self._items = self._items[overflow:]
                    self._evicted_count += len(evicted)
                    if self._on_evict:
                        for item in evicted:
                            try:
                                self._on_evict(item, EvictionReason.CAPACITY)
                            except Exception:
                                # 回调异常不影响主流程，记录 debug 日志便于排查
                                logger.debug("Eviction callback raised an exception", exc_info=True)
        else:
            self._max_size = new_max_size
            if len(self._items) > new_max_size:
                overflow = len(self._items) - new_max_size
                evicted = self._items[:overflow]
                self._items = self._items[overflow:]
                self._evicted_count += len(evicted)
                if self._on_evict:
                    for item in evicted:
                        try:
                            self._on_evict(item, EvictionReason.CAPACITY)
                        except Exception:
                            # 回调异常不影响主流程，记录 debug 日志便于排查
                            logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted


# ──────────────────────────────────────────────────────────
# LRUDict —— LRU 有界字典（支持 TTL）
# ──────────────────────────────────────────────────────────

class LRUDict(Generic[KT, VT]):
    """固定最大容量的字典，使用 LRU（最近最少使用）淘汰策略。

    特性：
    - LRU 淘汰：最近最少使用的键值对优先被淘汰
    - 支持 TTL（过期时间）
    - 线程安全（可选）
    - 支持溢出回调
    - 基于 OrderedDict 实现，get/set 均为 O(1)

    使用场景：
    - 缓存（Cache）
    - 索引映射（如 trace_id -> event_id 列表）
    - 会话存储
    - 任何使用 dict 存储且需要容量控制的地方

    示例::

        cache = LRUDict(max_size=1000, ttl=300)  # 5 分钟过期
        cache.set("key", value)
        value = cache.get("key")
        cache.delete("key")
    """

    def __init__(
        self,
        max_size: int,
        *,
        ttl: Optional[float] = None,
        thread_safe: bool = False,
        on_evict: Optional[Callable[[KT, VT, str], None]] = None,
    ) -> None:
        """初始化 LRU 字典。

        Args:
            max_size: 最大键数量，必须大于 0
            ttl: 键的存活时间（秒），None 表示永不过期
            thread_safe: 是否启用线程安全
            on_evict: 键值对被淘汰时的回调，签名为 (key, value, reason) -> None

        Raises:
            ValueError: max_size <= 0 时抛出
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")

        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[KT, tuple[VT, float]] = OrderedDict()  # key -> (value, expire_time)
        self._evicted_count = 0
        self._expired_count = 0
        self._on_evict = on_evict
        self._lock = threading.Lock() if thread_safe else None

    # ── 写入接口 ──────────────────────────────────────

    def set(self, key: KT, value: VT, *, ttl: Optional[float] = None) -> Optional[tuple[KT, VT]]:
        """设置键值对。如果键已存在则更新值并刷新 LRU 顺序。

        Args:
            key: 键
            value: 值
            ttl: 单独的过期时间（秒），None 则使用全局 ttl

        Returns:
            被淘汰的 (key, value) 元组（如果有），否则返回 None
        """
        evicted: Optional[tuple[KT, VT]] = None

        if self._lock:
            with self._lock:
                evicted = self._set_nolock(key, value, ttl)
        else:
            evicted = self._set_nolock(key, value, ttl)

        return evicted

    def _set_nolock(self, key: KT, value: VT, ttl: Optional[float]) -> Optional[tuple[KT, VT]]:
        """无锁版本的 set（内部使用）"""
        effective_ttl = ttl if ttl is not None else self._ttl
        expire_time = time.time() + effective_ttl if effective_ttl else float("inf")

        evicted: Optional[tuple[KT, VT]] = None

        # 如果键已存在，先删除旧的（以便移到末尾）
        if key in self._data:
            del self._data[key]

        self._data[key] = (value, expire_time)

        # 容量控制
        if len(self._data) > self._max_size:
            evicted_key, (evicted_value, _) = self._data.popitem(last=False)
            self._evicted_count += 1
            evicted = (evicted_key, evicted_value)
            if self._on_evict:
                try:
                    self._on_evict(evicted_key, evicted_value, EvictionReason.CAPACITY)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted

    def delete(self, key: KT) -> Optional[VT]:
        """删除指定键。

        Args:
            key: 要删除的键

        Returns:
            被删除的值，如果键不存在则返回 None
        """
        if self._lock:
            with self._lock:
                return self._delete_nolock(key)
        return self._delete_nolock(key)

    def _delete_nolock(self, key: KT) -> Optional[VT]:
        """无锁版本的 delete（内部使用）"""
        if key in self._data:
            value, _ = self._data.pop(key)
            return value
        return None

    def clear(self) -> None:
        """清空所有键值对。"""
        if self._lock:
            with self._lock:
                self._data.clear()
                self._evicted_count = 0
                self._expired_count = 0
        else:
            self._data.clear()
            self._evicted_count = 0
            self._expired_count = 0

    # ── 读取接口 ──────────────────────────────────────

    def get(self, key: KT, default: Optional[VT] = None) -> Optional[VT]:
        """获取值。访问会刷新 LRU 顺序。如果已过期则返回 default 并删除该键。

        Args:
            key: 键
            default: 键不存在或已过期时的默认值

        Returns:
            对应的值，或 default
        """
        if self._lock:
            with self._lock:
                return self._get_nolock(key, default)
        return self._get_nolock(key, default)

    def _get_nolock(self, key: KT, default: Optional[VT]) -> Optional[VT]:
        """无锁版本的 get（内部使用）"""
        if key not in self._data:
            return default

        value, expire_time = self._data[key]

        # 检查是否过期
        if expire_time != float("inf") and time.time() > expire_time:
            del self._data[key]
            self._expired_count += 1
            if self._on_evict:
                try:
                    self._on_evict(key, value, EvictionReason.EXPIRED)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)
            return default

        # 移到末尾（表示最近使用）
        self._data.move_to_end(key)
        return value

    def peek(self, key: KT, default: Optional[VT] = None) -> Optional[VT]:
        """获取值但不刷新 LRU 顺序，也不检查过期。

        用于只读访问，不影响淘汰顺序。
        """
        if self._lock:
            with self._lock:
                if key in self._data:
                    return self._data[key][0]
                return default
        if key in self._data:
            return self._data[key][0]
        return default

    def __getitem__(self, key: KT) -> VT:
        value = self.get(key)
        if value is None and key not in self:
            raise KeyError(key)
        return value  # type: ignore[return-value]

    def __setitem__(self, key: KT, value: VT) -> None:
        self.set(key, value)

    def __delitem__(self, key: KT) -> None:
        if self.delete(key) is None and key not in self:
            raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        # 包含检查也需要处理过期
        if self._lock:
            with self._lock:
                return self._contains_nolock(key)
        return self._contains_nolock(key)

    def _contains_nolock(self, key: object) -> bool:
        """无锁版本的 contains（内部使用）"""
        if key not in self._data:
            return False

        _, expire_time = self._data[key]  # type: ignore[index]
        if expire_time != float("inf") and time.time() > expire_time:
            # 过期了，惰性删除
            value = self._data.pop(key)[0]  # type: ignore[index]
            self._expired_count += 1
            if self._on_evict:
                try:
                    self._on_evict(key, value, EvictionReason.EXPIRED)  # type: ignore[arg-type]
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)
            return False

        return True

    def __len__(self) -> int:
        # len 不清理过期项，保持 O(1)
        if self._lock:
            with self._lock:
                return len(self._data)
        return len(self._data)

    def __iter__(self) -> Iterator[KT]:
        if self._lock:
            with self._lock:
                return iter(list(self._data.keys()))
        return iter(list(self._data.keys()))

    def keys(self) -> list[KT]:
        """返回所有键的列表（从最旧到最新）。"""
        if self._lock:
            with self._lock:
                return list(self._data.keys())
        return list(self._data.keys())

    def values(self) -> list[VT]:
        """返回所有值的列表（从最旧到最新）。"""
        if self._lock:
            with self._lock:
                return [v for v, _ in self._data.values()]
        return [v for v, _ in self._data.values()]

    def items(self) -> list[tuple[KT, VT]]:
        """返回所有 (key, value) 对的列表。"""
        if self._lock:
            with self._lock:
                return [(k, v) for k, (v, _) in self._data.items()]
        return [(k, v) for k, (v, _) in self._data.items()]

    # ── 过期清理 ──────────────────────────────────────

    def purge_expired(self) -> list[tuple[KT, VT]]:
        """主动清理所有已过期的键值对。

        Returns:
            被清理的 (key, value) 列表
        """
        expired: list[tuple[KT, VT]] = []

        if self._lock:
            with self._lock:
                expired = self._purge_expired_nolock()
        else:
            expired = self._purge_expired_nolock()

        return expired

    def _purge_expired_nolock(self) -> list[tuple[KT, VT]]:
        """无锁版本的 purge_expired（内部使用）"""
        if self._ttl is None:
            return []

        expired: list[tuple[KT, VT]] = []
        now = time.time()
        keys_to_remove: list[KT] = []

        for key, (value, expire_time) in self._data.items():
            if expire_time != float("inf") and now > expire_time:
                keys_to_remove.append(key)
                expired.append((key, value))

        for key in keys_to_remove:
            del self._data[key]

        self._expired_count += len(expired)

        if self._on_evict and expired:
            for key, value in expired:
                try:
                    self._on_evict(key, value, EvictionReason.EXPIRED)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)

        return expired

    # ── 统计与配置 ────────────────────────────────────

    @property
    def max_size(self) -> int:
        """最大容量。"""
        return self._max_size

    @property
    def ttl(self) -> Optional[float]:
        """全局 TTL（秒）。"""
        return self._ttl

    @property
    def evicted_count(self) -> int:
        """因容量不足被淘汰的次数。"""
        if self._lock:
            with self._lock:
                return self._evicted_count
        return self._evicted_count

    @property
    def expired_count(self) -> int:
        """因过期被清理的次数。"""
        if self._lock:
            with self._lock:
                return self._expired_count
        return self._expired_count

    @property
    def is_full(self) -> bool:
        """是否已满。"""
        return len(self) >= self._max_size

    @property
    def utilization(self) -> float:
        """当前容量利用率（0.0 ~ 1.0）。"""
        return len(self) / self._max_size

    def stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        return {
            "max_size": self._max_size,
            "current_size": len(self),
            "ttl": self._ttl,
            "evicted_count": self.evicted_count,
            "expired_count": self.expired_count,
            "is_full": self.is_full,
            "utilization": round(self.utilization, 4),
            "thread_safe": self._lock is not None,
        }

    def resize(self, new_max_size: int) -> list[tuple[KT, VT]]:
        """调整最大容量。如果新容量小于当前大小，最久未使用的键将被淘汰。

        Args:
            new_max_size: 新的最大容量

        Returns:
            因缩容被淘汰的 (key, value) 列表
        """
        if new_max_size <= 0:
            raise ValueError(f"new_max_size must be positive, got {new_max_size}")

        evicted: list[tuple[KT, VT]] = []

        if self._lock:
            with self._lock:
                evicted = self._resize_nolock(new_max_size)
        else:
            evicted = self._resize_nolock(new_max_size)

        return evicted

    def _resize_nolock(self, new_max_size: int) -> list[tuple[KT, VT]]:
        """无锁版本的 resize（内部使用）"""
        self._max_size = new_max_size
        evicted: list[tuple[KT, VT]] = []

        while len(self._data) > new_max_size:
            key, (value, _) = self._data.popitem(last=False)
            evicted.append((key, value))
            self._evicted_count += 1
            if self._on_evict:
                try:
                    self._on_evict(key, value, EvictionReason.CAPACITY)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted


# ──────────────────────────────────────────────────────────
# BoundedSet —— 有界集合（FIFO 淘汰）
# ──────────────────────────────────────────────────────────

class BoundedSet(Generic[T]):
    """固定最大容量的集合，超出时按 FIFO 顺序淘汰最旧的元素。

    特性：
    - 保持元素的插入顺序（FIFO 淘汰）
    - 自动去重（已存在的元素重新加入会刷新顺序）
    - 线程安全（可选）
    - 支持溢出回调

    使用场景：
    - 去重 + 容量控制
    - 会话 ID 集合
    - 任务 ID 追踪

    示例::

        bs = BoundedSet(max_size=1000)
        bs.add(item)
        if item in bs:
            process()
    """

    def __init__(
        self,
        max_size: int,
        *,
        thread_safe: bool = False,
        on_evict: Optional[Callable[[T, str], None]] = None,
    ) -> None:
        """初始化有界集合。

        Args:
            max_size: 最大容量，必须大于 0
            thread_safe: 是否启用线程安全
            on_evict: 元素被淘汰时的回调，签名为 (element, reason) -> None

        Raises:
            ValueError: max_size <= 0 时抛出
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")

        self._max_size = max_size
        # 使用 OrderedDict 模拟有序集合（值设为 None）
        self._data: OrderedDict[T, None] = OrderedDict()
        self._evicted_count = 0
        self._on_evict = on_evict
        self._lock = threading.Lock() if thread_safe else None

    # ── 写入接口 ──────────────────────────────────────

    def add(self, item: T) -> Optional[T]:
        """添加元素。如果元素已存在，将其移到最新位置。

        Args:
            item: 要添加的元素

        Returns:
            被淘汰的元素（如果有），否则返回 None
        """
        evicted: Optional[T] = None

        if self._lock:
            with self._lock:
                evicted = self._add_nolock(item)
        else:
            evicted = self._add_nolock(item)

        return evicted

    def _add_nolock(self, item: T) -> Optional[T]:
        """无锁版本的 add（内部使用）"""
        evicted: Optional[T] = None

        # 如果已存在，移到末尾（刷新顺序）
        if item in self._data:
            self._data.move_to_end(item)
            return None

        self._data[item] = None

        # 容量控制
        if len(self._data) > self._max_size:
            evicted, _ = self._data.popitem(last=False)
            self._evicted_count += 1
            if self._on_evict:
                try:
                    self._on_evict(evicted, EvictionReason.CAPACITY)
                except Exception:
                    # 回调异常不影响主流程，记录 debug 日志便于排查
                    logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted

    def update(self, iterable: Iterable[T]) -> list[T]:
        """批量添加元素。

        Args:
            iterable: 可迭代的元素序列

        Returns:
            被淘汰的元素列表
        """
        evicted: list[T] = []

        if self._lock:
            with self._lock:
                for item in iterable:
                    result = self._add_nolock(item)
                    if result is not None:
                        evicted.append(result)
        else:
            for item in iterable:
                result = self._add_nolock(item)
                if result is not None:
                    evicted.append(result)

        return evicted

    def discard(self, item: T) -> bool:
        """移除元素（如果存在）。

        Args:
            item: 要移除的元素

        Returns:
            是否成功移除
        """
        if self._lock:
            with self._lock:
                if item in self._data:
                    del self._data[item]
                    return True
                return False
        if item in self._data:
            del self._data[item]
            return True
        return False

    def clear(self) -> None:
        """清空所有元素。"""
        if self._lock:
            with self._lock:
                self._data.clear()
                self._evicted_count = 0
        else:
            self._data.clear()
            self._evicted_count = 0

    # ── 读取接口 ──────────────────────────────────────

    def __contains__(self, item: T) -> bool:
        # 注意：contains 不刷新 LRU 顺序（保持 set 的语义）
        if self._lock:
            with self._lock:
                return item in self._data
        return item in self._data

    def __len__(self) -> int:
        if self._lock:
            with self._lock:
                return len(self._data)
        return len(self._data)

    def __iter__(self) -> Iterator[T]:
        if self._lock:
            with self._lock:
                return iter(list(self._data.keys()))
        return iter(list(self._data.keys()))

    def __repr__(self) -> str:
        return f"BoundedSet(max_size={self._max_size}, current={len(self._data)})"

    def to_set(self) -> set[T]:
        """转换为普通集合（无序）。"""
        if self._lock:
            with self._lock:
                return set(self._data.keys())
        return set(self._data.keys())

    def to_list(self) -> list[T]:
        """转换为列表（按插入顺序，从最旧到最新）。"""
        if self._lock:
            with self._lock:
                return list(self._data.keys())
        return list(self._data.keys())

    # ── 统计与配置 ────────────────────────────────────

    @property
    def max_size(self) -> int:
        """最大容量。"""
        return self._max_size

    @property
    def evicted_count(self) -> int:
        """累计被淘汰的元素数量。"""
        if self._lock:
            with self._lock:
                return self._evicted_count
        return self._evicted_count

    @property
    def is_full(self) -> bool:
        """是否已满。"""
        return len(self) >= self._max_size

    @property
    def utilization(self) -> float:
        """当前容量利用率（0.0 ~ 1.0）。"""
        return len(self) / self._max_size

    def stats(self) -> dict[str, Any]:
        """获取统计信息。"""
        return {
            "max_size": self._max_size,
            "current_size": len(self),
            "evicted_count": self.evicted_count,
            "is_full": self.is_full,
            "utilization": round(self.utilization, 4),
            "thread_safe": self._lock is not None,
        }

    def resize(self, new_max_size: int) -> list[T]:
        """调整最大容量。如果新容量小于当前大小，最旧的元素将被淘汰。

        Args:
            new_max_size: 新的最大容量

        Returns:
            因缩容被淘汰的元素列表
        """
        if new_max_size <= 0:
            raise ValueError(f"new_max_size must be positive, got {new_max_size}")

        evicted: list[T] = []

        if self._lock:
            with self._lock:
                self._max_size = new_max_size
                while len(self._data) > new_max_size:
                    item, _ = self._data.popitem(last=False)
                    evicted.append(item)
                    self._evicted_count += 1
                    if self._on_evict:
                        try:
                            self._on_evict(item, EvictionReason.CAPACITY)
                        except Exception:
                            # 回调异常不影响主流程，记录 debug 日志便于排查
                            logger.debug("Eviction callback raised an exception", exc_info=True)
        else:
            self._max_size = new_max_size
            while len(self._data) > new_max_size:
                item, _ = self._data.popitem(last=False)
                evicted.append(item)
                self._evicted_count += 1
                if self._on_evict:
                    try:
                        self._on_evict(item, EvictionReason.CAPACITY)
                    except Exception:
                        # 回调异常不影响主流程，记录 debug 日志便于排查
                        logger.debug("Eviction callback raised an exception", exc_info=True)

        return evicted
