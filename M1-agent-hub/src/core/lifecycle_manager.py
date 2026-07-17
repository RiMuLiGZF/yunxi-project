"""
云汐内核 V6 - 生命周期管理器

灵感来源：Kubernetes Pod Lifecycle / Spring Boot Lifecycle

统一管理内核的启动、运行、关闭全生命周期：
- 有序启动：按依赖顺序初始化各组件
- 信号处理：捕获 SIGTERM/SIGINT 实现优雅关闭
- 资源清理：关闭连接、释放锁、持久化数据
- 超时保护：每个阶段都有超时限制

[V7] 优雅关闭增强（资源泄漏防护）：
- 全局 30 秒关闭超时，超时后强制释放
- 关闭过程中拒绝新请求（shutting_down 状态）
- 关键数据强制持久化后再退出（pre_shutdown 阶段）
- 按依赖顺序倒序关闭（先业务组件，后基础设施）
- 关闭完成后发送信号与详细日志
"""

from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

LifecycleHook = Callable[[], Awaitable[None]]
"""生命周期钩子函数签名"""

# 全局关闭超时（秒），超过后强制执行退出
GLOBAL_SHUTDOWN_TIMEOUT: float = 30.0


class LifecycleState(str, Enum):
    """生命周期状态"""
    INITIAL = "initial"          # 初始状态，未启动
    STARTING = "starting"        # 正在启动
    RUNNING = "running"          # 正常运行
    SHUTTING_DOWN = "shutting_down"  # 正在关闭（拒绝新请求）
    SHUTDOWN = "shutdown"        # 已关闭
    FORCE_SHUTDOWN = "force_shutdown"  # 强制关闭（超时触发）


@dataclass
class ComponentSpec:
    """组件规格

    Attributes:
        name: 组件名称
        startup_hook: 启动钩子
        shutdown_hook: 关闭钩子
        health_check: 健康检查
        timeout_seconds: 单组件超时时间
        priority: 关闭优先级，数字越小越先关闭（业务组件优先关闭）
                  如：业务层=10，服务层=20，基础设施=30
        is_critical: 是否为关键组件，关键组件关闭前需确保数据持久化
        pre_shutdown_hook: 预关闭钩子（数据持久化、状态保存等），
                          在正式关闭前执行，确保数据安全
    """

    name: str = ""
    startup_hook: LifecycleHook | None = None
    shutdown_hook: LifecycleHook | None = None
    health_check: Callable[[], Awaitable[bool]] | None = None
    timeout_seconds: float = 10.0
    priority: int = 50
    """关闭优先级，数字越小越先关闭（先业务后基础设施）"""
    is_critical: bool = False
    """是否为关键数据组件，关闭前需确保数据落盘"""
    pre_shutdown_hook: LifecycleHook | None = None
    """预关闭钩子（数据持久化、状态保存等）"""


