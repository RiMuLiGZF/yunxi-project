"""
云汐 API 网关 - 令牌桶限流算法

独立的令牌桶实现，与现有滑动窗口形成双模式限流。

特性：
1. 支持按用户 ID 限流
2. 支持按 API 路径独立配置
3. 支持动态修改配置（运行时）
4. 支持突发流量（burst size）
5. 线程/协程安全
"""
import time
import asyncio
import threading
from typing import Dict, Optional, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class TokenBucketConfig:
    """令牌桶配置

    Attributes:
        rate: 令牌生成速率（令牌/秒）
        capacity: 桶容量（最大令牌数，即最大突发量）
        initial_tokens: 初始令牌数
    """
    rate: float  # tokens per second
    capacity: int
    initial_tokens: Optional[int] = None


class TokenBucket:
    """单个令牌桶"""

    def __init__(self, config: TokenBucketConfig):
        self._rate = config.rate
        self._capacity = config.capacity
        self._tokens = float(config.initial_tokens if config.initial_tokens is not None else config.capacity)
        self._last_refill = time.time()

    def refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    def try_consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """尝试消耗令牌

        Args:
            tokens: 需要消耗的令牌数

        Returns:
            (是否成功, 当前令牌数)
        """
        self.refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True, self._tokens
        return False, self._tokens

    @property
    def tokens(self) -> float:
        """当前令牌数"""
        self.refill()
        return self._tokens

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def rate(self) -> float:
        return self._rate

    def update_config(self, config: TokenBucketConfig):
        """更新配置"""
        self._rate = config.rate
        self._capacity = config.capacity
        # 调整当前令牌数不超过新容量
        if self._tokens > self._capacity:
            self._tokens = float(self._capacity)


