"""
云汐系统本地缓存层
基于内存的 LRU + TTL 双层缓存，用于减少跨模块 HTTP 调用和数据库查询

SimpleCache 特性：
  - 线程安全（threading.Lock）
  - TTL 过期（惰性清理 + 定期后台清理）
  - 最大容量限制（LRU 淘汰）
  - 缓存统计（命中/未命中/命中率/淘汰数）
  - 缓存穿透防护（空值缓存）
  - 缓存雪崩防护（随机过期时间抖动）
  - 缓存装饰器（cached / cached_async）
  - 缓存预热机制
  - 双层缓存（热点数据常驻层 + 普通数据淘汰层）

使用方式::

    from shared.data.cache import get_cache, cached, CacheStats

    # 全局缓存
    cache = get_cache()
    cache.set("key", "value", ttl=60)
    value = cache.get("key")

    # 装饰器用法
    @cached(ttl=300, key_prefix="user")
    def get_user(user_id: int) -> dict:
        ...

    # 缓存统计
    stats = cache.get_stats()
"""

import os
import time
import random
import hashlib
import threading
import functools
import asyncio
from collections import OrderedDict
from typing import Any, Optional, Dict, List, Callable, Tuple, Union


# ============================================================
# 缓存统计
# ============================================================

class CacheStats:
    """缓存统计信息"""

    __slots__ = (
        "hits", "misses", "evictions", "sets", "deletes",
        "null_hits", "null_sets", "warmup_count", "stale_reads",
    )

    def __init__(self) -> None:
        self.hits = 0          # 普通命中
        self.misses = 0        # 未命中
        self.evictions = 0     # 淘汰数
        self.sets = 0          # 写入数
        self.deletes = 0       # 删除数
        self.null_hits = 0     # 空值命中（穿透防护）
        self.null_sets = 0     # 空值写入数
        self.warmup_count = 0  # 预热写入数
        self.stale_reads = 0   # 过期数据读取数（降级时使用）

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses + self.null_hits

    @property
    def hit_rate(self) -> float:
        total = self.total_requests
        if total == 0:
            return 0.0
        return (self.hits + self.null_hits) / total

    @property
    def real_hit_rate(self) -> float:
        """真实命中率（不含空值命中）"""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "sets": self.sets,
            "deletes": self.deletes,
            "null_hits": self.null_hits,
            "null_sets": self.null_sets,
            "warmup_count": self.warmup_count,
            "stale_reads": self.stale_reads,
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 4),
            "real_hit_rate": round(self.real_hit_rate, 4),
        }

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.sets = 0
        self.deletes = 0
        self.null_hits = 0
        self.null_sets = 0
        self.warmup_count = 0
        self.stale_reads = 0


# ============================================================
# 空值标记（用于缓存穿透防护）
# ============================================================

