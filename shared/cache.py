"""
云汐系统本地缓存层
基于内存的 TTL + LRU 缓存，用于减少跨模块 HTTP 调用

SimpleCache 特性：
  - 线程安全（threading.Lock）
  - TTL 过期（惰性清理 + 定期后台清理）
  - 最大容量限制（LRU 淘汰）
  - 缓存统计（命中/未命中/命中率/淘汰数）
"""

import os
import time
import threading
from collections import OrderedDict
from typing import Any, Optional, Dict


class CacheStats:
    """缓存统计信息"""

    __slots__ = ("hits", "misses", "evictions", "sets", "deletes")

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.sets = 0
        self.deletes = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        total = self.total_requests
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
            "total_requests": self.total_requests,
            "hit_rate": round(self.hit_rate, 4),
        }

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.sets = 0
        self.deletes = 0


class SimpleCache:
    """基于内存的 TTL + LRU 缓存

    线程安全，支持：
      - set(key, value, ttl)     写入缓存，ttl 单位秒
      - get(key)                 读取缓存，过期或不存在返回 None
      - delete(key)              删除指定 key
      - clear()                  清空所有缓存
      - delete_prefix(prefix)    按前缀批量删除（用于写操作后清理）
      - get_stats()              获取统计信息
      - reset_stats()            重置统计

    内部使用 OrderedDict 实现 LRU：
      - 最新访问的条目在末尾（move_to_end）
      - 容量满时淘汰最旧（最早访问）的条目（popitem(last=False)）
    """

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: float = 5.0,
        cleanup_interval: float = 60.0,
    ) -> None:
        """
        Args:
            max_size:         最大缓存条目数，超过后按 LRU 淘汰
            default_ttl:      默认过期时间（秒），可被 set 时的 ttl 覆盖
            cleanup_interval: 后台定期清理间隔（秒），设为 0 则禁用后台清理
        """
        self.max_size = max(1, max_size)
        self.default_ttl = max(0.1, float(default_ttl))
        self.cleanup_interval = max(0.0, float(cleanup_interval))

        # _store[key] = (expire_at, value)
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._stats = CacheStats()

        # 后台清理线程
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        if self.cleanup_interval > 0:
            self._start_cleanup_thread()

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
        """清理所有已过期的条目，返回清理数量（调用方需自行加锁）"""
        now = time.time()
        expired_keys = [
            key for key, (expire_at, _) in self._store.items() if expire_at <= now
        ]
        for key in expired_keys:
            del self._store[key]
        return len(expired_keys)

    # ---------- 公共 API ----------

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """写入缓存

        Args:
            key:   缓存键
            value: 缓存值
            ttl:   过期时间（秒），不传则使用 default_ttl
        """
        effective_ttl = self.default_ttl if ttl is None else max(0.1, float(ttl))
        expire_at = time.time() + effective_ttl

        with self._lock:
            # 已存在则先删再插（更新位置到末尾 = 最新）
            if key in self._store:
                del self._store[key]
            self._store[key] = (expire_at, value)
            self._stats.sets += 1

            # LRU 淘汰：超出容量时淘汰最久未访问的
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self._stats.evictions += 1

    def get(self, key: str) -> Optional[Any]:
        """读取缓存

        Returns:
            缓存值；若 key 不存在或已过期，返回 None
        """
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self._stats.misses += 1
                return None

            expire_at, value = item
            if expire_at <= time.time():
                # 惰性过期
                del self._store[key]
                self._stats.misses += 1
                return None

            # 命中：移到末尾（LRU 刷新访问时间）
            self._store.move_to_end(key)
            self._stats.hits += 1
            return value

    def delete(self, key: str) -> bool:
        """删除指定 key

        Returns:
            True 表示 key 存在并已删除，False 表示 key 不存在
        """
        with self._lock:
            if key in self._store:
                del self._store[key]
                self._stats.deletes += 1
                return True
            return False

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
        with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._store[k]
            self._stats.deletes += len(keys_to_delete)
            return len(keys_to_delete)

    def clear(self) -> int:
        """清空所有缓存，返回被清除的条目数"""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._stats.deletes += count
            return count

    def has(self, key: str) -> bool:
        """判断 key 是否存在且未过期（不影响 LRU 顺序和统计）"""
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return False
            expire_at, _ = item
            if expire_at <= time.time():
                del self._store[key]
                return False
            return True

    def size(self) -> int:
        """返回当前缓存条目数（含可能已过期但未清理的条目）"""
        with self._lock:
            # 顺手做一次惰性清理（只清理最旧的若干过期条目，避免阻塞）
            self._lazy_purge_head()
            return len(self._store)

    def _lazy_purge_head(self) -> None:
        """从字典头部开始惰性清理，遇到第一个未过期的就停止

        由于 OrderedDict 按访问时间排序，最旧的在头部，
        所以只需从头部开始清理过期条目即可，效率较高。
        """
        now = time.time()
        while self._store:
            key, (expire_at, _) = next(iter(self._store.items()))
            if expire_at <= now:
                del self._store[key]
            else:
                break

    # ---------- 统计 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            stats = self._stats.to_dict()
            stats["size"] = len(self._store)
            stats["max_size"] = self.max_size
            stats["default_ttl"] = self.default_ttl
            return stats

    def reset_stats(self) -> None:
        """重置统计计数"""
        with self._lock:
            self._stats.reset()

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


# ==================== 全局缓存配置 ====================

def get_cache_from_env() -> SimpleCache:
    """根据环境变量创建 SimpleCache 实例

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
}


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
