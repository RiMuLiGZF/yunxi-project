"""ConflictResolver 增强版单元测试.

测试 VersionVector、CRDTMerge 和 resolve_with_version_vector 的行为。
M3 v2.1.1 增强组件：VersionVector + CRDTMerge。
"""

from __future__ import annotations

import pytest

from edge_cloud_kernel.local_data.conflict_resolver import (
    CRDTMerge,
    ConflictResolution,
    ConflictResolver,
    VersionVector,
)
from edge_cloud_kernel.models.sync_models import SyncItem


class TestVersionVector:
    """VersionVector 版本向量核心逻辑测试."""

    def test_increment(self):
        """递增：首次递增为1，再次递增为2."""
        vv = VersionVector()
        vv.increment("dev_001")
        assert vv.vectors["dev_001"] == 1
        vv.increment("dev_001")
        assert vv.vectors["dev_001"] == 2

    def test_merge(self):
        """合并：取每个设备ID的最大值."""
        a = VersionVector(vectors={"dev_001": 3, "dev_002": 1})
        b = VersionVector(vectors={"dev_001": 1, "dev_003": 5})
        merged = a.merge(b)
        assert merged.vectors["dev_001"] == 3  # max(3, 1)
        assert merged.vectors["dev_002"] == 1
        assert merged.vectors["dev_003"] == 5

    def test_dominates(self):
        """支配：所有维度>=且至少一个>."""
        a = VersionVector(vectors={"dev_001": 5, "dev_002": 3})
        b = VersionVector(vectors={"dev_001": 3, "dev_002": 1})
        assert a.dominates(b) is True
        assert b.dominates(a) is False

    def test_concurrent(self):
        """并发：互不支配."""
        a = VersionVector(vectors={"dev_001": 5, "dev_002": 1})
        b = VersionVector(vectors={"dev_001": 3, "dev_002": 5})
        assert a.dominates(b) is False
        assert b.dominates(a) is False
        assert a.is_concurrent(b) is True

    def test_empty_dominates(self):
        """空向量被非空向量支配."""
        a = VersionVector(vectors={"dev_001": 1})
        b = VersionVector()
        assert a.dominates(b) is True
        assert b.dominates(a) is False

    def test_equal_not_dominates(self):
        """完全相等的向量互不支配（需要至少一个>）."""
        a = VersionVector(vectors={"dev_001": 3})
        b = VersionVector(vectors={"dev_001": 3})
        assert a.dominates(b) is False
        assert b.dominates(a) is False
        assert a.is_concurrent(b) is True

    def test_summary_version(self):
        """摘要版本号：所有维度之和."""
        vv = VersionVector(vectors={"a": 3, "b": 2})
        assert vv.summary_version == 5
        # 空向量摘要为0
        empty = VersionVector()
        assert empty.summary_version == 0

    def test_merge_is_idempotent(self):
        """合并是幂等的：合并自身结果不变."""
        vv = VersionVector(vectors={"dev_001": 5, "dev_002": 3})
        merged = vv.merge(vv)
        assert merged.vectors == vv.vectors


class TestCRDTMerge:
    """CRDTMerge CRDT风格合并策略测试."""

    @pytest.mark.asyncio
    async def test_merge_dicts_local_only(self):
        """仅local有key：保留local."""
        result = await CRDTMerge.merge_dicts({"a": 1}, {}, 1.0, 0.5)
        assert result["a"] == 1
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_merge_dicts_remote_only(self):
        """仅remote有key：采纳remote."""
        result = await CRDTMerge.merge_dicts({}, {"b": 2}, 0.5, 1.0)
        assert result["b"] == 2
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_merge_dicts_both_present(self):
        """双方都有key：合并结果包含所有key."""
        result = await CRDTMerge.merge_dicts(
            {"a": 1, "b": 2}, {"a": 10, "c": 3}, 1.0, 2.0
        )
        assert "a" in result
        assert "b" in result
        assert "c" in result
        assert len(result) == 3

    def test_detect_tombstones(self):
        """墓碑标记：已删除的key不应被远端恢复."""
        remote = {"a": 1, "b": 2, "c": 3}
        result = CRDTMerge.detect_tombstones({}, remote, deleted_keys={"b"})
        assert "b" not in result
        assert "a" in result
        assert "c" in result

    def test_detect_tombstones_empty_deleted(self):
        """无墓碑标记时结果与remote一致."""
        remote = {"a": 1, "b": 2}
        result = CRDTMerge.detect_tombstones({}, remote, deleted_keys=set())
        assert result == remote


