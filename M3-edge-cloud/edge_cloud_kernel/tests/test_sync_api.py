"""SyncAPI 单元测试.

验证端云同步 API 的四个标准 HTTPS/JSON 端点：
- POST /api/v1/sync/session
- POST /api/v1/sync/{session_id}/push
- GET  /api/v1/sync/{session_id}/pull
- POST /api/v1/sync/{session_id}/resolve

设计依据：M3 v2.1.0 评审报告 REV-20250628-M3-001。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from edge_cloud_kernel.models.exceptions import SyncError
from edge_cloud_kernel.models.sync_models import SyncResult, SyncStatus
from edge_cloud_kernel.sync.sync_api import (
    SERVER_VERSION,
    SyncAPI,
    SyncDelta,
    SyncPushRequest,
    SyncResolveRequest,
    SyncSessionRequest,
)


class TestSyncAPI:
    """SyncAPI 核心测试集."""

    @pytest_asyncio.fixture
    async def api(self):
        """创建带有 Mock 依赖的 SyncAPI 实例."""
        controller = AsyncMock()
        bridge = AsyncMock()
        ldm = AsyncMock()
        api = SyncAPI(
            sync_controller=controller,
            tide_bridge=bridge,
            local_data_manager=ldm,
        )
        yield api
        await api.cleanup_expired_sessions()

    @pytest.mark.asyncio
    async def test_create_session(self, api):
        """创建会话应返回有效的 session_id 和服务器版本."""
        req = SyncSessionRequest(
            device_id="device_001", scopes=["config", "memory"]
        )
        resp = await api.create_session(req)
        assert resp.session_id is not None
        assert resp.server_version == SERVER_VERSION
        assert "device_001" in {
            rec.device_id for rec in api._sessions.values()
        }

    @pytest.mark.asyncio
    async def test_create_session_invalid_device_id(self, api):
        """非法 device_id 应抛出 SyncError."""
        req = SyncSessionRequest(device_id="", scopes=["config"])
        with pytest.raises(SyncError) as exc_info:
            await api.create_session(req)
        assert exc_info.value.error_code == "SYNC_INVALID_DEVICE_ID"

    @pytest.mark.asyncio
    async def test_push_changes(self, api):
        """推送变更应返回 accepted 列表."""
        api._sync_controller.add_sync_item = AsyncMock(return_value=None)
        api._sync_controller.sync_pending = AsyncMock(
            return_value=[
                SyncResult(item_id="i1", status=SyncStatus.SUCCESS)
            ]
        )

        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        delta = SyncDelta(
            item_id="i1",
            item_type="config",
            content_hash="abc123",
            version=1,
            timestamp=1234567890.0,
        )
        req = SyncPushRequest(
            changes=[delta], version_vector={"device_001": 1}
        )
        resp = await api.push(sess.session_id, req)
        assert isinstance(resp.accepted, list)
        assert "i1" in resp.accepted

    @pytest.mark.asyncio
    async def test_push_conflict(self, api):
        """推送产生冲突时应返回 conflicts 列表."""
        api._sync_controller.add_sync_item = AsyncMock(return_value=None)
        api._sync_controller.sync_pending = AsyncMock(
            return_value=[
                SyncResult(
                    item_id="i2",
                    status=SyncStatus.CONFLICT,
                    error_message="版本冲突",
                )
            ]
        )

        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        delta = SyncDelta(
            item_id="i2",
            item_type="memory",
            content_hash="def456",
            version=2,
            timestamp=1234567890.0,
        )
        req = SyncPushRequest(changes=[delta], version_vector={"d1": 2})
        resp = await api.push(sess.session_id, req)
        assert len(resp.conflicts) == 1
        assert resp.conflicts[0]["item_id"] == "i2"

    @pytest.mark.asyncio
    async def test_pull_changes(self, api):
        """拉取变更应返回 changes 列表和服务器版本."""
        api._local_data_manager.list_files = MagicMock(
            return_value=["f1.json", "f2.json"]
        )

        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        resp = await api.pull(
            sess.session_id,
            since_version={
                "conversation": 0,
                "memory": 0,
                "config": 0,
            },
        )
        assert isinstance(resp.changes, list)
        assert resp.server_version == SERVER_VERSION

    @pytest.mark.asyncio
    async def test_resolve_conflicts(self, api):
        """解决冲突应返回 resolved 列表."""
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        api._sessions[sess.session_id].conflict_registry["c1"] = {
            "item_id": "c1"
        }
        req = SyncResolveRequest(
            conflict_ids=["c1", "c2"], resolution="local"
        )
        resp = await api.resolve(sess.session_id, req)
        assert isinstance(resp.resolved, list)
        assert "c1" in resp.resolved

    @pytest.mark.asyncio
    async def test_resolve_invalid_strategy(self, api):
        """非法解决策略应抛出 SyncError."""
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        req = SyncResolveRequest(
            conflict_ids=["c1"], resolution="invalid"
        )
        with pytest.raises(SyncError) as exc_info:
            await api.resolve(sess.session_id, req)
        assert exc_info.value.error_code == "SYNC_INVALID_RESOLUTION"

    @pytest.mark.asyncio
    async def test_session_not_found(self, api):
        """无效 session_id 应抛出 SyncError."""
        with pytest.raises(SyncError) as exc_info:
            await api.push(
                "invalid_session",
                SyncPushRequest(changes=[], version_vector={}),
            )
        assert exc_info.value.error_code == "SYNC_SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, api):
        """清理过期会话应正确移除失效记录."""
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        assert len(api._sessions) == 1
        api._sessions[sess.session_id].last_active_at = 0.0
        removed = await api.cleanup_expired_sessions()
        assert removed >= 1
        assert len(api._sessions) == 0

    @pytest.mark.asyncio
    async def test_handle_create_session(self, api):
        """HTTP handler wrapper 应返回包含 session_id 的字典."""
        resp = await api.handle_create_session(
            {"device_id": "d1", "scopes": ["memory"]}
        )
        assert "session_id" in resp
        assert "server_version" in resp
        assert resp["server_version"] == SERVER_VERSION

    @pytest.mark.asyncio
    async def test_handle_push(self, api):
        """HTTP handler wrapper 应正确解析请求体并推送."""
        api._sync_controller.add_sync_item = AsyncMock(return_value=None)
        api._sync_controller.sync_pending = AsyncMock(
            return_value=[
                SyncResult(item_id="i1", status=SyncStatus.SUCCESS)
            ]
        )
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        body = {
            "changes": [
                {
                    "item_id": "i1",
                    "item_type": "config",
                    "content_hash": "h1",
                    "timestamp": 1.0,
                    "version": 1,
                }
            ],
            "version_vector": {"d1": 1},
        }
        resp = await api.handle_push(sess.session_id, body)
        assert "accepted" in resp
        assert isinstance(resp["accepted"], list)

    @pytest.mark.asyncio
    async def test_handle_pull(self, api):
        """HTTP handler wrapper 应正确解析查询参数并拉取."""
        api._local_data_manager.list_files = MagicMock(return_value=[])
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        resp = await api.handle_pull(
            sess.session_id, {"since_version": {"config": 0}}
        )
        assert "changes" in resp
        assert resp["server_version"] == SERVER_VERSION

    @pytest.mark.asyncio
    async def test_handle_resolve(self, api):
        """HTTP handler wrapper 应正确解析请求体并解决冲突."""
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        api._sessions[sess.session_id].conflict_registry["c1"] = {
            "item_id": "c1"
        }
        resp = await api.handle_resolve(
            sess.session_id,
            {"conflict_ids": ["c1"], "resolution": "local"},
        )
        assert "resolved" in resp
        assert "c1" in resp["resolved"]

    @pytest.mark.asyncio
    async def test_pull_without_local_data_manager(self, api):
        """local_data_manager 未设置时应抛出 SyncError."""
        api._local_data_manager = None
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        with pytest.raises(SyncError) as exc_info:
            await api.pull(sess.session_id, since_version={"config": 0})
        assert exc_info.value.error_code == "SYNC_MANAGER_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_push_without_sync_controller(self, api):
        """sync_controller 未设置时应抛出 SyncError."""
        api._sync_controller = None
        sess = await api.create_session(
            SyncSessionRequest(device_id="d1")
        )
        delta = SyncDelta(
            item_id="i1",
            item_type="config",
            content_hash="h1",
            version=1,
            timestamp=1.0,
        )
        req = SyncPushRequest(changes=[delta], version_vector={})
        with pytest.raises(SyncError) as exc_info:
            await api.push(sess.session_id, req)
        assert exc_info.value.error_code == "SYNC_CONTROLLER_UNAVAILABLE"