class _NullSentinel:
    """空值哨兵对象，用于区分"缓存不存在"和"缓存了空值"

    当查询结果为 None/空列表时，使用此对象标记，
    防止缓存穿透（大量请求查询不存在的数据打到数据库）。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<NullSentinel>"

    def __bool__(self) -> bool:
        return False


NULL_VALUE = _NullSentinel()


# ============================================================
# 缓存条目
# ============================================================

class _CacheEntry:
    """缓存条目（值 + 过期时间 + 访问计数）"""

    __slots__ = ("value", "expire_at", "access_count", "created_at")

    def __init__(self, value: Any, expire_at: float) -> None:
        self.value = value
        self.expire_at = expire_at
        self.access_count = 0
        self.created_at = time.time()


# ============================================================
# 核心缓存类
# ============================================================

class SimpleCache:
    """基于内存的 LRU + TTL 双层缓存

    线程安全，支持：
      - set(key, value, ttl)        写入缓存，ttl 单位秒
      - get(key)                    读取缓存，过期或不存在返回 None
      - get_or_set(key, loader)     读取，不存在则通过 loader 获取并缓存
      - delete(key)                 删除指定 key
      - clear()                     清空所有缓存
      - delete_prefix(prefix)       按前缀批量删除（用于写操作后清理）
      - invalidate_tag(tag)         按标签批量失效
      - get_stats()                 获取统计信息
      - reset_stats()               重置统计
      - warmup(items)               缓存预热
      - get_many(keys)              批量读取

    双层缓存设计：
      - 热点层（hot layer）：高频访问的数据，TTL 更长，容量较小
      - 普通层（normal layer）：普通数据，标准 LRU + TTL

    内部使用 OrderedDict 实现 LRU：
      - 最新访问的条目在末尾（move_to_end）
      - 容量满时淘汰最旧（最早访问）的条目（popitem(last=False)）
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 5.0,
        cleanup_interval: float = 60.0,
        # 双层缓存配置
        hot_ratio: float = 0.2,
        hot_ttl_multiplier: float = 3.0,
        hot_access_threshold: int = 3,
        # 穿透/雪崩防护
        null_ttl: float = 30.0,
        jitter_ratio: float = 0.1,
        # 慢查询保护
        lock_timeout: float = 5.0,
    ) -> None:
        """
        Args:
            max_size:               最大缓存条目数，超过后按 LRU 淘汰
            default_ttl:            默认过期时间（秒），可被 set 时的 ttl 覆盖
            cleanup_interval:       后台定期清理间隔（秒），设为 0 则禁用后台清理
            hot_ratio:              热点层容量占比（0~1）
            hot_ttl_multiplier:     热点层 TTL 倍数
            hot_access_threshold:   晋升到热点层的访问次数阈值
            null_ttl:               空值缓存时间（秒），用于穿透防护
            jitter_ratio:           过期时间抖动比例（0~1），防止雪崩
            lock_timeout:           内部锁超时（秒），防止死锁
        """
        self.max_size = max(10, max_size)
        self.default_ttl = max(0.1, float(default_ttl))
        self.cleanup_interval = max(0.0, float(cleanup_interval))
        self.null_ttl = max(1.0, float(null_ttl))
        self.jitter_ratio = max(0.0, min(0.5, float(jitter_ratio)))

        # 双层缓存配置
        self._hot_max_size = max(1, int(self.max_size * hot_ratio))
        self._normal_max_size = self.max_size - self._hot_max_size
        self._hot_ttl_multiplier = hot_ttl_multiplier
        self._hot_access_threshold = max(1, hot_access_threshold)

        # 双层存储
        # _store[key] = _CacheEntry
        self._hot_store: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._normal_store: "OrderedDict[str, _CacheEntry]" = OrderedDict()

        # 标签索引（tag -> set of keys），用于批量失效
        self._tag_index: Dict[str, set] = {}

        # 同步
        self._lock = threading.RLock()
        self._lock_timeout = lock_timeout
        self._stats = CacheStats()

        # 后台清理线程
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        if self.cleanup_interval > 0:
            self._start_cleanup_thread()

    # ---------- 内部工具 ----------

    def _acquire_lock(self) -> bool:
        """获取锁，带超时保护"""
        return self._lock.acquire(timeout=self._lock_timeout)

    def _release_lock(self) -> None:
        """释放锁"""
        try:
            self._lock.release()
        except RuntimeError:
            pass

    def _jitter_ttl(self, ttl: float) -> float:
        """为 TTL 添加随机抖动，防止缓存雪崩

        在 ttl 的 ±jitter_ratio 范围内随机调整。
        """
        if self.jitter_ratio <= 0:
            return ttl
        jitter = ttl * self.jitter_ratio * (random.random() * 2 - 1)
        return max(0.1, ttl + jitter)

    def _is_expired(self, entry: _CacheEntry, now: float) -> bool:
        """检查条目是否过期"""
        return entry.expire_at <= now

    def _promote_to_hot(self, key: str, entry: _CacheEntry) -> None:
        """将条目晋升到热点层（调用方需持有锁）"""
        # 从普通层移除
        if key in self._normal_store:
            del self._normal_store[key]

        # 添加到热点层
        self._hot_store[key] = entry

        # 热点层 LRU 淘汰
        while len(self._hot_store) > self._hot_max_size:
            evicted_key, _ = self._hot_store.popitem(last=False)
            self._stats.evictions += 1
            # 清理标签索引
            self._remove_from_tag_index(evicted_key)

    def _demote_from_hot(self, key: str, entry: _CacheEntry) -> None:
        """将条目从热点层降级到普通层（调用方需持有锁）"""
        if key in self._hot_store:
            del self._hot_store[key]

        self._normal_store[key] = entry

        # 普通层 LRU 淘汰
        while len(self._normal_store) > self._normal_max_size:
            evicted_key, _ = self._normal_store.popitem(last=False)
            self._stats.evictions += 1
            self._remove_from_tag_index(evicted_key)

    def _add_to_tag_index(self, key: str, tags: Optional[List[str]]) -> None:
        """添加到标签索引"""
        if not tags:
            return
        for tag in tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(key)

    def _remove_from_tag_index(self, key: str) -> None:
        """从所有标签索引中移除 key"""
        for tag_keys in self._tag_index.values():
            tag_keys.discard(key)
        # 清理空标签
        empty_tags = [t for t, k in self._tag_index.items() if not k]
        for t in empty_tags:
            del self._tag_index[t]

    # ---------- 后台定期清理 ----------

    def _start_cleanup_thread(self) -> None:
        """启动后台过期清理守护线程"""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="SimpleCache-Cleaner",
            daemon=True,
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self) -> None:
        """后台清理循环：每隔 cleanup_interval 秒清理一次过期条目"""
        while not self._stop_event.is_set():
            # 使用 wait 替代 sleep，支持快速停止
            self._stop_event.wait(self.cleanup_interval)
            if self._stop_event.is_set():
                break
            try:
                self._purge_expired()
            except Exception:
                # 后台清理失败不影响主流程
                pass

    def _purge_expired(self) -> int:
        """清理所有已过期的条目，返回清理数量"""
        if not self._acquire_lock():
            return 0
        try:
            now = time.time()
            count = 0

            # 清理普通层
            expired_keys = [
                k for k, v in self._normal_store.items()
                if self._is_expired(v, now)
            ]
            for k in expired_keys:
                del self._normal_store[k]
                self._remove_from_tag_index(k)
                count += 1

            # 清理热点层
            expired_keys = [
                k for k, v in self._hot_store.items()
                if self._is_expired(v, now)
            ]
            for k in expired_keys:
                del self._hot_store[k]
                self._remove_from_tag_index(k)
                count += 1

            return count
        finally:
            self._release_lock()

    def _lazy_purge_head(self, store: "OrderedDict[str, _CacheEntry]") -> None:
        """从字典头部开始惰性清理，遇到第一个未过期的就停止

        由于 OrderedDict 按访问时间排序，最旧的在头部，
        所以只需从头部开始清理过期条目即可，效率较高。
        """
        now = time.time()
        while store:
            key, entry = next(iter(store.items()))
            if self._is_expired(entry, now):
                del store[key]
                self._remove_from_tag_index(key)
            else:
                break

    # ---------- 公共 API：基础操作 ----------

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        tags: Optional[List[str]] = None,
        is_null: bool = False,
    ) -> None:
        """写入缓存

        Args:
            key:     缓存键
            value:   缓存值
            ttl:     过期时间（秒），不传则使用 default_ttl
            tags:    标签列表，用于按标签批量失效
            is_null: 是否为空值缓存（穿透防护）
        """
        effective_ttl = self.default_ttl if ttl is None else max(0.1, float(ttl))

        # 空值使用更短的 TTL
        if is_null or value is None or value is NULL_VALUE:
            effective_ttl = self.null_ttl
            stored_value = NULL_VALUE
            is_null = True
        else:
            stored_value = value
            # 添加随机抖动防止雪崩
            effective_ttl = self._jitter_ttl(effective_ttl)

        expire_at = time.time() + effective_ttl
        entry = _CacheEntry(value=stored_value, expire_at=expire_at)

        if not self._acquire_lock():
            return
        try:
            # 已存在则先删再插（更新位置到末尾 = 最新）
            if key in self._hot_store:
                del self._hot_store[key]
            if key in self._normal_store:
                del self._normal_store[key]

            # 默认放入普通层
            self._normal_store[key] = entry
            self._stats.sets += 1
            if is_null:
                self._stats.null_sets += 1

            # 更新标签索引
            self._add_to_tag_index(key, tags)

            # LRU 淘汰：普通层超出容量时淘汰最久未访问的
            while len(self._normal_store) > self._normal_max_size:
                evicted_key, _ = self._normal_store.popitem(last=False)
                self._stats.evictions += 1
                self._remove_from_tag_index(evicted_key)
        finally:
            self._release_lock()

    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """读取缓存

        Args:
            key:     缓存键
            default: 未命中时返回的默认值

        Returns:
            缓存值；若 key 不存在或已过期，返回 default（默认 None）
            空值缓存命中时返回 None（表示已查询过，结果为空）
        """
        if not self._acquire_lock():
            return default
        try:
            now = time.time()

            # 先查热点层
            entry = self._hot_store.get(key)
            if entry is not None:
                if self._is_expired(entry, now):
                    del self._hot_store[key]
                    self._remove_from_tag_index(key)
                    self._stats.misses += 1
                    return default
                # 命中热点层：刷新访问时间
                self._hot_store.move_to_end(key)
                entry.access_count += 1
                self._stats.hits += 1
                if entry.value is NULL_VALUE:
                    self._stats.null_hits += 1
                    return None
                return entry.value

            # 再查普通层
            entry = self._normal_store.get(key)
            if entry is None:
                self._stats.misses += 1
                return default

            if self._is_expired(entry, now):
                # 惰性过期
                del self._normal_store[key]
                self._remove_from_tag_index(key)
                self._stats.misses += 1
                return default

            # 命中普通层
            self._normal_store.move_to_end(key)
            entry.access_count += 1
            self._stats.hits += 1

            # 达到阈值则晋升到热点层
            if entry.access_count >= self._hot_access_threshold:
                # 延长热点层 TTL
                entry.expire_at = now + self.default_ttl * self._hot_ttl_multiplier
                self._promote_to_hot(key, entry)

            if entry.value is NULL_VALUE:
                self._stats.null_hits += 1
                return None
            return entry.value
        finally:
            self._release_lock()

    def get_or_set(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: Optional[float] = None,
        tags: Optional[List[str]] = None,
        cache_null: bool = True,
    ) -> Any:
        """读取缓存，不存在则通过 loader 获取并缓存

        这是最常用的模式，避免了先 get 后 set 的竞态。

        Args:
            key:        缓存键
            loader:     加载函数，无参数，返回要缓存的值
            ttl:        过期时间（秒）
            tags:       标签列表
            cache_null: 是否缓存空值（穿透防护）

        Returns:
            缓存值或 loader 的返回值
        """
        value = self.get(key)
        # 注意：get 返回 None 可能是空值命中（穿透防护），也可能是真未命中
        # 需要用 has() 区分
        if value is not None:
            return value

        # 检查是否是空值命中
        if self.has(key):
            return None

        # 未命中，调用 loader
        result = loader()

        if result is None or (isinstance(result, (list, dict)) and len(result) == 0):
            if cache_null:
                self.set(key, NULL_VALUE, ttl=ttl, tags=tags, is_null=True)
        else:
            self.set(key, result, ttl=ttl, tags=tags)

        return result

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """批量读取缓存

        Args:
            keys: 缓存键列表

        Returns:
            命中的 key-value 字典
        """
        result = {}
        for key in keys:
            value = self.get(key)
            if value is not None or self.has(key):
                result[key] = value
        return result

    def set_many(self, items: Dict[str, Any], ttl: Optional[float] = None) -> None:
        """批量写入缓存

        Args:
            items: key-value 字典
            ttl:   过期时间（秒）
        """
        for key, value in items.items():
            self.set(key, value, ttl=ttl)

    def delete(self, key: str) -> bool:
        """删除指定 key

        Returns:
            True 表示 key 存在并已删除，False 表示 key 不存在
        """
        if not self._acquire_lock():
            return False
        try:
            found = False
            if key in self._hot_store:
                del self._hot_store[key]
                found = True
            if key in self._normal_store:
                del self._normal_store[key]
                found = True
            if found:
                self._stats.deletes += 1
                self._remove_from_tag_index(key)
            return found
        finally:
            self._release_lock()

    def delete_prefix(self, prefix: str) -> int:
        """按前缀批量删除缓存条目

        用于写操作后清除相关模块/路径的所有缓存，保证数据一致性。

        Args:
            prefix: 键前缀

        Returns:
            删除的条目数量
        """
        if not prefix:
            return 0
        if not self._acquire_lock():
            return 0
        try:
            keys_to_delete = []
            for store in (self._hot_store, self._normal_store):
                keys_to_delete.extend(
                    k for k in store if k.startswith(prefix)
                )

            for k in keys_to_delete:
                if k in self._hot_store:
                    del self._hot_store[k]
                if k in self._normal_store:
                    del self._normal_store[k]
                self._remove_from_tag_index(k)

            self._stats.deletes += len(keys_to_delete)
            return len(keys_to_delete)
        finally:
            self._release_lock()

    def invalidate_tag(self, tag: str) -> int:
        """按标签批量失效缓存

        用于同一实体的关联缓存失效（如用户信息变更时，清除所有带 "user:123" 标签的缓存）。

        Args:
            tag: 标签名

        Returns:
            失效的条目数量
        """
        if not self._acquire_lock():
            return 0
        try:
            keys = self._tag_index.get(tag, set())
            if not keys:
                return 0

            count = 0
            for key in keys:
                if key in self._hot_store:
                    del self._hot_store[key]
                    count += 1
                if key in self._normal_store:
                    del self._normal_store[key]
                    count += 1

            # 清理标签
            del self._tag_index[tag]

            # 清理其他标签中对这些 key 的引用
            for other_tag, other_keys in self._tag_index.items():
                other_keys -= keys

            self._stats.deletes += count
            return count
        finally:
            self._release_lock()

    def clear(self) -> int:
        """清空所有缓存，返回被清除的条目数"""
        if not self._acquire_lock():
            return 0
        try:
            count = len(self._hot_store) + len(self._normal_store)
            self._hot_store.clear()
            self._normal_store.clear()
            self._tag_index.clear()
            self._stats.deletes += count
            return count
        finally:
            self._release_lock()

    def has(self, key: str) -> bool:
        """判断 key 是否存在且未过期（不影响 LRU 顺序和统计）"""
        if not self._acquire_lock():
            return False
        try:
            now = time.time()
            # 检查热点层
            entry = self._hot_store.get(key)
            if entry is not None:
                if self._is_expired(entry, now):
                    del self._hot_store[key]
                    self._remove_from_tag_index(key)
                    return False
                return True

            # 检查普通层
            entry = self._normal_store.get(key)
            if entry is None:
                return False
            if self._is_expired(entry, now):
                del self._normal_store[key]
                self._remove_from_tag_index(key)
                return False
            return True
        finally:
            self._release_lock()

    def size(self) -> int:
        """返回当前缓存条目数（含可能已过期但未清理的条目）"""
        if not self._acquire_lock():
            return 0
        try:
            # 顺手做一次惰性清理（只清理最旧的若干过期条目，避免阻塞）
            self._lazy_purge_head(self._hot_store)
            self._lazy_purge_head(self._normal_store)
            return len(self._hot_store) + len(self._normal_store)
        finally:
            self._release_lock()

    # ---------- 缓存预热 ----------

    def warmup(self, items: Dict[str, Tuple[Any, float]], tags: Optional[List[str]] = None) -> int:
        """缓存预热 - 批量写入热点数据

        用于应用启动时，将热点数据预先加载到缓存中。
        预热数据直接放入热点层。

        Args:
            items: {key: (value, ttl_seconds)} 字典
            tags:  标签列表

        Returns:
            预热写入的条目数
        """
        count = 0
        for key, (value, ttl) in items.items():
            self._warmup_set(key, value, ttl, tags)
            count += 1

        if self._acquire_lock():
            try:
                self._stats.warmup_count += count
            finally:
                self._release_lock()

        return count

    def _warmup_set(
        self,
        key: str,
        value: Any,
        ttl: float,
        tags: Optional[List[str]],
    ) -> None:
        """预热写入 - 直接放入热点层（内部方法）"""
        expire_at = time.time() + ttl
        entry = _CacheEntry(value=value, expire_at=expire_at)
        entry.access_count = self._hot_access_threshold  # 直接标记为热点

        if not self._acquire_lock():
            # 降级为普通 set
            self.set(key, value, ttl=ttl, tags=tags)
            return
        try:
            # 已存在则先删除
            if key in self._hot_store:
                del self._hot_store[key]
            if key in self._normal_store:
                del self._normal_store[key]

            self._hot_store[key] = entry
            self._stats.sets += 1
            self._add_to_tag_index(key, tags)

            # 热点层 LRU 淘汰
            while len(self._hot_store) > self._hot_max_size:
                evicted_key, _ = self._hot_store.popitem(last=False)
                self._stats.evictions += 1
                self._remove_from_tag_index(evicted_key)
        finally:
            self._release_lock()

    # ---------- 统计 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        if not self._acquire_lock():
            return {}
        try:
            stats = self._stats.to_dict()
            stats["size"] = len(self._hot_store) + len(self._normal_store)
            stats["hot_size"] = len(self._hot_store)
            stats["normal_size"] = len(self._normal_store)
            stats["max_size"] = self.max_size
            stats["hot_max_size"] = self._hot_max_size
            stats["normal_max_size"] = self._normal_max_size
            stats["default_ttl"] = self.default_ttl
            stats["null_ttl"] = self.null_ttl
            stats["tag_count"] = len(self._tag_index)
            return stats
        finally:
            self._release_lock()

    def reset_stats(self) -> None:
        """重置统计计数"""
        if not self._acquire_lock():
            return
        try:
            self._stats.reset()
        finally:
            self._release_lock()

    # ---------- 生命周期 ----------

    def shutdown(self) -> None:
        """关闭缓存（停止后台清理线程）"""
        self._stop_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2.0)

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass

    # ---------- 上下文管理器支持 ----------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False


