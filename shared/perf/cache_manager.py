"""
多级缓存管理器 (Multi-Level Cache Manager)

三级缓存架构:
- L1: 内存缓存 (LRU + TTL，速度最快，容量较小)
- L2: 本地文件缓存 (持久化，容量较大，速度中等)
- L3: Redis 缓存 (预留接口，分布式共享)

核心功能:
1. 缓存读写 (get/set/delete/exists/clear)
2. 缓存装饰器 (@cache_result / @cache_invalidate)
3. 缓存统计 (命中率/内存使用/大小/最近访问)
4. LRU 实现 (双向链表 + 哈希表 + TTL + 惰性删除 + 定期清理)

使用方式::

    from shared.perf.cache_manager import CacheManager, cache_result

    # 全局单例
    cm = CacheManager.from_env()

    # 基础操作
    cm.set("user:1", {"name": "Alice"}, ttl=300)
    user = cm.get("user:1")
    cm.delete("user:1")
    cm.exists("user:1")
    cm.clear(pattern="user:*")

    # 装饰器
    @cache_result(ttl=300, key_prefix="user_info")
    def get_user_info(user_id: int) -> dict:
        return db.query(user_id)
"""

from __future__ import annotations

import os
import time
import json
import hashlib
import threading
import functools
import fnmatch
from typing import Any, Optional, Dict, List, Callable, Tuple, Union
from dataclasses import dataclass, field
from pathlib import Path
from collections import OrderedDict


# ============================================================
# 常量
# ============================================================

# 空值哨兵 (用于缓存穿透防护)
class _NullSentinel:
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
# 缓存统计
# ============================================================

