"""M11 MCP Bus - 限流服务.

提供内存和 Redis 两种限流实现，支持多实例部署。
- MemoryRateLimiter: 基于内存的令牌桶算法，单实例高性能
- RedisRateLimiter: 基于 Redis INCR + EXPIRE 的滑动窗口限流，支持多实例共享
- get_rate_limiter(): 工厂函数，根据配置自动选择后端
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict

from ..config import get_settings

logger = logging.getLogger(__name__)


# ============================================================
# 内存限流器
# ============================================================

class _RateLimitBucket:
    """令牌桶数据结构.

    记录某个 key 的请求计数和时间窗口。
    """

    def __init__(self) -> None:
        """初始化令牌桶."""
        self.count: int = 0
        self.window_start: float = time.time()


class MemoryRateLimiter:
    """限流服务 - 基于内存滑动窗口的令牌桶算法.

    为每个 key 维护独立的计数窗口，支持按时间窗口
    自动重置，同时提供剩余请求数查询功能。

    特点：
    - 基于内存，高性能
    - 线程安全
    - 自动清理过期的桶
    - 支持自定义限流阈值和窗口大小
    """

    def __init__(self, cleanup_interval: int = 60) -> None:
        """初始化限流服务.

        Args:
            cleanup_interval: 自动清理间隔（秒），定期清理过期的计数桶
        """
        self._buckets: Dict[str, _RateLimitBucket] = defaultdict(_RateLimitBucket)
        self._lock = Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    # --------------------------------------------------------
    # 核心方法
    # --------------------------------------------------------

    def check_rate(self, key: str, limit: int, window_seconds: int) -> bool:
        """检查是否超过速率限制.

        如果未超过限制，则消耗一个令牌（计数 +1）。

        Args:
            key: 限流键（如 API Key 哈希值）
            limit: 窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）

        Returns:
            True 表示允许通过（未超限），False 表示已超限
        """
        with self._lock:
            self._maybe_cleanup()

            bucket = self._buckets[key]
            now = time.time()

            # 如果当前窗口已过期，重置
            if now - bucket.window_start >= window_seconds:
                bucket.count = 0
                bucket.window_start = now

            if bucket.count >= limit:
                return False

            bucket.count += 1
            return True

    def get_remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """获取剩余请求数.

        Args:
            key: 限流键
            limit: 窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）

        Returns:
            剩余可请求次数
        """
        with self._lock:
            self._maybe_cleanup()

            bucket = self._buckets[key]
            now = time.time()

            if now - bucket.window_start >= window_seconds:
                return limit

            remaining = limit - bucket.count
            return max(remaining, 0)

    def reset(self, key: str) -> None:
        """重置指定 key 的计数.

        Args:
            key: 限流键
        """
        with self._lock:
            if key in self._buckets:
                del self._buckets[key]

    def reset_all(self) -> None:
        """重置所有计数."""
        with self._lock:
            self._buckets.clear()

    # --------------------------------------------------------
    # 统计与清理
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取限流统计信息.

        Returns:
            统计字典：活跃 key 数量、总请求数等
        """
        with self._lock:
            total_requests = sum(b.count for b in self._buckets.values())
            return {
                "backend": "memory",
                "active_keys": len(self._buckets),
                "total_tracked_requests": total_requests,
            }

    def _maybe_cleanup(self) -> None:
        """定期清理过期的计数桶.

        在获取锁后被调用，避免频繁清理带来的性能损耗。
        只清理超过 2 倍窗口时间未活动的桶。
        """
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now

        # 清理超过 2 倍清理间隔未活动的桶
        expiry_threshold = self._cleanup_interval * 2
        expired_keys = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.window_start > expiry_threshold
        ]
        for key in expired_keys:
            del self._buckets[key]


# ============================================================
# Redis 限流器
# ============================================================

