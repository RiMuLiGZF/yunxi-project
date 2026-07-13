"""API 请求模型校验单元测试.

验证 edge_cloud_kernel.models.api_requests 中所有请求模型的校验规则：
- 空字符串
- 超长字符串
- 越界数字
- 非法格式 ID
- 必填字段缺失
- 枚举值校验
- 列表长度限制
- 自定义格式校验

设计依据：M3 端云协同内核 API 输入全面校验任务。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from edge_cloud_kernel.models.api_requests import (
    ConfigBatchUpdateRequest,
    ConfigUpdateRequest,
    ConflictResolution,
    ConflictStrategy,
    DeviceQueryRequest,
    DeviceRegisterRequest,
    DeviceStatus,
    DeviceType,
    DeviceUpdateRequest,
    HealthCheckRequest,
    SyncPullRequest,
    SyncPushRequest,
    SyncResolveRequest,
    SyncScope,
    SyncSessionCreateRequest,
    SyncTriggerRequest,
    validate_conflict_id,
    validate_device_id_path,
    validate_session_id,
)


# ===========================================================================
# SyncSessionCreateRequest 测试
# ===========================================================================


class TestSyncSessionCreateRequest:
    """创建同步会话请求模型测试."""

    def test_valid_minimal(self):
        """最小合法请求应通过校验."""
        req = SyncSessionCreateRequest.model_validate({"device_id": "dev_001"})
        assert req.device_id == "dev_001"
        assert req.scopes == []

    def test_valid_with_scopes(self):
        """带 scopes 的合法请求应通过."""
        req = SyncSessionCreateRequest.model_validate({
            "device_id": "dev_001",
            "scopes": ["config", "memory"],
        })
        assert req.scopes == ["config", "memory"]

    def test_valid_max_length_device_id(self):
        """最大长度 device_id (63) 应通过."""
        device_id = "a" + "b" * 62
        req = SyncSessionCreateRequest.model_validate({"device_id": device_id})
        assert len(req.device_id) == 63

    def test_valid_scopes_deduplication(self):
        """重复 scope 应自动去重."""
        req = SyncSessionCreateRequest.model_validate({
            "device_id": "dev_001",
            "scopes": ["config", "memory", "config"],
        })
        assert req.scopes == ["config", "memory"]

    def test_missing_device_id(self):
        """缺少 device_id 应失败."""
        with pytest.raises(ValidationError) as exc_info:
            SyncSessionCreateRequest.model_validate({})
        errors = exc_info.value.errors()
        assert any(err["loc"] == ("device_id",) for err in errors)

    def test_empty_device_id(self):
        """空 device_id 应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({"device_id": ""})

    def test_too_short_device_id(self):
        """长度为 1 的 device_id 应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({"device_id": "a"})

    def test_too_long_device_id(self):
        """超长 device_id (65) 应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({"device_id": "a" * 65})

    def test_device_id_starts_with_hyphen(self):
        """以短横线开头的 device_id 应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({"device_id": "-invalid"})

    def test_device_id_special_chars(self):
        """含特殊字符 @ 的 device_id 应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({"device_id": "dev@001"})

    def test_empty_scope_element(self):
        """空 scope 元素应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({
                "device_id": "dev_001",
                "scopes": [""],
            })

    def test_scope_starts_with_digit(self):
        """scope 以数字开头应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({
                "device_id": "dev_001",
                "scopes": ["123invalid"],
            })

    def test_too_many_scopes(self):
        """超过最大 scopes 数量应失败."""
        with pytest.raises(ValidationError):
            SyncSessionCreateRequest.model_validate({
                "device_id": "dev_001",
                "scopes": [f"s{i}" for i in range(21)],
            })


# ===========================================================================
# SyncPushRequest 测试
# ===========================================================================


