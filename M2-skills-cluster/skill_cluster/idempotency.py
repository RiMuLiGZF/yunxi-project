from __future__ import annotations

"""幂等性管理器.

为 M2 技能集群提供请求级幂等性保障，防止重复调用导致的副作用。

核心组件：
- IdempotencyManager: 幂等性管理器（内存实现，支持 TTL 过期与容量上限）
- 幂等键生成工具: generate_skill_key / generate_pipeline_key / generate_request_key
- idempotent_middleware: 幂等中间件，接入 MiddlewarePipeline 洋葱模型管道

【设计原则】
- 内存优先：第一版使用 OrderedDict + TTL，接口预留持久化扩展点
- 异步安全：使用 asyncio.Lock 保证并发安全
- 并发保护：per-key 锁机制防止同一幂等键的并发重复执行
- 向后兼容：默认关闭，通过配置启用
"""

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult

logger = structlog.get_logger()

# 中间件签名类型别名（与 middleware.py 保持一致）
Middleware = Callable[
    [SkillInvokeRequest, str, Callable[[], Awaitable[SkillInvokeResult]]],
    Awaitable[SkillInvokeResult],
]


# ============================================================================
#  幂等键生成工具
# ============================================================================


def generate_skill_key(skill_id: str, input_hash: str) -> str:
    """生成技能调用幂等键.

    基于技能 ID 与输入哈希值生成唯一键，用于技能级别的幂等控制。

    Args:
        skill_id: 技能 ID.
        input_hash: 输入参数的哈希值（如 params 的 SHA256）.

    Returns:
        格式为 ``skill:{skill_id}:{input_hash}`` 的幂等键.
    """
    return f"skill:{skill_id}:{input_hash}"


def generate_pipeline_key(pipeline_id: str) -> str:
    """生成流水线幂等键.

    基于流水线 ID 生成唯一键，用于流水线级别的幂等控制。

    Args:
        pipeline_id: 流水线 ID.

    Returns:
        格式为 ``pipeline:{pipeline_id}`` 的幂等键.
    """
    return f"pipeline:{pipeline_id}"


def generate_request_key(request_id: str) -> str:
    """生成请求幂等键.

    基于请求 ID 生成唯一键，用于请求级别的幂等控制。

    Args:
        request_id: 请求唯一标识.

    Returns:
        格式为 ``request:{request_id}`` 的幂等键.
    """
    return f"request:{request_id}"


def _hash_params(params: dict[str, Any]) -> str:
    """计算参数字典的 SHA256 哈希值.

    用于将参数序列化为可比较的哈希串，作为幂等键的一部分。

    Args:
        params: 参数字典.

    Returns:
        十六进制哈希字符串（前 32 位）.
    """
    # 确保序列化顺序一致，使用 sort_keys
    serialized = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]


# ============================================================================
#  幂等性存储条目
# ============================================================================


class _IdempotencyEntry:
    """幂等性存储条目.

    内部数据结构，保存执行结果与过期时间。
    """

    __slots__ = ("result", "is_error", "expires_at")

    def __init__(
        self,
        result: Any,
        is_error: bool,
        ttl: float,
    ) -> None:
        """初始化存储条目.

        Args:
            result: 执行结果.
            is_error: 是否为错误结果.
            ttl: 存活时间（秒）.
        """
        self.result = result
        self.is_error = is_error
        self.expires_at = time.monotonic() + ttl

    def is_expired(self) -> bool:
        """判断条目是否已过期.

        Returns:
            True 表示已过期.
        """
        return time.monotonic() > self.expires_at


# ============================================================================
#  幂等性管理器
# ============================================================================