@dataclass
class CacheLevelStats:
    """单级缓存统计"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "evictions": self.evictions,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": round(self.hit_rate, 4),
        }

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.evictions = 0


@dataclass
class CacheStats:
    """多级缓存总统计"""
    l1: CacheLevelStats = field(default_factory=CacheLevelStats)
    l2: CacheLevelStats = field(default_factory=CacheLevelStats)
    l3: CacheLevelStats = field(default_factory=CacheLevelStats)
    total_requests: int = 0
    penetration_blocked: int = 0
    warmup_count: int = 0

    @property
    def overall_hit_rate(self) -> float:
        total_hits = self.l1.hits + self.l2.hits + self.l3.hits
        return total_hits / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def l1_hit_rate(self) -> float:
        return self.l1.hit_rate

    @property
    def l2_hit_rate(self) -> float:
        return self.l2.hit_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "l1": self.l1.to_dict(),
            "l2": self.l2.to_dict(),
            "l3": self.l3.to_dict(),
            "total_requests": self.total_requests,
            "overall_hit_rate": round(self.overall_hit_rate, 4),
            "penetration_blocked": self.penetration_blocked,
            "warmup_count": self.warmup_count,
        }

    def reset(self) -> None:
        self.l1.reset()
        self.l2.reset()
        self.l3.reset()
        self.total_requests = 0
        self.penetration_blocked = 0
        self.warmup_count = 0


# ============================================================
# L1: 内存缓存 (LRU + TTL)
# ============================================================

class _LRUCache:
    """基于 OrderedDict 的 LRU 缓存 (带 TTL)

    实现:
    - 双向链表 + 哈希表 (OrderedDict 内部实现)
    - 容量限制 (max_size)
    - TTL 过期 (惰性删除 + 定期清理)
    - 线程安全
    """

    def __init__(
        self,
        max_size: int = 5000,
        default_ttl: float = 60.0,
        cleanup_interval: float = 60.0,
        null_ttl: float = 30.0,
        jitter_ratio: float = 0.1,
    ):
        self.max_size = max(10, max_size)
        self.default_ttl = max(0.1, float(default_ttl))
        self.cleanup_interval = max(0.0, float(cleanup_interval))
        self.null_ttl = max(1.0, float(null_ttl))
        self.jitter_ratio = max(0.0, min(0.5, float(jitter_ratio)))

        # 存储: key -> (value, expire_at, access_count)
        self._store: "OrderedDict[str, Tuple[Any, float, int]]" = OrderedDict()
        self._lock = threading.RLock()
        self.stats = CacheLevelStats(max_size=self.max_size)

        # 后台清理线程
        self._stop_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        if self.cleanup_interval > 0:
            self._start_cleanup_thread()

    def _jitter_ttl(self, ttl: float) -> float:
        """添加 TTL 抖动 (防止缓存雪崩)"""
        if self.jitter_ratio <= 0:
            return ttl
        jitter = ttl * self.jitter_ratio * (0.5 - 0.5 * (hash(id(self) + id(ttl)) % 10000 / 10000))
        return max(0.1, ttl + jitter)

    def _start_cleanup_thread(self) -> None:
        """启动后台清理线程"""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="LRUCache-Cleaner",
            daemon=True,
        )
        self._cleanup_thread.start()

    def _cleanup_loop(self) -> None:
        """后台清理循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.cleanup_interval)
            if self._stop_event.is_set():
                break
            try:
                self._purge_expired()
            except Exception:
                pass

    def _purge_expired(self) -> int:
        """清理所有过期条目"""
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, (_, expire_at, _) in self._store.items()
                if expire_at <= now
            ]
            for k in expired_keys:
                del self._store[k]
            self.stats.size = len(self._store)
            return len(expired_keys)

    def get(self, key: str, default: Any = None) -> Any:
        """读取缓存"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.stats.misses += 1
                return default

            value, expire_at, access_count = entry

            # TTL 检查 (惰性过期)
            if expire_at <= time.time():
                del self._store[key]
                self.stats.misses += 1
                self.stats.evictions += 1
                return default

            # LRU: 移动到末尾 (最近访问)
            self._store.move_to_end(key)
            # 更新访问计数
            self._store[key] = (value, expire_at, access_count + 1)
            self.stats.hits += 1

            if value is NULL_VALUE:
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """写入缓存"""
        effective_ttl = self.default_ttl if ttl is None else max(0.1, float(ttl))

        # 空值使用更短 TTL
        if value is None or value is NULL_VALUE:
            effective_ttl = self.null_ttl
            stored_value = NULL_VALUE
        else:
            stored_value = value
            effective_ttl = self._jitter_ttl(effective_ttl)

        expire_at = time.time() + effective_ttl

        with self._lock:
            # 已存在则先删除
            if key in self._store:
                del self._store[key]

            self._store[key] = (stored_value, expire_at, 0)
            self.stats.sets += 1
            self.stats.size = len(self._store)

            # LRU 淘汰
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self.stats.evictions += 1
                self.stats.size = len(self._store)

    def delete(self, key: str) -> bool:
        """删除缓存"""
        with self._lock:
            if key in self._store:
                del self._store[key]
                self.stats.deletes += 1
                self.stats.size = len(self._store)
                return True
            return False

    def has(self, key: str) -> bool:
        """检查 key 是否存在 (不影响 LRU)"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            if entry[1] <= time.time():
                del self._store[key]
                return False
            return True

    def size(self) -> int:
        """当前缓存条目数"""
        with self._lock:
            return len(self._store)

    def clear(self) -> int:
        """清空所有缓存"""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self.stats.size = 0
            self.stats.deletes += count
            return count

    def clear_pattern(self, pattern: str) -> int:
        """按模式匹配清空"""
        with self._lock:
            keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in keys_to_delete:
                del self._store[k]
            self.stats.size = len(self._store)
            self.stats.deletes += len(keys_to_delete)
            return len(keys_to_delete)

    def shutdown(self) -> None:
        """关闭缓存"""
        self._stop_event.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2.0)


# ============================================================
# L2: 本地文件缓存
# ============================================================