# ============================================================
# 缓存装饰器
# ============================================================

def _make_cache_key(
    func: Callable,
    args: tuple,
    kwargs: dict,
    key_prefix: str,
) -> str:
    """生成缓存键

    基于函数名 + 参数生成唯一的缓存键。
    """
    # 处理 kwargs 排序，确保相同参数生成相同 key
    sorted_kwargs = sorted(kwargs.items()) if kwargs else []

    # 组合 key 字符串
    key_parts = [key_prefix or func.__name__]

    # 添加位置参数
    if args:
        key_parts.append(":".join(str(a) for a in args))

    # 添加关键字参数
    if sorted_kwargs:
        key_parts.append("|".join(f"{k}={v}" for k, v in sorted_kwargs))

    # 如果 key 太长，用 hash 缩短
    raw_key = "::".join(key_parts)
    if len(raw_key) > 200:
        hash_digest = hashlib.md5(raw_key.encode()).hexdigest()
        raw_key = f"{key_prefix or func.__name__}::hash:{hash_digest}"

    return raw_key


def cached(
    ttl: float = 60.0,
    key_prefix: Optional[str] = None,
    cache: Optional[SimpleCache] = None,
    cache_null: bool = True,
    tags: Optional[List[str]] = None,
):
    """同步函数缓存装饰器

    使用方式::

        @cached(ttl=300, key_prefix="user_info")
        def get_user_info(user_id: int) -> dict:
            # 从数据库查询
            return db.query(user_id)

    Args:
        ttl:        缓存过期时间（秒）
        key_prefix: 缓存键前缀，默认使用函数名
        cache:      缓存实例，不传则使用全局缓存
        cache_null: 是否缓存空值（穿透防护）
        tags:       标签列表，用于按标签批量失效
    """
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_instance = cache or get_cache()
            cache_key = _make_cache_key(func, args, kwargs, prefix)

            # 先尝试从缓存获取
            if cache_instance.has(cache_key):
                return cache_instance.get(cache_key)

            # 未命中，执行函数
            result = func(*args, **kwargs)

            # 缓存结果
            if (result is None or (isinstance(result, (list, dict)) and len(result) == 0)) and cache_null:
                cache_instance.set(cache_key, NULL_VALUE, ttl=ttl, tags=tags, is_null=True)
            elif result is not None:
                cache_instance.set(cache_key, result, ttl=ttl, tags=tags)

            return result

        # 添加手动失效方法
        def invalidate(*args, **kwargs):
            cache_instance = cache or get_cache()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            cache_instance.delete(cache_key)

        wrapper.invalidate = invalidate  # type: ignore
        wrapper.cache_key_func = lambda *a, **kw: _make_cache_key(func, a, kw, prefix)  # type: ignore

        return wrapper
    return decorator


