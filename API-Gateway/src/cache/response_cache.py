"""
云汐 API 网关 - 响应缓存

功能：
1. GET 请求响应缓存
2. 缓存键生成（URL + 查询参数 + 认证信息）
3. TTL 配置
4. 缓存失效机制
5. 缓存统计（命中率、大小）
"""
import hashlib
import time
import threading
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass, field


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    status_code: int
    headers: Dict[str, str]
    body: bytes
    created_at: float
    ttl: int  # 秒
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl

    @property
    def remaining_ttl(self) -> float:
        return max(0, self.ttl - (time.time() - self.created_at))

    @property
    def size_bytes(self) -> int:
        return len(self.body) + sum(
            len(k.encode()) + len(v.encode()) for k, v in self.headers.items()
        ) + len(self.key.encode())


@dataclass
class CacheConfig:
    """缓存配置

    Attributes:
        enabled: 是否启用缓存
        default_ttl: 默认 TTL（秒）
        max_size: 最大缓存大小（字节）
        max_entries: 最大缓存条目数
        cache_methods: 可缓存的 HTTP 方法
        include_auth_in_key: 是否在缓存键中包含认证信息
        vary_headers: 参与缓存键计算的请求头
    """
    enabled: bool = False
    default_ttl: int = 60  # 60秒
    max_size: int = 100 * 1024 * 1024  # 100MB
    max_entries: int = 10000
    cache_methods: List[str] = field(default_factory=lambda: ["GET", "HEAD"])
    include_auth_in_key: bool = True
    vary_headers: List[str] = field(default_factory=lambda: [
        "Accept", "Accept-Encoding", "Accept-Language"
    ])