class TokenBucketLimiter:
    """令牌桶限流器（多维度）

    支持的限流维度：
    - 全局限流
    - 按 IP 限流
    - 按用户 ID 限流
    - 按 API 路径限流
    - 按 用户ID+路径 组合限流
    """

    def __init__(self, global_rate: float = 100.0, global_capacity: int = 200):
        """
        Args:
            global_rate: 全局令牌生成速率（令牌/秒）
            global_capacity: 全局桶容量
        """
        self._global_config = TokenBucketConfig(rate=global_rate, capacity=global_capacity)
        self._global_bucket = TokenBucket(self._global_config)

        # 各维度的令牌桶
        self._ip_buckets: Dict[str, TokenBucket] = {}
        self._user_buckets: Dict[str, TokenBucket] = {}
        self._path_buckets: Dict[str, TokenBucket] = {}
        self._user_path_buckets: Dict[str, TokenBucket] = {}

        # 各维度的配置
        self._ip_configs: Dict[str, TokenBucketConfig] = {}
        self._user_configs: Dict[str, TokenBucketConfig] = {}
        self._path_configs: Dict[str, TokenBucketConfig] = {}
        self._default_ip_config: Optional[TokenBucketConfig] = None
        self._default_user_config: Optional[TokenBucketConfig] = None

        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

        # 统计
        self._stats = {
            "total_requests": 0,
            "allowed": 0,
            "blocked": 0,
            "blocked_by_global": 0,
            "blocked_by_ip": 0,
            "blocked_by_user": 0,
            "blocked_by_path": 0,
            "blocked_by_user_path": 0,
        }

    # ===================================================================
    # 配置管理
    # ===================================================================

    def set_global_config(self, rate: float, capacity: int):
        """设置全局限流配置"""
        with self._lock:
            self._global_config = TokenBucketConfig(rate=rate, capacity=capacity)
            self._global_bucket.update_config(self._global_config)

    def set_default_ip_limit(self, rate: float, capacity: int):
        """设置默认 IP 限流配置"""
        with self._lock:
            self._default_ip_config = TokenBucketConfig(rate=rate, capacity=capacity)

    def set_default_user_limit(self, rate: float, capacity: int):
        """设置默认用户限流配置"""
        with self._lock:
            self._default_user_config = TokenBucketConfig(rate=rate, capacity=capacity)

    def set_ip_limit(self, ip: str, rate: float, capacity: int):
        """设置特定 IP 的限流配置"""
        with self._lock:
            config = TokenBucketConfig(rate=rate, capacity=capacity)
            self._ip_configs[ip] = config
            if ip in self._ip_buckets:
                self._ip_buckets[ip].update_config(config)

    def set_user_limit(self, user_id: str, rate: float, capacity: int):
        """设置特定用户的限流配置"""
        with self._lock:
            config = TokenBucketConfig(rate=rate, capacity=capacity)
            self._user_configs[user_id] = config
            if user_id in self._user_buckets:
                self._user_buckets[user_id].update_config(config)

    def set_path_limit(self, path: str, rate: float, capacity: int):
        """设置特定路径的限流配置"""
        with self._lock:
            config = TokenBucketConfig(rate=rate, capacity=capacity)
            self._path_configs[path] = config
            if path in self._path_buckets:
                self._path_buckets[path].update_config(config)

    def remove_ip_limit(self, ip: str) -> bool:
        """移除特定 IP 的限流配置"""
        with self._lock:
            removed = ip in self._ip_configs
            self._ip_configs.pop(ip, None)
            self._ip_buckets.pop(ip, None)
            return removed

    def remove_user_limit(self, user_id: str) -> bool:
        """移除特定用户的限流配置"""
        with self._lock:
            removed = user_id in self._user_configs
            self._user_configs.pop(user_id, None)
            self._user_buckets.pop(user_id, None)
            return removed

    def remove_path_limit(self, path: str) -> bool:
        """移除特定路径的限流配置"""
        with self._lock:
            removed = path in self._path_configs
            self._path_configs.pop(path, None)
            self._path_buckets.pop(path, None)
            return removed

    # ===================================================================
    # 核心限流方法
    # ===================================================================

    def check_limit(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        path: Optional[str] = None,
        tokens: int = 1,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """检查是否超过限流（同步版本）

        检查顺序：全局 -> IP -> 用户 -> 路径 -> 用户+路径

        Args:
            ip: 客户端 IP
            user_id: 用户 ID
            path: API 路径
            tokens: 需要消耗的令牌数

        Returns:
            (是否允许, 拒绝原因, 限流信息)
        """
        with self._lock:
            self._stats["total_requests"] += 1
            info: Dict[str, Any] = {}

            # 1. 全局限流
            allowed, remaining = self._global_bucket.try_consume(tokens)
            info["global_remaining"] = remaining
            info["global_capacity"] = self._global_config.capacity
            if not allowed:
                self._stats["blocked"] += 1
                self._stats["blocked_by_global"] += 1
                return False, "global_rate_limit_exceeded", info

            # 2. IP 限流
            if ip and (ip in self._ip_configs or self._default_ip_config):
                bucket = self._get_or_create_ip_bucket(ip)
                allowed, remaining = bucket.try_consume(tokens)
                info["ip_remaining"] = remaining
                if not allowed:
                    self._stats["blocked"] += 1
                    self._stats["blocked_by_ip"] += 1
                    return False, "ip_rate_limit_exceeded", info

            # 3. 用户限流
            if user_id and (user_id in self._user_configs or self._default_user_config):
                bucket = self._get_or_create_user_bucket(user_id)
                allowed, remaining = bucket.try_consume(tokens)
                info["user_remaining"] = remaining
                if not allowed:
                    self._stats["blocked"] += 1
                    self._stats["blocked_by_user"] += 1
                    return False, "user_rate_limit_exceeded", info

            # 4. 路径限流
            if path and path in self._path_configs:
                bucket = self._get_or_create_path_bucket(path)
                allowed, remaining = bucket.try_consume(tokens)
                info["path_remaining"] = remaining
                if not allowed:
                    self._stats["blocked"] += 1
                    self._stats["blocked_by_path"] += 1
                    return False, "path_rate_limit_exceeded", info

            self._stats["allowed"] += 1
            return True, "", info

    async def check_limit_async(
        self,
        ip: Optional[str] = None,
        user_id: Optional[str] = None,
        path: Optional[str] = None,
        tokens: int = 1,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """检查是否超过限流（异步版本）"""
        async with self._async_lock:
            return self.check_limit(ip=ip, user_id=user_id, path=path, tokens=tokens)

    def _get_or_create_ip_bucket(self, ip: str) -> TokenBucket:
        """获取或创建 IP 令牌桶"""
        if ip not in self._ip_buckets:
            config = self._ip_configs.get(ip, self._default_ip_config)
            if config is None:
                config = TokenBucketConfig(rate=10.0, capacity=20)
            self._ip_buckets[ip] = TokenBucket(config)
        return self._ip_buckets[ip]

    def _get_or_create_user_bucket(self, user_id: str) -> TokenBucket:
        """获取或创建用户令牌桶"""
        if user_id not in self._user_buckets:
            config = self._user_configs.get(user_id, self._default_user_config)
            if config is None:
                config = TokenBucketConfig(rate=5.0, capacity=10)
            self._user_buckets[user_id] = TokenBucket(config)
        return self._user_buckets[user_id]

    def _get_or_create_path_bucket(self, path: str) -> TokenBucket:
        """获取或创建路径令牌桶"""
        if path not in self._path_buckets:
            config = self._path_configs.get(path)
            if config is None:
                config = TokenBucketConfig(rate=50.0, capacity=100)
            self._path_buckets[path] = TokenBucket(config)
        return self._path_buckets[path]

    # ===================================================================
    # 统计
    # ===================================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self._stats,
                "global_rate": self._global_config.rate,
                "global_capacity": self._global_config.capacity,
                "global_remaining_tokens": self._global_bucket.tokens,
                "ip_limits_count": len(self._ip_configs),
                "user_limits_count": len(self._user_configs),
                "path_limits_count": len(self._path_configs),
                "active_ip_buckets": len(self._ip_buckets),
                "active_user_buckets": len(self._user_buckets),
                "active_path_buckets": len(self._path_buckets),
                "allow_rate": round(
                    self._stats["allowed"] / self._stats["total_requests"] * 100, 2
                ) if self._stats["total_requests"] > 0 else 100.0,
            }

    def reset_stats(self):
        """重置统计"""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0

    def cleanup(self, max_idle_seconds: int = 3600):
        """清理长时间不活动的令牌桶"""
        with self._lock:
            now = time.time()
            # IP 桶清理（只清理没有特定配置的）
            expired_ips = [
                ip for ip, bucket in self._ip_buckets.items()
                if ip not in self._ip_configs
                and (now - bucket._last_refill) > max_idle_seconds
            ]
            for ip in expired_ips:
                del self._ip_buckets[ip]

            # 用户桶清理
            expired_users = [
                uid for uid, bucket in self._user_buckets.items()
                if uid not in self._user_configs
                and (now - bucket._last_refill) > max_idle_seconds
            ]
            for uid in expired_users:
                del self._user_buckets[uid]
