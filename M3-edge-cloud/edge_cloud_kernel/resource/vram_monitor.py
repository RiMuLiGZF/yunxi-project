"""显存监控器.

三水位线显存监控（安全/警戒/危险）。
内置紧急释放机制和 GPU 不可用状态检测。
支持请求级显存池预分配管理（VRAMPoolManager）。
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import Callable, Awaitable
from enum import Enum
from threading import Lock
from typing import Any

import structlog

from edge_cloud_kernel.models.exceptions import VRAMOverflowError
from edge_cloud_kernel.models.vram_report import VRAMLevel, VRAMReport

logger = structlog.get_logger(__name__)

# 水位线阈值
SAFE_THRESHOLD: float = 0.70  # < 70% 安全
WARNING_THRESHOLD: float = 0.85  # 70%-85% 警戒
# > 85% 危险

# 监控间隔
DEFAULT_MONITOR_INTERVAL_S: float = 5.0

# 显存池预分配默认总容量（MB）—— 14GB RTX 4090
VRAM_POOL_TOTAL_MB: float = 14_000.0


class GPUStatus(str, Enum):
    """GPU 状态枚举.

    Attributes:
        AVAILABLE: GPU 正常可用.
        UNAVAILABLE: nvidia-smi 不可用，GPU 状态未知.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "gpu_unavailable"