class ResponseCache:
    """响应缓存

    使用 LRU 策略管理缓存条目。
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        self._config = config or CacheConfig()
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: List[str] = []  # LRU 顺序，最近访问的在末尾
        self._lock = threading.Lock()
        self._total_size = 0

        # 统计
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_sets": 0,
            "cache_evictions": 0,
            "cache_invalidations": 0,
        }

    def update_config(self, config: CacheConfig):
        """更新缓存配置"""
        with self._lock:
            self._config = config
            # 如果新配置更小，触发清理（不增加条目）
            self._evict_if_needed(extra_entries=0)

    def get_config(self) -> CacheConfig:
        """获取当前配置"""
        return self._config

    def generate_cache_key(
        self,
        method: str,
        url: str,
        query_params: Optional[Dict[str, Any]] = None,
        auth_info: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """生成缓存键

        Args:
            method: HTTP 方法
            url: 请求 URL
            query_params: 查询参数
            auth_info: 认证信息
            headers: 请求头

        Returns:
            缓存键（MD5 哈希）
        """
        key_parts = [method.upper(), url]

        # 查询参数
        if query_params:
            sorted_params = sorted(query_params.items(), key=lambda x: x[0])
            key_parts.append("&".join(f"{k}={v}" for k, v in sorted_params))

        # 认证信息
        if self._config.include_auth_in_key and auth_info:
            key_parts.append(f"auth:{auth_info}")

        # Vary 头
        if headers and self._config.vary_headers:
            vary_values = []
            for h in self._config.vary_headers:
                for k, v in headers.items():
                    if k.lower() == h.lower():
                        vary_values.append(f"{h}={v}")
                        break
            if vary_values:
                key_parts.append("vary:" + "&".join(sorted(vary_values)))

        raw_key = "|".join(key_parts)
        return hashlib.md5(raw_key.encode()).hexdigest()

    def get(self, cache_key: str) -> Optional[Tuple[int, Dict[str, str], bytes]]:
        """获取缓存

        Args:
            cache_key: 缓存键

        Returns:
            (status_code, headers, body) 或 None
        """
        with self._lock:
            self._stats["total_requests"] += 1

            entry = self._cache.get(cache_key)
            if entry is None:
                self._stats["cache_misses"] += 1
                return None

            if entry.expired:
                # 过期，删除
                del self._cache[cache_key]
                self._total_size -= entry.size_bytes
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._stats["cache_misses"] += 1
                return None

            # 命中，更新 LRU 顺序
            entry.hit_count += 1
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)

            self._stats["cache_hits"] += 1

            # 返回副本，避免外部修改影响缓存
            return entry.status_code, dict(entry.headers), bytes(entry.body)

    def set(
        self,
        cache_key: str,
        status_code: int,
        headers: Dict[str, str],
        body: bytes,
        ttl: Optional[int] = None,
    ) -> bool:
        """设置缓存

        Args:
            cache_key: 缓存键
            status_code: HTTP 状态码
            headers: 响应头
            body: 响应体
            ttl: TTL（秒），不指定则使用默认值

        Returns:
            是否成功设置
        """
        with self._lock:
            if not self._config.enabled:
                return False

            # 只缓存 2xx 和 3xx 响应
            if not (200 <= status_code < 400):
                return False

            # 检查内容大小（单条不超过总大小的 10%）
            content_size = len(body)
            if content_size > self._config.max_size * 0.1:
                return False

            effective_ttl = ttl if ttl is not None else self._config.default_ttl

            # 如果已存在，先移除旧的
            if cache_key in self._cache:
                old_entry = self._cache[cache_key]
                self._total_size -= old_entry.size_bytes
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)

            # 创建新条目
            entry = CacheEntry(
                key=cache_key,
                status_code=status_code,
                headers=dict(headers),
                body=bytes(body),
                created_at=time.time(),
                ttl=effective_ttl,
            )

            # 检查是否有空间
            self._evict_if_needed(extra_size=entry.size_bytes)

            # 如果还是没有空间，不缓存
            if (len(self._cache) >= self._config.max_entries
                    or self._total_size + entry.size_bytes > self._config.max_size):
                return False

            self._cache[cache_key] = entry
            self._access_order.append(cache_key)
            self._total_size += entry.size_bytes
            self._stats["cache_sets"] += 1

            return True

    def _evict_if_needed(self, extra_size: int = 0, extra_entries: int = 1):
        """如果需要，驱逐最久未使用的条目

        必须在持有锁的情况下调用。

        Args:
            extra_size: 即将新增的内容大小
            extra_entries: 即将新增的条目数
        """
        # 先清理过期条目
        expired_keys = [k for k, e in self._cache.items() if e.expired]
        for key in expired_keys:
            entry = self._cache.pop(key)
            self._total_size -= entry.size_bytes
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats["cache_evictions"] += 1

        # 驱逐 LRU 条目直到有足够空间（考虑即将新增的条目）
        while (
            len(self._cache) + extra_entries > self._config.max_entries
            or self._total_size + extra_size > self._config.max_size
        ):
            if not self._access_order:
                break

            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                entry = self._cache.pop(oldest_key)
                self._total_size -= entry.size_bytes
                self._stats["cache_evictions"] += 1

    def invalidate(self, cache_key: str) -> bool:
        """使指定缓存失效

        Returns:
            是否找到了并删除了缓存
        """
        with self._lock:
            if cache_key in self._cache:
                entry = self._cache.pop(cache_key)
                self._total_size -= entry.size_bytes
                if cache_key in self._access_order:
                    self._access_order.remove(cache_key)
                self._stats["cache_invalidations"] += 1
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """按模式失效缓存（简单的前缀匹配）

        Args:
            pattern: 键前缀模式

        Returns:
            失效的缓存数
        """
        with self._lock:
            count = 0
            keys_to_remove = [k for k in self._cache if k.startswith(pattern)]
            for key in keys_to_remove:
                entry = self._cache.pop(key)
                self._total_size -= entry.size_bytes
                if key in self._access_order:
                    self._access_order.remove(key)
                count += 1
            self._stats["cache_invalidations"] += count
            return count

    def invalidate_all(self) -> int:
        """清空所有缓存

        Returns:
            清除的缓存条目数
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._access_order.clear()
            self._total_size = 0
            self._stats["cache_invalidations"] += count
            return count

    def is_cacheable_method(self, method: str) -> bool:
        """判断方法是否可缓存"""
        return method.upper() in [m.upper() for m in self._config.cache_methods]

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            hit_rate = (
                self._stats["cache_hits"] / self._stats["total_requests"] * 100
                if self._stats["total_requests"] > 0 else 0
            )
            return {
                **self._stats,
                "hit_rate_percent": round(hit_rate, 2),
                "entries_count": len(self._cache),
                "max_entries": self._config.max_entries,
                "total_size_bytes": self._total_size,
                "max_size_bytes": self._config.max_size,
                "size_percent": round(
                    self._total_size / self._config.max_size * 100, 2
                ) if self._config.max_size > 0 else 0,
                "enabled": self._config.enabled,
                "default_ttl": self._config.default_ttl,
            }

    def reset_stats(self):
        """重置统计"""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    def get_entry_info(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """获取缓存条目信息（不影响 LRU 顺序）"""
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            return {
                "key": entry.key,
                "status_code": entry.status_code,
                "headers_count": len(entry.headers),
                "body_size": len(entry.body),
                "created_at": entry.created_at,
                "ttl": entry.ttl,
                "remaining_ttl": entry.remaining_ttl,
                "hit_count": entry.hit_count,
                "size_bytes": entry.size_bytes,
                "expired": entry.expired,
            }