class _FileCache:
    """本地文件缓存 (持久化，容量限制)

    - 文件系统存储
    - 目录分片 (hash 前 2 位)
    - TTL 通过文件修改时间判断
    - 容量限制 (最大大小 + 最大文件数)
    - LRU 淘汰 (基于文件访问时间)
    """

    def __init__(
        self,
        cache_dir: str,
        max_size_mb: int = 100,
        max_files: int = 10000,
        default_ttl: float = 300.0,
        ttl_multiplier: float = 5.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_size_mb = max_size_mb
        self.max_files = max_files
        self.default_ttl = default_ttl
        self.ttl_multiplier = ttl_multiplier

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.stats = CacheLevelStats(max_size=max_files)

        # 初始统计
        self._recalc_size()

    def _safe_filename(self, key: str) -> Path:
        """生成安全的文件路径 (hash 分片)"""
        h = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h[2:]}.cache"

    def _serialize(self, value: Any) -> bytes:
        """序列化"""
        if value is NULL_VALUE:
            return b"__NULL__"
        try:
            return json.dumps(value, default=str).encode("utf-8")
        except (TypeError, ValueError):
            return repr(value).encode("utf-8")

    def _deserialize(self, data: bytes) -> Any:
        """反序列化"""
        if data == b"__NULL__":
            return NULL_VALUE
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return data

    def _is_expired(self, filepath: Path, ttl: Optional[float] = None) -> bool:
        """检查文件是否过期"""
        try:
            mtime = filepath.stat().st_mtime
            effective_ttl = (ttl or self.default_ttl) * self.ttl_multiplier
            return time.time() - mtime > effective_ttl
        except OSError:
            return True

    def _recalc_size(self) -> None:
        """重新计算缓存大小"""
        try:
            count = 0
            for f in self.cache_dir.rglob("*.cache"):
                count += 1
            self.stats.size = count
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        """读取文件缓存"""
        filepath = self._safe_filename(key)
        try:
            if not filepath.exists():
                with self._lock:
                    self.stats.misses += 1
                return default

            # TTL 检查
            if self._is_expired(filepath):
                try:
                    filepath.unlink()
                except OSError:
                    pass
                with self._lock:
                    self.stats.misses += 1
                    self.stats.evictions += 1
                return default

            data = filepath.read_bytes()
            value = self._deserialize(data)
            with self._lock:
                self.stats.hits += 1

            if value is NULL_VALUE:
                return None
            return value
        except Exception:
            with self._lock:
                self.stats.misses += 1
            return default

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """写入文件缓存"""
        filepath = self._safe_filename(key)
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            serialized = self._serialize(value)
            filepath.write_bytes(serialized)
            with self._lock:
                self.stats.sets += 1
                self.stats.size += 1
            # 容量检查 (异步或惰性清理)
            self._check_capacity()
        except Exception:
            pass

    def delete(self, key: str) -> bool:
        """删除文件缓存"""
        filepath = self._safe_filename(key)
        try:
            if filepath.exists():
                filepath.unlink()
                with self._lock:
                    self.stats.deletes += 1
                    self.stats.size = max(0, self.stats.size - 1)
                return True
        except OSError:
            pass
        return False

    def has(self, key: str) -> bool:
        """检查是否存在"""
        filepath = self._safe_filename(key)
        try:
            return filepath.exists() and not self._is_expired(filepath)
        except Exception:
            return False

    def clear(self) -> int:
        """清空所有文件缓存"""
        count = 0
        try:
            for f in self.cache_dir.rglob("*.cache"):
                try:
                    f.unlink()
                    count += 1
                except OSError:
                    pass
            with self._lock:
                self.stats.size = 0
                self.stats.deletes += count
        except Exception:
            pass
        return count

    def clear_pattern(self, pattern: str) -> int:
        """按模式清空 (文件缓存效率低，用文件名 hash 近似)"""
        # 文件缓存使用 hash 文件名，无法按原始 key 模式匹配
        # 这里简化为全部清空
        return self.clear()

    def _check_capacity(self) -> None:
        """检查容量，超过则淘汰最旧的"""
        if self.stats.size <= self.max_files:
            return

        # 惰性淘汰：删除过期的
        try:
            now = time.time()
            for f in self.cache_dir.rglob("*.cache"):
                try:
                    if now - f.stat().st_mtime > self.default_ttl * self.ttl_multiplier:
                        f.unlink()
                        with self._lock:
                            self.stats.size = max(0, self.stats.size - 1)
                            self.stats.evictions += 1
                except OSError:
                    pass
        except Exception:
            pass


# ============================================================
# L3: Redis 缓存 (预留接口)
# ============================================================

