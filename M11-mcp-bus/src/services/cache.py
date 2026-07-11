"""M11 MCP Bus - 缓存服务.

提供内存缓存功能，包括工具列表缓存和工具调用结果缓存。
使用简单的 TTL 机制，无需外部依赖。
"""

from __future__ import annotations

import hashlib
import json
import time
from threading import Lock
from typing import Any, Dict, List, Optional


class _CacheEntry:
    """缓存条目."""

    def __init__(self, value: Any, ttl: int) -> None:
        self.value = value
        self.expires_at = time.time() + ttl

    @property
    def is_expired(self) -> bool:
        """是否已过期."""
        return time.time() > self.expires_at


class McpCache:
    """MCP 缓存服务.

    提供内存缓存功能，支持：
    - 工具列表缓存
    - 工具调用结果缓存
    - TTL 过期机制
    - 线程安全访问
    """

    def __init__(
        self,
        tool_list_ttl: int = 300,
        tool_result_ttl: int = 60,
        max_result_entries: int = 1000,
    ) -> None:
        """初始化缓存服务.

        Args:
            tool_list_ttl: 工具列表缓存 TTL（秒）
            tool_result_ttl: 工具调用结果缓存 TTL（秒）
            max_result_entries: 结果缓存最大条目数
        """
        self._tool_list_ttl = tool_list_ttl
        self._tool_result_ttl = tool_result_ttl
        self._max_result_entries = max_result_entries

        # 工具列表缓存
        self._tool_list_cache: Optional[_CacheEntry] = None
        self._tool_list_lock = Lock()

        # 工具结果缓存：key -> _CacheEntry
        self._result_cache: Dict[str, _CacheEntry] = {}
        self._result_lock = Lock()

    # --------------------------------------------------------
    # 工具列表缓存
    # --------------------------------------------------------

    def get_tool_list_cache(self) -> Optional[List[Dict[str, Any]]]:
        """获取工具列表缓存.

        Returns:
            缓存的工具列表，未命中或已过期返回 None
        """
        with self._tool_list_lock:
            if self._tool_list_cache is None:
                return None
            if self._tool_list_cache.is_expired:
                self._tool_list_cache = None
                return None
            return self._tool_list_cache.value

    def set_tool_list_cache(self, tools: List[Dict[str, Any]]) -> None:
        """设置工具列表缓存.

        Args:
            tools: 工具列表
        """
        with self._tool_list_lock:
            self._tool_list_cache = _CacheEntry(tools, self._tool_list_ttl)

    def invalidate_tool_list_cache(self) -> None:
        """失效工具列表缓存."""
        with self._tool_list_lock:
            self._tool_list_cache = None

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
        return f"{tool_name}:{args_hash}"

    def make_args_hash(self, arguments: Dict[str, Any]) -> str:
        """计算参数的哈希值.

        Args:
            arguments: 参数字典

        Returns:
            哈希字符串
        """
        # 排序后序列化，确保相同参数生成相同哈希
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
        with self._result_lock:
            entry = self._result_cache.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._result_cache[key]
                return None
            return entry.value

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
        with self._result_lock:
            # 如果超过最大条目数，清理过期的；如果还超，就删除最老的
            if len(self._result_cache) >= self._max_result_entries:
                self._cleanup_expired_locked()
                if len(self._result_cache) >= self._max_result_entries:
                    # 删除最早的条目（简单策略：删除前 20%）
                    keys_to_remove = list(self._result_cache.keys())[
                        : int(self._max_result_entries * 0.2)
                    ]
                    for k in keys_to_remove:
                        del self._result_cache[k]

            self._result_cache[key] = _CacheEntry(result, self._tool_result_ttl)

    def invalidate_tool_result(self, tool_name: str, args_hash: str) -> bool:
        """失效指定的工具结果缓存.

        Args:
            tool_name: 工具名称
            args_hash: 参数哈希值

        Returns:
            是否成功删除
        """
        key = self._make_result_key(tool_name, args_hash)
        with self._result_lock:
            if key in self._result_cache:
                del self._result_cache[key]
                return True
            return False

    def invalidate_all_results(self) -> None:
        """失效所有结果缓存."""
        with self._result_lock:
            self._result_cache.clear()

    def invalidate_tool_results(self, tool_name: str) -> int:
        """失效某个工具的所有结果缓存.

        Args:
            tool_name: 工具名称

        Returns:
            被删除的条目数
        """
        prefix = f"{tool_name}:"
        with self._result_lock:
            keys_to_remove = [
                k for k in self._result_cache if k.startswith(prefix)
            ]
            for k in keys_to_remove:
                del self._result_cache[k]
            return len(keys_to_remove)

    # --------------------------------------------------------
    # 缓存管理
    # --------------------------------------------------------

    def _cleanup_expired_locked(self) -> int:
        """清理过期条目（调用方需持有锁）.

        Returns:
            清理的条目数
        """
        expired_keys = [
            k for k, v in self._result_cache.items() if v.is_expired
        ]
        for k in expired_keys:
            del self._result_cache[k]
        return len(expired_keys)

    def cleanup_expired(self) -> int:
        """清理所有过期的缓存条目.

        Returns:
            清理的条目数
        """
        with self._result_lock:
            return self._cleanup_expired_locked()

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息.

        Returns:
            统计信息字典
        """
        with self._tool_list_lock:
            tool_list_cached = self._tool_list_cache is not None and not self._tool_list_cache.is_expired

        with self._result_lock:
            result_count = len(self._result_cache)

        return {
            "tool_list_cached": tool_list_cached,
            "tool_list_ttl": self._tool_list_ttl,
            "result_cache_count": result_count,
            "result_cache_max": self._max_result_entries,
            "result_ttl": self._tool_result_ttl,
        }

    def clear_all(self) -> None:
        """清空所有缓存."""
        with self._tool_list_lock:
            self._tool_list_cache = None
        with self._result_lock:
            self._result_cache.clear()


# ============================================================
# 单例实例
# ============================================================

mcp_cache = McpCache()
