"""云端连接健康探测组件.

为 OfflineShadowProxy 和 CloudGateway 提供统一的网络连通性检测。
支持多端点优先级探测、连续失败计数和状态变更回调。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from urllib.parse import urljoin

import aiohttp
import structlog

from edge_cloud_kernel.models.gateway import HealthCheckerStats

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_CHECK_INTERVAL: float = 30.0
DEFAULT_TIMEOUT: float = 5.0
DEFAULT_HEALTH_PATH: str = "health"
DEGRADED_FAILURE_THRESHOLD: int = 3  # 连续失败次数达到此阈值时判定为 UNREACHABLE

# ---------------------------------------------------------------------------
# 枚举 & 数据模型
# ---------------------------------------------------------------------------


class HealthStatus(str, Enum):
    """云端端点健康状态.

    Attributes:
        HEALTHY: 端点正常可达，响应 200.
        DEGRADED: 端点可达但返回非 200 状态码.
        UNREACHABLE: 端点不可达（超时或连接失败）.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


@dataclass
class EndpointEntry:
    """已注册端点条目.

    Attributes:
        url: 端点基础 URL.
        priority: 优先级，数值越小优先级越高.
        last_status: 最近一次探测结果.
        last_check_time: 最近一次探测时间戳.
    """

    url: str
    priority: int = 0
    last_status: HealthStatus | None = None
    last_check_time: float | None = None


# ---------------------------------------------------------------------------
# HealthChecker
# ---------------------------------------------------------------------------


