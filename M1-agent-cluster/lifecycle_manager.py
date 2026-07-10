"""
云汐内核 V6 - 生命周期管理器

灵感来源：Kubernetes Pod Lifecycle / Spring Boot Lifecycle

统一管理内核的启动、运行、关闭全生命周期：
- 有序启动：按依赖顺序初始化各组件
- 信号处理：捕获 SIGTERM/SIGINT 实现优雅关闭
- 资源清理：关闭连接、释放锁、持久化数据
- 超时保护：每个阶段都有超时限制
"""

from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

LifecycleHook = Callable[[], Awaitable[None]]
"""生命周期钩子函数签名"""


@dataclass
class ComponentSpec:
    """组件规格"""

    name: str = ""
    startup_hook: LifecycleHook | None = None
    shutdown_hook: LifecycleHook | None = None
    health_check: Callable[[], Awaitable[bool]] | None = None
    timeout_seconds: float = 10.0


class LifecycleManager:
    """生命周期管理器

    管理所有组件的启动和关闭顺序。
    """

    def __init__(self) -> None:
        self._components: list[ComponentSpec] = []
        self._running: bool = False
        self._shutdown_event: asyncio.Event | None = None
        self._logger = logger.bind(service="lifecycle_manager")

    def register(
        self,
        name: str,
        startup: LifecycleHook | None = None,
        shutdown: LifecycleHook | None = None,
        health_check: Callable[[], Awaitable[bool]] | None = None,
        timeout: float = 10.0,
    ) -> None:
        """注册组件"""
        self._components.append(
            ComponentSpec(
                name=name,
                startup_hook=startup,
                shutdown_hook=shutdown,
                health_check=health_check,
                timeout_seconds=timeout,
            )
        )
        self._logger.debug("component_registered", name=name)

    # ── 启动 ────────────────────────────────────────────

    async def startup(self) -> None:
        """有序启动所有组件"""
        self._logger.info("lifecycle_startup_begin", component_count=len(self._components))
        self._shutdown_event = asyncio.Event()
        self._running = True

        for spec in self._components:
            if spec.startup_hook is None:
                continue
            self._logger.info("component_starting", name=spec.name)
            start = time.time()
            try:
                await asyncio.wait_for(spec.startup_hook(), timeout=spec.timeout_seconds)
                elapsed = time.time() - start
                self._logger.info("component_started", name=spec.name, elapsed_ms=round(elapsed * 1000, 2))
            except asyncio.TimeoutError:
                self._logger.error("component_startup_timeout", name=spec.name, timeout=spec.timeout_seconds)
                raise RuntimeError(f"组件 '{spec.name}' 启动超时")
            except Exception as exc:
                self._logger.error("component_startup_failed", name=spec.name, error=str(exc))
                raise

        self._logger.info("lifecycle_startup_complete")

    # ── 关闭 ────────────────────────────────────────────

    async def shutdown(self) -> None:
        """有序关闭所有组件（逆序）"""
        if not self._running:
            return

        self._logger.info("lifecycle_shutdown_begin", component_count=len(self._components))
        self._running = False

        # 逆序关闭
        for spec in reversed(self._components):
            if spec.shutdown_hook is None:
                continue
            self._logger.info("component_shutting_down", name=spec.name)
            start = time.time()
            try:
                await asyncio.wait_for(spec.shutdown_hook(), timeout=spec.timeout_seconds)
                elapsed = time.time() - start
                self._logger.info("component_shutdown", name=spec.name, elapsed_ms=round(elapsed * 1000, 2))
            except asyncio.TimeoutError:
                self._logger.warning("component_shutdown_timeout", name=spec.name)
            except Exception as exc:
                self._logger.error("component_shutdown_error", name=spec.name, error=str(exc))

        if self._shutdown_event:
            self._shutdown_event.set()
        self._logger.info("lifecycle_shutdown_complete")

    # ── 信号处理 ────────────────────────────────────────

    def setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self._on_signal(s)))
            self._logger.info("signal_handlers_registered")
        except RuntimeError:
            # 不在事件循环中
            pass

    async def _on_signal(self, sig: signal.Signals) -> None:
        """信号处理回调"""
        self._logger.info("signal_received", signal=sig.name)
        await self.shutdown()

    # ── 等待 ────────────────────────────────────────────

    async def wait_for_shutdown(self) -> None:
        """阻塞直到关闭信号触发"""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        await self._shutdown_event.wait()

    # ── 状态查询 ────────────────────────────────────────

    def is_running(self) -> bool:
        return self._running

    async def health_check_all(self) -> dict[str, bool]:
        """检查所有组件健康状态"""
        results = {}
        for spec in self._components:
            if spec.health_check is None:
                results[spec.name] = True
                continue
            try:
                results[spec.name] = await asyncio.wait_for(
                    spec.health_check(), timeout=5.0
                )
            except Exception:
                results[spec.name] = False
        return results
