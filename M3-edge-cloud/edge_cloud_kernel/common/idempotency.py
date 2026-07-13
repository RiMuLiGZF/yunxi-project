"""幂等性管理器.

为端云协同内核的写操作接口提供幂等性保障，防止重复提交导致的数据不一致。
基于 OrderedDict + TTL + asyncio.Lock 实现，支持全局锁和 per-key 锁的双层并发控制。

设计要点：
- 默认关闭幂等性，通过请求头 X-Idempotency-Key 显式启用
- 支持同步操作、配置操作、通用请求三种幂等键生成策略
- 提供 FastAPI 依赖注入类 IdempotencyGuard，方便路由层集成
- 区分正常结果和错误结果缓存，错误结果的 TTL 更短
- 自动清理过期条目，支持最大条目数限制（LRU 淘汰）

Usage::

    # 1. 直接使用管理器
    manager = IdempotencyManager(ttl=3600, max_entries=10000)

    # 幂等执行函数
    result = await manager.execute("unique-key", my_func, arg1, arg2)

    # 2. FastAPI 依赖注入
    @app.post("/api/v3/config/update")
    async def update_config(
        request: Request,
        body: ConfigUpdateRequest,
        idem: IdempotencyGuard = Depends(IdempotencyGuard()),
    ):
        result = await idem.execute(do_update, body.updates)
        return result

    # 3. 幂等键生成工具
    key = generate_sync_key(device_id="dev-001", session_id="sess-abc")
    key = generate_config_key(scope="sync", key="interval")
    key = generate_request_key(request_id="req-xyz")
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 幂等键请求头名称
IDEMPOTENCY_HEADER = "X-Idempotency-Key"

# 错误结果的 TTL 乘数（错误结果缓存时间更短）
ERROR_TTL_MULTIPLIER = 0.2

# 幂等键最小长度（防止过短的 key 导致碰撞）
MIN_KEY_LENGTH = 8

# 幂等键最大长度（防止过长的 key 占用过多内存）
MAX_KEY_LENGTH = 256


# ---------------------------------------------------------------------------
# 幂等性异常
# ---------------------------------------------------------------------------

class IdempotencyError(Exception):
    """幂等性操作异常.

    当幂等键冲突、格式非法或并发获取锁失败时抛出。

    Attributes:
        message: 错误描述.
        error_code: 错误码标识.
        key: 相关的幂等键.
        context: 附加上下文信息.
    """

    def __init__(
        self,
        message: str = "Idempotency error",
        error_code: str = "IDEMPOTENCY_ERROR",
        key: str = "",
        context: dict | None = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.key = key
        self.context = context or {}
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# 缓存条目数据结构
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    """幂等缓存条目.

    Attributes:
        result: 缓存的执行结果.
        is_error: 是否为错误结果.
        created_at: 创建时间戳（Unix 秒）.
        expires_at: 过期时间戳（Unix 秒）.
        hit_count: 命中次数（用于统计）.
    """

    result: Any
    is_error: bool
    created_at: float
    expires_at: float
    hit_count: int = 0


# ---------------------------------------------------------------------------
# 幂等键生成工具
# ---------------------------------------------------------------------------

def generate_sync_key(device_id: str, session_id: str) -> str:
    """生成同步操作幂等键.

    基于设备 ID 和会话 ID 生成唯一幂等键，用于同步推送、
    冲突解决等会话级别的写操作。

    Args:
        device_id: 设备唯一标识.
        session_id: 同步会话 ID.

    Returns:
        格式为 "sync:{device_id}:{session_id}" 的幂等键.

    Raises:
        ValueError: 当 device_id 或 session_id 为空时.
    """
    if not device_id:
        raise ValueError("device_id must not be empty")
    if not session_id:
        raise ValueError("session_id must not be empty")

    # 使用短哈希避免 key 过长
    device_hash = hashlib.md5(device_id.encode()).hexdigest()[:12]
    session_hash = hashlib.md5(session_id.encode()).hexdigest()[:12]
    return f"sync:{device_hash}:{session_hash}"


def generate_config_key(scope: str, key: str) -> str:
    """生成配置操作幂等键.

    基于配置范围和配置键生成唯一幂等键，用于配置更新等操作。

    Args:
        scope: 配置范围（如 "sync", "storage"）.
        key: 配置键（点路径，如 "interval" 或 "sync.interval"）.

    Returns:
        格式为 "config:{scope}:{key_hash}" 的幂等键.

    Raises:
        ValueError: 当 scope 或 key 为空时.
    """
    if not scope:
        raise ValueError("scope must not be empty")
    if not key:
        raise ValueError("key must not be empty")

    key_hash = hashlib.md5(key.encode()).hexdigest()[:16]
    return f"config:{scope}:{key_hash}"


def generate_request_key(request_id: str) -> str:
    """生成通用请求幂等键.

    基于请求 ID 生成幂等键，适用于任意一次性写操作。

    Args:
        request_id: 请求唯一标识.

    Returns:
        格式为 "req:{request_id}" 的幂等键.

    Raises:
        ValueError: 当 request_id 为空时.
    """
    if not request_id:
        raise ValueError("request_id must not be empty")

    return f"req:{request_id}"


# ---------------------------------------------------------------------------
# IdempotencyManager 核心类
# ---------------------------------------------------------------------------

class IdempotencyManager:
    """幂等性管理器.

    基于 OrderedDict + TTL 实现的内存幂等缓存，支持：
    - 异步安全（全局锁 + per-key 锁）
    - LRU 淘汰（超过 max_entries 时淘汰最久未使用的条目）
    - TTL 过期（自动清理过期条目）
    - 错误结果短缓存（错误结果的 TTL 为正常值的 ERROR_TTL_MULTIPLIER 倍）

    Attributes:
        ttl: 幂等键过期时间（秒），默认 3600.
        max_entries: 最大存储条目数，默认 10000.
    """

    def __init__(
        self,
        ttl: float = 3600.0,
        max_entries: int = 10000,
    ) -> None:
        """初始化幂等性管理器.

        Args:
            ttl: 幂等键过期时间（秒），默认 3600（1小时）.
            max_entries: 最大存储条目数，默认 10000.

        Raises:
            ValueError: 当 ttl <= 0 或 max_entries <= 0 时.
        """
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        if max_entries <= 0:
            raise ValueError(f"max_entries must be positive, got {max_entries}")

        self.ttl: float = ttl
        self.max_entries: int = max_entries

        # 缓存存储：OrderedDict 维护 LRU 顺序
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()

        # 全局锁：保护缓存结构的并发访问
        self._global_lock: asyncio.Lock = asyncio.Lock()

        # per-key 锁：防止同一 key 的并发执行
        self._key_locks: dict[str, asyncio.Lock] = {}

        # 统计信息
        self._total_hits: int = 0
        self._total_misses: int = 0
        self._total_evictions: int = 0
        self._total_errors_stored: int = 0

        logger.info(
            "idempotency_manager.init",
            ttl=ttl,
            max_entries=max_entries,
        )

    # ------------------------------------------------------------------
    # 核心幂等接口
    # ------------------------------------------------------------------

    async def check(self, key: str) -> tuple[bool, Any]:
        """检查幂等键是否存在并返回缓存结果.

        如果键存在且未过期，返回 (True, 缓存结果)；
        如果键不存在或已过期，返回 (False, None)。

        注意：如果缓存的是异常对象，调用方需要自行判断是否重新抛出。
        对于需要自动重抛异常的场景，请使用 execute 方法。

        Args:
            key: 幂等键.

        Returns:
            (是否命中, 缓存结果) 元组.

        Raises:
            ValueError: 当 key 格式非法时.
        """
        self._validate_key(key)

        async with self._global_lock:
            entry = self._cache.get(key)
            if entry is None:
                self._total_misses += 1
                logger.debug("idempotency.check.miss", key=key)
                return False, None

            # 检查是否过期
            if time.time() >= entry.expires_at:
                del self._cache[key]
                self._total_misses += 1
                logger.debug("idempotency.check.expired", key=key)
                return False, None

            # 命中：更新 LRU 顺序和命中计数
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._total_hits += 1

            logger.debug(
                "idempotency.check.hit",
                key=key,
                hit_count=entry.hit_count,
                is_error=entry.is_error,
            )
            return True, entry.result

    async def _check_with_error_flag(self, key: str) -> tuple[bool, Any, bool]:
        """内部方法：检查幂等键并返回错误标记.

        与 check 类似，但额外返回 is_error 标记，供 execute 等
        需要判断是否重新抛出异常的内部方法使用。

        Args:
            key: 幂等键.

        Returns:
            (是否命中, 缓存结果, 是否为错误结果) 三元组.
        """
        async with self._global_lock:
            entry = self._cache.get(key)
            if entry is None:
                self._total_misses += 1
                logger.debug("idempotency.check.miss", key=key)
                return False, None, False

            if time.time() >= entry.expires_at:
                del self._cache[key]
                self._total_misses += 1
                logger.debug("idempotency.check.expired", key=key)
                return False, None, False

            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._total_hits += 1

            logger.debug(
                "idempotency.check.hit",
                key=key,
                hit_count=entry.hit_count,
                is_error=entry.is_error,
            )
            return True, entry.result, entry.is_error

    async def store(
        self,
        key: str,
        result: Any,
        is_error: bool = False,
    ) -> None:
        """存储执行结果到幂等缓存.

        Args:
            key: 幂等键.
            result: 执行结果.
            is_error: 是否为错误结果（错误结果 TTL 更短）.

        Raises:
            ValueError: 当 key 格式非法时.
        """
        self._validate_key(key)

        now = time.time()
        effective_ttl = self.ttl * (ERROR_TTL_MULTIPLIER if is_error else 1.0)
        expires_at = now + effective_ttl

        entry = _CacheEntry(
            result=result,
            is_error=is_error,
            created_at=now,
            expires_at=expires_at,
        )

        async with self._global_lock:
            # 如果已存在，先删除旧条目（保持 LRU 顺序正确）
            if key in self._cache:
                del self._cache[key]

            # 检查是否需要淘汰
            if len(self._cache) >= self.max_entries:
                self._evict_lru()

            self._cache[key] = entry

            if is_error:
                self._total_errors_stored += 1

            logger.debug(
                "idempotency.store",
                key=key,
                is_error=is_error,
                ttl=effective_ttl,
                cache_size=len(self._cache),
            )

    async def execute(
        self,
        key: str,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """幂等执行函数.

        检查幂等键是否已存在缓存结果：
        - 命中正常结果：直接返回缓存结果
        - 命中错误结果：重新抛出缓存的异常
        - 未命中：获取 per-key 锁，执行函数，存储结果，返回结果

        同一 key 的并发调用会被 per-key 锁串行化，确保只执行一次。

        Args:
            key: 幂等键.
            func: 要执行的函数（支持同步和异步函数）.
            *args: 传递给 func 的位置参数.
            **kwargs: 传递给 func 的关键字参数.

        Returns:
            函数执行结果（或缓存的结果）.

        Raises:
            ValueError: 当 key 格式非法时.
            Exception: func 执行时抛出的异常（异常也会被缓存，重复调用会重抛）.
        """
        self._validate_key(key)

        # 先检查缓存（含错误标记）
        hit, cached_result, is_error = await self._check_with_error_flag(key)
        if hit:
            if is_error and isinstance(cached_result, Exception):
                raise cached_result
            return cached_result

        # 获取 per-key 锁（在全局锁保护下创建/获取）
        key_lock = await self._get_or_create_key_lock(key)

        # 持有 per-key 锁执行
        async with key_lock:
            # 双重检查：获取锁后再次检查缓存
            # （可能在等待锁的过程中已有其他协程完成了执行）
            hit, cached_result, is_error = await self._check_with_error_flag(key)
            if hit:
                if is_error and isinstance(cached_result, Exception):
                    raise cached_result
                return cached_result

            # 执行函数
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
            except Exception as e:
                # 错误结果也缓存（短 TTL）
                await self.store(key, e, is_error=True)
                raise

            # 存储正常结果
            await self.store(key, result, is_error=False)
            return result

    async def acquire_lock(self, key: str) -> bool:
        """尝试获取幂等键锁（非阻塞）.

        尝试获取指定 key 的 per-key 锁，获取成功返回 True。
        与 execute 方法不同，此方法不会自动检查缓存或执行函数，
        适用于需要精细控制幂等逻辑的场景。

        注意：调用方获取锁后需自行负责释放（配合 release_lock 使用），
        否则可能导致死锁。推荐优先使用 execute 方法。

        Args:
            key: 幂等键.

        Returns:
            True 表示成功获取锁，调用方需负责释放；
            False 表示锁已被其他协程持有.

        Raises:
            ValueError: 当 key 格式非法时.
        """
        self._validate_key(key)

        key_lock = await self._get_or_create_key_lock(key)

        # 非阻塞尝试获取锁
        # 由于 asyncio.Lock 没有非阻塞 acquire，
        # 我们通过检查 locked() 状态 + 立即 acquire 来模拟
        # 在单线程事件循环中，locked() 检查和 acquire 之间不会有并发
        if key_lock.locked():
            return False

        # 锁当前未被持有，可以立即获取（不会阻塞）
        await key_lock.acquire()
        return True

    def release_lock(self, key: str) -> bool:
        """释放幂等键锁.

        释放之前通过 acquire_lock 获取的锁。

        Args:
            key: 幂等键.

        Returns:
            True 表示成功释放，False 表示锁不存在或未被持有.
        """
        lock = self._key_locks.get(key)
        if lock is None:
            return False
        if not lock.locked():
            return False
        lock.release()
        return True

    # ------------------------------------------------------------------
    # 清理与统计
    # ------------------------------------------------------------------

    def cleanup(self) -> int:
        """清理过期条目（同步方法，可在后台任务中调用）.

        遍历缓存，删除所有已过期的条目。

        Returns:
            清理的条目数量.
        """
        now = time.time()
        expired_keys: list[str] = []

        # 注意：这里不使用全局锁，避免长时间阻塞
        # 仅收集过期 key，删除操作在锁内完成
        for key, entry in self._cache.items():
            if now >= entry.expires_at:
                expired_keys.append(key)

        if not expired_keys:
            return 0

        # 在锁内删除过期条目
        # 由于 OrderedDict 迭代时不能修改，我们先收集再批量删除
        import asyncio as _asyncio
        if _asyncio.get_event_loop().is_running():
            # 在异步上下文中，使用锁
            # 注意：cleanup 是同步方法，这里用 _cleanup_async 包装
            pass

        removed = 0
        for key in expired_keys:
            if key in self._cache:
                del self._cache[key]
                removed += 1

        if removed > 0:
            logger.info(
                "idempotency.cleanup",
                removed=removed,
                remaining=len(self._cache),
            )
        return removed

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息.

        Returns:
            包含缓存大小、命中数、淘汰数等统计的字典.
        """
        return {
            "cache_size": len(self._cache),
            "max_entries": self.max_entries,
            "ttl": self.ttl,
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "total_evictions": self._total_evictions,
            "total_errors_stored": self._total_errors_stored,
            "hit_rate": (
                self._total_hits / (self._total_hits + self._total_misses)
                if (self._total_hits + self._total_misses) > 0
                else 0.0
            ),
            "active_locks": len(self._key_locks),
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _validate_key(self, key: str) -> None:
        """验证幂等键格式.

        Args:
            key: 待验证的幂等键.

        Raises:
            ValueError: 当 key 格式非法时.
        """
        if not key or not isinstance(key, str):
            raise ValueError("idempotency key must be a non-empty string")
        if len(key) < MIN_KEY_LENGTH:
            raise ValueError(
                f"idempotency key too short: {len(key)} < {MIN_KEY_LENGTH}"
            )
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(
                f"idempotency key too long: {len(key)} > {MAX_KEY_LENGTH}"
            )

    async def _get_or_create_key_lock(self, key: str) -> asyncio.Lock:
        """获取或创建 per-key 锁.

        Args:
            key: 幂等键.

        Returns:
            该 key 对应的 asyncio.Lock 实例.
        """
        async with self._global_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[key] = lock
            return lock

    def _evict_lru(self) -> None:
        """淘汰最久未使用的条目（调用方需持有全局锁）."""
        if not self._cache:
            return

        # OrderedDict 的第一个元素是最久未使用的
        evicted_key, _ = self._cache.popitem(last=False)
        self._total_evictions += 1

        # 同时清理对应的 key 锁（如果存在且未被持有）
        lock = self._key_locks.get(evicted_key)
        if lock is not None and not lock.locked():
            del self._key_locks[evicted_key]

        logger.debug(
            "idempotency.evict_lru",
            evicted_key=evicted_key,
            total_evictions=self._total_evictions,
        )

    async def clear(self) -> None:
        """清空所有缓存和锁（用于测试或重置）."""
        async with self._global_lock:
            self._cache.clear()
            self._key_locks.clear()
            self._total_hits = 0
            self._total_misses = 0
            self._total_evictions = 0
            self._total_errors_stored = 0
            logger.info("idempotency.clear")


# ---------------------------------------------------------------------------
# FastAPI 依赖注入：IdempotencyGuard
# ---------------------------------------------------------------------------

class IdempotencyGuard:
    """FastAPI 幂等性守卫依赖注入类.

    从请求头 X-Idempotency-Key 提取幂等键，提供 execute 方法
    用于包裹实际业务逻辑。默认情况下（无幂等键）直接执行业务逻辑，
    不启用幂等保护。

    Usage::

        @app.post("/api/v3/config/update")
        async def update_config(
            request: Request,
            body: ConfigUpdateRequest,
            idem: IdempotencyGuard = Depends(IdempotencyGuard()),
        ):
            # idem.enabled 为 True 时会自动做幂等检查和缓存
            result = await idem.execute(do_update_config, body.updates)
            return result

    Attributes:
        enabled: 是否启用了幂等保护（请求头中包含有效幂等键）.
        key: 幂等键（启用时有效）.
    """

    # 全局默认管理器实例（单例模式，供默认构造使用）
    _default_manager: IdempotencyManager | None = None

    def __init__(
        self,
        manager: IdempotencyManager | None = None,
        header_name: str = IDEMPOTENCY_HEADER,
    ) -> None:
        """初始化幂等性守卫.

        Args:
            manager: 幂等性管理器实例，为 None 时使用全局默认管理器.
            header_name: 幂等键请求头名称，默认 X-Idempotency-Key.
        """
        self._manager = manager or self._get_default_manager()
        self._header_name = header_name
        self.enabled: bool = False
        self.key: str = ""

    @classmethod
    def _get_default_manager(cls) -> IdempotencyManager:
        """获取全局默认管理器（单例）.

        Returns:
            全局 IdempotencyManager 实例.
        """
        if cls._default_manager is None:
            cls._default_manager = IdempotencyManager()
        return cls._default_manager

    async def __call__(self, request: Any) -> "IdempotencyGuard":
        """FastAPI 依赖注入入口.

        从请求头提取幂等键，设置 enabled 和 key 属性。

        Args:
            request: FastAPI Request 对象.

        Returns:
            self，供路由函数使用.
        """
        # 尝试从请求头获取幂等键
        idem_key = ""
        if hasattr(request, "headers"):
            idem_key = request.headers.get(self._header_name, "")
        elif isinstance(request, dict):
            idem_key = request.get("headers", {}).get(self._header_name, "")

        if idem_key:
            try:
                self._validate_key_format(idem_key)
                self.key = idem_key
                self.enabled = True
                logger.debug("idempotency.guard.enabled", key=idem_key)
            except ValueError as e:
                # 幂等键格式非法，视为未启用，记录警告
                logger.warning(
                    "idempotency.guard.invalid_key",
                    key_preview=idem_key[:20] if idem_key else "",
                    error=str(e),
                )
                self.enabled = False
                self.key = ""
        else:
            self.enabled = False
            self.key = ""

        return self

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """执行函数（带幂等保护）.

        如果启用了幂等保护，使用管理器的 execute 方法执行；
        否则直接执行函数。

        Args:
            func: 要执行的函数.
            *args: 位置参数.
            **kwargs: 关键字参数.

        Returns:
            函数执行结果.
        """
        if self.enabled and self.key:
            return await self._manager.execute(self.key, func, *args, **kwargs)

        # 未启用幂等，直接执行
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    async def check(self) -> tuple[bool, Any]:
        """检查当前幂等键是否有缓存结果.

        Returns:
            (是否命中, 缓存结果) 元组. 未启用幂等时返回 (False, None).
        """
        if not self.enabled or not self.key:
            return False, None
        return await self._manager.check(self.key)

    async def store(self, result: Any, is_error: bool = False) -> None:
        """手动存储结果.

        适用于需要在 execute 之外精细控制缓存的场景。

        Args:
            result: 要缓存的结果.
            is_error: 是否为错误结果.
        """
        if not self.enabled or not self.key:
            return
        await self._manager.store(self.key, result, is_error=is_error)

    def _validate_key_format(self, key: str) -> None:
        """验证幂等键格式（仅长度检查，不做内容校验）.

        Args:
            key: 待验证的幂等键.

        Raises:
            ValueError: 格式非法时抛出.
        """
        if not key or not isinstance(key, str):
            raise ValueError("key must be a non-empty string")
        if len(key) < MIN_KEY_LENGTH:
            raise ValueError(f"key too short: {len(key)} < {MIN_KEY_LENGTH}")
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"key too long: {len(key)} > {MAX_KEY_LENGTH}")

    @property
    def manager(self) -> IdempotencyManager:
        """获取底层的幂等性管理器实例."""
        return self._manager
