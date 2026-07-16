"""幂等性管理器.

基于内存的幂等性管理，通过 request_id 确保接口的幂等调用，
重复请求直接返回首次结果。适用于同步 SQLAlchemy 场景。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class IdempotencyManager:
    """幂等性管理器.

    通过 request_id 确保接口的幂等调用，重复请求直接返回首次结果。

    使用有序字典 + TTL 机制实现：
    - 键按访问顺序维护，LRU 淘汰策略
    - 超过 TTL 的键自动过期
    - 超过 max_keys 时淘汰最久未使用的键

    Args:
        ttl: 幂等键存活时间（秒），默认 24 小时
        max_keys: 最大缓存键数量，默认 10000
    """

    def __init__(self, ttl: int = 86400, max_keys: int = 10000):
        self._ttl = ttl
        self._max_keys = max_keys
        # OrderedDict: key -> (result, expire_timestamp)
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, Any]:
        """检查幂等键是否已存在.

        如果键存在且未过期，将其移到末尾（标记为最近使用）并返回结果。
        如果键已过期，删除该键并返回不存在。

        Args:
            key: 幂等键（通常为 request_id）

        Returns:
            (exists, cached_result)
            - exists: 键是否存在且有效
            - cached_result: 缓存的结果，不存在时为 None
        """
        with self._lock:
            if key not in self._cache:
                return False, None

            result, expire_at = self._cache[key]

            # 检查是否过期
            if time.time() > expire_at:
                del self._cache[key]
                return False, None

            # 标记为最近使用（移到末尾）
            self._cache.move_to_end(key)
            return True, result

    def store(self, key: str, result: Any) -> None:
        """存储幂等结果.

        如果键已存在，更新结果和过期时间，并移到末尾。
        如果超过 max_keys，淘汰最久未使用的键。

        Args:
            key: 幂等键（通常为 request_id）
            result: 要缓存的结果
        """
        with self._lock:
            expire_at = time.time() + self._ttl

            if key in self._cache:
                # 更新已存在的键
                self._cache[key] = (result, expire_at)
                self._cache.move_to_end(key)
            else:
                # 检查是否需要淘汰
                while len(self._cache) >= self._max_keys:
                    # 淘汰最久未使用的（队首）
                    self._cache.popitem(last=False)
                self._cache[key] = (result, expire_at)

    def cleanup(self) -> int:
        """清理过期键，返回清理数量.

        遍历所有键，删除已过期的条目。

        Returns:
            被清理的过期键数量
        """
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, (_, expire_at) in self._cache.items()
                if now > expire_at
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    @property
    def size(self) -> int:
        """当前缓存的键数量."""
        with self._lock:
            return len(self._cache)

    @property
    def ttl(self) -> int:
        """幂等键存活时间（秒）."""
        return self._ttl

    @property
    def max_keys(self) -> int:
        """最大缓存键数量."""
        return self._max_keys


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: IdempotencyManager | None = None
_instance_lock = threading.Lock()


def get_idempotency_manager(
    ttl: int = 86400,
    max_keys: int = 10000,
) -> IdempotencyManager:
    """获取全局幂等性管理器单例.

    首次调用时创建单例，后续调用直接返回已创建的实例。
    单例创建后，ttl 和 max_keys 参数不再生效。

    Args:
        ttl: 幂等键存活时间（秒），默认 24 小时，仅首次调用有效
        max_keys: 最大缓存键数量，默认 10000，仅首次调用有效

    Returns:
        全局 IdempotencyManager 单例
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = IdempotencyManager(ttl=ttl, max_keys=max_keys)
    return _instance