class TestSyncPushRequest:
    """推送同步数据请求模型测试."""

    VALID_CHANGE = {
        "item_id": "item_001",
        "item_type": "config",
        "content_hash": "abc123",
        "timestamp": 1234567890.0,
        "version": 1,
    }

    def test_valid_single_change(self):
        """单条变更应通过."""
        req = SyncPushRequest.model_validate({"changes": [self.VALID_CHANGE]})
        assert len(req.changes) == 1

    def test_valid_with_version_vector(self):
        """带版本向量应通过."""
        req = SyncPushRequest.model_validate({
            "changes": [self.VALID_CHANGE],
            "version_vector": {"config": 1},
        })
        assert req.version_vector == {"config": 1}

    def test_missing_changes(self):
        """缺少 changes 应失败."""
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({})

    def test_empty_changes(self):
        """空 changes 列表应失败."""
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({"changes": []})

    def test_missing_required_fields(self):
        """缺少必要字段应失败."""
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({"changes": [{"item_id": "i1"}]})

    def test_version_zero(self):
        """version 为 0 应失败."""
        bad = dict(self.VALID_CHANGE, version=0)
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({"changes": [bad]})

    def test_empty_item_id(self):
        """空 item_id 应失败."""
        bad = dict(self.VALID_CHANGE, item_id="")
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({"changes": [bad]})

    def test_version_vector_empty_key(self):
        """版本向量空键应失败."""
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({
                "changes": [self.VALID_CHANGE],
                "version_vector": {"": 1},
            })

    def test_version_vector_negative(self):
        """版本向量负值应失败."""
        with pytest.raises(ValidationError):
            SyncPushRequest.model_validate({
                "changes": [self.VALID_CHANGE],
                "version_vector": {"config": -1},
            })


# ===========================================================================
# SyncPullRequest 测试
# ===========================================================================


class TestSyncPullRequest:
    """拉取同步数据请求模型测试."""

    def test_valid_default(self):
        """默认空版本向量应通过."""
        req = SyncPullRequest.model_validate({})
        assert req.since_version == {}

    def test_valid_with_versions(self):
        """带版本向量应通过."""
        req = SyncPullRequest.model_validate({
            "since_version": {"config": 1, "memory": 5},
        })
        assert req.since_version == {"config": 1, "memory": 5}

    def test_empty_scope_key(self):
        """空 scope 键应失败."""
        with pytest.raises(ValidationError):
            SyncPullRequest.model_validate({"since_version": {"": 1}})

    def test_negative_version(self):
        """负数版本应失败."""
        with pytest.raises(ValidationError):
            SyncPullRequest.model_validate({"since_version": {"config": -1}})


# ===========================================================================
# SyncResolveRequest 测试
# ===========================================================================


class TestSyncResolveRequest:
    """解决冲突请求模型测试."""

    def test_valid_local(self):
        """local 策略应通过."""
        req = SyncResolveRequest.model_validate({"resolution": "local"})
        assert req.resolution == "local"

    def test_valid_remote(self):
        """remote 策略应通过."""
        req = SyncResolveRequest.model_validate({"resolution": "remote"})
        assert req.resolution == "remote"

    def test_valid_merge(self):
        """merge 策略应通过."""
        req = SyncResolveRequest.model_validate({"resolution": "merge"})
        assert req.resolution == "merge"

    def test_valid_with_conflict_ids(self):
        """带 conflict_ids 应通过."""
        req = SyncResolveRequest.model_validate({
            "resolution": "local",
            "conflict_ids": ["c1", "c2"],
        })
        assert req.conflict_ids == ["c1", "c2"]

    def test_valid_conflict_ids_dedup(self):
        """重复 conflict_id 应去重."""
        req = SyncResolveRequest.model_validate({
            "resolution": "local",
            "conflict_ids": ["c1", "c2", "c1"],
        })
        assert req.conflict_ids == ["c1", "c2"]

    def test_missing_resolution(self):
        """缺少 resolution 应失败."""
        with pytest.raises(ValidationError):
            SyncResolveRequest.model_validate({})

    def test_empty_resolution(self):
        """空 resolution 应失败."""
        with pytest.raises(ValidationError):
            SyncResolveRequest.model_validate({"resolution": ""})

    def test_invalid_resolution(self):
        """非法 resolution 应失败."""
        with pytest.raises(ValidationError):
            SyncResolveRequest.model_validate({"resolution": "invalid"})

    def test_invalid_conflict_id_format(self):
        """非法 conflict_id 格式应失败."""
        with pytest.raises(ValidationError):
            SyncResolveRequest.model_validate({
                "resolution": "local",
                "conflict_ids": ["-bad"],
            })


# ===========================================================================
# SyncTriggerRequest 测试
# ===========================================================================


