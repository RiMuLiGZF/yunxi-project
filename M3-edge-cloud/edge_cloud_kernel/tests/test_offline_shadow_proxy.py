"""OfflineShadowProxy 单元测试.

测试离线影子代理在网络中断场景下的队列缓存、状态转换、批量回放等行为。
M3 v2.1.1 新增组件：OfflineShadowProxy。
"""

from __future__ import annotations

import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from edge_cloud_kernel.sync.offline_shadow_proxy import (
    ConnectionState,
    OfflineReplayResult,
    OfflineShadowProxy,
)
from edge_cloud_kernel.sync.sync_api import (
    SyncPushRequest,
    SyncPullResponse,
    SyncSessionRequest,
)


class TestOfflineShadowProxy:
    """OfflineShadowProxy 核心行为测试."""

    @staticmethod
    async def _create_proxy_with_db():
        """创建带临时数据库的代理实例，返回 (proxy, mock_api, stop_coro)."""
        mock_api = AsyncMock()
        tmpdir_obj = tempfile.TemporaryDirectory()
        tmpdir = tmpdir_obj.name
        db_path = os.path.join(tmpdir, "test_queue.db")
        proxy = OfflineShadowProxy(sync_api=mock_api, db_path=db_path)
        await proxy.start()
        return proxy, mock_api, tmpdir_obj

    @pytest.mark.asyncio
    async def test_online_push_passthrough(self):
        """Online状态：push直接透传到SyncAPI，不入队."""
        mock_api = AsyncMock()
        mock_api.push = AsyncMock(
            return_value=MagicMock(accepted=["i1"], rejected=[], conflicts=[])
        )
        proxy = OfflineShadowProxy(sync_api=mock_api)
        proxy._state = ConnectionState.ONLINE
        # 在线模式不需要 start/stop（不依赖数据库）
        request = SyncPushRequest(changes=[], version_vector={})
        await proxy.push("sess1", request)
        mock_api.push.assert_awaited_once_with("sess1", request)

    @pytest.mark.asyncio
    async def test_offline_push_queued(self):
        """Offline状态：push入队，不调用SyncAPI."""
        mock_api = AsyncMock()
        proxy = OfflineShadowProxy(sync_api=mock_api)
        proxy._state = ConnectionState.OFFLINE
        # 离线入队依赖数据库
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy._db_path = os.path.join(tmpdir, "test.db")
            await proxy._ensure_db()
            request = SyncPushRequest(
                changes=[], version_vector={}
            )
            resp = await proxy.push("sess1", request)
            mock_api.push.assert_not_called()
            assert resp.accepted == []  # 无changes
            assert await proxy.get_queue_size() == 1
            await proxy._db.close()

    @pytest.mark.asyncio
    async def test_offline_pull_returns_empty(self):
        """Offline状态：pull返回空变更（只读操作不入队）."""
        mock_api = AsyncMock()
        proxy = OfflineShadowProxy(sync_api=mock_api)
        proxy._state = ConnectionState.OFFLINE
        resp = await proxy.pull("sess1", {"conversation": 0})
        assert resp is not None
        assert isinstance(resp, SyncPullResponse)
        assert resp.changes == []
        assert resp.server_version == "offline"
        mock_api.pull.assert_not_called()

    @pytest.mark.asyncio
    async def test_offline_create_session_queued(self):
        """Offline状态：create_session入队，返回占位session_id."""
        mock_api = AsyncMock()
        proxy = OfflineShadowProxy(sync_api=mock_api)
        proxy._state = ConnectionState.OFFLINE
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy._db_path = os.path.join(tmpdir, "test.db")
            await proxy._ensure_db()
            request = SyncSessionRequest(device_id="dev_001", scopes=["conversation"])
            resp = await proxy.create_session(request)
            mock_api.create_session.assert_not_called()
            assert resp.session_id == "__offline_pending__"
            assert await proxy.get_queue_size() == 1
            await proxy._db.close()

    @pytest.mark.asyncio
    async def test_replay_push_batch(self):
        """重连后回放：连续push合并为批量推送."""
        proxy, mock_api, tmpdir_obj = await self._create_proxy_with_db()
        try:
            mock_api.push = AsyncMock(
                return_value=MagicMock(accepted=["i1"], rejected=[], conflicts=[])
            )
            proxy._state = ConnectionState.OFFLINE

            # 入队3条push
            for i in range(3):
                request = SyncPushRequest(
                    changes=[], version_vector={"scope": i + 1}
                )
                await proxy.push("sess1", request)

            assert await proxy.get_queue_size() == 3

            # 切换为在线并回放
            proxy._state = ConnectionState.ONLINE
            result = await proxy.replay()
            # batch合并后一次push调用即可处理全部
            assert result.success_count >= 1
            assert result.failed_count == 0
            # 队列应被清空
            assert await proxy.get_queue_size() == 0
        finally:
            await proxy.stop()
            tmpdir_obj.cleanup()

    @pytest.mark.asyncio
    async def test_replay_empty_queue(self):
        """回放空队列：返回零结果，不调用SyncAPI."""
        proxy, mock_api, tmpdir_obj = await self._create_proxy_with_db()
        try:
            result = await proxy.replay()
            assert result.success_count == 0
            assert result.failed_count == 0
            assert result.skipped_count == 0
        finally:
            await proxy.stop()
            tmpdir_obj.cleanup()

    @pytest.mark.asyncio
    async def test_purge_expired(self):
        """清理超过最大重试次数的操作."""
        proxy, mock_api, tmpdir_obj = await self._create_proxy_with_db()
        try:
            deleted = await proxy.purge(max_retries=0)
            # 空队列时删除0条
            assert deleted == 0
        finally:
            await proxy.stop()
            tmpdir_obj.cleanup()

    @pytest.mark.asyncio
    async def test_connection_state_transitions(self):
        """状态转换：ONLINE -> OFFLINE -> RECONNECTING -> ONLINE."""
        proxy = OfflineShadowProxy(sync_api=AsyncMock())
        assert proxy.state == ConnectionState.ONLINE
        proxy._state = ConnectionState.OFFLINE
        assert proxy.state == ConnectionState.OFFLINE
        assert proxy.is_online is False
        proxy._state = ConnectionState.RECONNECTING
        assert proxy.state == ConnectionState.RECONNECTING
        proxy._state = ConnectionState.ONLINE
        assert proxy.state == ConnectionState.ONLINE
        assert proxy.is_online is True

    @pytest.mark.asyncio
    async def test_set_connectivity_callback(self):
        """外部通知网络状态变更：设置回调并验证触发."""
        mock_api = AsyncMock()
        proxy = OfflineShadowProxy(sync_api=mock_api)
        callback = MagicMock()
        proxy.set_connectivity_callback(callback)
        # 手动触发状态转换
        proxy._state = ConnectionState.OFFLINE
        await proxy._transition_state(ConnectionState.RECONNECTING)
        # callback 被调用了（OFFLINE -> RECONNECTING）
        callback.assert_called_once_with(ConnectionState.RECONNECTING)

    @pytest.mark.asyncio
    async def test_offline_resolve_queued(self):
        """Offline状态：resolve入队，不调用SyncAPI."""
        from edge_cloud_kernel.sync.sync_api import SyncResolveRequest

        mock_api = AsyncMock()
        proxy = OfflineShadowProxy(sync_api=mock_api)
        proxy._state = ConnectionState.OFFLINE
        with tempfile.TemporaryDirectory() as tmpdir:
            proxy._db_path = os.path.join(tmpdir, "test.db")
            await proxy._ensure_db()
            request = SyncResolveRequest(
                conflict_ids=["c1", "c2"], resolution="local"
            )
            resp = await proxy.resolve("sess1", request)
            mock_api.resolve.assert_not_called()
            assert resp.resolved == ["c1", "c2"]
            assert await proxy.get_queue_size() == 1
            await proxy._db.close()
