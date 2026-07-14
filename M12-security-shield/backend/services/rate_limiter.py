"""
云汐 M12 安全盾 - 速率限制服务
基于令牌桶算法实现的请求速率限制器，支持：

1. 按 IP 地址限流
2. 按 API Key 限流
3. 自定义限流阈值
4. 令牌桶算法（支持突发流量）

令牌桶算法原理：
- 桶内有固定容量的令牌
- 令牌以固定速率生成
- 每个请求消耗一个令牌
- 桶满时多余令牌丢弃
- 桶空时请求被拒绝
"""

import time
import threading
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field


# ===========================================================================
# 令牌桶
# ===========================================================================

@dataclass
class TokenBucket:
    """
    令牌桶数据结构

    Attributes:
        capacity: 桶容量（最大令牌数，即突发请求数）
        rate: 令牌生成速率（每秒生成多少令牌）
        tokens: 当前令牌数
        last_refill: 上次补充令牌的时间戳
    """
    capacity: float = 60.0
    rate: float = 1.0  # 每秒生成的令牌数
    tokens: float = 60.0
    last_refill: float = field(default_factory=time.time)

    def refill(self) -> None:
        """补充令牌（根据时间差计算）"""
        now = time.time()
        elapsed = now - self.last_refill
        if elapsed > 0:
            new_tokens = elapsed * self.rate
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        """消耗令牌

        Args:
            tokens: 需要消耗的令牌数

        Returns:
            是否有足够的令牌
        """
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_retry_after(self) -> float:
        """获取需要等待的时间（秒）

        Returns:
            等待时间（秒），直到有一个可用令牌
        """
        self.refill()
        if self.tokens >= 1:
            return 0
        deficit = 1 - self.tokens
        if self.rate > 0:
            return deficit / self.rate
        return float("inf")


# ===========================================================================
# 速率限制器
# ===========================================================================