class VRAMMonitor:
    """显存监控器.

    定期采样 GPU 显存使用情况，维护三水位线状态机，
    在显存不足时发出告警或触发模型卸载。

    当 nvidia-smi 不可用时，自动标记为 GPU_UNAVAILABLE 状态，
    此时 can_load_model 始终返回 True（无 GPU 限制，允许 CPU 推理）。

    Attributes:
        _interval_s: 监控采样间隔（秒）.
        _current_report: 最新的显存报告.
        _gpu_available: GPU 是否可用（nvidia-smi 是否可执行）.
        _running: 是否正在运行.
        _monitor_task: 监控任务句柄.
        _callbacks: 水位线变化回调列表.
    """

    def __init__(
        self,
        interval_s: float = DEFAULT_MONITOR_INTERVAL_S,
    ) -> None:
        """初始化 VRAMMonitor.

        Args:
            interval_s: 监控采样间隔（秒）.
        """
        self._interval_s = interval_s
        self._current_report: VRAMReport = VRAMReport()
        self._gpu_available: GPUStatus = GPUStatus.AVAILABLE
        self._auto_offload_callback: Callable[[VRAMReport], Awaitable[None]] | None = None
        self._offload_triggered: bool = False
        self._running = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._callbacks: list[Any] = []
        logger.info(
            "vram_monitor.init",
            interval_s=interval_s,
        )

    async def start(self) -> None:
        """启动显存监控."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("vram_monitor.started")

    async def stop(self) -> None:
        """停止显存监控."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("vram_monitor.stopped")

    async def _monitor_loop(self) -> None:
        """监控主循环."""
        while self._running:
            try:
                report = await self.sample()
                prev_level = self._current_report.level
                self._current_report = report

                # 水位线变化通知
                if report.level != prev_level:
                    logger.warning(
                        "vram_monitor.level_changed",
                        prev=prev_level.value,
                        current=report.level.value,
                        usage_ratio=report.usage_ratio,
                    )
                    await self._notify_level_change(report.level, prev_level)

                # CRITICAL 时触发 auto_offload
                if (
                    report.level == VRAMLevel.CRITICAL
                    and self._auto_offload_callback is not None
                    and not self._offload_triggered
                ):
                    self._offload_triggered = True
                    try:
                        await self._auto_offload_callback(report)
                        logger.warning(
                            "vram_monitor.auto_offload_triggered_in_loop",
                            usage_ratio=report.usage_ratio,
                        )
                    except Exception:
                        logger.exception("vram_monitor.auto_offload_error_in_loop")
                elif report.level != VRAMLevel.CRITICAL:
                    self._offload_triggered = False

            except Exception:
                logger.exception("vram_monitor.sample_error")

            await asyncio.sleep(self._interval_s)

    async def sample(self) -> VRAMReport:
        """采样当前显存使用情况.

        Returns:
            VRAMReport: 显存使用报告. 若 GPU 不可用则返回空报告.

        Raises:
            VRAMOverflowError: 显存严重不足（仅 GPU 可用时）.
        """
        total_mb, used_mb = await self._read_gpu_stats()

        # GPU 不可用：返回空报告并标记状态
        if total_mb == 0.0 and used_mb == 0.0:
            if self._gpu_available != GPUStatus.UNAVAILABLE:
                self._gpu_available = GPUStatus.UNAVAILABLE
                logger.warning(
                    "vram_monitor.gpu_unavailable",
                    message="nvidia-smi not found or failed, switching to GPU_UNAVAILABLE",
                )
                await self._notify_gpu_unavailable()
            return VRAMReport()

        # GPU 恢复可用
        if self._gpu_available == GPUStatus.UNAVAILABLE:
            self._gpu_available = GPUStatus.AVAILABLE
            logger.info("vram_monitor.gpu_available_restored")

        free_mb = total_mb - used_mb
        usage_ratio = used_mb / total_mb if total_mb > 0 else 0.0

        # 确定水位线级别
        if usage_ratio > WARNING_THRESHOLD:
            level = VRAMLevel.CRITICAL
        elif usage_ratio > SAFE_THRESHOLD:
            level = VRAMLevel.WARNING
        else:
            level = VRAMLevel.SAFE

        report = VRAMReport(
            total_mb=total_mb,
            used_mb=used_mb,
            free_mb=free_mb,
            usage_ratio=round(usage_ratio, 4),
            level=level,
        )

        if level == VRAMLevel.CRITICAL:
            logger.critical(
                "vram_monitor.critical",
                usage_ratio=usage_ratio,
                free_mb=free_mb,
            )

        return report

    async def _read_gpu_stats(self) -> tuple[float, float]:
        """读取 GPU 显存统计.

        通过 nvidia-smi 命令获取显存信息。
        当 nvidia-smi 不可用时标记 GPU_UNAVAILABLE 状态。

        Returns:
            (total_mb, used_mb) 显存总量和已使用量.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)

            if proc.returncode != 0 or not stdout:
                logger.warning("vram_monitor.nvidia_smi_failed", stderr=stderr.decode())
                self._gpu_available = GPUStatus.UNAVAILABLE
                return 0.0, 0.0

            parts = stdout.decode().strip().split(", ")
            total_mb = float(parts[0].strip())
            used_mb = float(parts[1].strip())
            self._gpu_available = GPUStatus.AVAILABLE
            return total_mb, used_mb

        except FileNotFoundError:
            logger.warning("vram_monitor.nvidia_smi_not_found")
            self._gpu_available = GPUStatus.UNAVAILABLE
            return 0.0, 0.0
        except asyncio.TimeoutError:
            logger.warning("vram_monitor.nvidia_smi_timeout")
            self._gpu_available = GPUStatus.UNAVAILABLE
            return 0.0, 0.0
        except ValueError:
            logger.warning("vram_monitor.nvidia_smi_parse_error")
            self._gpu_available = GPUStatus.UNAVAILABLE
            return 0.0, 0.0

    @property
    def current_report(self) -> VRAMReport:
        """获取最新的显存报告.

        Returns:
            最新的 VRAMReport.
        """
        return self._current_report

    @property
    def usage_ratio(self) -> float:
        """获取当前显存使用率.

        Returns:
            使用率 0.0-1.0.
        """
        return self._current_report.usage_ratio

    @property
    def level(self) -> VRAMLevel:
        """获取当前水位线级别.

        Returns:
            当前 VRAMLevel.
        """
        return self._current_report.level

    def on_level_change(self, callback: Any) -> None:
        """注册水位线变化回调.

        Args:
            callback: 回调函数 callback(new_level, old_level).
        """
        self._callbacks.append(callback)

    async def _notify_level_change(
        self, new_level: VRAMLevel, old_level: VRAMLevel
    ) -> None:
        """通知水位线变化.

        Args:
            new_level: 新水位线级别.
            old_level: 旧水位线级别.
        """
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(new_level, old_level)
                else:
                    callback(new_level, old_level)
            except Exception:
                logger.exception("vram_monitor.callback_error")

    async def _notify_gpu_unavailable(self) -> None:
        """通知上层 GPU 不可用.

        通过消息总线发布 system.vram.alert 消息。
        """
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("gpu_unavailable", "available")
                else:
                    callback("gpu_unavailable", "available")
            except Exception:
                logger.exception("vram_monitor.gpu_unavailable_notify_error")

    def check_vram_for_model(self, required_mb: float) -> bool:
        """检查是否有足够显存加载模型.

        当 GPU 不可用（nvidia-smi 缺失）时，始终返回 True，
        允许 CPU 推理不受 GPU 限制。

        Args:
            required_mb: 模型所需显存（MB）.

        Returns:
            是否有足够显存（或 GPU 不可用时为 True）.
        """
        if self._gpu_available == GPUStatus.UNAVAILABLE:
            return True  # 无 GPU 限制，允许 CPU 推理
        return self._current_report.can_load_model(required_mb)

    def set_auto_offload_callback(
        self,
        callback: Callable[[VRAMReport], Awaitable[None]],
    ) -> None:
        """设置 CRITICAL 水位线时的自动卸载回调.

        当显存水位线达到 CRITICAL 时，自动触发此回调以释放显存。

        Args:
            callback: 异步回调函数，接收 VRAMReport 参数.
        """
        self._auto_offload_callback = callback
        logger.info("vram_monitor.auto_offload_callback_set")

    async def emergency_release(self, target_mb: float = 0.0) -> float:
        """紧急释放显存.

        当显存达到 CRITICAL 水位时手动或自动触发显存释放。
        优先调用 auto_offload 回调卸载模型，其次尝试清空 KV-Cache。

        Args:
            target_mb: 目标释放量（MB），默认释放到安全水位以下.

        Returns:
            实际释放的显存量（MB），0 表示无法释放.
        """
        report = self._current_report
        if report.level != VRAMLevel.CRITICAL:
            logger.info(
                "vram_monitor.emergency_release_not_critical",
                current_level=report.level.value,
            )
            return 0.0

        released_mb: float = 0.0

        # Step 1: 触发 auto_offload 回调
        if self._auto_offload_callback is not None:
            try:
                await self._auto_offload_callback(report)
                logger.warning(
                    "vram_monitor.auto_offload_triggered",
                    used_mb=report.used_mb,
                    target_mb=target_mb,
                )
                # 假设卸载后释放了模型占用的显存
                released_mb = report.model_resident_mb + report.kv_cache_mb
            except Exception:
                logger.exception("vram_monitor.auto_offload_error")
        else:
            logger.warning(
                "vram_monitor.emergency_release_no_callback",
                used_mb=report.used_mb,
            )

        # Step 2: 重新采样验证
        if self._gpu_available == GPUStatus.AVAILABLE:
            new_report = await self.sample()
            self._current_report = new_report
            actual_released = report.used_mb - new_report.used_mb
            if actual_released > 0:
                released_mb = actual_released

        logger.warning(
            "vram_monitor.emergency_release_completed",
            released_mb=round(released_mb, 2),
            current_usage=self._current_report.usage_ratio,
        )
        return released_mb

    @property
    def gpu_status(self) -> str:
        """获取 GPU 可用性状态.

        Returns:
            "available" 或 "unavailable".
        """
        return self._gpu_available


class VRAMPoolManager:
    """请求级显存池预分配管理器.

    管理可用显存池，为每个推理请求分配显存预算。
    与 VRAMMonitor 三水位线监控集成：CRITICAL 时拒绝新分配。

    设计原则:
        - 采用「请求级排队 + 显存池预分配」方案，不依赖 CUDA MPS。
        - 每个推理请求在执行前需通过 allocate() 获取显存预算，
          执行完毕后通过 release() 归还显存。
        - CRITICAL 水位线时拒绝所有新分配，保障系统稳定性。

    Attributes:
        total_available_mb: 显存池总容量（MB）.
        _allocated: 当前已分配的显存记录 {request_id: allocated_mb}.
        _lock: 线程锁，保证并发安全.
        _monitor: 关联的 VRAMMonitor 实例，用于检查水位线.
    """

    def __init__(
        self,
        total_available_mb: float = VRAM_POOL_TOTAL_MB,
        monitor: VRAMMonitor | None = None,
    ) -> None:
        """初始化 VRAMPoolManager.

        Args:
            total_available_mb: 显存池总容量（MB），默认 14GB.
            monitor: 关联的 VRAMMonitor，用于三水位线联动.
        """
        self.total_available_mb = total_available_mb
        self._allocated: dict[str, float] = {}
        self._lock = Lock()
        self._monitor = monitor
        logger.info(
            "vram_pool_manager.init",
            total_mb=total_available_mb,
        )

    @property
    def used_mb(self) -> float:
        """当前已分配的显存总量（MB）.

        Returns:
            已分配显存量（MB）.
        """
        return sum(self._allocated.values())

    @property
    def free_mb(self) -> float:
        """当前可分配的显存量（MB）.

        Returns:
            剩余可分配显存量（MB）.
        """
        return self.total_available_mb - self.used_mb

    @property
    def allocation_count(self) -> int:
        """当前活跃分配数.

        Returns:
            活跃分配的请求数.
        """
        return len(self._allocated)

    def allocate(self, request_id: str, required_mb: float) -> bool:
        """为推理请求分配显存预算.

        检查流程：
        1. 检查水位线：若关联的 VRAMMonitor 处于 CRITICAL，拒绝分配。
        2. 检查剩余池容量：若不足，拒绝分配。
        3. 记录分配。

        Args:
            request_id: 请求唯一标识.
            required_mb: 所需显存（MB）.

        Returns:
            是否分配成功.
        """
        with self._lock:
            # 三水位线联动：CRITICAL 时拒绝新分配
            if self._monitor is not None:
                if self._monitor.level == VRAMLevel.CRITICAL:
                    logger.warning(
                        "vram_pool_manager.allocate_rejected_critical",
                        request_id=request_id,
                        required_mb=required_mb,
                        current_level="CRITICAL",
                    )
                    return False

            if request_id in self._allocated:
                logger.warning(
                    "vram_pool_manager.allocate_already_exists",
                    request_id=request_id,
                    existing_mb=self._allocated[request_id],
                )
                return True  # 已分配，视为成功

            if required_mb > self.free_mb:
                logger.warning(
                    "vram_pool_manager.allocate_insufficient",
                    request_id=request_id,
                    required_mb=required_mb,
                    free_mb=round(self.free_mb, 2),
                )
                return False

            self._allocated[request_id] = required_mb
            logger.info(
                "vram_pool_manager.allocated",
                request_id=request_id,
                required_mb=required_mb,
                used_mb=round(self.used_mb, 2),
                free_mb=round(self.free_mb, 2),
            )
            return True

    def release(self, request_id: str) -> float:
        """释放推理请求占用的显存预算.

        Args:
            request_id: 请求唯一标识.

        Returns:
            释放的显存量（MB），若请求不存在则返回 0.0.
        """
        with self._lock:
            released_mb = self._allocated.pop(request_id, 0.0)
            if released_mb > 0:
                logger.info(
                    "vram_pool_manager.released",
                    request_id=request_id,
                    released_mb=released_mb,
                    used_mb=round(self.used_mb, 2),
                    free_mb=round(self.free_mb, 2),
                )
            else:
                logger.debug(
                    "vram_pool_manager.release_not_found",
                    request_id=request_id,
                )
            return released_mb

    def get_allocation(self, request_id: str) -> float:
        """查询指定请求的已分配显存.

        Args:
            request_id: 请求唯一标识.

        Returns:
            该请求已分配的显存（MB），不存在则返回 0.0.
        """
        with self._lock:
            return self._allocated.get(request_id, 0.0)

    def force_release_all(self) -> float:
        """强制释放所有已分配显存（紧急场景使用）.

        Returns:
            释放的显存总量（MB）.
        """
        with self._lock:
            total = sum(self._allocated.values())
            count = len(self._allocated)
            self._allocated.clear()
            logger.warning(
                "vram_pool_manager.force_release_all",
                released_mb=round(total, 2),
                request_count=count,
            )
            return total
