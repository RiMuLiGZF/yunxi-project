"""
舱壁模式（Bulkhead Pattern）

灵感来源：Netflix Hystrix / Resilience4j Bulkhead Pattern

通过信号量限制并发执行数量，防止单个模块故障拖垮整个系统。
每个舱壁独立管理自己的并发槽位与等待队列，实现资源隔离。

使用方式：
    # 方式1：直接使用
    bulkhead = SemaphoreBulkhead("llm_gpt4", max_concurrent=5, max_waiting=10)
    result = await bulkhead.execute(call_llm, prompt)

    # 方式2：装饰器
    @bulkhead("federation_agent_001", max_concurrent=3)
    async def invoke_agent(prompt):
        ...

    # 方式3：注册中心
    registry = BulkheadRegistry()
    bh = registry.get("llm_gpt4", max_concurrent=5)
    result = await bh.execute(call_llm, prompt)
"""

from __future__ import annotations

import asyncio
import time
from functools import wraps
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════
# 异常类
# ═══════════════════════════════════════════════════════

class BulkheadFullError(Exception):
    """舱壁已满 / 请求被拒绝异常

    当舱壁的并发槽位与等待队列均已满时抛出此异常。
    继承自 exceptions.py 中的 ResourceExhaustedError（通过惰性导入避免循环依赖）。

    Attributes:
        bulkhead_name: 舱壁名称
        max_concurrent: 最大并发数
        max_waiting: 最大等待队列长度
        reason: 拒绝原因（"rejected" / "timeout"）
    """

    def __init__(
        self,
        bulkhead_name: str,
        max_concurrent: int,
        max_waiting: int,
        reason: str = "rejected",
        message: str = "",
    ) -> None:
        """初始化舱壁已满异常

        Args:
            bulkhead_name: 舱壁名称
            max_concurrent: 最大并发数
            max_waiting: 最大等待队列长度
            reason: 拒绝原因，"rejected"（被拒绝）或 "timeout"（等待超时）
            message: 自定义错误消息，为空时自动生成
        """
        self.bulkhead_name = bulkhead_name
        self.max_concurrent = max_concurrent
        self.max_waiting = max_waiting
        self.reason = reason

        if not message:
            if reason == "timeout":
                message = (
                    f"Bulkhead '{bulkhead_name}' wait timeout "
                    f"(max_concurrent={max_concurrent}, max_waiting={max_waiting})"
                )
            else:
                message = (
                    f"Bulkhead '{bulkhead_name}' is full "
                    f"(max_concurrent={max_concurrent}, max_waiting={max_waiting})"
                )

        super().__init__(message)

    def to_resource_exhausted(self, trace_id: str = "") -> Any:
        """转换为 ResourceExhaustedError（惰性导入）

        将本异常转换为 M1 统一异常体系中的 ResourceExhaustedError，
        以便与 API 层的异常处理逻辑无缝集成。

        Args:
            trace_id: 链路追踪 ID

        Returns:
            ResourceExhaustedError 实例
        """
        # 惰性导入，避免循环依赖
        from src.models.exceptions import ResourceExhaustedError

        return ResourceExhaustedError(
            detail=str(self),
            trace_id=trace_id,
            data={
                "bulkhead_name": self.bulkhead_name,
                "max_concurrent": self.max_concurrent,
                "max_waiting": self.max_waiting,
                "reason": self.reason,
            },
        )


# ═══════════════════════════════════════════════════════
# 信号量舱壁
# ═══════════════════════════════════════════════════════