class TestSyncTriggerRequest:
    """触发同步请求模型测试."""

    def test_valid_default(self):
        """默认值应通过."""
        req = SyncTriggerRequest.model_validate({})
        assert req.scope is None
        assert req.conflict_strategy == "newest_wins"

    def test_valid_with_scope(self):
        """带 scope 应通过."""
        req = SyncTriggerRequest.model_validate({
            "scope": ["conversation", "memory"],
        })
        assert req.scope == ["conversation", "memory"]

    def test_valid_newest_wins(self):
        """newest_wins 策略应通过."""
        req = SyncTriggerRequest.model_validate({"conflict_strategy": "newest_wins"})
        assert req.conflict_strategy == "newest_wins"

    def test_valid_manual(self):
        """manual 策略应通过."""
        req = SyncTriggerRequest.model_validate({"conflict_strategy": "manual"})
        assert req.conflict_strategy == "manual"

    def test_valid_local_wins(self):
        """local_wins 策略应通过."""
        req = SyncTriggerRequest.model_validate({"conflict_strategy": "local_wins"})
        assert req.conflict_strategy == "local_wins"

    def test_invalid_conflict_strategy(self):
        """非法 conflict_strategy 应失败."""
        with pytest.raises(ValidationError):
            SyncTriggerRequest.model_validate({"conflict_strategy": "invalid"})

    def test_empty_scope_element(self):
        """空 scope 元素应失败."""
        with pytest.raises(ValidationError):
            SyncTriggerRequest.model_validate({"scope": [""]})

    def test_scope_starts_with_digit(self):
        """scope 以数字开头应失败."""
        with pytest.raises(ValidationError):
            SyncTriggerRequest.model_validate({"scope": ["123bad"]})

    def test_scope_none(self):
        """scope 为 None 应通过."""
        req = SyncTriggerRequest.model_validate({"scope": None})
        assert req.scope is None


# ===========================================================================
# ConfigUpdateRequest 测试
# ===========================================================================


class TestConfigUpdateRequest:
    """配置更新请求模型测试."""

    def test_valid_single_key(self):
        """单个点路径更新应通过."""
        req = ConfigUpdateRequest.model_validate({
            "updates": {"sync.mode": "manual"},
        })
        assert req.updates == {"sync.mode": "manual"}

    def test_valid_multiple_keys(self):
        """多个更新应通过."""
        req = ConfigUpdateRequest.model_validate({
            "updates": {"sync.interval": 60, "log_level": "debug"},
        })
        assert len(req.updates) == 2

    def test_valid_nested_path(self):
        """多级点路径应通过."""
        req = ConfigUpdateRequest.model_validate({
            "updates": {"a.b.c.d": "value"},
        })
        assert req.updates == {"a.b.c.d": "value"}

    def test_valid_list_value(self):
        """列表值应通过."""
        req = ConfigUpdateRequest.model_validate({
            "updates": {"items": [1, 2, 3]},
        })
        assert req.updates == {"items": [1, 2, 3]}

    def test_missing_updates(self):
        """缺少 updates 应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({})

    def test_empty_updates(self):
        """空 updates 应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {}})

    def test_empty_key(self):
        """空键名应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {"": "value"}})

    def test_key_starts_with_dot(self):
        """以点开头的键应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {".invalid": "value"}})

    def test_key_ends_with_dot(self):
        """以点结尾的键应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {"invalid.": "value"}})

    def test_key_starts_with_digit(self):
        """键以数字开头应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {"123bad": "value"}})

    def test_key_special_chars(self):
        """键含特殊字符应失败."""
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {"key@bad": "value"}})

    def test_value_too_long_string(self):
        """超长字符串值应失败."""
        long_str = "a" * 65537
        with pytest.raises(ValidationError):
            ConfigUpdateRequest.model_validate({"updates": {"key": long_str}})


# ===========================================================================
# ConfigBatchUpdateRequest 测试
# ===========================================================================


class TestConfigBatchUpdateRequest:
    """批量配置更新请求模型测试."""

    def test_valid_default(self):
        """默认 validate_only=False 应通过."""
        req = ConfigBatchUpdateRequest.model_validate({
            "updates": {"sync.mode": "manual"},
        })
        assert req.validate_only is False

    def test_valid_validate_only(self):
        """validate_only=True 应通过."""
        req = ConfigBatchUpdateRequest.model_validate({
            "updates": {"sync.mode": "manual"},
            "validate_only": True,
        })
        assert req.validate_only is True

    def test_empty_updates(self):
        """空 updates 应失败（复用 ConfigUpdateRequest 校验）."""
        with pytest.raises(ValidationError):
            ConfigBatchUpdateRequest.model_validate({"updates": {}})


# ===========================================================================
# DeviceRegisterRequest 测试
# ===========================================================================