class RedisRateLimiter:
    """Redis 限流器 - 基于 INCR + EXPIRE 的滑动窗口限流.

    使用 Redis 的原子 INCR 操作实现分布式限流，
    每个 key 对应一个计数器，配合 EXPIRE 实现窗口过期。
    多实例之间共享限流状态。

    特点：
    - 支持多实例部署，限流状态共享
    - 基于 Redis 原子操作，保证并发安全
    - Redis 不可用时自动降级（返回 True 表示放行）
    """

    def __init__(self) -> None:
        """初始化 Redis 限流器."""
        # 延迟导入，避免循环依赖
        from .redis_client import redis_client
        self._redis = redis_client

    def _make_key(self, key: str, window_seconds: int) -> str:
        """生成 Redis 限流键.

        将时间窗口纳入 key，实现滑动窗口效果。
        每个时间片一个计数器，窗口大小即为时间片长度。

        Args:
            key: 限流键
            window_seconds: 窗口大小（秒）

        Returns:
            Redis 键名
        """
        # 使用当前时间戳除以窗口大小，得到时间片编号
        time_slice = int(time.time() // window_seconds)
        return f"rate_limit:{key}:{window_seconds}:{time_slice}"

    # --------------------------------------------------------
    # 核心方法
    # --------------------------------------------------------

    def check_rate(self, key: str, limit: int, window_seconds: int) -> bool:
        """检查是否超过速率限制（Redis 版本）.

        使用 INCR 原子递增，首次设置时同时设置过期时间。
        Redis 不可用时自动降级为放行（返回 True）。

        Args:
            key: 限流键
            limit: 窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）

        Returns:
            True 表示允许通过，False 表示已超限
        """
        if not self._redis.is_available():
            # Redis 不可用时降级：放行所有请求
            logger.debug("[RateLimiter] Redis 不可用，降级放行: %s", key)
            return True

        redis_key = self._make_key(key, window_seconds)

        try:
            # 原子递增
            current = self._redis.incr(redis_key, 1)
            if current is None:
                return True  # 操作失败，降级放行

            # 如果是第一次设置，设置过期时间
            if current == 1:
                self._redis.expire(redis_key, window_seconds)

            return current <= limit
        except Exception as e:
            logger.debug("[RateLimiter] Redis 操作异常，降级放行: %s", e)
            return True

    def get_remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """获取剩余请求数（Redis 版本）.

        Args:
            key: 限流键
            limit: 窗口内允许的最大请求数
            window_seconds: 时间窗口大小（秒）

        Returns:
            剩余可请求次数，Redis 不可用时返回 limit
        """
        if not self._redis.is_available():
            return limit

        redis_key = self._make_key(key, window_seconds)

        try:
            value = self._redis.get(redis_key)
            if value is None:
                return limit
            current = int(value)
            remaining = limit - current
            return max(remaining, 0)
        except Exception:
            return limit

    def reset(self, key: str) -> None:
        """重置指定 key 的计数.

        注意：由于 Redis 限流键包含时间片，这里会尝试删除
        当前和上一个时间片的 key。

        Args:
            key: 限流键
        """
        if not self._redis.is_available():
            return

        # 删除所有匹配模式的 key（简化实现，实际生产可用 SCAN）
        pattern = f"rate_limit:{key}:*"
        keys = self._redis.keys(pattern)
        for k in keys:
            self._redis.delete(k)

    def reset_all(self) -> None:
        """重置所有计数（删除所有限流相关 key）."""
        if not self._redis.is_available():
            return

        keys = self._redis.keys("rate_limit:*")
        for k in keys:
            self._redis.delete(k)

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取限流统计信息.

        Returns:
            统计字典
        """
        available = self._redis.is_available()
        return {
            "backend": "redis",
            "available": available,
        }


# ============================================================
# 工厂函数
# ============================================================

def get_rate_limiter() -> Any:
    """获取限流器实例.

    根据配置自动选择后端：
    - 配置了 redis_url 且 Redis 可用：返回 RedisRateLimiter
    - 否则：返回 MemoryRateLimiter

    Returns:
        限流器实例（MemoryRateLimiter 或 RedisRateLimiter）
    """
    settings = get_settings()
    if settings.use_redis:
        # 延迟导入
        from .redis_client import redis_client
        if redis_client.is_available():
            return RedisRateLimiter()
    return MemoryRateLimiter()


# ============================================================
# 全局单例
# ============================================================

# 初始使用内存限流器，应用启动时会根据配置重新初始化
rate_limiter = MemoryRateLimiter()


def init_rate_limiter() -> Any:
    """初始化全局限流器单例.

    在应用启动时调用，根据配置选择合适的后端。
    替换 module 级别的 rate_limiter 实例。

    Returns:
        初始化后的限流器实例
    """
    global rate_limiter
    rate_limiter = get_rate_limiter()
    logger.info("[RateLimiter] 使用后端: %s", rate_limiter.get_stats().get("backend", "unknown"))
    return rate_limiter