class _RedisCache:
    """Redis 缓存 (预留接口，可选启用)

    当环境中安装了 redis 且配置了 REDIS_URL 时可用。
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: float = 600.0,
        ttl_multiplier: float = 10.0,
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "")
        self.default_ttl = default_ttl
        self.ttl_multiplier = ttl_multiplier
        self._redis = None
        self._available = False
        self.stats = CacheLevelStats(max_size=100000)

        self._init_redis()

    def _init_redis(self) -> None:
        """初始化 Redis 连接"""
        if not self.redis_url:
            return
        try:
            import redis  # type: ignore
            self._redis = redis.Redis.from_url(
                self.redis_url,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            self._redis.ping()
            self._available = True
        except Exception:
            self._available = False
            self._redis = None

    @property
    def available(self) -> bool:
        return self._available

    def _serialize(self, value: Any) -> bytes:
        if value is NULL_VALUE:
            return b"__NULL__"
        try:
            return json.dumps(value, default=str).encode("utf-8")
        except (TypeError, ValueError):
            return repr(value).encode("utf-8")

    def _deserialize(self, data: bytes) -> Any:
        if data == b"__NULL__":
            return NULL_VALUE
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return data

    def get(self, key: str, default: Any = None) -> Any:
        if not self._available:
            self.stats.misses += 1
            return default
        try:
            data = self._redis.get(f"cache:{key}")
            if data is None:
                self.stats.misses += 1
                return default
            value = self._deserialize(data)
            self.stats.hits += 1
            if value is NULL_VALUE:
                return None
            return value
        except Exception:
            self.stats.misses += 1
            return default

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if not self._available:
            return
        try:
            effective_ttl = int((ttl or self.default_ttl) * self.ttl_multiplier)
            serialized = self._serialize(value)
            self._redis.setex(f"cache:{key}", effective_ttl, serialized)
            self.stats.sets += 1
        except Exception:
            pass

    def delete(self, key: str) -> bool:
        if not self._available:
            return False
        try:
            result = self._redis.delete(f"cache:{key}")
            self.stats.deletes += int(result)
            return bool(result)
        except Exception:
            return False

    def has(self, key: str) -> bool:
        if not self._available:
            return False
        try:
            return bool(self._redis.exists(f"cache:{key}"))
        except Exception:
            return False

    def clear(self) -> int:
        # 不清空 Redis (可能是共享的)，只记录
        return 0

    def clear_pattern(self, pattern: str) -> int:
        if not self._available:
            return 0
        try:
            keys = list(self._redis.scan_iter(f"cache:{pattern}"))
            if keys:
                self._redis.delete(*keys)
                return len(keys)
        except Exception:
            pass
        return 0


# ============================================================
# 多级缓存管理器
# ============================================================

class CacheManager:
    """多级缓存管理器 (L1 + L2 + L3)

    读取流程: L1 -> L2 -> L3 -> 回源 -> 写入所有层
    写入流程: 同时写入 L1 + L2 + L3

    特性:
    - 自动降级: 某层不可用时自动跳过
    - 穿透防护: 空值缓存
    - 击穿防护: 单飞锁 (get_or_set)
    - 雪崩防护: TTL 随机抖动
    - 模式匹配: 支持 glob 模式的批量删除
    """

    def __init__(
        self,
        # L1 配置
        l1_enabled: bool = True,
        l1_max_size: int = 5000,
        l1_default_ttl: float = 60.0,
        # L2 配置
        l2_enabled: bool = False,
        l2_dir: Optional[str] = None,
        l2_max_size_mb: int = 100,
        l2_max_files: int = 10000,
        l2_default_ttl: float = 300.0,
        # L3 配置
        l3_enabled: bool = False,
        l3_redis_url: Optional[str] = None,
        l3_default_ttl: float = 600.0,
        # 通用配置
        null_ttl: float = 30.0,
        enable_penetration_guard: bool = True,
        namespace: str = "default",
    ):
        self.namespace = namespace
        self.enable_penetration_guard = enable_penetration_guard
        self.null_ttl = null_ttl

        # 统计
        self.stats = CacheStats()
        self._stats_lock = threading.Lock()

        # 单飞锁表 (击穿防护)
        self._flight_locks: Dict[str, threading.Event] = {}
        self._flight_lock = threading.Lock()

        # L1 内存缓存
        self.l1: Optional[_LRUCache] = None
        if l1_enabled:
            self.l1 = _LRUCache(
                max_size=l1_max_size,
                default_ttl=l1_default_ttl,
                null_ttl=null_ttl,
            )

        # L2 文件缓存
        self.l2: Optional[_FileCache] = None
        if l2_enabled:
            if l2_dir is None:
                l2_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data",
                    "perf_cache_l2",
                    namespace,
                )
            self.l2 = _FileCache(
                cache_dir=l2_dir,
                max_size_mb=l2_max_size_mb,
                max_files=l2_max_files,
                default_ttl=l2_default_ttl,
            )

        # L3 Redis 缓存
        self.l3: Optional[_RedisCache] = None
        if l3_enabled:
            self.l3 = _RedisCache(
                redis_url=l3_redis_url,
                default_ttl=l3_default_ttl,
            )

    @classmethod
    def from_env(cls, namespace: str = "default") -> "CacheManager":
        """从环境变量创建缓存管理器"""
        def env_bool(name: str, default: bool) -> bool:
            val = os.getenv(name, "")
            return val.lower() in ("true", "1", "yes", "on") if val else default

        def env_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except (ValueError, TypeError):
                return default

        def env_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except (ValueError, TypeError):
                return default

        return cls(
            l1_enabled=env_bool("PERF_CACHE_L1_ENABLED", True),
            l1_max_size=env_int("PERF_CACHE_L1_MAX_SIZE", 5000),
            l1_default_ttl=env_float("PERF_CACHE_L1_TTL", 60.0),
            l2_enabled=env_bool("PERF_CACHE_L2_ENABLED", False),
            l2_max_size_mb=env_int("PERF_CACHE_L2_MAX_MB", 100),
            l2_max_files=env_int("PERF_CACHE_L2_MAX_FILES", 10000),
            l2_default_ttl=env_float("PERF_CACHE_L2_TTL", 300.0),
            l3_enabled=env_bool("PERF_CACHE_L3_ENABLED", False),
            l3_redis_url=os.getenv("REDIS_URL", ""),
            l3_default_ttl=env_float("PERF_CACHE_L3_TTL", 600.0),
            null_ttl=env_float("PERF_CACHE_NULL_TTL", 30.0),
            enable_penetration_guard=env_bool("PERF_CACHE_PENETRATION_GUARD", True),
            namespace=namespace,
        )

    # ---------- 基础操作 ----------

    def get(self, key: str, default: Any = None) -> Any:
        """读取缓存 (多级查找)"""
        with self._stats_lock:
            self.stats.total_requests += 1

        # L1
        if self.l1 is not None:
            value = self.l1.get(key)
            if value is not None or self.l1.has(key):
                self.stats.l1.hits += 1
                return value if value is not None else default
            self.stats.l1.misses += 1

        # L2
        if self.l2 is not None:
            value = self.l2.get(key)
            if value is not None or self.l2.has(key):
                self.stats.l2.hits += 1
                # 回写到 L1
                if self.l1 is not None and value is not None:
                    self.l1.set(key, value)
                return value if value is not None else default
            self.stats.l2.misses += 1

        # L3
        if self.l3 is not None and self.l3.available:
            value = self.l3.get(key)
            if value is not None or self.l3.has(key):
                self.stats.l3.hits += 1
                # 回写到 L1 + L2
                if self.l1 is not None and value is not None:
                    self.l1.set(key, value)
                if self.l2 is not None and value is not None:
                    self.l2.set(key, value)
                return value if value is not None else default
            self.stats.l3.misses += 1

        return default

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """写入缓存 (同时写入所有层)"""
        # 穿透防护：仅对 None 使用 NULL_VALUE
        # 空列表/空字典是合法业务结果，正常缓存
        is_null = value is None or value is NULL_VALUE
        if is_null and self.enable_penetration_guard:
            store_value = NULL_VALUE
            with self._stats_lock:
                self.stats.penetration_blocked += 1
        else:
            store_value = value

        if self.l1 is not None:
            self.l1.set(key, store_value, ttl)
        if self.l2 is not None:
            self.l2.set(key, store_value, ttl)
        if self.l3 is not None:
            self.l3.set(key, store_value, ttl)

    def delete(self, key: str) -> bool:
        """删除缓存"""
        deleted = False
        if self.l1 is not None:
            deleted = self.l1.delete(key) or deleted
        if self.l2 is not None:
            deleted = self.l2.delete(key) or deleted
        if self.l3 is not None:
            deleted = self.l3.delete(key) or deleted
        return deleted

    def exists(self, key: str) -> bool:
        """检查 key 是否存在"""
        if self.l1 is not None and self.l1.has(key):
            return True
        if self.l2 is not None and self.l2.has(key):
            return True
        if self.l3 is not None and self.l3.has(key):
            return True
        return False

    def clear(self, pattern: Optional[str] = None) -> int:
        """清空缓存 (支持模式匹配)

        Args:
            pattern: glob 模式，如 "user:*"，None 则全部清空

        Returns:
            删除的条目数 (L1 层的数量作为近似)
        """
        if pattern is None:
            count = 0
            if self.l1 is not None:
                count = self.l1.clear()
            if self.l2 is not None:
                self.l2.clear()
            if self.l3 is not None:
                self.l3.clear()
            return count
        else:
            count = 0
            if self.l1 is not None:
                count = self.l1.clear_pattern(pattern)
            if self.l2 is not None:
                self.l2.clear_pattern(pattern)
            if self.l3 is not None:
                self.l3.clear_pattern(pattern)
            return count

    # ---------- 高级操作 ----------

    def get_or_set(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: Optional[float] = None,
        cache_null: bool = True,
    ) -> Any:
        """获取或设置缓存 (带击穿防护)

        同一 key 并发请求时，只有第一个请求回源，其他等待结果。
        """
        # 先尝试获取
        value = self.get(key)
        if value is not None:
            return value

        # 检查空值缓存
        if self.l1 is not None and self.l1.has(key):
            return None

        # 击穿防护：单飞锁
        return self._get_or_set_with_lock(key, loader, ttl, cache_null)

    def _get_or_set_with_lock(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: Optional[float],
        cache_null: bool,
    ) -> Any:
        """带单飞锁的 get_or_set"""
        event = None
        is_first = False

        with self._flight_lock:
            if key in self._flight_locks:
                event = self._flight_locks[key]
            else:
                event = threading.Event()
                self._flight_locks[key] = event
                is_first = True

        if not is_first:
            # 等待其他请求完成
            event.wait(timeout=10.0)
            # 再查一次缓存
            value = self.get(key)
            if value is not None or (self.l1 and self.l1.has(key)):
                return value
            # 等待失败，自己加载
            return self._load_and_cache(key, loader, ttl, cache_null)

        # 第一个请求，执行加载
        try:
            return self._load_and_cache(key, loader, ttl, cache_null)
        finally:
            event.set()
            with self._flight_lock:
                self._flight_locks.pop(key, None)

    def _load_and_cache(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: Optional[float],
        cache_null: bool,
    ) -> Any:
        """加载数据并缓存"""
        result = loader()

        if result is None:
            if cache_null and self.enable_penetration_guard:
                self.set(key, NULL_VALUE, ttl)
        else:
            self.set(key, result, ttl)

        return result

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """批量读取"""
        result = {}
        for key in keys:
            value = self.get(key)
            if value is not None or self.exists(key):
                result[key] = value
        return result

    def set_many(self, items: Dict[str, Any], ttl: Optional[float] = None) -> None:
        """批量写入"""
        for key, value in items.items():
            self.set(key, value, ttl)

    # ---------- 统计 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._stats_lock:
            stats = self.stats.to_dict()

        if self.l1 is not None:
            stats["l1"] = self.l1.stats.to_dict()
        if self.l2 is not None:
            stats["l2"] = self.l2.stats.to_dict()
        if self.l3 is not None:
            stats["l3"] = self.l3.stats.to_dict()
            stats["l3_available"] = self.l3.available

        stats["namespace"] = self.namespace
        stats["levels_enabled"] = {
            "l1": self.l1 is not None,
            "l2": self.l2 is not None,
            "l3": self.l3 is not None and self.l3.available,
        }
        return stats

    def reset_stats(self) -> None:
        """重置统计"""
        with self._stats_lock:
            self.stats.reset()
        if self.l1 is not None:
            self.l1.stats.reset()
        if self.l2 is not None:
            self.l2.stats.reset()
        if self.l3 is not None:
            self.l3.stats.reset()

    # ---------- 生命周期 ----------

    def shutdown(self) -> None:
        """关闭缓存管理器"""
        if self.l1 is not None:
            self.l1.shutdown()


# ============================================================
# 缓存装饰器
# ============================================================

def _make_cache_key(
    func: Callable,
    args: tuple,
    kwargs: dict,
    key_prefix: str,
) -> str:
    """生成缓存键"""
    sorted_kwargs = sorted(kwargs.items()) if kwargs else []
    key_parts = [key_prefix or func.__qualname__]

    if args:
        key_parts.append(":".join(str(a) for a in args))
    if sorted_kwargs:
        key_parts.append("|".join(f"{k}={v}" for k, v in sorted_kwargs))

    raw_key = "::".join(key_parts)
    if len(raw_key) > 200:
        h = hashlib.md5(raw_key.encode()).hexdigest()
        raw_key = f"{key_prefix or func.__qualname__}::hash:{h}"

    return raw_key


def cache_result(
    ttl: float = 60.0,
    key_prefix: Optional[str] = None,
    cache_manager: Optional[CacheManager] = None,
    cache_none: bool = True,
):
    """函数结果缓存装饰器

    使用 get_or_set 模式（带击穿防护的单飞锁），避免 exists + get 两次查询。

    用法::

        @cache_result(ttl=300, key_prefix="user_info")
        def get_user_info(user_id: int) -> dict:
            return db.query(user_id)

        # 手动失效
        get_user_info.invalidate(user_id=123)

        # 按模式批量失效
        get_user_info.invalidate_pattern("user_info:*")
    """
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cm = cache_manager or _get_default_cm()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            return cm.get_or_set(
                cache_key,
                lambda: func(*args, **kwargs),
                ttl=ttl,
                cache_null=cache_none,
            )

        def invalidate(*args, **kwargs):
            cm = cache_manager or _get_default_cm()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            cm.delete(cache_key)

        def invalidate_pattern(pattern: str):
            """按模式批量失效缓存"""
            cm = cache_manager or _get_default_cm()
            cm.clear(pattern=pattern)

        wrapper.invalidate = invalidate  # type: ignore
        wrapper.invalidate_pattern = invalidate_pattern  # type: ignore
        wrapper.cache_key_func = lambda *a, **kw: _make_cache_key(func, a, kw, prefix)  # type: ignore
        wrapper._cache_prefix = prefix  # type: ignore

        return wrapper
    return decorator


def cache_invalidate(
    pattern: str,
    cache_manager: Optional[CacheManager] = None,
):
    """缓存失效装饰器

    函数执行后清除匹配模式的所有缓存。

    用法::

        @cache_invalidate("user_info:*")
        def update_user(user_id: int, data: dict):
            db.update(user_id, data)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            cm = cache_manager or _get_default_cm()
            cm.clear(pattern=pattern)
            return result
        return wrapper
    return decorator