class RateLimiter:
    """
    速率限制器

    基于令牌桶算法实现，支持按不同 key（IP、API Key 等）进行限流。
    线程安全，支持高并发场景。
    """

    def __init__(
        self,
        default_rate_per_minute: int = 60,
        burst_size: int = 30,
        enabled: bool = True,
    ):
        """初始化速率限制器

        Args:
            default_rate_per_minute: 默认每分钟请求数
            burst_size: 突发请求数（桶容量）
            enabled: 是否启用限流
        """
        self.default_rate = default_rate_per_minute
        self.default_burst = burst_size
        self.enabled = enabled

        # 令牌桶存储：key -> TokenBucket
        self._buckets: Dict[str, TokenBucket] = {}
        self._custom_rates: Dict[str, int] = {}  # 自定义速率配置

        # 清理相关
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 每 5 分钟清理一次
        self._bucket_ttl = 3600  # 桶的过期时间（1小时无访问则清理）

        # 线程锁
        self._lock = threading.Lock()

    def enable(self) -> None:
        """启用限流"""
        self.enabled = True

    def disable(self) -> None:
        """禁用限流"""
        self.enabled = False

    def toggle(self) -> bool:
        """切换限流开关

        Returns:
            切换后的状态
        """
        self.enabled = not self.enabled
        return self.enabled

    def is_active(self) -> bool:
        """检查限流是否启用

        Returns:
            是否启用
        """
        return self.enabled

    def set_custom_rate(self, key: str, rate_per_minute: int, burst: Optional[int] = None) -> None:
        """为指定 key 设置自定义速率

        Args:
            key: 限流 key（如 IP 地址、API Key ID）
            rate_per_minute: 每分钟请求数
            burst: 突发请求数，默认使用 rate_per_minute 的一半
        """
        with self._lock:
            self._custom_rates[key] = rate_per_minute
            # 更新或创建对应的令牌桶
            if burst is None:
                burst = max(5, rate_per_minute // 2)
            rate_per_second = rate_per_minute / 60.0
            self._buckets[key] = TokenBucket(
                capacity=float(burst),
                rate=rate_per_second,
                tokens=float(burst),
            )

    def remove_custom_rate(self, key: str) -> None:
        """移除自定义速率配置

        Args:
            key: 限流 key
        """
        with self._lock:
            self._custom_rates.pop(key, None)
            self._buckets.pop(key, None)

    def allow_request(self, key: str, cost: float = 1.0) -> bool:
        """检查请求是否被允许（消耗令牌）

        Args:
            key: 限流 key（IP 地址、API Key 等）
            cost: 本次请求消耗的令牌数

        Returns:
            是否允许请求
        """
        # 如果限流未启用，直接通过
        if not self.enabled:
            return True

        # 定期清理过期的桶
        self._maybe_cleanup()

        with self._lock:
            bucket = self._get_or_create_bucket(key)
            return bucket.consume(cost)

    def check_available(self, key: str) -> Tuple[bool, float]:
        """检查是否有可用令牌（不消耗）

        Args:
            key: 限流 key

        Returns:
            (是否可用, 当前令牌数)
        """
        if not self.enabled:
            return (True, float("inf"))

        with self._lock:
            bucket = self._get_or_create_bucket(key)
            bucket.refill()
            return (bucket.tokens >= 1, bucket.tokens)

    def get_retry_after(self, key: str) -> float:
        """获取需要等待的时间

        Args:
            key: 限流 key

        Returns:
            需要等待的秒数
        """
        if not self.enabled:
            return 0

        with self._lock:
            bucket = self._get_or_create_bucket(key)
            return bucket.get_retry_after()

    def get_stats(self, key: str) -> Dict[str, float]:
        """获取指定 key 的限流统计

        Args:
            key: 限流 key

        Returns:
            统计信息字典
        """
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return {
                    "tokens": 0,
                    "capacity": 0,
                    "rate": 0,
                    "rate_per_minute": self.default_rate,
                }
            return {
                "tokens": bucket.tokens,
                "capacity": bucket.capacity,
                "rate": bucket.rate,
                "rate_per_minute": bucket.rate * 60,
            }

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """获取所有限流 key 的统计

        Returns:
            所有 key 的统计信息
        """
        with self._lock:
            result = {}
            for key, bucket in self._buckets.items():
                bucket.refill()
                result[key] = {
                    "tokens": bucket.tokens,
                    "capacity": bucket.capacity,
                    "rate_per_minute": bucket.rate * 60,
                }
            return result

    def _get_or_create_bucket(self, key: str) -> TokenBucket:
        """获取或创建令牌桶（需在锁内调用）

        Args:
            key: 限流 key

        Returns:
            TokenBucket 实例
        """
        if key not in self._buckets:
            # 检查是否有自定义速率
            custom_rate = self._custom_rates.get(key)
            if custom_rate:
                rate_per_second = custom_rate / 60.0
                burst = max(5, custom_rate // 2)
                self._buckets[key] = TokenBucket(
                    capacity=float(burst),
                    rate=rate_per_second,
                    tokens=float(burst),
                )
            else:
                rate_per_second = self.default_rate / 60.0
                self._buckets[key] = TokenBucket(
                    capacity=float(self.default_burst),
                    rate=rate_per_second,
                    tokens=float(self.default_burst),
                )
        return self._buckets[key]

    def _maybe_cleanup(self) -> None:
        """定期清理过期的令牌桶"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        with self._lock:
            # 双重检查
            if now - self._last_cleanup < self._cleanup_interval:
                return

            self._last_cleanup = now
            expired_keys = []
            for key, bucket in self._buckets.items():
                # 如果桶的上次补充时间超过 TTL，标记为过期
                if now - bucket.last_refill > self._bucket_ttl:
                    expired_keys.append(key)

            for key in expired_keys:
                self._buckets.pop(key, None)
                self._custom_rates.pop(key, None)

    def reset(self, key: str) -> None:
        """重置指定 key 的令牌桶

        Args:
            key: 限流 key
        """
        with self._lock:
            self._buckets.pop(key, None)

    def reset_all(self) -> None:
        """重置所有令牌桶"""
        with self._lock:
            self._buckets.clear()
            self._custom_rates.clear()


# ===========================================================================
# 单例管理
# ===========================================================================

_rate_limiter: Optional[RateLimiter] = None
_rate_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """获取速率限制器单例

    Returns:
        RateLimiter 实例
    """
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                # 延迟导入配置以避免循环引用
                try:
                    from ..config import get_settings
                    settings = get_settings()
                    _rate_limiter = RateLimiter(
                        default_rate_per_minute=settings.default_rate_per_minute,
                        burst_size=settings.rate_limit_burst,
                        enabled=settings.rate_limit_enabled,
                    )
                except ImportError:
                    _rate_limiter = RateLimiter()
    return _rate_limiter


# 兼容直接运行测试
if __name__ == "__main__":
    rl = get_rate_limiter()
    print(f"速率限制器已初始化")
    print(f"默认速率: {rl.default_rate} 次/分钟")
    print(f"突发容量: {rl.default_burst}")
    print()

    # 测试限流
    test_ip = "192.168.1.100"
    print(f"测试 IP: {test_ip}")
    for i in range(5):
        allowed = rl.allow_request(test_ip)
        stats = rl.get_stats(test_ip)
        print(f"  请求 {i+1}: {'允许' if allowed else '拒绝'} (剩余令牌: {stats['tokens']:.2f})")

    print()
    print(f"需要等待: {rl.get_retry_after(test_ip):.2f} 秒")
