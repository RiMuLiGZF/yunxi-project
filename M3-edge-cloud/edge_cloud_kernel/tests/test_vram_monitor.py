"""VRAMMonitor 单元测试.

验证显存监控器的三水位线判定、GPU 不可用降级、
紧急释放机制及生命周期管理。

设计依据：M3 v2.1.0 评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from edge_cloud_kernel.models.vram_report import VRAMLevel
from edge_cloud_kernel.resource.vram_monitor import GPUStatus, VRAMMonitor


class TestVRAMMonitor:
    """显存监控器核心测试集."""

    @pytest.mark.asyncio
    async def test_critical_level(self):
        """使用率 > 85% 时应判定为 CRITICAL."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 12000.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.CRITICAL
            assert report.usage_ratio > 0.85

    @pytest.mark.asyncio
    async def test_warning_level(self):
        """使用率在 70%-85% 之间时应判定为 WARNING."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 10000.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.WARNING

    @pytest.mark.asyncio
    async def test_safe_level(self):
        """使用率 < 70% 时应判定为 SAFE."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 4000.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.SAFE
            assert report.usage_ratio < 0.70

    @pytest.mark.asyncio
    async def test_safe_threshold_boundary(self):
        """使用率恰好为 70% 时应判定为 SAFE（边界为开区间）."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(10000.0, 7000.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.SAFE

    @pytest.mark.asyncio
    async def test_critical_threshold_boundary(self):
        """使用率恰好为 85% 时应判定为 WARNING（边界为开区间）."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(10000.0, 8500.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.WARNING

    @pytest.mark.asyncio
    async def test_emergency_release_triggers_callback(self):
        """CRITICAL 状态下 emergency_release 应触发 auto_offload 回调."""
        monitor = VRAMMonitor()
        callback = AsyncMock()
        monitor.set_auto_offload_callback(callback)
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 13000.0)
        ):
            report = await monitor.sample()
            assert report.level == VRAMLevel.CRITICAL
            monitor._current_report = report
            released = await monitor.emergency_release()
            callback.assert_awaited_once()
            assert released >= 0.0

    @pytest.mark.asyncio
    async def test_emergency_release_not_critical(self):
        """非 CRITICAL 状态下 emergency_release 应直接返回 0.0."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 4000.0)
        ):
            report = await monitor.sample()
            monitor._current_report = report
            released = await monitor.emergency_release()
            assert released == 0.0

    def test_gpu_status_enum(self):
        """GPUStatus 枚举值应符合定义."""
        assert GPUStatus.AVAILABLE.value == "available"
        assert GPUStatus.UNAVAILABLE.value == "gpu_unavailable"

    @pytest.mark.asyncio
    async def test_monitor_start_stop(self):
        """start/stop 生命周期管理不应抛出异常."""
        monitor = VRAMMonitor()
        await monitor.start()
        assert monitor._running is True
        await monitor.stop()
        assert monitor._running is False
        await monitor.stop()

    @pytest.mark.asyncio
    async def test_gpu_unavailable_fallback(self):
        """nvidia-smi 不可用时状态应降级为 UNAVAILABLE."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(0.0, 0.0)
        ):
            report = await monitor.sample()
            assert monitor._gpu_available == GPUStatus.UNAVAILABLE
            assert report.total_mb == 0.0

    @pytest.mark.asyncio
    async def test_gpu_available_restored(self):
        """GPU 从不可用恢复为可用时应更新状态."""
        monitor = VRAMMonitor()
        monitor._gpu_available = GPUStatus.UNAVAILABLE
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 4000.0)
        ):
            await monitor.sample()
            assert monitor._gpu_available == GPUStatus.AVAILABLE

    @pytest.mark.asyncio
    async def test_check_vram_for_model_when_unavailable(self):
        """GPU 不可用时 check_vram_for_model 应始终返回 True."""
        monitor = VRAMMonitor()
        monitor._gpu_available = GPUStatus.UNAVAILABLE
        assert monitor.check_vram_for_model(10000.0) is True

    @pytest.mark.asyncio
    async def test_check_vram_for_model_insufficient(self):
        """显存不足时应返回 False."""
        monitor = VRAMMonitor()
        monitor._current_report = MagicMock()
        monitor._current_report.can_load_model = MagicMock(
            return_value=False
        )
        monitor._gpu_available = GPUStatus.AVAILABLE
        assert monitor.check_vram_for_model(10000.0) is False

    @pytest.mark.asyncio
    async def test_level_change_callback(self):
        """水位线变化时应触发已注册的回调."""
        monitor = VRAMMonitor()
        callback = MagicMock()
        monitor.on_level_change(callback)
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 13000.0)
        ):
            report = await monitor.sample()
            await monitor._notify_level_change(
                report.level, VRAMLevel.SAFE
            )
            callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_sample_returns_correct_report(self):
        """sample() 应返回包含正确显存使用率的报告."""
        monitor = VRAMMonitor()
        with patch.object(
            monitor, "_read_gpu_stats", return_value=(14000.0, 4000.0)
        ):
            report = await monitor.sample()
            assert report.total_mb == 14000.0
            assert report.used_mb == 4000.0
            assert report.free_mb == 10000.0
            assert report.level == VRAMLevel.SAFE

    def test_on_level_change_accepts_coro(self):
        """on_level_change 应能接受异步回调函数."""
        monitor = VRAMMonitor()

        async def async_callback(new, old):
            pass

        monitor.on_level_change(async_callback)
        assert len(monitor._callbacks) == 1

    def test_set_auto_offload_callback(self):
        """set_auto_offload_callback 应正确注册回调."""
        monitor = VRAMMonitor()

        async def cb(report):
            pass

        monitor.set_auto_offload_callback(cb)
        assert monitor._auto_offload_callback is cb
