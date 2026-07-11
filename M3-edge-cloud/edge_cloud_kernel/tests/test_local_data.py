"""本地数据管理模块单元测试.

覆盖 LocalDataManager、ConflictResolver、SyncClient 三个核心类，
验证单例模式、目录初始化、冲突解决策略及同步客户端生命周期。

目标：提升 edge_cloud_kernel.local_data 包覆盖率。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from edge_cloud_kernel.local_data.conflict_resolver import (
    ConflictResolver,
    ConflictStrategy,
)
from edge_cloud_kernel.local_data.local_data_manager import (
    DEFAULT_DATA_DIR,
    LocalDataManager,
)
from edge_cloud_kernel.local_data.sync_client import SyncClient, SyncMode
from edge_cloud_kernel.models.sync_models import SyncItem, SyncResult, SyncStatus


class TestLocalDataManager:
    """LocalDataManager 核心测试集."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """每个测试用例前重置单例."""
        LocalDataManager.reset_instance()
        yield
        LocalDataManager.reset_instance()

    @pytest_asyncio.fixture
    async def ldm(self, tmp_path):
        """创建并初始化临时 LocalDataManager 实例."""
        mgr = LocalDataManager(data_dir=str(tmp_path))
        await mgr.initialize()
        yield mgr

    @pytest.mark.asyncio
    async def test_initialize_creates_directories(self, ldm):
        """初始化应自动创建所有必要子目录."""
        assert (Path(ldm.data_dir) / "config").exists()
        assert (Path(ldm.data_dir) / "cache").exists()
        assert (Path(ldm.data_dir) / "logs").exists()
        assert (Path(ldm.data_dir) / "audit").exists()
        assert (Path(ldm.data_dir) / "sessions").exists()
        assert (Path(ldm.data_dir) / "models").exists()

    @pytest.mark.asyncio
    async def test_properties_return_paths(self, ldm):
        """各属性应返回正确的子目录路径."""
        assert ldm.config_dir == Path(ldm.data_dir) / "config"
        assert ldm.cache_dir == Path(ldm.data_dir) / "cache"
        assert ldm.logs_dir == Path(ldm.data_dir) / "logs"
        assert ldm.audit_dir == Path(ldm.data_dir) / "audit"
        assert ldm.sessions_dir == Path(ldm.data_dir) / "sessions"
        assert ldm.models_dir == Path(ldm.data_dir) / "models"

    @pytest.mark.asyncio
    async def test_db_path(self, ldm):
        """db_path 应指向数据目录下的 yunxi.db."""
        assert ldm.db_path == str(Path(ldm.data_dir) / "yunxi.db")

    @pytest.mark.asyncio
    async def test_get_file_path(self, ldm):
        """get_file_path 应返回分类下的绝对路径."""
        path = ldm.get_file_path("config", "test.json")
        assert path == str(Path(ldm.data_dir) / "config" / "test.json")

    @pytest.mark.asyncio
    async def test_list_files(self, ldm):
        """list_files 应列出指定分类下的所有文件."""
        # 创建测试文件
        test_file = Path(ldm.data_dir) / "config" / "foo.json"
        test_file.write_text("{}")
        files = ldm.list_files("config")
        assert "foo.json" in files

    @pytest.mark.asyncio
    async def test_list_files_missing_category_returns_empty(self, ldm):
        """分类目录不存在时应返回空列表."""
        files = ldm.list_files("nonexistent_category")
        assert files == []

    @pytest.mark.asyncio
    async def test_singleton(self):
        """LocalDataManager 应为单例."""
        m1 = LocalDataManager()
        m2 = LocalDataManager()
        assert m1 is m2

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, ldm):
        """多次初始化应为幂等操作，不应抛出异常."""
        await ldm.initialize()
        await ldm.initialize()
        assert ldm._initialized is True

    @pytest.mark.asyncio
    async def test_cleanup_logs_no_error(self, ldm):
        """cleanup 应正常执行且不抛出异常."""
        await ldm.cleanup()


class TestConflictResolver:
    """ConflictResolver 核心测试集."""

    @pytest.fixture
    def resolver(self):
        """创建 ConflictResolver 实例."""
        return ConflictResolver()

    @pytest.mark.asyncio
    async def test_resolve_local_first(self, resolver):
        """LOCAL_FIRST 策略应始终保留本地版本."""
        local = SyncItem(
            item_id="i1",
            key="k1",
            version=1,
            timestamp=50.0,
        )
        remote = {"version": 2, "timestamp": 100.0}
        result = await resolver.resolve(local, remote, strategy=ConflictStrategy.LOCAL_FIRST)
        assert result.status == SyncStatus.SUCCESS
        assert result.resolved_version == 1

    @pytest.mark.asyncio
    async def test_resolve_remote_first(self, resolver):
        """REMOTE_FIRST 策略应始终保留远端版本."""
        local = SyncItem(
            item_id="i1",
            key="k1",
            version=1,
            timestamp=100.0,
        )
        remote = {"version": 2, "timestamp": 50.0}
        result = await resolver.resolve(local, remote, strategy=ConflictStrategy.REMOTE_FIRST)
        assert result.status == SyncStatus.SUCCESS
        assert result.resolved_version == 2

    @pytest.mark.asyncio
    async def test_resolve_timestamp_local_newer(self, resolver):
        """TIMESTAMP 策略：本地时间戳更新时应保留本地."""
        local = SyncItem(
            item_id="i1",
            key="k1",
            version=1,
            timestamp=100.0,
        )
        remote = {"version": 2, "timestamp": 50.0}
        result = await resolver.resolve(local, remote, strategy=ConflictStrategy.TIMESTAMP)
        assert result.status == SyncStatus.SUCCESS
        assert result.resolved_version == 1

    @pytest.mark.asyncio
    async def test_resolve_timestamp_remote_newer(self, resolver):
        """TIMESTAMP 策略：远端时间戳更新时应使用远端版本."""
        local = SyncItem(
            item_id="i1",
            key="k1",
            version=1,
            timestamp=50.0,
        )
        remote = {"version": 2, "timestamp": 100.0}
        result = await resolver.resolve(local, remote, strategy=ConflictStrategy.TIMESTAMP)
        assert result.status == SyncStatus.SUCCESS
        assert result.resolved_version == 2

    @pytest.mark.asyncio
    async def test_resolve_manual_queues_conflict(self, resolver):
        """MANUAL 策略应将冲突加入待处理队列."""
        local = SyncItem(
            item_id="i1",
            key="k1",
            version=1,
        )
        remote = {"version": 2, "timestamp": 100.0}
        result = await resolver.resolve(local, remote, strategy=ConflictStrategy.MANUAL)
        assert result.status == SyncStatus.CONFLICT
        assert resolver.get_manual_conflicts()

    @pytest.mark.asyncio
    async def test_resolve_manual_and_resolve_it(self, resolver):
        """手动冲突后应能人工解决."""
        local = SyncItem(item_id="i1", key="k1", version=1)
        remote = {"version": 2}
        await resolver.resolve(local, remote, strategy=ConflictStrategy.MANUAL)
        assert len(resolver.get_manual_conflicts()) == 1
        ok = resolver.resolve_manual("i1", keep="local")
        assert ok is True
        assert len(resolver.get_manual_conflicts()) == 0

    @pytest.mark.asyncio
    async def test_resolve_manual_not_found(self, resolver):
        """解决不存在的冲突应返回 False."""
        ok = resolver.resolve_manual("not_found", keep="local")
        assert ok is False

    @pytest.mark.asyncio
    async def test_default_strategy_is_timestamp(self, resolver):
        """默认策略应为 TIMESTAMP."""
        assert resolver._default_strategy == ConflictStrategy.TIMESTAMP

    def test_get_history(self, resolver):
        """get_history 应返回解决历史记录."""
        history = resolver.get_history()
        assert isinstance(history, list)


class TestSyncClient:
    """SyncClient 核心测试集."""

    @pytest.fixture
    def client(self):
        """创建 SyncClient 实例."""
        return SyncClient(cloud_endpoint="https://test.example.com", api_key="test_key")

    @pytest.mark.asyncio
    async def test_upload_success(self, client):
        """上传成功列表应返回 SUCCESS 结果."""
        items = [SyncItem(item_id="i1", key="k1", value="v1")]
        results = await client.upload(items)
        assert len(results) == 1
        assert results[0].status == SyncStatus.SUCCESS
        assert results[0].item_id == "i1"

    @pytest.mark.asyncio
    async def test_download_success(self, client):
        """下载成功应返回 SUCCESS 结果."""
        results = await client.download(["k1", "k2"])
        assert len(results) == 2
        for r in results:
            assert r.status == SyncStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_bidirectional_structure(self, client):
        """双向同步应返回包含 upload_results、download_results、conflicts 的字典."""
        items = [SyncItem(item_id="i1", key="k1", value="v1")]
        result = await client.bidirectional(items)
        assert "upload_results" in result
        assert "download_results" in result
        assert "conflicts" in result
        assert isinstance(result["conflicts"], list)

    @pytest.mark.asyncio
    async def test_bidirectional_detects_checksum_conflict(self, client):
        """双向同步中校验和不一致时应记录冲突."""
        # 构造一个 download 结果带有不同 remote_checksum 的场景
        item = SyncItem(item_id="i1", key="k1", value="v1", checksum="aaa")
        with patch.object(client, "download", return_value=[
            MagicMock(
                status=SyncStatus.SUCCESS,
                item_id="k1",
                remote_checksum="bbb",
            )
        ]):
            result = await client.bidirectional([item])
            assert len(result["conflicts"]) == 1
            assert result["conflicts"][0]["key"] == "k1"

    @pytest.mark.asyncio
    async def test_last_sync_time_updated_after_upload(self, client):
        """上传后 last_sync_time 应被更新."""
        assert client.last_sync_time == 0.0
        await client.upload([SyncItem(item_id="i1", key="k1")])
        assert client.last_sync_time > 0.0

    @pytest.mark.asyncio
    async def test_is_configured_true(self, client):
        """已配置端点和密钥时 is_configured 应为 True."""
        assert client.is_configured() is True

    @pytest.mark.asyncio
    async def test_is_configured_false(self):
        """未配置时 is_configured 应为 False."""
        c = SyncClient()
        assert c.is_configured() is False