def cached_async(
    ttl: float = 60.0,
    key_prefix: Optional[str] = None,
    cache: Optional[SimpleCache] = None,
    cache_null: bool = True,
    tags: Optional[List[str]] = None,
    lock_timeout: float = 10.0,
):
    """异步函数缓存装饰器

    使用方式::

        @cached_async(ttl=300, key_prefix="user_info")
        async def get_user_info(user_id: int) -> dict:
            return await db.query(user_id)

    注意：使用简单的内存锁防止缓存击穿（同一 key 并发时只有一个请求回源）。

    Args:
        ttl:          缓存过期时间（秒）
        key_prefix:   缓存键前缀，默认使用函数名
        cache:        缓存实例，不传则使用全局缓存
        cache_null:   是否缓存空值（穿透防护）
        tags:         标签列表
        lock_timeout: 单飞锁超时（秒），防止死锁
    """
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"
        # 单飞锁表（防止缓存击穿）
        _flight_locks: Dict[str, asyncio.Lock] = {}
        _flight_locks_lock = threading.Lock()

        def _get_flight_lock(key: str) -> asyncio.Lock:
            with _flight_locks_lock:
                if key not in _flight_locks:
                    _flight_locks[key] = asyncio.Lock()
                return _flight_locks[key]

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cache_instance = cache or get_cache()
            cache_key = _make_cache_key(func, args, kwargs, prefix)

            # 先尝试从缓存获取
            if cache_instance.has(cache_key):
                return cache_instance.get(cache_key)

            # 获取单飞锁，防止缓存击穿
            flight_lock = _get_flight_lock(cache_key)
            try:
                async with asyncio.wait_for(flight_lock.acquire(), timeout=lock_timeout):
                    # 双重检查：拿到锁后再查一次缓存
                    if cache_instance.has(cache_key):
                        return cache_instance.get(cache_key)

                    # 未命中，执行函数
                    result = await func(*args, **kwargs)

                    # 缓存结果
                    if (result is None or (isinstance(result, (list, dict)) and len(result) == 0)) and cache_null:
                        cache_instance.set(cache_key, NULL_VALUE, ttl=ttl, tags=tags, is_null=True)
                    elif result is not None:
                        cache_instance.set(cache_key, result, ttl=ttl, tags=tags)

                    return result
            except asyncio.TimeoutError:
                # 锁超时，直接执行（降级）
                return await func(*args, **kwargs)
            finally:
                if flight_lock.locked():
                    try:
                        flight_lock.release()
                    except RuntimeError:
                        pass

        # 添加手动失效方法
        def invalidate(*args, **kwargs):
            cache_instance = cache or get_cache()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            cache_instance.delete(cache_key)

        wrapper.invalidate = invalidate  # type: ignore
        wrapper.cache_key_func = lambda *a, **kw: _make_cache_key(func, a, kw, prefix)  # type: ignore

        return wrapper
    return decorator


