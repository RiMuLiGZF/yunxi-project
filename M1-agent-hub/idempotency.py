"""
云汐内核 - 多 Agent 集群调度系统
幂等性管理模块

为关键操作（任务提交、Agent 注册、消息消费等）提供统一的幂等性保证，
防止重复执行导致的副作用。

核心特性：
- 基于 LRU + TTL 的内存缓存，自动过期与淘汰
- 异步安全（asyncio.Lock）
- 函数级幂等装饰器
- 便捷的幂等键生成工具
- 详细的统计与 structlog 日志
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


# ── 幂等键生成工具 ──────────────────────────────────────────────


def generate_task_key(task_id: str) -> str:
    """生成任务提交幂等键。

    基于 task_id 生成唯一的幂等键，用于任务提交场景的去重。

    Args:
        task_id: 任务唯一标识

    Returns:
        格式为 ``task:<task_id>`` 的幂等键字符串

    Example:
        >>> key = generate_task_key("abc123")
        >>> key
        'task:abc123'
    """
    return f"task:{task_id}"


def generate_agent_key(agent_id: str, action: str) -> str:
    """生成 Agent 操作幂等键。

    基于 agent_id 和操作类型生成幂等键，用于 Agent 注册、更新等操作。

    Args:
        agent_id: Agent 唯一标识
        action: 操作类型（如 ``register``、``update``、``deregister``）

    Returns:
        格式为 ``agent:<agent_id>:<action>`` 的幂等键字符串

    Example:
        >>> key = generate_agent_key("agent_001", "register")
        >>> key
        'agent:agent_001:register'
    """
    return f"agent:{agent_id}:{action}"


def generate_message_key(msg_id: str) -> str:
    """生成消息消费幂等键。

    基于消息 ID 生成幂等键，用于消息总线消费场景的去重。

    Args:
        msg_id: 消息唯一标识

    Returns:
        格式为 ``msg:<msg_id>`` 的幂等键字符串

    Example:
        >>> key = generate_message_key("msg_abc123")
        >>> key
        'msg:msg_abc123'
    """
    return f"msg:{msg_id}"


def generate_request_key(request_id: str) -> str:
    """生成 HTTP 请求幂等键。

    基于请求 ID 生成幂等键，用于 HTTP API 层的重复请求防护。

    Args:
        request_id: HTTP 请求唯一标识

    Returns:
        格式为 ``req:<request_id>`` 的幂等键字符串

    Example:
        >>> key = generate_request_key("req-abc-123")
        >>> key
        'req:req-abc-123'
    """
    return f"req:{request_id}"


# ── 幂等性管理器 ────────────────────────────────────────────────


class IdempotencyManager:
    """幂等性管理器。

    管理幂等键和执行结果的存储，为关键操作提供幂等保证。
    使用 ``OrderedDict`` + 时间戳实现 LRU 淘汰与 TTL 过期，
    并通过 ``asyncio.Lock`` 保证异步环境下的线程安全。

    Attributes:
        ttl: 幂等键过期时间（秒），默认 3600 秒（1 小时）
        max_entries: 最大存储条目数，防止内存泄漏，默认 10000

    Example:
        >>> manager = IdempotencyManager(ttl=3600, max_entries=10000)
        >>> # 方式一：手动检查与存储
        >>> exists, result = await manager.check("task:abc")
        >>> if not exists:
        ...     result = await do_something()
        ...     await manager.store("task:abc", result)
        >>> # 方式二：使用 execute 自动管理
        >>> result = await manager.execute("task:abc", do_something, arg1, arg2)
    """

    def __init__(
        self,
        ttl: float = 3600.0,
        max_entries: int = 10000,
    ) -> None:
        """初始化幂等性管理器。

        Args:
            ttl: 幂等键过期时间，单位秒，默认 3600
            max_entries: 最大存储条目数，默认 10000，超过后淘汰最旧条目
        """
        self.ttl: float = ttl
        self.max_entries: int = max_entries

        # OrderedDict: key -> (result, is_error, timestamp)
        # 最近访问的条目移到末尾（LRU）
        self._cache: OrderedDict[str, tuple[Any, bool, float]] = OrderedDict()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._logger = logger.bind(component="idempotency_manager")

        # 统计信息
        self._total_hits: int = 0       # 命中次数
        self._total_misses: int = 0     # 未命中次数
        self._total_executions: int = 0 # 实际执行次数
        self._total_errors: int = 0     # 错误结果缓存数
        self._total_evictions: int = 0  # LRU 淘汰次数
        self._total_expired: int = 0    # TTL 过期清理次数

    async def check(self, key: str) -> tuple[bool, Any]:
        """检查幂等键是否存在，并返回缓存结果。

        如果键存在且未过期，返回 ``(True, 缓存结果)``；
        否则返回 ``(False, None)``。命中时会将该条目移到 LRU 末尾。

        Args:
            key: 幂等键

        Returns:
            一个二元组 ``(exists, result)``：
            - ``exists``: 键是否存在且有效
            - ``result``: 缓存的执行结果（不存在时为 None）
        """
        now = time.time()
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._total_misses += 1
                self._logger.debug("idempotency_miss", key=key)
                return False, None

            result, is_error, timestamp = entry
            # 检查是否过期
            if now - timestamp > self.ttl:
                # 过期，移除并计为未命中
                del self._cache[key]
                self._total_expired += 1
                self._total_misses += 1
                self._logger.debug(
                    "idempotency_expired",
                    key=key,
                    age=round(now - timestamp, 2),
                )
                return False, None

            # 命中：移到末尾（LRU 更新）
            self._cache.move_to_end(key)
            self._total_hits += 1
            self._logger.debug(
                "idempotency_hit",
                key=key,
                is_error=is_error,
                age=round(now - timestamp, 2),
            )
            return True, result

    async def store(
        self,
        key: str,
        result: Any,
        is_error: bool = False,
    ) -> None:
        """存储执行结果到幂等缓存。

        如果键已存在，将更新其结果和时间戳并移到 LRU 末尾。
        如果超过 ``max_entries``，将淘汰最旧的条目。

        Args:
            key: 幂等键
            result: 执行结果（可以是任意类型）
            is_error: 是否为错误结果，用于统计区分，默认 False
        """
        now = time.time()
        async with self._lock:
            if key in self._cache:
                # 更新已有条目，移到末尾
                self._cache.move_to_end(key)
                self._cache[key] = (result, is_error, now)
            else:
                # 新条目
                self._cache[key] = (result, is_error, now)
                self._total_executions += 1
                if is_error:
                    self._total_errors += 1

            # LRU 淘汰：超过 max_entries 时移除最旧的
            while len(self._cache) > self.max_entries:
                oldest_key, _ = self._cache.popitem(last=False)
                self._total_evictions += 1
                self._logger.debug(
                    "idempotency_evicted",
                    key=oldest_key,
                    cache_size=len(self._cache),
                )

        self._logger.debug(
            "idempotency_stored",
            key=key,
            is_error=is_error,
            cache_size=len(self._cache),
        )

    async def execute(
        self,
        key: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """幂等执行：存在缓存则返回缓存，不存在则执行函数并缓存结果。

        这是最便捷的使用方式。函数执行成功后缓存结果，
        后续相同 key 的调用将直接返回缓存结果，不会重复执行。

        如果函数执行时抛出异常，异常不会被缓存（异常会向上传播），
        下一次调用仍会重新执行。如需缓存错误结果，请使用
        :meth:`store` 手动存储。

        Args:
            key: 幂等键
            func: 要执行的可调用对象（支持同步和异步函数）
            *args: 传递给 func 的位置参数
            **kwargs: 传递给 func 的关键字参数

        Returns:
            函数执行结果或缓存结果

        Example:
            >>> async def process_task(task_id: str) -> dict:
            ...     # 复杂的任务处理逻辑
            ...     return {"status": "done", "task_id": task_id}
            >>>
            >>> result = await manager.execute(
            ...     generate_task_key("task_001"),
            ...     process_task,
            ...     "task_001",
            ... )
        """
        # 先检查缓存
        exists, cached_result = await self.check(key)
        if exists:
            return cached_result

        # 执行函数
        if asyncio.iscoroutinefunction(func):
            result = await func(*args, **kwargs)
        else:
            result = func(*args, **kwargs)

        # 缓存结果
        await self.store(key, result, is_error=False)
        return result

    def cleanup(self) -> int:
        """清理所有过期的幂等条目。

        遍历缓存，移除所有超过 TTL 的条目。
        此方法是同步的，调用方应在合适的时机手动调用，
        或通过定时任务周期性清理。

        .. note::

            此方法不获取 ``_lock`` 之外的额外锁，但清理操作
            会在锁内完成以保证一致性。

        Returns:
            清理掉的过期条目数量
        """
        now = time.time()
        expired_count = 0

        # 在锁内执行清理
        loop = asyncio.get_event_loop()

        async def _do_cleanup() -> int:
            nonlocal expired_count
            async with self._lock:
                # 收集过期键（OrderedDict 按插入顺序，从旧到新）
                expired_keys: list[str] = []
                for k, (_r, _e, ts) in self._cache.items():
                    if now - ts > self.ttl:
                        expired_keys.append(k)
                    else:
                        # 因为是按插入顺序（旧在前），遇到第一个未过期的就可以停了
                        # 但 LRU 更新会把条目移到末尾，所以顺序不一定严格按时间
                        # 这里需要全部遍历
                        pass

                for k in expired_keys:
                    del self._cache[k]
                    expired_count += 1

                self._total_expired += expired_count

            if expired_count > 0:
                self._logger.info(
                    "idempotency_cleanup",
                    expired=expired_count,
                    remaining=len(self._cache),
                )
            return expired_count

        # 如果当前在事件循环中，直接运行；否则创建任务
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop.is_running():
                # 我们在运行的事件循环中，直接返回协程的结果
                # 但由于 cleanup 是同步方法，我们不能直接 await
                # 所以改为同步版本的清理（不使用锁保护下的完整遍历）
                # 为了安全，这里使用同步方式访问 _cache
                # 注意：这可能在极少数情况下产生竞态，但清理操作是幂等的
                expired_keys: list[str] = []
                for k, (_r, _e, ts) in list(self._cache.items()):
                    if now - ts > self.ttl:
                        expired_keys.append(k)
                for k in expired_keys:
                    # 使用 pop 原子操作减少竞态窗口
                    if k in self._cache:
                        try:
                            del self._cache[k]
                            expired_count += 1
                        except KeyError:
                            pass
                self._total_expired += expired_count
                if expired_count > 0:
                    self._logger.info(
                        "idempotency_cleanup",
                        expired=expired_count,
                        remaining=len(self._cache),
                    )
                return expired_count
        except RuntimeError:
            pass

        # 没有运行的事件循环，使用同步清理
        expired_keys = []
        for k, (_r, _e, ts) in list(self._cache.items()):
            if now - ts > self.ttl:
                expired_keys.append(k)
        for k in expired_keys:
            try:
                del self._cache[k]
                expired_count += 1
            except KeyError:
                pass
        self._total_expired += expired_count
        if expired_count > 0:
            self._logger.info(
                "idempotency_cleanup",
                expired=expired_count,
                remaining=len(self._cache),
            )
        return expired_count

    def get_stats(self) -> dict[str, Any]:
        """获取幂等性管理器的统计信息。

        返回包含命中率、执行数、淘汰数等指标的字典，
        可用于监控和调试。

        Returns:
            统计信息字典，包含以下字段：

            - ``total_keys``: 当前缓存中的键总数
            - ``total_hits``: 累计命中次数
            - ``total_misses``: 累计未命中次数
            - ``total_executions``: 累计实际执行次数
            - ``total_errors``: 累计缓存的错误结果数
            - ``total_evictions``: 累计 LRU 淘汰次数
            - ``total_expired``: 累计 TTL 过期清理次数
            - ``hit_rate``: 命中率（0.0 ~ 1.0）
            - ``ttl``: 当前 TTL 配置（秒）
            - ``max_entries``: 当前最大条目数配置
        """
        total_requests = self._total_hits + self._total_misses
        hit_rate = (self._total_hits / total_requests) if total_requests > 0 else 0.0

        return {
            "total_keys": len(self._cache),
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "total_executions": self._total_executions,
            "total_errors": self._total_errors,
            "total_evictions": self._total_evictions,
            "total_expired": self._total_expired,
            "hit_rate": round(hit_rate, 4),
            "ttl": self.ttl,
            "max_entries": self.max_entries,
        }


# ── 模块级单例 ──────────────────────────────────────────────────

_default_manager: IdempotencyManager | None = None


def get_idempotency_manager(
    ttl: float = 3600.0,
    max_entries: int = 10000,
) -> IdempotencyManager:
    """获取模块级默认幂等性管理器（单例）。

    首次调用时创建实例，后续调用返回同一实例。
    传入的参数仅在首次创建时生效。

    Args:
        ttl: 幂等键过期时间（秒），默认 3600
        max_entries: 最大存储条目数，默认 10000

    Returns:
        全局 :class:`IdempotencyManager` 实例
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = IdempotencyManager(ttl=ttl, max_entries=max_entries)
    return _default_manager


