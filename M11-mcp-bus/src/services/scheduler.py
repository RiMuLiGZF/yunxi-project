"""M11 MCP Bus - 后台定时任务调度器.

管理所有后台周期性任务，包括：
- 工具列表自动刷新
- 离线服务器检测
- SSE 会话清理

所有任务在独立的后台线程中运行，不阻塞主服务。
"""

from __future__ import annotations

import asyncio
import logging
import time
from threading import Thread
from typing import Optional

from ..config import get_settings

logger = logging.getLogger(__name__)


class TaskScheduler:
    """后台定时任务调度器.

    在独立线程中运行 asyncio 事件循环，
    管理多个周期性任务的调度执行。
    """

    def __init__(self) -> None:
        """初始化调度器."""
        self._settings = get_settings()
        self._running = False
        self._thread: Optional[Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------

    def start(self) -> None:
        """启动后台调度线程.

        在独立线程中运行 asyncio 事件循环，
        启动所有注册的周期性任务。
        如果启动失败则降级为手动模式，不影响主服务。
        """
        if self._running:
            return

        try:
            self._running = True
            self._thread = Thread(
                target=self._run_loop,
                daemon=True,
                name="mcp-task-scheduler",
            )
            self._thread.start()
            print("[M11] 后台定时任务调度器已启动")
        except Exception as e:
            self._running = False
            print(f"[M11] 后台调度器启动失败，降级为手动模式: {e}")

    def stop(self) -> None:
        """停止调度器."""
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        print("[M11] 后台定时任务调度器已停止")

    def _run_loop(self) -> None:
        """后台线程入口：运行 asyncio 事件循环."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._main_loop())
        except Exception as e:
            print(f"[M11] 后台调度器线程异常: {e}")
        finally:
            if self._loop:
                self._loop.close()
                self._loop = None
            self._running = False

    async def _main_loop(self) -> None:
        """主调度循环：并发运行所有周期性任务."""
        tasks = [
            self._tool_refresh_loop(),
            self._offline_check_loop(),
            self._sse_cleanup_loop(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # --------------------------------------------------------
    # 任务1：工具列表自动刷新
    # --------------------------------------------------------

    async def _tool_refresh_loop(self) -> None:
        """工具列表自动刷新循环.

        定期遍历所有在线服务，调用其 tools/list 接口刷新本地工具缓存。
        刷新失败时记录日志，不影响服务运行。
        """
        interval = self._settings.tool_refresh_interval
        print(f"[M11] 工具自动刷新任务已启动，间隔: {interval}秒")

        while self._running:
            try:
                await self._refresh_all_tools()
            except Exception as e:
                print(f"[M11] 工具刷新任务异常: {e}")

            # 分段等待，以便快速响应停止信号
            wait_seconds = interval
            while self._running and wait_seconds > 0:
                await asyncio.sleep(min(1, wait_seconds))
                wait_seconds -= 1

    async def _refresh_all_tools(self) -> None:
        """执行一次全量工具刷新.

        遍历所有在线服务器，刷新其工具列表。
        单个服务器刷新失败不影响其他服务器。
        """
        from .registry import mcp_registry

        start_time = time.time()
        try:
            result = mcp_registry.refresh_all_tools(force=False)
            duration = int((time.time() - start_time) * 1000)

            refreshed = result.get("refreshed", 0)
            failed = result.get("failed", 0)
            total_tools = result.get("total_tools", 0)
            total_servers = result.get("total_servers", 0)

            if failed > 0:
                errors = result.get("errors", [])
                print(
                    f"[M11] 工具刷新完成: {refreshed}/{total_servers} 成功, "
                    f"{failed} 失败, 共 {total_tools} 个工具 "
                    f"({duration}ms)"
                )
                for err in errors:
                    print(f"[M11] 工具刷新失败 - {err}")
            else:
                print(
                    f"[M11] 工具刷新完成: {refreshed}/{total_servers} 服务器, "
                    f"共 {total_tools} 个工具 ({duration}ms)"
                )
        except Exception as e:
            print(f"[M11] 工具刷新异常: {e}")

    # --------------------------------------------------------
    # 任务2：离线服务器检测
    # --------------------------------------------------------

    async def _offline_check_loop(self) -> None:
        """离线服务器检测循环.

        定期检查心跳超时的服务器并标记为 offline。
        """
        interval = 30  # 每30秒检查一次
        print(f"[M11] 离线服务器检测任务已启动，间隔: {interval}秒")

        while self._running:
            try:
                from .registry import mcp_registry
                offline_count = mcp_registry.check_offline_servers()
                if offline_count > 0:
                    print(f"[M11] 检测到 {offline_count} 个服务器超时，已标记为离线")
            except Exception as e:
                print(f"[M11] 离线检测任务异常: {e}")

            # 分段等待
            wait_seconds = interval
            while self._running and wait_seconds > 0:
                await asyncio.sleep(min(1, wait_seconds))
                wait_seconds -= 1

    # --------------------------------------------------------
    # 任务3：SSE 会话清理
    # --------------------------------------------------------

    async def _sse_cleanup_loop(self) -> None:
        """SSE 会话清理循环.

        定期清理过期的 SSE 会话，释放资源。
        """
        interval = 60  # 每60秒清理一次
        max_idle = 300  # 最大空闲时间 300 秒

        while self._running:
            try:
                from .sse_manager import sse_manager
                cleaned = await sse_manager.cleanup_stale_sessions(max_idle=max_idle)
                if cleaned > 0:
                    print(f"[M11] 清理了 {cleaned} 个过期 SSE 会话")
            except Exception as e:
                # SSE 模块可能未初始化，忽略异常
                pass

            # 分段等待
            wait_seconds = interval
            while self._running and wait_seconds > 0:
                await asyncio.sleep(min(1, wait_seconds))
                wait_seconds -= 1

    # --------------------------------------------------------
    # 状态查询
    # --------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """是否正在运行."""
        return self._running

    def trigger_refresh(self) -> bool:
        """手动触发一次工具刷新.

        Returns:
            是否成功触发
        """
        if not self._loop or not self._running:
            return False

        asyncio.run_coroutine_threadsafe(self._refresh_all_tools(), self._loop)
        return True


# ============================================================
# 单例实例
# ============================================================

task_scheduler = TaskScheduler()