# ============================================================
# 全局缓存实例
# ============================================================

_default_cache: Optional[SimpleCache] = None
_cache_lock = threading.Lock()


def get_cache() -> SimpleCache:
    """获取全局缓存单例

    根据环境变量配置：
      CACHE_MAX_SIZE       最大缓存条目数，默认 5000
      CACHE_DEFAULT_TTL    默认 TTL（秒），默认 30
      CACHE_CLEANUP_INT    后台清理间隔（秒），默认 60
      CACHE_HOT_RATIO      热点层占比，默认 0.2
      CACHE_NULL_TTL       空值缓存时间（秒），默认 30
      CACHE_JITTER         过期抖动比例，默认 0.1
    """
    global _default_cache
    if _default_cache is not None:
        return _default_cache

    with _cache_lock:
        if _default_cache is not None:
            return _default_cache

        max_size = int(os.getenv("CACHE_MAX_SIZE", "5000"))
        default_ttl = float(os.getenv("CACHE_DEFAULT_TTL", "30"))
        cleanup_interval = float(os.getenv("CACHE_CLEANUP_INT", "60"))
        hot_ratio = float(os.getenv("CACHE_HOT_RATIO", "0.2"))
        null_ttl = float(os.getenv("CACHE_NULL_TTL", "30"))
        jitter_ratio = float(os.getenv("CACHE_JITTER", "0.1"))

        _default_cache = SimpleCache(
            max_size=max_size,
            default_ttl=default_ttl,
            cleanup_interval=cleanup_interval,
            hot_ratio=hot_ratio,
            null_ttl=null_ttl,
            jitter_ratio=jitter_ratio,
        )
        return _default_cache


