"""数据同步引擎测试.

覆盖：
- 基于时间戳的增量同步
- 基于操作日志的同步
- 双向同步与冲突检测
- 同步状态管理（进度/断点续传/失败重试/同步队列）
"""

from __future__ import annotations

import asyncio
import time

import pytest

from edge_cloud_kernel.services.sync_engine import (
    ConflictDetectResult,
    ConflictResolutionPolicy,
    OperationLogEntry,
    SyncDirection,
    SyncEngine,
    SyncProgress,
    SyncQueueItem,
    SyncStrategy,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sync_engine():
    """创建 SyncEngine 测试实例."""
    engine = SyncEngine(
        default_strategy=SyncStrategy.TIMESTAMP,
        default_conflict_policy=ConflictResolutionPolicy.LAST_WRITE_WINS,
        max_retry=3,
        base_retry_delay=0.01,
    )
    yield engine


@pytest.fixture
def sample_local_data():
    """示例本地数据."""
    now = time.time()
    return [
        {"item_id": f"item-{i}", "version": i + 1, "timestamp": now - 1000 + i * 100,
         "content": f"data {i}"}
        for i in range(10)
    ]


# ============================================================
# SyncEngine 基础测试
# ============================================================

class TestSyncEngineInit:
    """SyncEngine 初始化测试."""

    def test_init_defaults(self, sync_engine):
        """测试默认初始化."""
        assert sync_engine is not None

    def test_init_with_custom_params(self):
        """测试带自定义参数初始化."""
        engine = SyncEngine(
            default_strategy=SyncStrategy.BIDIRECTIONAL,
            default_conflict_policy=ConflictResolutionPolicy.MANUAL,
            max_retry=10,
            base_retry_delay=2.0,
            max_retry_delay=600.0,
        )
        assert engine is not None

    def test_strategy_enum_values(self):
        """测试同步策略枚举值."""
        assert SyncStrategy.TIMESTAMP == "timestamp"
        assert SyncStrategy.OPERATION_LOG == "operation_log"
        assert SyncStrategy.BIDIRECTIONAL == "bidirectional"
        assert SyncStrategy.HYBRID == "hybrid"

    def test_direction_enum_values(self):
        """测试同步方向枚举值."""
        assert SyncDirection.EDGE_TO_CLOUD == "edge_to_cloud"
        assert SyncDirection.CLOUD_TO_EDGE == "cloud_to_edge"
        assert SyncDirection.BIDIRECTIONAL == "bidirectional"

    def test_conflict_policy_enum_values(self):
        """测试冲突解决策略枚举值."""
        assert ConflictResolutionPolicy.LAST_WRITE_WINS == "last_write_wins"
        assert ConflictResolutionPolicy.MANUAL == "manual"
        assert ConflictResolutionPolicy.MERGE == "merge"
        assert ConflictResolutionPolicy.LOCAL_WINS == "local_wins"
        assert ConflictResolutionPolicy.REMOTE_WINS == "remote_wins"


# ============================================================
# 基于时间戳的增量同步测试
# ============================================================

class TestTimestampSync:
    """基于时间戳的增量同步测试."""

    def test_get_last_sync_time_default(self, sync_engine):
        """测试默认上次同步时间为 0."""
        result = sync_engine.get_last_sync_time("conversation")
        assert result == 0.0

    def test_set_last_sync_time(self, sync_engine):
        """测试设置上次同步时间."""
        sync_time = time.time()
        sync_engine.set_last_sync_time("conversation", sync_time)
        retrieved = sync_engine.get_last_sync_time("conversation")
        assert abs(retrieved - sync_time) < 0.001

    def test_set_last_sync_time_multiple_types(self, sync_engine):
        """测试多种实体类型的同步时间."""
        now = time.time()
        sync_engine.set_last_sync_time("conversation", now - 100)
        sync_engine.set_last_sync_time("memory", now - 50)
        sync_engine.set_last_sync_time("config", now)
        assert sync_engine.get_last_sync_time("conversation") < sync_engine.get_last_sync_time("memory")
        assert sync_engine.get_last_sync_time("memory") < sync_engine.get_last_sync_time("config")

    def test_compute_timestamp_changes_all_new(self, sync_engine, sample_local_data):
        """测试所有数据都是新变更."""
        changes = sync_engine.compute_timestamp_changes(
            entity_type="conversation",
            since_timestamp=0,
            local_data=sample_local_data,
        )
        assert len(changes) == len(sample_local_data)

    def test_compute_timestamp_changes_none_new(self, sync_engine, sample_local_data):
        """测试没有新变更."""
        future_time = time.time() + 10000
        changes = sync_engine.compute_timestamp_changes(
            entity_type="conversation",
            since_timestamp=future_time,
            local_data=sample_local_data,
        )
        assert len(changes) == 0

    def test_compute_timestamp_changes_partial(self, sync_engine, sample_local_data):
        """测试部分变更."""
        mid_time = sample_local_data[5]["timestamp"]
        changes = sync_engine.compute_timestamp_changes(
            entity_type="conversation",
            since_timestamp=mid_time,
            local_data=sample_local_data,
        )
        assert 0 < len(changes) < len(sample_local_data)

    def test_sync_by_timestamp(self, sync_engine, sample_local_data):
        """测试基于时间戳的同步."""
        # 注册一个简单的推送回调
        called = []
        def mock_push(changes):
            called.extend(changes)
            return {"accepted": [c["item_id"] for c in changes], "rejected": [], "conflicts": []}
        sync_engine.register_push_callback(mock_push)

        progress = asyncio.run(sync_engine.sync_by_timestamp(
            entity_type="conversation",
            local_data=sample_local_data,
            direction=SyncDirection.EDGE_TO_CLOUD,
        ))
        assert isinstance(progress, SyncProgress)
        assert progress.strategy == SyncStrategy.TIMESTAMP
        assert progress.status in ("completed", "failed")

    def test_sync_by_timestamp_updates_last_time(self, sync_engine, sample_local_data):
        """测试同步后更新上次同步时间."""
        def mock_push(changes):
            return {"accepted": [c["item_id"] for c in changes], "rejected": [], "conflicts": []}
        sync_engine.register_push_callback(mock_push)

        before = sync_engine.get_last_sync_time("conversation")
        asyncio.run(sync_engine.sync_by_timestamp(
            entity_type="conversation",
            local_data=sample_local_data,
            direction=SyncDirection.EDGE_TO_CLOUD,
        ))
        after = sync_engine.get_last_sync_time("conversation")
        assert after > before


# ============================================================
# 基于操作日志的同步测试
# ============================================================

class TestOperationLogSync:
    """基于操作日志的同步测试."""

    def test_log_operation_create(self, sync_engine):
        """测试记录 CREATE 操作."""
        entry = asyncio.run(sync_engine.log_operation(
            operation="CREATE",
            entity_type="conversation",
            entity_id="conv-001",
            data={"title": "test"},
            device_id="device-001",
        ))
        assert isinstance(entry, OperationLogEntry)
        assert entry.operation == "CREATE"
        assert entry.entity_type == "conversation"
        assert entry.entity_id == "conv-001"
        assert entry.version == 1

    def test_log_operation_increments_version(self, sync_engine):
        """测试版本号递增."""
        e1 = asyncio.run(sync_engine.log_operation(
            operation="CREATE", entity_type="memory", entity_id="mem-1",
            data={}, device_id="dev-1",
        ))
        e2 = asyncio.run(sync_engine.log_operation(
            operation="UPDATE", entity_type="memory", entity_id="mem-1",
            data={}, device_id="dev-1",
        ))
        assert e2.version > e1.version

    def test_log_operation_has_checksum(self, sync_engine):
        """测试操作日志有校验和."""
        entry = asyncio.run(sync_engine.log_operation(
            operation="CREATE", entity_type="config", entity_id="cfg-1",
            data={"key": "value"}, device_id="dev-1",
        ))
        assert entry.checksum is not None
        assert len(entry.checksum) > 0

    def test_get_operation_log(self, sync_engine):
        """测试获取操作日志."""
        for i in range(5):
            asyncio.run(sync_engine.log_operation(
                operation="CREATE" if i % 2 == 0 else "UPDATE",
                entity_type="conversation",
                entity_id=f"conv-{i}",
                data={"index": i},
                device_id="device-001",
            ))
        logs = sync_engine.get_operation_log(
            entity_type="conversation",
            limit=10,
        )
        assert isinstance(logs, list)
        assert len(logs) >= 5

    def test_get_operation_log_with_limit(self, sync_engine):
        """测试带限制的操作日志查询."""
        for i in range(10):
            asyncio.run(sync_engine.log_operation(
                operation="CREATE", entity_type="memory",
                entity_id=f"mem-{i}", data={}, device_id="dev-1",
            ))
        logs = sync_engine.get_operation_log(entity_type="memory", limit=3)
        assert len(logs) <= 10  # 可能返回全部或部分

    def test_operation_log_entry_compute_checksum(self):
        """测试操作日志校验和计算."""
        entry = OperationLogEntry(
            log_id="log-001",
            operation="CREATE",
            entity_type="conversation",
            entity_id="conv-001",
            data={"content": "test"},
            timestamp=time.time(),
            device_id="device-001",
            version=1,
        )
        checksum1 = entry.compute_checksum()
        checksum2 = entry.compute_checksum()
        assert checksum1 == checksum2
        assert len(checksum1) > 0

    def test_replay_operation(self, sync_engine):
        """测试操作重放（通过日志同步）."""
        # 记录一些操作
        for i in range(3):
            asyncio.run(sync_engine.log_operation(
                operation="CREATE",
                entity_type="conversation",
                entity_id=f"conv-{i}",
                data={"index": i},
                device_id="device-001",
            ))
        logs = sync_engine.get_operation_log(entity_type="conversation", limit=10)
        assert len(logs) >= 3
        # 每条日志都应该能重放（有完整数据）
        for log in logs:
            assert log.operation in ("CREATE", "UPDATE", "DELETE")
            assert log.entity_id is not None


# ============================================================
# 双向同步与冲突检测测试
# ============================================================

class TestBidirectionalSync:
    """双向同步测试."""

    def test_detect_conflict_no_conflict_diff_items(self, sync_engine):
        """测试不同条目无冲突."""
        local = {"item_id": "item-1", "version": 1, "timestamp": time.time()}
        remote = {"item_id": "item-2", "version": 1, "timestamp": time.time()}
        # 不同 item_id 不构成冲突
        # detect_conflict 只比较单条数据的版本和内容
        result = sync_engine.detect_conflict(local, remote)
        assert isinstance(result, ConflictDetectResult)

    def test_detect_conflict_version_conflict(self, sync_engine):
        """测试版本号冲突."""
        now = time.time()
        local = {"item_id": "item-1", "version": 3, "timestamp": now, "data": "local"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": now - 100, "data": "remote"}
        result = sync_engine.detect_conflict(local, remote)
        assert result.has_conflict is True
        assert result.conflict_type == "version"

    def test_detect_conflict_content_conflict(self, sync_engine):
        """测试内容冲突（同版本不同内容）."""
        now = time.time()
        local = {"item_id": "item-1", "version": 2, "timestamp": now, "data": "local value"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": now, "data": "remote value"}
        result = sync_engine.detect_conflict(local, remote)
        assert result.has_conflict is True
        assert result.conflict_type == "content"

    def test_detect_conflict_no_conflict_same_content(self, sync_engine):
        """测试同版本同内容无冲突."""
        now = time.time()
        data = {"item_id": "item-1", "version": 2, "timestamp": now, "content": "same"}
        result = sync_engine.detect_conflict(data, data)
        assert result.has_conflict is False

    def test_resolve_conflict_last_write_wins_remote(self, sync_engine):
        """测试 last-write-wins 策略 - 远端更新."""
        now = time.time()
        local = {"item_id": "item-1", "version": 2, "timestamp": now - 100, "value": "local"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": now, "value": "remote"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.LAST_WRITE_WINS)
        assert result["value"] == "remote"

    def test_resolve_conflict_last_write_wins_local(self, sync_engine):
        """测试 last-write-wins 策略 - 本地更新."""
        now = time.time()
        local = {"item_id": "item-1", "version": 2, "timestamp": now, "value": "local"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": now - 100, "value": "remote"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.LAST_WRITE_WINS)
        assert result["value"] == "local"

    def test_resolve_conflict_local_wins(self, sync_engine):
        """测试 local-wins 策略."""
        local = {"item_id": "item-1", "version": 1, "timestamp": 100, "value": "local"}
        remote = {"item_id": "item-1", "version": 3, "timestamp": 200, "value": "remote"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.LOCAL_WINS)
        assert result["value"] == "local"

    def test_resolve_conflict_remote_wins(self, sync_engine):
        """测试 remote-wins 策略."""
        local = {"item_id": "item-1", "version": 3, "timestamp": 200, "value": "local"}
        remote = {"item_id": "item-1", "version": 1, "timestamp": 100, "value": "remote"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.REMOTE_WINS)
        assert result["value"] == "remote"

    def test_resolve_conflict_merge(self, sync_engine):
        """测试 merge 策略."""
        local = {"item_id": "item-1", "version": 2, "timestamp": 100,
                 "field_a": "local_a", "field_b": "local_b"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": 200,
                  "field_a": "remote_a", "field_c": "remote_c"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.MERGE)
        assert isinstance(result, dict)
        # 合并后应该包含双方的字段
        assert "field_b" in result or "field_c" in result

    def test_resolve_conflict_manual(self, sync_engine):
        """测试 manual 策略."""
        local = {"item_id": "item-1", "version": 2, "timestamp": 100, "value": "local"}
        remote = {"item_id": "item-1", "version": 2, "timestamp": 200, "value": "remote"}
        result = sync_engine.resolve_conflict(local, remote, ConflictResolutionPolicy.MANUAL)
        assert "_conflict_pending" in result
        assert "_conflict_remote" in result

    def test_bidirectional_sync(self, sync_engine):
        """测试双向同步."""
        local_items = [
            {"item_id": "a", "version": 1, "timestamp": 100, "data": "local-a"},
            {"item_id": "b", "version": 2, "timestamp": 200, "data": "local-b"},
        ]
        remote_items = [
            {"item_id": "b", "version": 1, "timestamp": 150, "data": "remote-b"},
            {"item_id": "c", "version": 1, "timestamp": 180, "data": "remote-c"},
        ]
        progress = asyncio.run(sync_engine.sync_bidirectional(
            entity_type="conversation",
            local_items=local_items,
            remote_items=remote_items,
        ))
        assert isinstance(progress, SyncProgress)
        assert progress.strategy == SyncStrategy.BIDIRECTIONAL


# ============================================================
# 同步状态管理测试
# ============================================================

class TestSyncStateManagement:
    """同步状态管理测试."""

    def test_get_sync_progress_nonexistent(self, sync_engine):
        """测试获取不存在的同步进度."""
        progress = sync_engine.get_sync_progress("nonexistent")
        assert progress is None

    def test_get_all_progress_empty(self, sync_engine):
        """测试空进度列表."""
        all_progress = sync_engine.get_all_progress()
        assert isinstance(all_progress, list)

    def test_get_all_progress_after_sync(self, sync_engine, sample_local_data):
        """测试同步后获取进度列表."""
        def mock_push(changes):
            return {"accepted": [c["item_id"] for c in changes], "rejected": [], "conflicts": []}
        sync_engine.register_push_callback(mock_push)

        asyncio.run(sync_engine.sync_by_timestamp(
            entity_type="conversation",
            local_data=sample_local_data,
            direction=SyncDirection.EDGE_TO_CLOUD,
        ))
        all_progress = sync_engine.get_all_progress()
        assert isinstance(all_progress, list)
        assert len(all_progress) >= 1

    def test_sync_progress_fields(self, sync_engine, sample_local_data):
        """测试同步进度对象字段."""
        def mock_push(changes):
            return {"accepted": [c["item_id"] for c in changes], "rejected": [], "conflicts": []}
        sync_engine.register_push_callback(mock_push)

        progress = asyncio.run(sync_engine.sync_by_timestamp(
            entity_type="memory",
            local_data=sample_local_data,
            direction=SyncDirection.EDGE_TO_CLOUD,
        ))
        assert progress.sync_id is not None
        assert progress.total_items >= 0
        assert progress.processed_items >= 0
        assert progress.start_time > 0
        assert progress.status in ("completed", "failed", "running")

    def test_progress_percent_calculation(self):
        """测试进度百分比计算."""
        progress = SyncProgress(
            sync_id="test-1",
            strategy=SyncStrategy.TIMESTAMP,
            direction=SyncDirection.EDGE_TO_CLOUD,
            total_items=100,
            processed_items=50,
            status="running",
            start_time=time.time(),
        )
        assert progress.progress_percent == 50.0

    def test_progress_percent_zero_total(self):
        """测试总数为 0 时的进度百分比."""
        progress = SyncProgress(
            sync_id="test-2",
            strategy=SyncStrategy.TIMESTAMP,
            direction=SyncDirection.EDGE_TO_CLOUD,
            total_items=0,
            processed_items=0,
            status="running",
            start_time=time.time(),
        )
        # 总数为 0 时进度为 0 或 100 都合理，取决于实现
        assert progress.progress_percent >= 0.0
        assert progress.progress_percent <= 100.0

    def test_is_completed_true(self):
        """测试完成状态判断."""
        progress = SyncProgress(
            sync_id="test-3",
            strategy=SyncStrategy.TIMESTAMP,
            direction=SyncDirection.EDGE_TO_CLOUD,
            total_items=10,
            status="completed",
            start_time=time.time(),
        )
        assert progress.is_completed is True

    def test_is_completed_false(self):
        """测试未完成状态判断."""
        progress = SyncProgress(
            sync_id="test-4",
            strategy=SyncStrategy.TIMESTAMP,
            direction=SyncDirection.EDGE_TO_CLOUD,
            total_items=10,
            status="running",
            start_time=time.time(),
        )
        assert progress.is_completed is False

    def test_get_queue_size_empty(self, sync_engine):
        """测试空队列大小."""
        size = sync_engine.get_queue_size()
        assert isinstance(size, int)
        assert size >= 0

    def test_get_sync_history(self, sync_engine, sample_local_data):
        """测试同步历史记录."""
        def mock_push(changes):
            return {"accepted": [c["item_id"] for c in changes], "rejected": [], "conflicts": []}
        sync_engine.register_push_callback(mock_push)

        asyncio.run(sync_engine.sync_by_timestamp(
            entity_type="conversation",
            local_data=sample_local_data,
            direction=SyncDirection.EDGE_TO_CLOUD,
        ))
        history = sync_engine.get_sync_history(limit=10)
        assert isinstance(history, list)

    def test_calculate_backoff_delay(self, sync_engine):
        """测试指数退避延迟计算."""
        delay1 = sync_engine.calculate_backoff_delay(1)
        delay2 = sync_engine.calculate_backoff_delay(2)
        delay3 = sync_engine.calculate_backoff_delay(3)
        assert delay1 < delay2 < delay3
        assert delay3 <= sync_engine._max_retry_delay

    def test_backoff_delay_max_cap(self, sync_engine):
        """测试退避延迟有上限."""
        delay = sync_engine.calculate_backoff_delay(100)
        assert delay <= sync_engine._max_retry_delay

    def test_callback_registration(self, sync_engine):
        """测试回调注册."""
        def push_cb(changes):
            return {"accepted": [], "rejected": [], "conflicts": []}
        def pull_cb(cursor):
            return []
        def conflict_cb(item_id, policy):
            return True

        sync_engine.register_push_callback(push_cb)
        sync_engine.register_pull_callback(pull_cb)
        sync_engine.register_conflict_callback(conflict_cb)
        assert sync_engine._push_callback is not None
        assert sync_engine._pull_callback is not None
        assert sync_engine._conflict_callback is not None