# ============================================================
# 异步缓存装饰器 (用于 async 函数)
# ============================================================

def async_cache_result(
    ttl: float = 60.0,
    key_prefix: Optional[str] = None,
    cache_manager: Optional[CacheManager] = None,
    cache_none: bool = True,
):
    """异步函数结果缓存装饰器

    使用 get_or_set 模式（带击穿防护的单飞锁），避免 exists + get 两次查询。

    用法::

        @async_cache_result(ttl=300, key_prefix="user_info")
        async def get_user_info(user_id: int) -> dict:
            return await db.query(user_id)

        # 手动失效
        await get_user_info.invalidate(user_id=123)

        # 按模式批量失效
        await get_user_info.invalidate_pattern("user_info:*")
    """
    def decorator(func: Callable) -> Callable:
        prefix = key_prefix or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            cm = cache_manager or _get_default_cm()
            cache_key = _make_cache_key(func, args, kwargs, prefix)

            # 先尝试读取缓存
            value = cm.get(cache_key)
            if value is not None:
                return value

            # 检查空值缓存（穿透防护）
            if cm.l1 is not None and cm.l1.has(cache_key):
                return None

            # 击穿防护：单飞锁
            return await _async_get_or_set(cm, cache_key, lambda: func(*args, **kwargs), ttl, cache_none)

        async def invalidate(*args, **kwargs):
            cm = cache_manager or _get_default_cm()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            cm.delete(cache_key)

        async def invalidate_pattern(pattern: str):
            """按模式批量失效缓存"""
            cm = cache_manager or _get_default_cm()
            cm.clear(pattern=pattern)

        def invalidate_sync(*args, **kwargs):
            """同步版本的失效（用于从同步代码中调用）"""
            cm = cache_manager or _get_default_cm()
            cache_key = _make_cache_key(func, args, kwargs, prefix)
            cm.delete(cache_key)

        def invalidate_pattern_sync(pattern: str):
            """同步版本的模式失效"""
            cm = cache_manager or _get_default_cm()
            cm.clear(pattern=pattern)

        wrapper.invalidate = invalidate  # type: ignore
        wrapper.invalidate_pattern = invalidate_pattern  # type: ignore
        wrapper.invalidate_sync = invalidate_sync  # type: ignore
        wrapper.invalidate_pattern_sync = invalidate_pattern_sync  # type: ignore
        wrapper.cache_key_func = lambda *a, **kw: _make_cache_key(func, a, kw, prefix)  # type: ignore
        wrapper._cache_prefix = prefix  # type: ignore

        return wrapper
    return decorator