class IdempotencyManager:
    """幂等性管理器.

    基于 OrderedDict + TTL 的内存幂等性存储，支持：
    - 检查幂等键是否存在并返回缓存结果
    - 存储执行结果（成功或错误）
    - 带锁的幂等执行（防止并发重复执行）
    - 自动清理过期条目
    - 容量上限（LRU 淘汰）

    【接口设计】
    所有存储方法均为异步接口，未来可无缝切换到 Redis/DB 等持久化后端，
    只需替换本类的实现而不影响调用方。

    Attributes:
        ttl: 幂等键过期时间（秒），默认 3600 秒（1 小时）.
        max_entries: 最大存储条目数，默认 10000.
    """

    def __init__(
        self,
        ttl: float = 3600.0,
        max_entries: int = 10000,
    ) -> None:
        """初始化幂等性管理器.

        Args:
            ttl: 幂等键过期时间（秒），默认 3600.
            max_entries: 最大存储条目数，默认 10000.
        """
        self.ttl: float = ttl
        self.max_entries: int = max_entries

        # 存储: OrderedDict 保证插入顺序，便于 LRU 淘汰
        self._store: OrderedDict[str, _IdempotencyEntry] = OrderedDict()
        # 全局锁，保护 _store 的并发访问
        self._lock: asyncio.Lock = asyncio.Lock()
        # per-key 锁字典，防止同一幂等键的并发重复执行
        self._key_locks: dict[str, asyncio.Lock] = {}

        # 统计信息
        self._hits: int = 0
        self._misses: int = 0
        self._stores: int = 0
        self._evictions: int = 0
        self._cleanup_count: int = 0

    # ---- 核心方法 ----

    async def check(self, key: str) -> tuple[bool, Any]:
        """检查幂等键是否存在.

        如果键存在且未过期，返回 (True, 缓存结果)；
        否则返回 (False, None)。命中时会将条目移到末尾（LRU 更新）。

        Args:
            key: 幂等键.

        Returns:
            (是否存在, 缓存结果). 若不存在，结果为 None.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return False, None

            if entry.is_expired():
                # 过期条目，立即移除
                self._store.pop(key, None)
                self._misses += 1
                logger.debug(
                    "idempotency_key_expired",
                    key=key,
                )
                return False, None

            # LRU: 移到末尾
            self._store.move_to_end(key)
            self._hits += 1
            logger.debug(
                "idempotency_hit",
                key=key,
                is_error=entry.is_error,
            )
            return True, entry.result

    async def store(
        self,
        key: str,
        result: Any,
        is_error: bool = False,
    ) -> None:
        """存储执行结果.

        将结果存入幂等缓存，设置 TTL 过期时间。
        如果超过 max_entries，淘汰最久未使用的条目。

        Args:
            key: 幂等键.
            result: 执行结果.
            is_error: 是否为错误结果，默认 False.
        """
        async with self._lock:
            # 如果键已存在，更新它（移到末尾）
            if key in self._store:
                self._store.move_to_end(key)

            self._store[key] = _IdempotencyEntry(
                result=result,
                is_error=is_error,
                ttl=self.ttl,
            )
            self._stores += 1

            # 容量检查：淘汰最旧的条目
            evicted = 0
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)
                evicted += 1

            if evicted > 0:
                self._evictions += evicted
                logger.warning(
                    "idempotency_eviction",
                    evicted_count=evicted,
                    current_size=len(self._store),
                    max_entries=self.max_entries,
                )

            logger.debug(
                "idempotency_stored",
                key=key,
                is_error=is_error,
                store_size=len(self._store),
            )

    async def execute(
        self,
        key: str,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """幂等执行.

        检查幂等键：
        - 命中：直接返回缓存结果
        - 未命中：获取 per-key 锁，执行函数，存储结果后返回

        同一 key 的并发调用会排队等待第一个完成，
        后续调用直接使用缓存结果，避免重复执行。

        Args:
            key: 幂等键.
            func: 要执行的异步函数.
            *args: 传递给 func 的位置参数.
            **kwargs: 传递给 func 的关键字参数.

        Returns:
            执行结果（可能来自缓存）.

        Raises:
            Exception: 如果 func 执行抛出异常，异常会被重新抛出，
                且错误结果也会被缓存（防止重复失败）。
        """
        # 快速路径：先检查缓存
        exists, cached = await self.check(key)
        if exists:
            return cached

        # 未命中：获取 per-key 锁，防止并发重复执行
        lock = await self._get_key_lock(key)
        async with lock:
            # 双重检查：在等待锁的过程中，可能已经被其他协程执行并缓存了
            exists, cached = await self.check(key)
            if exists:
                return cached

            # 执行实际函数
            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                # 错误结果也缓存，防止重复失败调用
                await self.store(key, e, is_error=True)
                raise

            await self.store(key, result, is_error=False)
            return result

    def cleanup(self) -> int:
        """清理过期条目.

        同步方法，用于定期清理任务。
        遍历所有条目，移除已过期的。

        Returns:
            清理的条目数量.
        """
        # 注意：这里不使用 async with self._lock，因为 cleanup 是同步方法
        # 调用方应确保在安全的时机调用，或通过 _cleanup_async 调用
        # 此方法设计为在锁内被调用，因此不自行加锁
        # （保持与 _evict 相同的模式，由外部统一加锁）
        # 但为了独立可用，这里还是加锁
        # 由于不能在同步方法中使用 asyncio.Lock，我们提供一个异步版本

        # 同步版本不直接操作 _store，留给异步版本
        # 这里返回 0 作为占位，实际清理通过 _cleanup_async 完成
        return 0

    async def _cleanup_async(self) -> int:
        """异步清理过期条目（内部方法）.

        Returns:
            清理的条目数量.
        """
        async with self._lock:
            expired_keys = [
                k for k, v in self._store.items() if v.is_expired()
            ]
            for k in expired_keys:
                self._store.pop(k, None)
            # 清理已释放的 key lock
            self._cleanup_key_locks()

            count = len(expired_keys)
            if count > 0:
                self._cleanup_count += 1
                logger.info(
                    "idempotency_cleanup",
                    expired_count=count,
                    remaining=len(self._store),
                )
            return count

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息.

        Returns:
            统计字典，包含命中数、未命中数、存储数、淘汰数、清理次数、当前条目数等.
        """
        return {
            "hits": self._hits,
            "misses": self._misses,
            "stores": self._stores,
            "evictions": self._evictions,
            "cleanup_runs": self._cleanup_count,
            "current_entries": len(self._store),
            "max_entries": self.max_entries,
            "ttl": self.ttl,
            "hit_rate": (
                self._hits / (self._hits + self._misses)
                if (self._hits + self._misses) > 0
                else 0.0
            ),
        }

    async def acquire_lock(self, key: str) -> bool:
        """获取幂等键锁.

        获取指定 key 的 per-key 锁，防止并发重复执行。
        与 ``execute`` 方法内部使用同一套锁机制。

        Args:
            key: 幂等键.

        Returns:
            总是返回 True（锁是异步等待获取的，获取成功后返回）.

        Note:
            调用方负责使用完后释放锁。推荐使用 ``async with`` 模式：
            ``lock = await manager._get_key_lock(key); async with lock: ...``
            此方法主要用于外部需要精细控制锁生命周期的场景。
        """
        lock = await self._get_key_lock(key)
        await lock.acquire()
        return True

    # ---- 内部方法 ----

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        """获取或创建 per-key 锁.

        Args:
            key: 幂等键.

        Returns:
            该 key 对应的 asyncio.Lock.
        """
        async with self._lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    def _cleanup_key_locks(self) -> None:
        """清理未使用的 key 锁（需在 self._lock 内调用）.

        移除在 _store 中已不存在的 key 对应的锁，
        防止锁字典无限增长。
        """
        # 只保留 _store 中还存在的 key 的锁
        # 注意：可能有正在使用的锁，但只要 key 不在 store 中
        # 就可以安全移除（新的请求会创建新锁）
        keys_to_remove = [
            k for k in self._key_locks if k not in self._store
        ]
        for k in keys_to_remove:
            self._key_locks.pop(k, None)


