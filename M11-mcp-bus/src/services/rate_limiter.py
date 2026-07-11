"""M11 MCP Bus - 限流服务.

基于内存的令牌桶算法实现，提供 API Key 级别的速率限制。
支持自动清理过期计数，避免内存泄漏。
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict


class _RateLimitBucket:
    """令牌桶数据结构.

    记录某个 key 的请求计数和时间窗口。
    """

    def __init__(self) -> None:
        """初始化令牌桶."""
        self.count: int = 0
        self.window_start: float = time.time()


class RateLimiter:
    """限流服务 - 基于滑动窗口的令牌桶算法.

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
# 单例实例
# ============================================================

rate_limiter = RateLimiter()
