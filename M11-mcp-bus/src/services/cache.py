"""M11 MCP Bus - 缓存服务.

提供内存和 Redis 两种缓存后端，支持多实例部署。
- MemoryCache: 基于 dict + TTL 的内存缓存
- RedisCache: 基于 Redis SETEX 的分布式缓存
- CacheService: 工厂类，根据配置自动选择后端

上层 McpCache 通过 CacheService 访问底层存储，
保持业务接口不变，自动适配后端。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)


# ============================================================
# 底层缓存后端：MemoryCache
# ============================================================

class _CacheEntry:
    """缓存条目."""

    def __init__(self, value: Any, ttl: int) -> None:
        self.value = value
        self.expires_at = time.time() + ttl

    @property
    def is_expired(self) -> bool:
        """是否已过期."""
        return time.time() > self.expires_at


class MemoryCache:
    """内存缓存 - 基于 dict + TTL.

    线程安全的内存缓存实现，支持自动过期。
    """

    def __init__(self, max_entries: int = 10000) -> None:
        """初始化内存缓存.

        Args:
            max_entries: 最大缓存条目数
        """
        self._cache: Dict[str, _CacheEntry] = {}
        self._lock = Lock()
        self._max_entries = max_entries

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值.

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在或已过期返回 None
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._cache[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值.

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        with self._lock:
            # 超过上限时清理过期条目
            if len(self._cache) >= self._max_entries:
                self._cleanup_expired_locked()
                if len(self._cache) >= self._max_entries:
                    # 简单策略：删除最早的 20%
                    keys = list(self._cache.keys())
                    remove_count = max(1, int(self._max_entries * 0.2))
                    for k in keys[:remove_count]:
                        del self._cache[k]

            self._cache[key] = _CacheEntry(value, ttl)

    def delete(self, key: str) -> bool:
        """删除缓存条目.

        Args:
            key: 缓存键

        Returns:
            True 表示成功删除
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空所有缓存."""
        with self._lock:
            self._cache.clear()

    def delete_prefix(self, prefix: str) -> int:
        """删除所有带指定前缀的缓存.

        Args:
            prefix: 键前缀

        Returns:
            删除的条目数
        """
        with self._lock:
            keys_to_remove = [
                k for k in self._cache if k.startswith(prefix)
            ]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    def _cleanup_expired_locked(self) -> int:
        """清理过期条目（需持有锁）.

        Returns:
            清理的条目数
        """
        expired = [k for k, v in self._cache.items() if v.is_expired]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def get_size(self) -> int:
        """获取缓存条目数."""
        with self._lock:
            return len(self._cache)


# ============================================================
# 底层缓存后端：RedisCache
# ============================================================

class RedisCache:
    """Redis 缓存 - 基于 Redis SETEX.

    分布式缓存实现，支持多实例共享。
    Redis 不可用时自动降级为 None 返回，
    由上层业务处理降级逻辑。
    """

    def __init__(self) -> None:
        """初始化 Redis 缓存."""
        from .redis_client import redis_client
        self._redis = redis_client

    def _encode(self, value: Any) -> str:
        """将值序列化为 JSON 字符串.

        Args:
            value: 任意可序列化的值

        Returns:
            JSON 字符串
        """
        return json.dumps(value, ensure_ascii=False)

    def _decode(self, raw: Optional[str]) -> Optional[Any]:
        """将 JSON 字符串反序列化为值.

        Args:
            raw: JSON 字符串

        Returns:
            反序列化后的值，失败返回 None
        """
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值.

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在或失败返回 None
        """
        if not self._redis.is_available():
            return None
        raw = self._redis.get(f"cache:{key}")
        return self._decode(raw)

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值.

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）
        """
        if not self._redis.is_available():
            return
        try:
            encoded = self._encode(value)
            self._redis.set(f"cache:{key}", encoded, ex=ttl)
        except Exception as e:
            logger.debug("[Cache] Redis set 失败: %s", e)

    def delete(self, key: str) -> bool:
        """删除缓存条目.

        Args:
            key: 缓存键

        Returns:
            True 表示成功删除
        """
        if not self._redis.is_available():
            return False
        return self._redis.delete(f"cache:{key}")

    def clear(self) -> None:
        """清空所有缓存（删除 cache: 前缀的 key）."""
        if not self._redis.is_available():
            return
        keys = self._redis.keys("cache:*")
        for k in keys:
            self._redis.delete(k)

    def delete_prefix(self, prefix: str) -> int:
        """删除所有带指定前缀的缓存.

        Args:
            prefix: 键前缀

        Returns:
            删除的条目数
        """
        if not self._redis.is_available():
            return 0
        pattern = f"cache:{prefix}*"
        keys = self._redis.keys(pattern)
        count = 0
        for k in keys:
            if self._redis.delete(k):
                count += 1
        return count

    def get_size(self) -> int:
        """获取缓存条目数（近似）."""
        if not self._redis.is_available():
            return 0
        return len(self._redis.keys("cache:*"))


# ============================================================
# 缓存服务工厂
# ============================================================

class CacheService:
    """缓存服务 - 根据配置自动选择后端.

    提供统一的缓存访问接口，自动在 Redis 和内存之间切换。
    Redis 可用时优先使用 Redis，否则降级为内存缓存。
    """

    _instance: Optional["CacheService"] = None

    def __new__(cls) -> "CacheService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化缓存服务."""
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._backend: Optional[Any] = None
        self._init_backend()

    def _init_backend(self) -> None:
        """初始化后端缓存."""
        settings = get_settings()
        if settings.use_redis:
            from .redis_client import redis_client
            if redis_client.is_available():
                self._backend = RedisCache()
                logger.info("[Cache] 使用 Redis 缓存后端")
                return
        self._backend = MemoryCache()
        logger.info("[Cache] 使用内存缓存后端")

    def reload_backend(self) -> None:
        """重新加载后端（Redis 连接状态变化时调用）."""
        self._initialized = False
        self._backend = None
        self._init_backend()

    @property
    def backend_type(self) -> str:
        """获取当前后端类型."""
        if isinstance(self._backend, RedisCache):
            return "redis"
        return "memory"

    # ---- 统一接口 ----

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值."""
        return self._backend.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        """设置缓存值."""
        self._backend.set(key, value, ttl)

    def delete(self, key: str) -> bool:
        """删除缓存条目."""
        return self._backend.delete(key)

    def clear(self) -> None:
        """清空所有缓存."""
        self._backend.clear()

    def delete_prefix(self, prefix: str) -> int:
        """删除所有带指定前缀的缓存."""
        return self._backend.delete_prefix(prefix)

    def get_size(self) -> int:
        """获取缓存条目数."""
        return self._backend.get_size()


# ============================================================
# 上层业务缓存：McpCache
# ============================================================

class McpCache:
    """MCP 缓存服务.

    提供 MCP 业务相关的缓存功能，包括：
    - 工具列表缓存
    - 工具调用结果缓存
    - TTL 过期机制

    底层通过 CacheService 访问，自动适配 Redis/内存后端。
    """

    def __init__(
        self,
        tool_list_ttl: int = 300,
        tool_result_ttl: int = 60,
    ) -> None:
        """初始化缓存服务.

        Args:
            tool_list_ttl: 工具列表缓存 TTL（秒）
            tool_result_ttl: 工具调用结果缓存 TTL（秒）
        """
        self._tool_list_ttl = tool_list_ttl
        self._tool_result_ttl = tool_result_ttl
        self._cache = CacheService()

        # 工具列表缓存键
        self._TOOL_LIST_KEY = "tool_list"
        # 结果缓存前缀
        self._RESULT_PREFIX = "result:"

    # --------------------------------------------------------
    # 工具列表缓存
    # --------------------------------------------------------

    def get_tool_list_cache(self) -> Optional[List[Dict[str, Any]]]:
        """获取工具列表缓存.

        Returns:
            缓存的工具列表，未命中或已过期返回 None
        """
        value = self._cache.get(self._TOOL_LIST_KEY)
        if value is not None and isinstance(value, list):
            return value
        return None

    def set_tool_list_cache(self, tools: List[Dict[str, Any]]) -> None:
        """设置工具列表缓存.

        Args:
            tools: 工具列表
        """
        self._cache.set(self._TOOL_LIST_KEY, tools, self._tool_list_ttl)

    def invalidate_tool_list_cache(self) -> None:
        """失效工具列表缓存."""
        self._cache.delete(self._TOOL_LIST_KEY)

    # --------------------------------------------------------
    # 工具结果缓存
    # --------------------------------------------------------

    def _make_result_key(self, tool_name: str, args_hash: str) -> str:
        """生成结果缓存键.

        Args:
            tool_name: 工具名称
            args_hash: 参数哈希

        Returns:
            缓存键字符串
        """
        return f"{self._RESULT_PREFIX}{tool_name}:{args_hash}"

    def make_args_hash(self, arguments: Dict[str, Any]) -> str:
        """计算参数的哈希值.

        Args:
            arguments: 参数字典

        Returns:
            哈希字符串
        """
        sorted_args = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(sorted_args.encode("utf-8")).hexdigest()

    def get_tool_result_cache(
        self, tool_name: str, args_hash: str
    ) -> Optional[Any]:
        """获取工具调用结果缓存.

        Args:
            tool_name: 工具名称
            args_hash: 参数哈希值

        Returns:
            缓存的结果，未命中或已过期返回 None
        """
        key = self._make_result_key(tool_name, args_hash)
        return self._cache.get(key)

    def set_tool_result_cache(
        self, tool_name: str, args_hash: str, result: Any
    ) -> None:
        """设置工具调用结果缓存.

        Args:
            tool_name: 工具名称
            args_hash: 参数哈希值
            result: 调用结果
        """
        key = self._make_result_key(tool_name, args_hash)
        self._cache.set(key, result, self._tool_result_ttl)

    def invalidate_tool_result(self, tool_name: str, args_hash: str) -> bool:
        """失效指定的工具结果缓存.

        Args:
            tool_name: 工具名称
            args_hash: 参数哈希值

        Returns:
            是否成功删除
        """
        key = self._make_result_key(tool_name, args_hash)
        return self._cache.delete(key)

    def invalidate_all_results(self) -> None:
        """失效所有结果缓存."""
        self._cache.delete_prefix(self._RESULT_PREFIX)

    def invalidate_tool_results(self, tool_name: str) -> int:
        """失效某个工具的所有结果缓存.

        Args:
            tool_name: 工具名称

        Returns:
            被删除的条目数
        """
        prefix = f"{self._RESULT_PREFIX}{tool_name}:"
        return self._cache.delete_prefix(prefix)

    # --------------------------------------------------------
    # 缓存管理
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息.

        Returns:
            统计信息字典
        """
        tool_list_cached = self.get_tool_list_cache() is not None

        return {
            "backend": self._cache.backend_type,
            "tool_list_cached": tool_list_cached,
            "tool_list_ttl": self._tool_list_ttl,
            "result_ttl": self._tool_result_ttl,
            "cache_size": self._cache.get_size(),
        }

    def clear_all(self) -> None:
        """清空所有缓存."""
        self._cache.clear()


# ============================================================
# 单例实例
# ============================================================

mcp_cache = McpCache()
