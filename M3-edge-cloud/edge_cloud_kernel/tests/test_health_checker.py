"""HealthChecker 单元测试.

测试云端连接健康探测器的端点探测、状态聚合、连续失败升级和回调通知。
M3 v2.1.1 新增组件：HealthChecker。
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from edge_cloud_kernel.gateway.health_checker import (
    HealthChecker,
    HealthStatus,
)


class TestHealthChecker:
    """HealthChecker 核心行为测试."""

    @pytest.fixture
    def checker(self):
        """创建带测试端点的 HealthChecker 实例."""
        return HealthChecker(
            endpoints=["http://test:8000/sync"],
            check_interval=999,
        )

    @pytest.mark.asyncio
    async def test_check_healthy(self):
        """200响应 -> HEALTHY."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=5.0,
        )
        mock_response = AsyncMock()
        mock_response.status = 200
        # _probe_single 内部使用 session.get 返回 async context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        checker._session = mock_session

        status = await checker.check()
        assert status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_check_unreachable_timeout(self):
        """超时 -> UNREACHABLE."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=0.01,
        )
        import aiohttp

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("connection refused")
        )
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        checker._session = mock_session

        status = await checker.check()
        assert status == HealthStatus.UNREACHABLE

    @pytest.mark.asyncio
    async def test_check_degraded_5xx(self):
        """500响应 -> DEGRADED（首次）或连续失败升级为UNREACHABLE."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=5.0,
        )
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        checker._session = mock_session

        status = await checker.check()
        # 首次5xx：DEGRADED，但连续失败计数+1
        # 连续失败>=3才升级为UNREACHABLE
        assert status in (HealthStatus.DEGRADED, HealthStatus.UNREACHABLE)

    @pytest.mark.asyncio
    async def test_consecutive_failures_upgrade(self):
        """连续多次失败后状态升级为UNREACHABLE."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=0.01,
        )
        import aiohttp

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("connection refused")
        )
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        checker._session = mock_session

        # 连续探测，直到状态升级为UNREACHABLE
        for _ in range(5):
            status = await checker.check()

        assert status == HealthStatus.UNREACHABLE
        assert checker._consecutive_failures >= 3

    @pytest.mark.asyncio
    async def test_register_endpoint(self):
        """动态注册端点：列表长度增加."""
        checker = HealthChecker()
        await checker.register_endpoint("http://new:8000/sync", priority=1)
        await checker.register_endpoint("http://backup:9000/sync", priority=0)
        assert len(checker._endpoints) == 2
        # priority=0 应排在 priority=1 前面
        assert checker._endpoints[0].priority == 0

    @pytest.mark.asyncio
    async def test_status_callback_on_change(self):
        """状态变更触发回调：记录old_status和new_status."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=5.0,
        )
        callback = MagicMock()
        checker.set_status_callback(callback)

        # 初始状态为UNREACHABLE（默认），先探测一次设为HEALTHY
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        mock_session.closed = False
        checker._session = mock_session

        await checker.check()
        # 从UNREACHABLE -> HEALTHY 触发回调
        callback.assert_called()
        # 回调参数为 (old_status, new_status)
        args = callback.call_args[0]
        assert args[0] == HealthStatus.UNREACHABLE
        assert args[1] == HealthStatus.HEALTHY

    def test_get_stats(self):
        """获取统计快照：包含必要字段."""
        checker = HealthChecker(endpoints=["http://test:8000/sync"])
        stats = checker.get_stats()
        assert "current_status" in stats
        assert "total_checks" in stats
        assert "consecutive_failures" in stats
        assert "endpoint_count" in stats
        assert stats["endpoint_count"] == 1

    @pytest.mark.asyncio
    async def test_no_endpoints_returns_unreachable(self):
        """无注册端点时返回UNREACHABLE."""
        checker = HealthChecker()
        status = await checker.check()
        assert status == HealthStatus.UNREACHABLE

    @pytest.mark.asyncio
    async def test_recovery_resets_failures(self):
        """恢复健康后连续失败计数归零."""
        checker = HealthChecker(
            endpoints=["http://test:8000/sync"],
            timeout=5.0,
        )

        # 先用失败探测
        import aiohttp

        fail_cm = AsyncMock()
        fail_cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientError("fail")
        )
        fail_cm.__aexit__ = AsyncMock(return_value=False)
        fail_session = MagicMock()
        fail_session.get = MagicMock(return_value=fail_cm)
        fail_session.closed = False
        checker._session = fail_session
        await checker.check()
        assert checker._consecutive_failures == 1

        # 再用成功探测恢复
        mock_response = AsyncMock()
        mock_response.status = 200
        ok_cm = AsyncMock()
        ok_cm.__aenter__ = AsyncMock(return_value=mock_response)
        ok_cm.__aexit__ = AsyncMock(return_value=False)
        ok_session = MagicMock()
        ok_session.get = MagicMock(return_value=ok_cm)
        ok_session.closed = False
        checker._session = ok_session
        await checker.check()
        assert checker._consecutive_failures == 0