class TestDeviceRegisterRequest:
    """设备注册请求模型测试."""

    def test_valid_minimal(self):
        """仅 device_id 应通过."""
        req = DeviceRegisterRequest.model_validate({"device_id": "dev_001"})
        assert req.device_id == "dev_001"
        assert req.name == ""
        assert req.device_type == "unknown"

    def test_valid_full(self):
        """完整信息应通过."""
        req = DeviceRegisterRequest.model_validate({
            "device_id": "dev_001",
            "name": "My Device",
            "device_type": "desktop",
            "metadata": {"os": "linux"},
        })
        assert req.name == "My Device"
        assert req.device_type == "desktop"

    def test_valid_smartwatch(self):
        """智能手表类型应通过."""
        req = DeviceRegisterRequest.model_validate({
            "device_id": "dev_001",
            "device_type": "smartwatch",
        })
        assert req.device_type == "smartwatch"

    def test_missing_device_id(self):
        """缺少 device_id 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({})

    def test_empty_device_id(self):
        """空 device_id 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({"device_id": ""})

    def test_too_short_device_id(self):
        """长度为 1 的 device_id 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({"device_id": "a"})

    def test_invalid_device_id_chars(self):
        """含非法字符的 device_id 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({"device_id": "@bad"})

    def test_invalid_device_type(self):
        """非法 device_type 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({
                "device_id": "dev_001",
                "device_type": "invalid",
            })

    def test_too_long_name(self):
        """超长 name 应失败."""
        with pytest.raises(ValidationError):
            DeviceRegisterRequest.model_validate({
                "device_id": "dev_001",
                "name": "a" * 129,
            })


# ===========================================================================
# DeviceUpdateRequest 测试
# ===========================================================================


class TestDeviceUpdateRequest:
    """设备更新请求模型测试."""

    def test_valid_empty(self):
        """空请求（全可选）应通过."""
        req = DeviceUpdateRequest.model_validate({})
        assert req.name is None
        assert req.device_type is None
        assert req.status is None

    def test_valid_name_only(self):
        """仅更新 name 应通过."""
        req = DeviceUpdateRequest.model_validate({"name": "New Name"})
        assert req.name == "New Name"

    def test_valid_status_online(self):
        """online 状态应通过."""
        req = DeviceUpdateRequest.model_validate({"status": "online"})
        assert req.status == "online"

    def test_valid_status_offline(self):
        """offline 状态应通过."""
        req = DeviceUpdateRequest.model_validate({"status": "offline"})
        assert req.status == "offline"

    def test_invalid_device_type(self):
        """非法 device_type 应失败."""
        with pytest.raises(ValidationError):
            DeviceUpdateRequest.model_validate({"device_type": "invalid"})

    def test_invalid_status(self):
        """非法 status 应失败."""
        with pytest.raises(ValidationError):
            DeviceUpdateRequest.model_validate({"status": "invalid"})

    def test_device_type_none(self):
        """device_type 为 None 应通过."""
        req = DeviceUpdateRequest.model_validate({"device_type": None})
        assert req.device_type is None

    def test_status_none(self):
        """status 为 None 应通过."""
        req = DeviceUpdateRequest.model_validate({"status": None})
        assert req.status is None


# ===========================================================================
# DeviceQueryRequest 测试
# ===========================================================================


class TestDeviceQueryRequest:
    """设备查询请求模型测试."""

    def test_valid_default(self):
        """默认值应通过."""
        req = DeviceQueryRequest.model_validate({})
        assert req.page == 1
        assert req.page_size == 20
        assert req.status is None

    def test_valid_pagination(self):
        """标准分页应通过."""
        req = DeviceQueryRequest.model_validate({"page": 5, "page_size": 50})
        assert req.page == 5
        assert req.page_size == 50

    def test_valid_status_online(self):
        """按 online 过滤应通过."""
        req = DeviceQueryRequest.model_validate({"status": "online"})
        assert req.status == "online"

    def test_valid_status_offline(self):
        """按 offline 过滤应通过."""
        req = DeviceQueryRequest.model_validate({"status": "offline"})
        assert req.status == "offline"

    def test_valid_status_unknown(self):
        """按 unknown 过滤应通过."""
        req = DeviceQueryRequest.model_validate({"status": "unknown"})
        assert req.status == "unknown"

    def test_page_zero(self):
        """page 为 0 应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"page": 0})

    def test_page_negative(self):
        """page 为负数应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"page": -1})

    def test_page_too_large(self):
        """page 超过 10000 应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"page": 10001})

    def test_page_size_zero(self):
        """page_size 为 0 应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"page_size": 0})

    def test_page_size_too_large(self):
        """page_size 超过 100 应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"page_size": 101})

    def test_invalid_status(self):
        """非法 status 应失败."""
        with pytest.raises(ValidationError):
            DeviceQueryRequest.model_validate({"status": "invalid"})


# ===========================================================================
# HealthCheckRequest 测试
# ===========================================================================