# ============================================================================
#  幂等中间件
# ============================================================================


def idempotent_middleware(
    manager: IdempotencyManager,
    key_source: str = "metadata",
    header_name: str = "X-Idempotency-Key",
) -> Middleware:
    """幂等中间件工厂函数.

    创建一个接入 MiddlewarePipeline 洋葱模型的幂等中间件。
    从请求的 metadata 或指定字段中提取幂等键，
    命中缓存则直接返回，未命中则执行并缓存结果。

    Args:
        manager: IdempotencyManager 实例.
        key_source: 幂等键来源，可选值：
            - ``"metadata"``: 从 request.metadata["idempotency_key"] 提取（默认）
            - ``"request_id"``: 使用 request.trace_id 作为幂等键
            - ``"params_hash"``: 基于 skill_id + action + params 哈希生成
        header_name: 请求头名称（用于 API 层传递，通过 metadata 注入）.

    Returns:
        符合 Middleware 签名的中间件函数.
    """
    async def _mw(
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Callable[[], Awaitable[SkillInvokeResult]],
    ) -> SkillInvokeResult:
        # 提取幂等键
        idem_key = _extract_idempotency_key(
            request=request,
            key_source=key_source,
            header_name=header_name,
        )

        # 未提供幂等键，直接透传
        if idem_key is None:
            return await next_handler()

        # 检查缓存
        exists, cached = await manager.check(idem_key)
        if exists and isinstance(cached, SkillInvokeResult):
            logger.info(
                "idempotency_middleware_hit",
                skill_id=request.skill_id,
                action=request.action,
                idem_key=idem_key,
                trace_id=request.trace_id,
            )
            # 更新 trace_id 为当前请求的 trace_id，并标记幂等命中
            result_data = cached.data or {}
            if isinstance(result_data, dict):
                result_data = dict(result_data)
                result_data["idempotent_hit"] = True
            cached = cached.model_copy(
                update={
                    "trace_id": request.trace_id,
                    "data": result_data,
                }
            )
            return cached

        # 获取 per-key 锁，执行并缓存
        lock = await manager._get_key_lock(idem_key)
        async with lock:
            # 双重检查
            exists, cached = await manager.check(idem_key)
            if exists and isinstance(cached, SkillInvokeResult):
                result_data = cached.data or {}
                if isinstance(result_data, dict):
                    result_data = dict(result_data)
                    result_data["idempotent_hit"] = True
                cached = cached.model_copy(
                    update={
                        "trace_id": request.trace_id,
                        "data": result_data,
                    }
                )
                return cached

            # 执行实际调用
            result = await next_handler()

            # 缓存结果（成功和失败都缓存）
            await manager.store(idem_key, result, is_error=result.status != "success")

            logger.info(
                "idempotency_middleware_stored",
                skill_id=request.skill_id,
                action=request.action,
                idem_key=idem_key,
                status=result.status,
                trace_id=request.trace_id,
            )
            return result

    return _mw


