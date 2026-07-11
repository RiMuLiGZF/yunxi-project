"""潮汐记忆桥接单测.

验证 TideMemoryBridge 的 recall、archive、compress 接口及
降级策略（FULL / READ_ONLY / DISABLED）的逐级切换。

目标：提升 edge_cloud_kernel.sync.tide_memory_bridge 覆盖率。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from edge_cloud_kernel.sync.tide_memory_bridge import (
    DegradationLevel,
    TideMemoryBridge,
)


class TestTideMemoryBridge:
    """TideMemoryBridge 核心测试集."""

    @pytest.fixture
    def bridge(self):
        """创建 TideMemoryBridge 实例."""
        return TideMemoryBridge()

    @pytest.mark.asyncio
    async def test_recall_with_mock_router(self, bridge):
        """设置 Mock Router 后 recall 应返回记忆列表."""
        mock_router = AsyncMock()
        mock_router.call = AsyncMock(return_value=[{"content": "memory1"}])
        bridge.set_skill_router(mock_router)
        result = await bridge.recall("query", session_id="s1", top_k=3)
        assert len(result) == 1
        mock_router.call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recall_without_router_degrades(self, bridge):
        """未设置 Router 时应降级并返回空列表."""
        result = await bridge.recall("query", session_id="s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_timeout_degrades(self, bridge):
        """recall 超时应触发降级并返回空列表."""
        mock_router = AsyncMock()
        mock_router.call = AsyncMock(side_effect=asyncio.TimeoutError)
        bridge.set_skill_router(mock_router)
        result = await bridge.recall("query", session_id="s1")
        assert result == []
        assert bridge.degradation_level == DegradationLevel.READ_ONLY

    @pytest.mark.asyncio
    async def test_recall_exception_degrades(self, bridge):
        """recall 异常应触发降级并返回空列表."""
        mock_router = AsyncMock()
        mock_router.call = AsyncMock(side_effect=RuntimeError("boom"))
        bridge.set_skill_router(mock_router)
        result = await bridge.recall("query", session_id="s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_disabled_returns_empty(self, bridge):
        """DISABLED 状态下 recall 应直接返回空列表."""
        bridge._degradation_level = DegradationLevel.DISABLED
        result = await bridge.recall("query", session_id="s1")
        assert result == []

    @pytest.mark.asyncio
    async def test_archive_with_mock_router(self, bridge):
        """设置 Mock Router 后 archive 应返回 True."""
        mock_router = AsyncMock()
        mock_router.call = AsyncMock(return_value=None)
        bridge.set_skill_router(mock_router)
        result = await bridge.archive("test content", session_id="s1")
        assert result is True

    @pytest.mark.asyncio
    async def test_archive_without_router_caches_offline(self, bridge):
        """未设置 Router 时应降级到离线缓存."""
        result = await bridge.archive("test content", session_id="s1")
        assert result is True
        assert bridge.offline_cache_size == 1

    @pytest.mark.asyncio
    async def test_archive_read_only_blocks_write(self, bridge):
        """READ_ONLY 状态下 archive 应被阻塞并离线缓存."""
        mock_router = AsyncMock()
        bridge.set_skill_router(mock_router)
        bridge._degradation_level = DegradationLevel.READ_ONLY
        result = await bridge.archive("test content", session_id="s1")
        assert result is True
        mock_router.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_disabled_blocks_write(self, bridge):
        """DISABLED 状态下 archive 应被阻塞并离线缓存."""
        mock_router = AsyncMock()
        bridge.set_skill_router(mock_router)
        bridge._degradation_level = DegradationLevel.DISABLED
        result = await bridge.archive("test content", session_id="s1")
        assert result is True
        mock_router.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_compress_with_mock_router(self, bridge):
        """设置 Mock Router 后 compress 应成功调度后台任务."""
        mock_router = AsyncMock()
        bridge.set_skill_router(mock_router)
        result = await bridge.compress(session_id="s1", strategy="summary")
        assert result is True

    @pytest.mark.asyncio
    async def test_compress_without_router_returns_false(self, bridge):
        """未设置 Router 时 compress 应返回 False."""
        result = await bridge.compress(session_id="s1")
        assert result is False

    @pytest.mark.asyncio
    async def test_compress_read_only_returns_false(self, bridge):
        """READ_ONLY 状态下 compress 应返回 False."""
        mock_router = AsyncMock()
        bridge.set_skill_router(mock_router)
        bridge._degradation_level = DegradationLevel.READ_ONLY
        result = await bridge.compress(session_id="s1")
        assert result is False

    def test_degradation_level_enum(self, bridge):
        """DegradationLevel 枚举值应符合定义."""
        assert DegradationLevel.FULL.value == "full"
        assert DegradationLevel.READ_ONLY.value == "read_only"
        assert DegradationLevel.DISABLED.value == "disabled"

    def test_set_degradation_level(self, bridge):
        """直接设置降级级别后属性应同步更新."""
        bridge._degradation_level = DegradationLevel.READ_ONLY
        assert bridge.degradation_level == DegradationLevel.READ_ONLY

    def test_reset_degradation(self, bridge):
        """reset_degradation 应将级别恢复为 FULL."""
        bridge._degradation_level = DegradationLevel.DISABLED
        bridge.reset_degradation()
        assert bridge.degradation_level == DegradationLevel.FULL

    def test_offline_cache_size(self, bridge):
        """offline_cache_size 应统计所有离线缓存条目."""
        assert bridge.offline_cache_size == 0
        bridge._cache_offline("content1", session_id="s1")
        bridge._cache_offline("content2", session_id="s1")
        bridge._cache_offline("content3", session_id="s2")
        assert bridge.offline_cache_size == 3

    @pytest.mark.asyncio
    async def test_archive_exception_caches_offline(self, bridge):
        """archive 异常时应安全降级到离线缓存."""
        mock_router = AsyncMock()
        mock_router.call = AsyncMock(side_effect=RuntimeError("boom"))
        bridge.set_skill_router(mock_router)
        result = await bridge.archive("content", session_id="s1")
        assert result is True
        assert bridge.offline_cache_size == 1

    @pytest.mark.asyncio
    async def test_do_compress_executes_call(self, bridge):
        """_do_compress 应实际调用 SkillRouter."""
        mock_router = AsyncMock()
        bridge.set_skill_router(mock_router)
        await bridge._do_compress(session_id="s1", strategy="merge")
        mock_router.call.assert_awaited_once()