class LifecycleManager:
    """生命周期管理器

    管理所有组件的启动和关闭顺序。

    [V7] 增强特性：
    - 全局关闭超时（默认 30 秒），超时后强制关闭
    - 关闭过程中拒绝新请求（shutting_down 状态）
    - 关键数据强制持久化后再退出
    - 按优先级倒序关闭（先业务组件，后基础设施）
    - 关闭完成后发送详细信号与日志
    """

    def __init__(
        self,
        global_shutdown_timeout: float = GLOBAL_SHUTDOWN_TIMEOUT,
    ) -> None:
        self._components: list[ComponentSpec] = []
        self._state: LifecycleState = LifecycleState.INITIAL
        self._shutdown_event: asyncio.Event | None = None
        self._global_shutdown_timeout: float = global_shutdown_timeout
        """全局关闭超时时间（秒），超过后强制释放所有资源"""
        self._shutdown_start_time: float = 0.0
        """关闭开始时间戳"""
        self._logger = logger.bind(service="lifecycle_manager")

    # ── 组件注册 ────────────────────────────────────────

    def register(
        self,
        name: str,
        startup: LifecycleHook | None = None,
        shutdown: LifecycleHook | None = None,
        health_check: Callable[[], Awaitable[bool]] | None = None,
        timeout: float = 10.0,
        priority: int = 50,
        is_critical: bool = False,
        pre_shutdown: LifecycleHook | None = None,
    ) -> None:
        """注册组件

        Args:
            name: 组件名称
            startup: 启动钩子
            shutdown: 关闭钩子
            health_check: 健康检查
            timeout: 单组件超时时间（秒）
            priority: 关闭优先级，数字越小越先关闭
            is_critical: 是否为关键数据组件
            pre_shutdown: 预关闭钩子（数据持久化等）
        """
        if self._state in (LifecycleState.SHUTTING_DOWN, LifecycleState.SHUTDOWN,
                           LifecycleState.FORCE_SHUTDOWN):
            self._logger.warning(
                "component_register_rejected_shutdown",
                name=name,
                state=self._state.value,
            )
            return

        self._components.append(
            ComponentSpec(
                name=name,
                startup_hook=startup,
                shutdown_hook=shutdown,
                health_check=health_check,
                timeout_seconds=timeout,
                priority=priority,
                is_critical=is_critical,
                pre_shutdown_hook=pre_shutdown,
            )
        )
        self._logger.debug("component_registered", name=name, priority=priority)

    def get_state(self) -> LifecycleState:
        """获取当前生命周期状态"""
        return self._state

    def is_running(self) -> bool:
        """检查是否处于运行状态"""
        return self._state == LifecycleState.RUNNING

    def is_shutting_down(self) -> bool:
        """检查是否正在关闭（用于拒绝新请求）"""
        return self._state in (
            LifecycleState.SHUTTING_DOWN,
            LifecycleState.SHUTDOWN,
            LifecycleState.FORCE_SHUTDOWN,
        )

    # ── 启动 ────────────────────────────────────────────

    async def startup(self) -> None:
        """有序启动所有组件

        按注册顺序启动组件（先注册的基础设施先启动）。
        """
        if self._state != LifecycleState.INITIAL:
            self._logger.warning(
                "lifecycle_startup_skipped",
                current_state=self._state.value,
            )
            return

        self._state = LifecycleState.STARTING
        self._logger.info(
            "lifecycle_startup_begin",
            component_count=len(self._components),
        )
        self._shutdown_event = asyncio.Event()

        for spec in self._components:
            if spec.startup_hook is None:
                continue
            self._logger.info("component_starting", name=spec.name)
            start = time.time()
            try:
                await asyncio.wait_for(spec.startup_hook(), timeout=spec.timeout_seconds)
                elapsed = time.time() - start
                self._logger.info(
                    "component_started",
                    name=spec.name,
                    elapsed_ms=round(elapsed * 1000, 2),
                )
            except asyncio.TimeoutError:
                self._logger.error(
                    "component_startup_timeout",
                    name=spec.name,
                    timeout=spec.timeout_seconds,
                )
                self._state = LifecycleState.INITIAL
                raise RuntimeError(f"组件 '{spec.name}' 启动超时")
            except Exception as exc:
                self._logger.error(
                    "component_startup_failed",
                    name=spec.name,
                    error=str(exc),
                )
                self._state = LifecycleState.INITIAL
                raise

        self._state = LifecycleState.RUNNING
        self._logger.info("lifecycle_startup_complete")

    # ── 关闭 ────────────────────────────────────────────

    async def shutdown(self) -> None:
        """有序关闭所有组件（增强版）

        关闭流程：
        1. 标记为 SHUTTING_DOWN，拒绝新请求
        2. 执行关键组件的 pre_shutdown（数据持久化）
        3. 按优先级倒序关闭组件（先业务，后基础设施）
        4. 全局超时保护（默认 30 秒），超时后强制关闭
        5. 设置关闭完成事件
        6. 记录详细关闭统计
        """
        if self.is_shutting_down():
            self._logger.debug(
                "lifecycle_shutdown_already_in_progress",
                current_state=self._state.value,
            )
            return

        if self._state == LifecycleState.INITIAL:
            self._state = LifecycleState.SHUTDOWN
            self._logger.info("lifecycle_shutdown_skipped_not_started")
            return

        self._state = LifecycleState.SHUTTING_DOWN
        self._shutdown_start_time = time.time()
        self._logger.info(
            "lifecycle_shutdown_begin",
            component_count=len(self._components),
            global_timeout=self._global_shutdown_timeout,
        )

        try:
            await asyncio.wait_for(
                self._do_shutdown(),
                timeout=self._global_shutdown_timeout,
            )
            self._state = LifecycleState.SHUTDOWN
            elapsed = time.time() - self._shutdown_start_time
            self._logger.info(
                "lifecycle_shutdown_complete",
                elapsed_ms=round(elapsed * 1000, 2),
            )
        except asyncio.TimeoutError:
            self._state = LifecycleState.FORCE_SHUTDOWN
            elapsed = time.time() - self._shutdown_start_time
            self._logger.error(
                "lifecycle_shutdown_timeout_force",
                elapsed_ms=round(elapsed * 1000, 2),
                global_timeout=self._global_shutdown_timeout,
                message="全局关闭超时，已强制执行关闭，可能存在资源泄漏",
            )
            # 强制设置事件，避免等待者永久阻塞
        finally:
            if self._shutdown_event:
                self._shutdown_event.set()

    async def _do_shutdown(self) -> None:
        """执行实际的关闭流程（内部方法）。

        阶段一：预关闭（关键数据持久化）
        阶段二：按优先级倒序关闭组件
        """
        # 阶段一：执行所有关键组件的 pre_shutdown（数据持久化）
        self._logger.info("lifecycle_pre_shutdown_begin")
        critical_components = [s for s in self._components if s.is_critical]
        for spec in sorted(critical_components, key=lambda s: s.priority):
            if spec.pre_shutdown_hook is None:
                continue
            self._logger.info(
                "component_pre_shutdown",
                name=spec.name,
            )
            start = time.time()
            try:
                await asyncio.wait_for(
                    spec.pre_shutdown_hook(),
                    timeout=min(spec.timeout_seconds, 5.0),  # pre_shutdown 最多 5 秒
                )
                elapsed = time.time() - start
                self._logger.info(
                    "component_pre_shutdown_complete",
                    name=spec.name,
                    elapsed_ms=round(elapsed * 1000, 2),
                )
            except asyncio.TimeoutError:
                self._logger.warning(
                    "component_pre_shutdown_timeout",
                    name=spec.name,
                )
            except Exception as exc:
                self._logger.error(
                    "component_pre_shutdown_error",
                    name=spec.name,
                    error=str(exc),
                )

        # 阶段二：按优先级倒序关闭（先业务，后基础设施）
        # priority 数字越小越先关闭（如业务层=10，基础设施=30）
        sorted_components = sorted(self._components, key=lambda s: s.priority)

        self._logger.info(
            "lifecycle_shutdown_sorted",
            order=[s.name for s in sorted_components],
        )

        success_count = 0
        timeout_count = 0
        error_count = 0

        for spec in sorted_components:
            if spec.shutdown_hook is None:
                continue
            self._logger.info("component_shutting_down", name=spec.name)
            start = time.time()
            try:
                await asyncio.wait_for(
                    spec.shutdown_hook(),
                    timeout=spec.timeout_seconds,
                )
                elapsed = time.time() - start
                self._logger.info(
                    "component_shutdown",
                    name=spec.name,
                    elapsed_ms=round(elapsed * 1000, 2),
                )
                success_count += 1
            except asyncio.TimeoutError:
                self._logger.warning(
                    "component_shutdown_timeout",
                    name=spec.name,
                    timeout=spec.timeout_seconds,
                )
                timeout_count += 1
            except Exception as exc:
                self._logger.error(
                    "component_shutdown_error",
                    name=spec.name,
                    error=str(exc),
                )
                error_count += 1

        self._logger.info(
            "lifecycle_shutdown_summary",
            success=success_count,
            timeout=timeout_count,
            error=error_count,
            total=success_count + timeout_count + error_count,
        )

    # ── 信号处理 ────────────────────────────────────────

    def setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._on_signal(s)),
                )
            self._logger.info("signal_handlers_registered")
        except RuntimeError:
            # 不在事件循环中
            pass

    async def _on_signal(self, sig: signal.Signals) -> None:
        """信号处理回调"""
        self._logger.info(
            "signal_received",
            signal=sig.name,
            current_state=self._state.value,
        )
        await self.shutdown()

    # ── 等待 ────────────────────────────────────────────

    async def wait_for_shutdown(self) -> None:
        """阻塞直到关闭信号触发"""
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        await self._shutdown_event.wait()

    # ── 健康检查 ────────────────────────────────────────

    async def health_check_all(self) -> dict[str, bool]:
        """检查所有组件健康状态"""
        results: dict[str, bool] = {}
        for spec in self._components:
            if spec.health_check is None:
                results[spec.name] = True
                continue
            try:
                results[spec.name] = await asyncio.wait_for(
                    spec.health_check(),
                    timeout=5.0,
                )
            except Exception:
                results[spec.name] = False
        return results

    # ── 统计 ────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取生命周期管理器统计"""
        return {
            "state": self._state.value,
            "component_count": len(self._components),
            "global_shutdown_timeout": self._global_shutdown_timeout,
            "components": [
                {
                    "name": s.name,
                    "priority": s.priority,
                    "is_critical": s.is_critical,
                    "has_startup": s.startup_hook is not None,
                    "has_shutdown": s.shutdown_hook is not None,
                    "has_pre_shutdown": s.pre_shutdown_hook is not None,
                    "timeout_seconds": s.timeout_seconds,
                }
                for s in self._components
            ],
        }