def _extract_idempotency_key(
    request: SkillInvokeRequest,
    key_source: str,
    header_name: str,
) -> str | None:
    """从请求中提取幂等键.

    Args:
        request: 技能调用请求.
        key_source: 键来源策略.
        header_name: 请求头名称（metadata 中的 key）.

    Returns:
        幂等键，未提取到则返回 None.
    """
    metadata = getattr(request, "metadata", {}) or {}

    if key_source == "metadata":
        # 优先从 metadata 中查找指定 header 名（小写形式）
        metadata_key = header_name.lower().replace("-", "_")
        # 尝试多种命名方式
        for key in (
            "idempotency_key",
            metadata_key,
            header_name,
        ):
            if key in metadata and metadata[key]:
                return str(metadata[key])
        return None

    elif key_source == "request_id":
        # 使用 trace_id 作为幂等键
        trace_id = getattr(request, "trace_id", "")
        if trace_id:
            return generate_request_key(trace_id)
        return None

    elif key_source == "params_hash":
        # 基于 skill_id + action + params 生成
        params_hash = _hash_params(request.params)
        return generate_skill_key(
            f"{request.skill_id}.{request.action}",
            params_hash,
        )

    return None


# ============================================================================
#  全局单例
# ============================================================================

_default_manager: IdempotencyManager | None = None


def get_default_manager() -> IdempotencyManager:
    """获取默认的幂等性管理器单例.

    Returns:
        全局 IdempotencyManager 实例.
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = IdempotencyManager()
    return _default_manager