class HealthChecker:
    """云端连接健康探测器.

    定期对已注册的云端端点发起轻量 GET 请求，判断网络连通性。
    多端点按优先级依次探测，聚合状态取最优结果。
    连续失败达到阈值后状态升级为 UNREACHABLE。

    Args:
        endpoints: 初始端点 URL 列表，可后续通过 register_endpoint 动态追加.
        check_interval: 探测间隔（秒），默认 30s.
        timeout: 单次请求超时（秒），默认 5s.
    """

    def __init__(
        self,
        endpoints: list[str] | None = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._check_interval = check_interval
        self._timeout = timeout

        # 端点注册表，按 priority 升序排列
        self._endpoints: list[EndpointEntry] = []
        if endpoints:
            for url in endpoints:
                self._endpoints.append(EndpointEntry(url=url))

        # 运行时状态
        self._current_status: HealthStatus = HealthStatus.UNREACHABLE
        self._consecutive_failures: int = 0
        self._total_checks: int = 0
        self._healthy_checks: int = 0
        self._last_check_time: float | None = None

        # 回调
        self._status_callback: Callable[[HealthStatus, HealthStatus], Any] | None = None

        # 后台任务
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False

        # aiohttp session（延迟创建）
        self._session: aiohttp.ClientSession | None = None

        logger.debug(
            "health_checker_init",
            endpoints=[e.url for e in self._endpoints],
            check_interval=check_interval,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # 端点管理
    # ------------------------------------------------------------------

    async def register_endpoint(self, url: str, priority: int = 0) -> None:
        """注册新的探测端点.

        Args:
            url: 端点基础 URL.
            priority: 优先级，数值越小越优先.
        """
        entry = EndpointEntry(url=url, priority=priority)
        self._endpoints.append(entry)
        # 按 priority 排序
        self._endpoints.sort(key=lambda e: e.priority)
        logger.info("endpoint_registered", url=url, priority=priority)

    # ------------------------------------------------------------------
    # 单次探测
    # ------------------------------------------------------------------

    async def _probe_single(self, session: aiohttp.ClientSession, url: str) -> HealthStatus:
        """对单个端点执行健康探测 GET 请求.

        Args:
            session: aiohttp 会话.
            url: 端点基础 URL.

        Returns:
            探测结果状态.
        """
        health_url = urljoin(url.rstrip("/") + "/", DEFAULT_HEALTH_PATH)
        try:
            async with session.get(
                health_url,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                if resp.status == 200:
                    return HealthStatus.HEALTHY
                # 4xx / 5xx 视为 DEGRADED
                return HealthStatus.DEGRADED
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return HealthStatus.UNREACHABLE

    async def check(self) -> HealthStatus:
        """对所有已注册端点执行一轮健康探测，返回聚合状态.

        按 priority 从高到低依次探测，遇到 HEALTHY 立即返回；
        否则取所有端点中最优状态。连续失败计数也会据此更新。

        Returns:
            聚合健康状态.
        """
        if not self._endpoints:
            logger.warning("health_check_no_endpoints")
            return HealthStatus.UNREACHABLE

        session = self._get_or_create_session()

        best_status = HealthStatus.UNREACHABLE
        any_degraded = False

        for entry in self._endpoints:
            status = await self._probe_single(session, entry.url)
            entry.last_status = status
            entry.last_check_time = time.monotonic()

            if status == HealthStatus.HEALTHY:
                best_status = HealthStatus.HEALTHY
                break  # 最优结果，不再继续
            if status == HealthStatus.DEGRADED:
                any_degraded = True

        if best_status != HealthStatus.HEALTHY and any_degraded:
            best_status = HealthStatus.DEGRADED

        # 更新统计
        self._total_checks += 1
        self._last_check_time = time.monotonic()

        old_status = self._current_status

        if best_status == HealthStatus.HEALTHY:
            self._healthy_checks += 1
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            # 连续失败达到阈值，升级为 UNREACHABLE
            if self._consecutive_failures >= DEGRADED_FAILURE_THRESHOLD:
                best_status = HealthStatus.UNREACHABLE

        self._current_status = best_status

        # 状态变更回调
        if old_status != best_status:
            logger.info(
                "health_status_changed",
                old_status=old_status.value,
                new_status=best_status.value,
                consecutive_failures=self._consecutive_failures,
            )
            if self._status_callback is not None:
                try:
                    self._status_callback(old_status, best_status)
                except Exception:
                    logger.exception("status_callback_error")

        return self._current_status

    # ------------------------------------------------------------------
    # 持续监控
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台健康探测循环.

        若已在运行则忽略。循环以 check_interval 为间隔持续执行 check()。
        """
        if self._running:
            logger.warning("health_checker_already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("health_checker_started", interval=self._check_interval)

    async def stop(self) -> None:
        """停止后台健康探测循环并释放资源."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        await self._close_session()
        logger.info("health_checker_stopped")

    async def _monitor_loop(self) -> None:
        """后台监控循环，周期性执行 check()."""
        while self._running:
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("health_check_loop_error")
            await asyncio.sleep(self._check_interval)

    # ------------------------------------------------------------------
    # Session 管理
    # ------------------------------------------------------------------

    def _get_or_create_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话（非 async 上下文中使用）."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _close_session(self) -> None:
        """关闭 aiohttp 会话."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # 回调 & 统计
    # ------------------------------------------------------------------

    def set_status_callback(self, callback: Callable[[HealthStatus, HealthStatus], Any]) -> None:
        """设置健康状态变更回调函数.

        Args:
            callback: 回调函数，签名 (old_status, new_status) -> None.
        """
        self._status_callback = callback
        logger.debug("status_callback_set")

    def get_stats(self) -> dict:
        """获取健康探测统计快照.

        Returns:
            包含 current_status、last_check_time、consecutive_failures、
            total_checks、uptime_ratio 等字段的字典.
        """
        uptime = (
            self._healthy_checks / self._total_checks
            if self._total_checks > 0
            else 0.0
        )
        stats = HealthCheckerStats(
            current_status=self._current_status,
            last_check_time=self._last_check_time,
            consecutive_failures=self._consecutive_failures,
            total_checks=self._total_checks,
            healthy_checks=self._healthy_checks,
            uptime_ratio=round(uptime, 4),
            endpoint_count=len(self._endpoints),
        )
        return stats.model_dump()