def reset_global_cache() -> None:
    """重置全局缓存（主要用于测试）"""
    global _default_cache
    with _cache_lock:
        if _default_cache is not None:
            _default_cache.shutdown()
            _default_cache = None


# ============================================================
# 旧版兼容 API（保留向后兼容）
# ============================================================

def get_cache_from_env() -> SimpleCache:
    """根据环境变量创建 SimpleCache 实例（旧版 API，兼容保留）

    环境变量：
      MODULE_CACHE_MAX_SIZE   最大缓存条目数，默认 1000
      MODULE_CACHE_TTL        默认 TTL（秒），默认 5
      MODULE_CACHE_CLEANUP    后台清理间隔（秒），默认 60，设为 0 禁用
    """
    max_size = int(os.getenv("MODULE_CACHE_MAX_SIZE", "1000"))
    default_ttl = float(os.getenv("MODULE_CACHE_TTL", "5"))
    cleanup_interval = float(os.getenv("MODULE_CACHE_CLEANUP", "60"))
    return SimpleCache(
        max_size=max_size,
        default_ttl=default_ttl,
        cleanup_interval=cleanup_interval,
    )


# 路径级 TTL 配置（path prefix -> ttl seconds）
# 可被环境变量 MODULE_CACHE_PATH_TTLS 覆盖，格式：
#   "/health=2,/api/config=30,/api/v1/config=30"
DEFAULT_PATH_TTL_MAP: Dict[str, float] = {
    "/health": 2.0,
    "/api/health": 2.0,
    "/config": 30.0,
    "/api/config": 30.0,
    "/api/v1/config": 30.0,
    # 新增热点路径的 TTL 配置
    "/api/modules": 10.0,
    "/api/modules/status": 5.0,
    "/api/workflows": 15.0,
    "/api/v1/workflows": 15.0,
    "/api/memories": 10.0,
}