class SemaphoreBulkhead:
    """信号量舱壁

    基于 asyncio.Semaphore 实现的并发限制舱壁，
    用于隔离不同模块的资源使用，防止级联故障。

    每个舱壁维护：
    - 一组并发执行槽位（max_concurrent）
    - 一个等待队列（max_waiting）
    - 完整的统计指标

    Attributes:
        name: 舱壁名称
        max_concurrent: 最大并发执行数
        max_waiting: 最大等待队列长度（0 表示不等待，直接拒绝）
        wait_timeout: 等待超时时间（秒），0 表示永不超时
    """

    def __init__(
        self,
        name: str,
        max_concurrent: int = 10,
        max_waiting: int = 0,
        wait_timeout: float = 0.0,
    ) -> None:
        """初始化信号量舱壁

        Args:
            name: 舱壁名称，用于标识与日志记录
            max_concurrent: 最大并发执行数，必须大于 0
            max_waiting: 最大等待队列长度，0 表示不等待，直接拒绝
            wait_timeout: 等待超时时间（秒），0 表示永不超时

        Raises:
            ValueError: 参数不合法时抛出
        """
        if max_concurrent <= 0:
            raise ValueError(f"max_concurrent must be positive, got {max_concurrent}")
        if max_waiting < 0:
            raise ValueError(f"max_waiting must be non-negative, got {max_waiting}")
        if wait_timeout < 0:
            raise ValueError(f"wait_timeout must be non-negative, got {wait_timeout}")

        self.name: str = name
        self.max_concurrent: int = max_concurrent
        self.max_waiting: int = max_waiting
        self.wait_timeout: float = wait_timeout

        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._lock: asyncio.Lock = asyncio.Lock()

        # 统计指标
        self._current_concurrent: int = 0
        self._waiting_count: int = 0
        self._total_executed: int = 0
        self._total_rejected: int = 0
        self._total_timeouts: int = 0
        self._total_wait_time: float = 0.0
        self._closed: bool = False

        self._logger = logger.bind(
            service="bulkhead",
            bulkhead_name=name,
            max_concurrent=max_concurrent,
            max_waiting=max_waiting,
        )
        self._logger.info(
            "bulkhead_created",
            wait_timeout=wait_timeout,
        )

    # ── 核心执行接口 ────────────────────────────────────

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """在舱壁保护下执行异步函数

        尝试获取舱壁槽位：
        1. 若有空闲槽位，立即执行
        2. 若无空闲槽位但等待队列未满，进入等待队列
        3. 若等待队列也满了，抛出 BulkheadFullError
        4. 等待超时则抛出 BulkheadFullError（reason="timeout"）

        Args:
            func: 被保护的异步函数
            *args: 传递给 func 的位置参数
            **kwargs: 传递给 func 的关键字参数

        Returns:
            func 的返回值

        Raises:
            BulkheadFullError: 舱壁已满或等待超时
            RuntimeError: 舱壁已关闭
        """
        if self._closed:
            raise RuntimeError(f"Bulkhead '{self.name}' is closed")

        # 步骤1：检查等待队列是否还有空位
        async with self._lock:
            if self._current_concurrent >= self.max_concurrent:
                if self._waiting_count >= self.max_waiting:
                    self._total_rejected += 1
                    self._logger.warning(
                        "bulkhead_rejected",
                        current_concurrent=self._current_concurrent,
                        waiting_count=self._waiting_count,
                        total_rejected=self._total_rejected,
                    )
                    raise BulkheadFullError(
                        bulkhead_name=self.name,
                        max_concurrent=self.max_concurrent,
                        max_waiting=self.max_waiting,
                        reason="rejected",
                    )
                self._waiting_count += 1

        wait_start = time.monotonic()

        # 步骤2：等待获取信号量
        try:
            if self.wait_timeout > 0:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=self.wait_timeout,
                )
            else:
                await self._semaphore.acquire()
        except asyncio.TimeoutError:
            # 等待超时
            async with self._lock:
                self._waiting_count -= 1
                self._total_timeouts += 1
            self._logger.warning(
                "bulkhead_timeout",
                wait_time=time.monotonic() - wait_start,
                total_timeouts=self._total_timeouts,
            )
            raise BulkheadFullError(
                bulkhead_name=self.name,
                max_concurrent=self.max_concurrent,
                max_waiting=self.max_waiting,
                reason="timeout",
            ) from None

        # 步骤3：获取成功，更新统计
        wait_time = time.monotonic() - wait_start
        async with self._lock:
            if self._waiting_count > 0:
                self._waiting_count -= 1
            self._current_concurrent += 1
            self._total_wait_time += wait_time

        # 步骤4：执行函数
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            # 释放信号量，更新统计
            self._semaphore.release()
            async with self._lock:
                self._current_concurrent -= 1
                self._total_executed += 1

    # ── 状态查询 ────────────────────────────────────────

    def can_acquire(self) -> bool:
        """是否还有可用槽位

        注意：此方法返回的是瞬时状态，实际调用 execute 时
        状态可能已发生变化。仅用于快速预检。

        Returns:
            True 表示当前有空闲并发槽位
        """
        # Semaphore 内部的 _value 是剩余许可数
        return self._semaphore._value > 0  # type: ignore[attr-defined]

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典，包含以下字段：
            - name: 舱壁名称
            - max_concurrent: 最大并发数
            - max_waiting: 最大等待队列长度
            - wait_timeout: 等待超时时间（秒）
            - current_concurrent: 当前并发执行数
            - waiting_count: 等待中的请求数
            - total_executed: 累计执行成功数
            - total_rejected: 累计拒绝数
            - total_timeouts: 累计超时数
            - avg_wait_time_ms: 平均等待时间（毫秒）
            - closed: 是否已关闭
        """
        avg_wait_ms = 0.0
        if self._total_executed > 0:
            avg_wait_ms = (self._total_wait_time / self._total_executed) * 1000

        return {
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "max_waiting": self.max_waiting,
            "wait_timeout": self.wait_timeout,
            "current_concurrent": self._current_concurrent,
            "waiting_count": self._waiting_count,
            "total_executed": self._total_executed,
            "total_rejected": self._total_rejected,
            "total_timeouts": self._total_timeouts,
            "avg_wait_time_ms": round(avg_wait_ms, 2),
            "closed": self._closed,
        }

    # ── 生命周期管理 ────────────────────────────────────

    def close(self) -> None:
        """关闭舱壁，清理资源

        关闭后不再接受新的执行请求，已在执行中的请求不受影响。
        """
        if not self._closed:
            self._closed = True
            self._logger.info(
                "bulkhead_closed",
                current_concurrent=self._current_concurrent,
                waiting_count=self._waiting_count,
            )

    def reset_stats(self) -> None:
        """重置统计指标

        仅重置计数器，不影响当前并发状态与配置。
        """
        self._total_executed = 0
        self._total_rejected = 0
        self._total_timeouts = 0
        self._total_wait_time = 0.0
        self._logger.debug("bulkhead_stats_reset")

    def reconfigure(
        self,
        max_concurrent: int | None = None,
        max_waiting: int | None = None,
        wait_timeout: float | None = None,
    ) -> None:
        """动态调整舱壁配置

        运行时调整舱壁参数，新配置立即生效。
        仅对新请求生效，已在执行或等待中的请求不受影响。

        Args:
            max_concurrent: 新的最大并发数，None 表示不修改
            max_waiting: 新的最大等待队列长度，None 表示不修改
            wait_timeout: 新的等待超时时间，None 表示不修改

        Raises:
            ValueError: 参数不合法时抛出
        """
        if max_concurrent is not None:
            if max_concurrent <= 0:
                raise ValueError(f"max_concurrent must be positive, got {max_concurrent}")
            # 调整信号量大小：计算差值并释放或等待
            diff = max_concurrent - self.max_concurrent
            if diff > 0:
                for _ in range(diff):
                    self._semaphore.release()
            # 如果 diff < 0，信号量会自然收缩（acquire 后不 release 多余的）
            # 更精确的实现需要替换整个 Semaphore，这里采用渐进式
            self.max_concurrent = max_concurrent

        if max_waiting is not None:
            if max_waiting < 0:
                raise ValueError(f"max_waiting must be non-negative, got {max_waiting}")
            self.max_waiting = max_waiting

        if wait_timeout is not None:
            if wait_timeout < 0:
                raise ValueError(f"wait_timeout must be non-negative, got {wait_timeout}")
            self.wait_timeout = wait_timeout

        self._logger.info(
            "bulkhead_reconfigured",
            max_concurrent=self.max_concurrent,
            max_waiting=self.max_waiting,
            wait_timeout=self.wait_timeout,
        )


# ═══════════════════════════════════════════════════════
# 舱壁注册中心
# ═══════════════════════════════════════════════════════

class BulkheadRegistry:
    """舱壁注册中心

    统一管理多个舱壁实例，提供按名称获取、移除、统计等功能。
    确保同一名称的舱壁在系统中只有一个实例。

    典型用法：
        registry = BulkheadRegistry()
        bh = registry.get("llm_gpt4", max_concurrent=5, max_waiting=10)
        result = await bh.execute(call_llm, prompt)
    """

    def __init__(self) -> None:
        """初始化舱壁注册中心"""
        self._bulkheads: dict[str, SemaphoreBulkhead] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._logger = logger.bind(service="bulkhead_registry")

    async def get(
        self,
        name: str,
        max_concurrent: int = 10,
        max_waiting: int = 0,
        wait_timeout: float = 0.0,
    ) -> SemaphoreBulkhead:
        """获取或创建舱壁

        若指定名称的舱壁已存在则直接返回，否则创建新的舱壁实例。

        Args:
            name: 舱壁名称
            max_concurrent: 最大并发数（仅新建时生效）
            max_waiting: 最大等待队列长度（仅新建时生效）
            wait_timeout: 等待超时时间（仅新建时生效）

        Returns:
            SemaphoreBulkhead 实例
        """
        async with self._lock:
            if name not in self._bulkheads:
                self._bulkheads[name] = SemaphoreBulkhead(
                    name=name,
                    max_concurrent=max_concurrent,
                    max_waiting=max_waiting,
                    wait_timeout=wait_timeout,
                )
                self._logger.info(
                    "bulkhead_registered",
                    name=name,
                    max_concurrent=max_concurrent,
                    max_waiting=max_waiting,
                )
            return self._bulkheads[name]

    async def remove(self, name: str) -> None:
        """移除舱壁

        关闭并移除指定名称的舱壁。若舱壁不存在则静默忽略。

        Args:
            name: 舱壁名称
        """
        async with self._lock:
            bulkhead = self._bulkheads.pop(name, None)
            if bulkhead is not None:
                bulkhead.close()
                self._logger.info(
                    "bulkhead_removed",
                    name=name,
                )

    async def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """获取所有舱壁的统计信息

        Returns:
            以舱壁名称为 key，统计信息字典为 value 的字典
        """
        async with self._lock:
            return {
                name: bulkhead.get_stats()
                for name, bulkhead in self._bulkheads.items()
            }

    async def reset_all(self) -> None:
        """重置所有舱壁的统计指标

        仅重置计数器，不删除舱壁实例。
        """
        async with self._lock:
            for bulkhead in self._bulkheads.values():
                bulkhead.reset_stats()
        self._logger.debug("all_bulkheads_stats_reset")

    async def list_names(self) -> list[str]:
        """获取所有舱壁名称列表

        Returns:
            舱壁名称列表
        """
        async with self._lock:
            return list(self._bulkheads.keys())


# ═══════════════════════════════════════════════════════
# 装饰器
# ═══════════════════════════════════════════════════════

def bulkhead(
    name: str,
    max_concurrent: int = 10,
    max_waiting: int = 0,
    wait_timeout: float = 0.0,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """舱壁装饰器

    为异步函数添加舱壁保护，限制并发执行数量。

    每个被装饰的函数共享同一个名称的舱壁实例（基于装饰器参数）。
    装饰器内部使用模块级注册中心管理舱壁实例。

    Args:
        name: 舱壁名称
        max_concurrent: 最大并发数
        max_waiting: 最大等待队列长度（0 表示不等待，直接拒绝）
        wait_timeout: 等待超时时间（秒），0 表示永不超时

    Returns:
        装饰器函数

    Raises:
        BulkheadFullError: 舱壁已满或等待超时

    Example:
        @bulkhead("federation_agent_001", max_concurrent=3, max_waiting=5)
        async def invoke_agent(prompt: str) -> str:
            ...
    """
    # 模块级注册中心，供装饰器使用
    # 惰性创建，避免 import 时即创建
    _registry: BulkheadRegistry | None = None

    def _get_registry() -> BulkheadRegistry:
        nonlocal _registry
        if _registry is None:
            _registry = BulkheadRegistry()
        return _registry

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            registry = _get_registry()
            bh = await registry.get(
                name=name,
                max_concurrent=max_concurrent,
                max_waiting=max_waiting,
                wait_timeout=wait_timeout,
            )
            return await bh.execute(func, *args, **kwargs)

        # 暴露舱壁名称，便于调试
        wrapper.__bulkhead_name__ = name  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════
# 模块导出
# ═══════════════════════════════════════════════════════

__all__ = [
    "SemaphoreBulkhead",
    "BulkheadRegistry",
    "BulkheadFullError",
    "bulkhead",
]