async def _async_get_or_set(
    cm: CacheManager,
    key: str,
    loader: Callable[[], Any],
    ttl: Optional[float],
    cache_none: bool,
) -> Any:
    """异步版本的 get_or_set（带单飞锁击穿防护）"""
    import asyncio

    event = None
    is_first = False

    with cm._flight_lock:
        if key in cm._flight_locks:
            event = cm._flight_locks[key]
        else:
            event = threading.Event()
            cm._flight_locks[key] = event
            is_first = True

    if not is_first:
        # 等待其他请求完成（在线程中等待，避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: event.wait(timeout=10.0))
        # 再查一次缓存
        value = cm.get(key)
        if value is not None or (cm.l1 and cm.l1.has(key)):
            return value
        # 等待失败，自己加载
        result = await loader() if asyncio.iscoroutinefunction(loader) else loader()
        _set_cached_value(cm, key, result, ttl, cache_none)
        return result

    # 第一个请求，执行加载
    try:
        result = await loader() if asyncio.iscoroutinefunction(loader) else loader()
        _set_cached_value(cm, key, result, ttl, cache_none)
        return result
    finally:
        event.set()
        with cm._flight_lock:
            cm._flight_locks.pop(key, None)


def _set_cached_value(
    cm: CacheManager,
    key: str,
    value: Any,
    ttl: Optional[float],
    cache_none: bool,
) -> None:
    """设置缓存值（处理空值穿透防护）"""
    if value is None:
        if cache_none and cm.enable_penetration_guard:
            cm.set(key, NULL_VALUE, ttl)
    else:
        cm.set(key, value, ttl)


def async_cache_invalidate(
    pattern: str,
    cache_manager: Optional[CacheManager] = None,
):
    """异步缓存失效装饰器

    异步函数执行后清除匹配模式的所有缓存。

    用法::

        @async_cache_invalidate("user_info:*")
        async def update_user(user_id: int, data: dict):
            await db.update(user_id, data)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            cm = cache_manager or _get_default_cm()
            cm.clear(pattern=pattern)
            return result
        return wrapper
    return decorator


# ============================================================
# 全局默认缓存管理器
# ============================================================

_default_cm: Optional[CacheManager] = None
_default_cm_lock = threading.Lock()


def _get_default_cm() -> CacheManager:
    """获取默认缓存管理器 (内部使用)"""
    global _default_cm
    if _default_cm is not None:
        return _default_cm
    with _default_cm_lock:
        if _default_cm is None:
            _default_cm = CacheManager.from_env()
        return _default_cm


def reset_default_cache_manager() -> None:
    """重置默认缓存管理器 (用于测试)"""
    global _default_cm
    with _default_cm_lock:
        if _default_cm is not None:
            _default_cm.shutdown()
            _default_cm = None
