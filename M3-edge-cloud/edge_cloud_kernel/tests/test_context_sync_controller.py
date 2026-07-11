"""上下文增量同步控制器单元测试.

验证 ConflictRegistry、ConflictRecord、ContextSyncController 的
校验和计算、冲突检测、版本解决及增量同步流程。

目标：提升 edge_cloud_kernel.sync.context_sync_controller 覆盖率。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from edge_cloud_kernel.models.sync_models import (
    SessionState,
    SyncItem,
    SyncResult,
    SyncStatus,
)
from edge_cloud_kernel.sync.context_sync_controller import (
    ConflictRecord,
    ConflictRegistry,
    ConflictResolutionStrategy,
    ContextSyncController,
)


class TestConflictRegistry:
    """ConflictRegistry 核心测试集."""

    @pytest.fixture
    def registry(self):
        """创建 ConflictRegistry 实例."""
        return ConflictRegistry(max_size=5)

    def test_register_and_get(self, registry):
        """注册冲突后应能通过 item_id 获取."""
        record = ConflictRecord(
            item_id="i1",
            key="k1",
            local_version=1,
            remote_version=2,
        )
        registry.register(record)
        fetched = registry.get("i1")
        assert fetched is not None
        assert fetched.key == "k1"

    def test_register_evicts_oldest_when_full(self, registry):
        """超出容量时应淘汰最旧的冲突记录."""
        for i in range(6):
            r = ConflictRecord(
                item_id=f"i{i}",
                key=f"k{i}",
                local_version=1,
                remote_version=2,
            )
            # 人为调整时间戳以确保淘汰顺序
            r.detected_at = float(i)
            registry.register(r)
        assert registry.count == 5
        assert registry.get("i0") is None
        assert registry.get("i5") is not None

    def test_list_all(self, registry):
        """list_all 应返回所有冲突记录."""
        registry.register(ConflictRecord("i1", "k1", 1, 2))
        registry.register(ConflictRecord("i2", "k2", 1, 2))
        assert len(registry.list_all()) == 2

    def test_clear_resolved(self, registry):
        """clear_resolved 应清除非 MANUAL 状态的记录."""
        registry.register(
            ConflictRecord("i1", "k1", 1, 2, resolution=ConflictResolutionStrategy.LOCAL_WINS)
        )
        registry.register(
            ConflictRecord("i2", "k2", 1, 2, resolution=ConflictResolutionStrategy.MANUAL)
        )
        cleared = registry.clear_resolved()
        assert cleared == 1
        assert registry.count == 1

    def test_conflict_record_to_dict(self):
        """ConflictRecord.to_dict 应返回结构化字典."""
        r = ConflictRecord(
            item_id="i1",
            key="k1",
            local_version=1,
            remote_version=2,
            resolution=ConflictResolutionStrategy.HIGHEST_VERSION,
        )
        d = r.to_dict()
        assert d["item_id"] == "i1"
        assert d["resolution"] == "highest_version"


class TestContextSyncController:
    """ContextSyncController 核心测试集."""

    @pytest.fixture
    def controller(self):
        """创建 ContextSyncController 实例."""
        return ContextSyncController()

    @pytest.mark.asyncio
    async def test_compute_checksum_sha256(self, controller):
        """_compute_checksum 应返回 64 位十六进制 SHA-256 值."""
        data = {"msg": "test data"}
        checksum = ContextSyncController._compute_checksum(data)
        assert len(checksum) == 64
        # 相同数据应产生相同校验和
        assert ContextSyncController._compute_checksum(data) == checksum

    @pytest.mark.asyncio
    async def test_compute_checksum_different_data(self, controller):
        """不同数据应产生不同校验和."""
        c1 = ContextSyncController._compute_checksum({"a": 1})
        c2 = ContextSyncController._compute_checksum({"a": 2})
        assert c1 != c2

    @pytest.mark.asyncio
    async def test_add_sync_item_updates_state(self, controller):
        """add_sync_item 应更新本地状态追踪."""
        item = SyncItem(item_id="i1", key="k1", value="v1", version=2)
        await controller.add_sync_item(item)
        assert controller.pending_count == 1
        assert controller._local_state["k1"]["version"] == 2

    @pytest.mark.asyncio
    async def test_sync_pending_empty(self, controller):
        """无待处理条目时 sync_pending 应返回空列表."""
        results = await controller.sync_pending()
        assert results == []

    @pytest.mark.asyncio
    async def test_sync_pending_without_client_skips(self, controller):
        """未配置 SyncClient 时同步应标记为 SKIPPED."""
        item = SyncItem(item_id="i1", key="k1", value="v1")
        await controller.add_sync_item(item)
        results = await controller.sync_pending()
        assert len(results) == 1
        assert results[0].status == SyncStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_sync_pending_with_mock_client(self, controller):
        """配置 Mock SyncClient 时应正确同步."""
        mock_client = AsyncMock()
        mock_client.upload = AsyncMock(
            return_value=[SyncResult(item_id="i1", status=SyncStatus.SUCCESS)]
        )
        controller._sync_client = mock_client
        item = SyncItem(item_id="i1", key="k1", value="v1", checksum="abc")
        await controller.add_sync_item(item)
        # mock fetch_remote_checksum to None to avoid extra path
        with patch.object(
            controller, "_fetch_remote_checksum", return_value=None
        ):
            results = await controller.sync_pending()
            assert len(results) == 1
            assert results[0].status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_resolve_conflict_version_local_wins(self, controller):
        """LOCAL_WINS 策略应返回本地版本号."""
        result = ContextSyncController._resolve_conflict_version(
            5, 3, ConflictResolutionStrategy.LOCAL_WINS
        )
        assert result == 5

    @pytest.mark.asyncio
    async def test_resolve_conflict_version_remote_wins(self, controller):
        """REMOTE_WINS 策略应返回远端版本号."""
        result = ContextSyncController._resolve_conflict_version(
            2, 8, ConflictResolutionStrategy.REMOTE_WINS
        )
        assert result == 8

    @pytest.mark.asyncio
    async def test_resolve_conflict_version_highest(self, controller):
        """HIGHEST_VERSION 策略应返回较大版本号."""
        result = ContextSyncController._resolve_conflict_version(
            3, 7, ConflictResolutionStrategy.HIGHEST_VERSION
        )
        assert result == 7

    @pytest.mark.asyncio
    async def test_resolve_conflict_version_manual(self, controller):
        """MANUAL 策略默认应保留本地版本."""
        result = ContextSyncController._resolve_conflict_version(
            4, 9, ConflictResolutionStrategy.MANUAL
        )
        assert result == 4

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, controller):
        """start/stop 应能正常管理后台同步任务."""
        await controller.start()
        assert controller._running is True
        await controller.stop()
        assert controller._running is False

    @pytest.mark.asyncio
    async def test_conflict_registry_property(self, controller):
        """conflict_registry 属性应返回 ConflictRegistry 实例."""
        registry = controller.conflict_registry
        assert isinstance(registry, ConflictRegistry)

    @pytest.mark.asyncio
    async def test_sync_session_without_client(self, controller):
        """未配置客户端时 sync_session 应返回 SKIPPED."""
        session = SessionState(session_id="s1")
        result = await controller.sync_session(session)
        assert result.status == SyncStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_fetch_remote_checksum_without_client(self, controller):
        """未配置客户端时 _fetch_remote_checksum 应返回 None."""
        result = await controller._fetch_remote_checksum("k1")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_remote_state_without_client(self, controller):
        """未配置客户端时 _fetch_remote_state 应返回 None."""
        result = await controller._fetch_remote_state("k1")
        assert result is None
