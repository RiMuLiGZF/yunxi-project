"""
云汐内核 - 统一资源管理器

为 M1 Agent 集群提供资源泄漏防护能力，集中管理连接、内存、文件句柄等资源。

核心特性：
- 统一资源注册与生命周期管理
- 泄漏检测（长时间未释放的资源）
- 分类别资源统计与清理
- 异步安全（asyncio.Lock）
- 上下文管理器装饰器确保自动释放
- 鸭子类型：资源只需支持 close() 方法

使用方式：
    manager = ResourceManager(name="agent_hub", max_resources=1000)
    rid = manager.register(conn, category="db_connection")
    # ... 使用资源 ...
    manager.release(rid)

    # 或使用上下文管理器：
    async with managed_resource(rid, manager):
        # ... 使用资源 ...
        pass  # 退出时自动释放
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class Resource(Protocol):
    """资源协议（鸭子类型）。

    任何具有 ``close()`` 方法的对象都可以作为资源注册。
    """

    def close(self) -> None:
        """关闭/释放资源。"""
        ...


@dataclass
class ResourceEntry:
    """资源条目（内部使用）。

    Attributes:
        resource_id: 资源唯一标识
        resource: 资源对象（需支持 close()）
        category: 资源类别（如 db_connection、file_handle、network_socket）
        created_at: 注册时间戳
        last_accessed: 最后访问时间戳
        metadata: 附加元数据
    """

    resource_id: str
    resource: Any
    category: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class ResourceManager:
    """统一资源管理器。

    集中管理连接、内存、文件句柄等资源，防止泄漏。
    支持分类注册、泄漏检测、批量清理、统计查询。

    Attributes:
        name: 管理器名称，用于日志标识
        max_resources: 最大资源数（防泄漏阈值），超过后拒绝新注册

    Example:
        >>> manager = ResourceManager(name="hub", max_resources=1000)
        >>> rid = manager.register(my_conn, category="db_connection")
        >>> stats = manager.get_stats()
        >>> leaks = manager.leak_check(max_idle_seconds=3600)
        >>> manager.release(rid)
    """

    def __init__(
        self,
        name: str = "default",
        max_resources: int = 10000,
    ) -> None:
        """初始化资源管理器。

        Args:
            name: 管理器名称，用于日志区分
            max_resources: 最大允许注册的资源数，超过阈值后拒绝新注册，
                          防止无限制增长导致的内存泄漏
        """
        self.name: str = name
        self.max_resources: int = max_resources

        self._resources: dict[str, ResourceEntry] = {}
        """resource_id -> ResourceEntry"""

        self._lock: asyncio.Lock = asyncio.Lock()
        """异步锁，保证并发安全"""

        self._logger: structlog.stdlib.BoundLogger = logger.bind(
            service="resource_manager",
            manager_name=name,
        )

        # 统计
        self._total_registered: int = 0
        self._total_released: int = 0
        self._total_leaked: int = 0  # 被泄漏检测清理的资源数

    # ── 注册与释放 ────────────────────────────────────────

    async def register(
        self,
        resource: Any,
        category: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """注册一个资源，返回资源 ID。

        资源必须支持 ``close()`` 方法（鸭子类型）。
        如果当前资源数已达到 max_resources，将拒绝注册并抛出 RuntimeError。

        Args:
            resource: 资源对象，必须具有 close() 方法
            category: 资源类别，用于分类统计和批量清理
            metadata: 附加元数据，便于调试和审计

        Returns:
            资源 ID（字符串），用于后续释放和查询

        Raises:
            RuntimeError: 资源数超过 max_resources 阈值
            TypeError: 资源不支持 close() 方法
        """
        # 鸭子类型检查
        if not hasattr(resource, "close") or not callable(resource.close):
            raise TypeError(
                f"Resource of type {type(resource).__name__} does not have a callable close() method"
            )

        resource_id = f"res_{uuid.uuid4().hex[:12]}"

        async with self._lock:
            if len(self._resources) >= self.max_resources:
                self._logger.error(
                    "resource_register_rejected_max_exceeded",
                    category=category,
                    current_count=len(self._resources),
                    max_resources=self.max_resources,
                )
                raise RuntimeError(
                    f"Resource manager '{self.name}' has reached max_resources "
                    f"({self.max_resources}), registration rejected"
                )

            entry = ResourceEntry(
                resource_id=resource_id,
                resource=resource,
                category=category,
                metadata=metadata or {},
            )
            self._resources[resource_id] = entry
            self._total_registered += 1

        self._logger.debug(
            "resource_registered",
            resource_id=resource_id,
            category=category,
            current_count=len(self._resources),
        )
        return resource_id

    async def release(self, resource_id: str) -> bool:
        """释放指定资源。

        调用资源的 ``close()`` 方法并从注册表中移除。
        若资源已不存在或释放失败，返回 False。

        Args:
            resource_id: 资源 ID

        Returns:
            True 表示成功释放，False 表示资源不存在或释放异常
        """
        async with self._lock:
            entry = self._resources.pop(resource_id, None)

        if entry is None:
            self._logger.warning(
                "resource_release_not_found",
                resource_id=resource_id,
            )
            return False

        try:
            entry.resource.close()
            self._total_released += 1
            self._logger.debug(
                "resource_released",
                resource_id=resource_id,
                category=entry.category,
                age_seconds=round(time.time() - entry.created_at, 2),
            )
            return True
        except Exception as exc:
            self._logger.error(
                "resource_release_failed",
                resource_id=resource_id,
                category=entry.category,
                error=str(exc),
            )
            # 即使 close 失败，也从注册表中移除，避免重复尝试
            self._total_released += 1
            return False

    # ── 分类清理 ──────────────────────────────────────────

    async def cleanup_category(self, category: str) -> int:
        """清理指定类别的所有资源。

        按类别批量释放资源，常用于特定子系统下线时的资源回收。

        Args:
            category: 资源类别

        Returns:
            成功释放的资源数量
        """
        # 先收集该类别下所有资源 ID（避免遍历时修改字典）
        async with self._lock:
            target_ids = [
                rid for rid, entry in self._resources.items()
                if entry.category == category
            ]

        self._logger.info(
            "cleanup_category_start",
            category=category,
            count=len(target_ids),
        )

        released = 0
        for rid in target_ids:
            if await self.release(rid):
                released += 1

        self._logger.info(
            "cleanup_category_complete",
            category=category,
            released=released,
            total=len(target_ids),
        )
        return released

    # ── 统计 ──────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """获取资源统计信息。

        Returns:
            统计字典，包含：
            - total_registered: 累计注册数
            - total_released: 累计释放数
            - total_leaked: 累计泄漏清理数
            - active_count: 当前活跃资源数
            - max_resources: 最大资源数阈值
            - utilization: 使用率（0.0 ~ 1.0）
            - by_category: 按类别统计的活跃资源数
            - oldest_age_seconds: 最老资源的存活时间
        """
        async with self._lock:
            active_count = len(self._resources)
            by_category: dict[str, int] = {}
            oldest_age = 0.0
            now = time.time()

            for entry in self._resources.values():
                by_category[entry.category] = by_category.get(entry.category, 0) + 1
                age = now - entry.created_at
                if age > oldest_age:
                    oldest_age = age

        utilization = active_count / self.max_resources if self.max_resources > 0 else 0.0

        return {
            "manager_name": self.name,
            "total_registered": self._total_registered,
            "total_released": self._total_released,
            "total_leaked": self._total_leaked,
            "active_count": active_count,
            "max_resources": self.max_resources,
            "utilization": round(utilization, 4),
            "by_category": by_category,
            "oldest_age_seconds": round(oldest_age, 2),
        }

    # ── 泄漏检测 ──────────────────────────────────────────

    async def leak_check(
        self,
        max_idle_seconds: float = 3600.0,
        auto_cleanup: bool = False,
    ) -> dict[str, Any]:
        """泄漏检测：查找长时间未释放的资源。

        基于资源的 ``last_accessed`` 时间判断，若超过 max_idle_seconds
        则视为潜在泄漏。

        Args:
            max_idle_seconds: 最大空闲时间（秒），超过则视为泄漏
            auto_cleanup: 是否自动清理泄漏资源（调用 close()）

        Returns:
            泄漏检测结果字典：
            - leak_count: 泄漏资源数量
            - leaked: 泄漏资源列表 [{resource_id, category, idle_seconds, metadata}]
            - auto_cleaned: 自动清理的资源数量（仅 auto_cleanup=True 时有效）
        """
        now = time.time()
        leaked_entries: list[dict[str, Any]] = []

        async with self._lock:
            for entry in self._resources.values():
                idle = now - entry.last_accessed
                if idle > max_idle_seconds:
                    leaked_entries.append({
                        "resource_id": entry.resource_id,
                        "category": entry.category,
                        "idle_seconds": round(idle, 2),
                        "age_seconds": round(now - entry.created_at, 2),
                        "metadata": dict(entry.metadata),
                    })

        result: dict[str, Any] = {
            "leak_count": len(leaked_entries),
            "leaked": leaked_entries,
            "auto_cleaned": 0,
            "max_idle_seconds": max_idle_seconds,
        }

        if leaked_entries:
            self._logger.warning(
                "resource_leak_detected",
                leak_count=len(leaked_entries),
                max_idle_seconds=max_idle_seconds,
                sample_ids=[e["resource_id"] for e in leaked_entries[:5]],
            )

        if auto_cleanup and leaked_entries:
            cleaned = 0
            for entry_info in leaked_entries:
                if await self.release(entry_info["resource_id"]):
                    cleaned += 1
                    self._total_leaked += 1
            result["auto_cleaned"] = cleaned
            self._logger.info(
                "resource_leak_auto_cleanup",
                cleaned=cleaned,
                total=len(leaked_entries),
            )

        return result

    # ── 资源访问更新 ──────────────────────────────────────

    async def touch(self, resource_id: str) -> bool:
        """更新资源的最后访问时间。

        用于在资源被使用时刷新 last_accessed，避免被泄漏检测误判。

        Args:
            resource_id: 资源 ID

        Returns:
            True 表示成功更新，False 表示资源不存在
        """
        async with self._lock:
            entry = self._resources.get(resource_id)
            if entry is None:
                return False
            entry.last_accessed = time.time()
        return True

    # ── 全部清理 ──────────────────────────────────────────

    async def cleanup_all(self) -> int:
        """清理所有资源（关闭时调用）。

        遍历所有已注册资源，逐一调用 close() 并清空注册表。
        即使部分资源关闭失败，也会继续清理其余资源。

        Returns:
            成功释放的资源数量
        """
        async with self._lock:
            all_ids = list(self._resources.keys())

        self._logger.info(
            "cleanup_all_start",
            total=len(all_ids),
        )

        released = 0
        for rid in all_ids:
            if await self.release(rid):
                released += 1

        self._logger.info(
            "cleanup_all_complete",
            released=released,
            total=len(all_ids),
        )
        return released


# ── 上下文管理器装饰器 ────────────────────────────────────


@asynccontextmanager
async def managed_resource(
    resource_id: str,
    manager: ResourceManager,
) -> AsyncIterator[None]:
    """资源上下文管理器，确保资源自动释放。

    进入上下文时不做额外操作（假设资源已注册），
    退出时自动调用 ``manager.release(resource_id)`` 释放资源。

    Args:
        resource_id: 已注册的资源 ID
        manager: 资源管理器实例

    Yields:
        None

    Example:
        >>> manager = ResourceManager()
        >>> rid = await manager.register(conn, "db")
        >>> async with managed_resource(rid, manager):
        ...     # 使用 conn
        ...     pass
        >>> # 退出上下文后，conn 已被自动释放
    """
    try:
        # 刷新访问时间，标记资源正在使用
        await manager.touch(resource_id)
        yield
    finally:
        await manager.release(resource_id)


# ── 模块级默认管理器 ──────────────────────────────────────

_default_manager: ResourceManager | None = None


def get_resource_manager(
    name: str = "global",
    max_resources: int = 10000,
) -> ResourceManager:
    """获取模块级默认资源管理器（单例）。

    首次调用时创建实例，后续调用返回同一实例。
    传入的参数仅在首次创建时生效。

    Args:
        name: 管理器名称，默认 "global"
        max_resources: 最大资源数，默认 10000

    Returns:
        全局 ResourceManager 实例
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = ResourceManager(name=name, max_resources=max_resources)
    return _default_manager