_path_ttl_map_cache: Optional[Dict[str, float]] = None
_path_ttl_map_lock = threading.Lock()


def _get_path_ttl_map() -> Dict[str, float]:
    """读取路径 TTL 配置（支持环境变量覆盖）"""
    global _path_ttl_map_cache
    if _path_ttl_map_cache is not None:
        return _path_ttl_map_cache

    with _path_ttl_map_lock:
        if _path_ttl_map_cache is not None:
            return _path_ttl_map_cache

        ttl_map = dict(DEFAULT_PATH_TTL_MAP)

        # 环境变量覆盖
        env_ttls = os.getenv("MODULE_CACHE_PATH_TTLS", "").strip()
        if env_ttls:
            for pair in env_ttls.split(","):
                pair = pair.strip()
                if not pair or "=" not in pair:
                    continue
                path_prefix, ttl_str = pair.split("=", 1)
                path_prefix = path_prefix.strip()
                try:
                    ttl = float(ttl_str.strip())
                    if path_prefix and ttl > 0:
                        ttl_map[path_prefix] = ttl
                except ValueError:
                    continue

        _path_ttl_map_cache = ttl_map
        return ttl_map


def get_path_ttl(path: str, default_ttl: float) -> float:
    """根据路径匹配获取对应 TTL

    最长前缀匹配：path 以哪个配置的前缀开头，就用那个前缀对应的 TTL。
    没匹配到则返回 default_ttl。
    """
    ttl_map = _get_path_ttl_map()
    if not ttl_map:
        return default_ttl

    # 按前缀长度从长到短排序，优先匹配更具体的路径
    best_ttl = default_ttl
    best_len = 0
    for prefix, ttl in ttl_map.items():
        if path.startswith(prefix) and len(prefix) > best_len:
            best_ttl = ttl
            best_len = len(prefix)
    return best_ttl