class TestHealthCheckRequest:
    """健康检查请求模型测试."""

    def test_valid_default(self):
        """默认值应通过."""
        req = HealthCheckRequest.model_validate({})
        assert req.deep is False
        assert req.include_metrics is False

    def test_valid_deep(self):
        """深度检查应通过."""
        req = HealthCheckRequest.model_validate({"deep": True})
        assert req.deep is True

    def test_valid_both_flags(self):
        """两个标志都为 True 应通过."""
        req = HealthCheckRequest.model_validate({
            "deep": True,
            "include_metrics": True,
        })
        assert req.deep is True
        assert req.include_metrics is True


# ===========================================================================
# Path 参数校验函数测试
# ===========================================================================


class TestPathValidators:
    """Path 参数校验函数测试."""

    # --- validate_conflict_id ---

    def test_validate_conflict_id_valid(self):
        """合法冲突 ID 应通过."""
        result = validate_conflict_id("conflict_001")
        assert result == "conflict_001"

    def test_validate_conflict_id_empty(self):
        """空 ID 应失败."""
        with pytest.raises(ValueError):
            validate_conflict_id("")

    def test_validate_conflict_id_special_chars(self):
        """含非法字符应失败."""
        with pytest.raises(ValueError):
            validate_conflict_id("@bad")

    def test_validate_conflict_id_too_short(self):
        """单字符应失败."""
        with pytest.raises(ValueError):
            validate_conflict_id("a")

    # --- validate_device_id_path ---

    def test_validate_device_id_valid(self):
        """合法设备 ID 应通过."""
        result = validate_device_id_path("dev_001")
        assert result == "dev_001"

    def test_validate_device_id_too_short(self):
        """单字符应失败."""
        with pytest.raises(ValueError):
            validate_device_id_path("a")

    def test_validate_device_id_special_chars(self):
        """含非法字符应失败."""
        with pytest.raises(ValueError):
            validate_device_id_path("dev@001")

    # --- validate_session_id ---

    def test_validate_session_id_valid(self):
        """合法 UUID 应通过."""
        result = validate_session_id("550e8400-e29b-41d4-a716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_validate_session_id_invalid_format(self):
        """非 UUID 格式应失败."""
        with pytest.raises(ValueError):
            validate_session_id("not-a-uuid")

    def test_validate_session_id_empty(self):
        """空 UUID 应失败."""
        with pytest.raises(ValueError):
            validate_session_id("")

    def test_validate_session_id_uppercase(self):
        """大写 UUID 应通过."""
        result = validate_session_id("550E8400-E29B-41D4-A716-446655440000")
        assert result == "550E8400-E29B-41D4-A716-446655440000"


# ===========================================================================
# 枚举类型测试
# ===========================================================================


class TestEnums:
    """枚举类型测试."""

    def test_conflict_resolution_values(self):
        """ConflictResolution 枚举值应正确."""
        assert ConflictResolution.LOCAL.value == "local"
        assert ConflictResolution.REMOTE.value == "remote"
        assert ConflictResolution.MERGE.value == "merge"

    def test_conflict_strategy_values(self):
        """ConflictStrategy 枚举值应正确."""
        assert ConflictStrategy.NEWEST_WINS.value == "newest_wins"
        assert ConflictStrategy.LOCAL_WINS.value == "local_wins"
        assert ConflictStrategy.REMOTE_WINS.value == "remote_wins"
        assert ConflictStrategy.MANUAL.value == "manual"

    def test_device_status_values(self):
        """DeviceStatus 枚举值应正确."""
        assert DeviceStatus.ONLINE.value == "online"
        assert DeviceStatus.OFFLINE.value == "offline"
        assert DeviceStatus.UNKNOWN.value == "unknown"

    def test_device_type_values(self):
        """DeviceType 枚举值应正确."""
        assert DeviceType.DESKTOP.value == "desktop"
        assert DeviceType.LAPTOP.value == "laptop"
        assert DeviceType.MOBILE.value == "mobile"
        assert DeviceType.TABLET.value == "tablet"
        assert DeviceType.SMARTWATCH.value == "smartwatch"
        assert DeviceType.DRONE.value == "drone"
        assert DeviceType.RING.value == "ring"
        assert DeviceType.UNKNOWN.value == "unknown"

    def test_sync_scope_values(self):
        """SyncScope 枚举值应正确."""
        assert SyncScope.CONVERSATION.value == "conversation"
        assert SyncScope.MEMORY.value == "memory"
        assert SyncScope.CONFIG.value == "config"
        assert SyncScope.ALL.value == "all"