class TestConflictResolverVersionVector:
    """ConflictResolver.resolve_with_version_vector 集成测试."""

    @pytest.mark.asyncio
    async def test_local_dominates(self):
        """本地版本向量支配远端 -> LOCAL_WINS."""
        resolver = ConflictResolver()
        local_vv = VersionVector(vectors={"dev": 5})
        remote_vv = VersionVector(vectors={"dev": 3})
        local = SyncItem(item_id="i1", key="k1", value="local")
        remote = SyncItem(item_id="i1", key="k1", value="remote")
        result = await resolver.resolve_with_version_vector(
            local, remote, local_vv, remote_vv
        )
        assert result == ConflictResolution.LOCAL_WINS

    @pytest.mark.asyncio
    async def test_remote_dominates(self):
        """远端版本向量支配本地 -> REMOTE_WINS."""
        resolver = ConflictResolver()
        local_vv = VersionVector(vectors={"dev": 2})
        remote_vv = VersionVector(vectors={"dev": 5})
        local = SyncItem(item_id="i1", key="k1", value="local")
        remote = SyncItem(item_id="i1", key="k1", value="remote")
        result = await resolver.resolve_with_version_vector(
            local, remote, local_vv, remote_vv
        )
        assert result == ConflictResolution.REMOTE_WINS

    @pytest.mark.asyncio
    async def test_concurrent_dict_triggers_merge(self):
        """并发版本且双方value为dict -> MERGED（CRDT合并）."""
        resolver = ConflictResolver()
        local_vv = VersionVector(vectors={"dev": 5, "phone": 1})
        remote_vv = VersionVector(vectors={"dev": 3, "phone": 5})
        local = SyncItem(
            item_id="i1", key="k1",
            value={"field_a": "local_val", "field_b": "only_local"},
        )
        remote = SyncItem(
            item_id="i1", key="k1",
            value={"field_a": "remote_val", "field_c": "only_remote"},
        )
        result = await resolver.resolve_with_version_vector(
            local, remote, local_vv, remote_vv
        )
        assert result == ConflictResolution.MERGED

    @pytest.mark.asyncio
    async def test_concurrent_non_dict_falls_back(self):
        """并发版本且value非dict -> 降级到原有resolve方法."""
        resolver = ConflictResolver()
        local_vv = VersionVector(vectors={"dev": 5, "phone": 1})
        remote_vv = VersionVector(vectors={"dev": 3, "phone": 5})
        local = SyncItem(item_id="i1", key="k1", value="local")
        remote = SyncItem(item_id="i1", key="k1", value="remote")
        result = await resolver.resolve_with_version_vector(
            local, remote, local_vv, remote_vv
        )
        # 非dict并发 -> 降级到timestamp策略
        # 不应抛出异常
        assert result in (
            ConflictResolution.MERGED,
            ConflictResolution.CONCURRENT,
            ConflictResolution.LOCAL_WINS,
            ConflictResolution.REMOTE_WINS,
        )

    @pytest.mark.asyncio
    async def test_version_vector_resolution_recorded(self):
        """版本向量解决结果记录在历史中."""
        resolver = ConflictResolver()
        local_vv = VersionVector(vectors={"dev": 5})
        remote_vv = VersionVector(vectors={"dev": 3})
        local = SyncItem(item_id="i1", key="k1", value="local")
        remote = SyncItem(item_id="i1", key="k1", value="remote")
        await resolver.resolve_with_version_vector(
            local, remote, local_vv, remote_vv
        )
        history = resolver.get_history()
        assert len(history) == 1
        assert history[0]["strategy"] == "version_vector"
        assert history[0]["winner"] == "local"