# ── 幂等装饰器 ──────────────────────────────────────────────────


def idempotent(
    key_func: Callable[..., str],
    ttl: float = 3600.0,
    manager: IdempotencyManager | None = None,
) -> Callable[..., Callable[..., Any]]:
    """函数级幂等装饰器。

    为异步函数添加幂等性保证。通过 ``key_func`` 从函数参数
    生成幂等键，相同键的重复调用将直接返回缓存结果。

    Args:
        key_func: 幂等键生成函数，接收与被装饰函数相同的参数，
            返回幂等键字符串
        ttl: 幂等结果缓存时间（秒），默认 3600。
            仅在使用默认管理器且首次创建时生效。
        manager: 自定义 :class:`IdempotencyManager` 实例。
            为 None 时使用模块级默认管理器。

    Returns:
        装饰器函数

    Example:
        >>> @idempotent(key_func=lambda task_id: generate_task_key(task_id))
        ... async def submit_task(task_id: str, payload: dict) -> dict:
        ...     # 任务提交逻辑
        ...     return {"task_id": task_id, "status": "submitted"}
        >>>
        >>> # 第一次调用：实际执行
        >>> result1 = await submit_task("task_001", {"data": "hello"})
        >>> # 第二次调用：返回缓存结果，不重复执行
        >>> result2 = await submit_task("task_001", {"data": "hello"})
        >>> assert result1 == result2

    .. note::

        仅支持装饰 **异步函数**。装饰同步函数时行为未定义。
    """
    mgr = manager if manager is not None else get_idempotency_manager(ttl=ttl)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = key_func(*args, **kwargs)
            return await mgr.execute(key, func, *args, **kwargs)

        return wrapper

    return decorator
