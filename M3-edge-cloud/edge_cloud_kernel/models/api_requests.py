"""API 请求校验模型.

定义所有 HTTP API 端点的请求体 Pydantic 模型，提供严格的输入校验：
- 字符串字段：min_length / max_length / pattern
- 数字字段：ge / le / gt / lt
- 列表字段：min_length / max_length
- 枚举字段：使用 Enum 约束
- 自定义校验：field_validator（ID 格式、版本号格式等）

所有模型继承 EdgeCloudBaseModel，保持与现有模型体系一致。
向后兼容：合法请求的行为与原有裸 dict/Body 方式完全一致。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from edge_cloud_kernel.models.base import EdgeCloudBaseModel

# ---------------------------------------------------------------------------
# 常量与正则
# ---------------------------------------------------------------------------

# 设备 ID / 冲突 ID / 会话 ID 通用格式：字母、数字、下划线、短横线
_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{1,63}$")

# 配置点路径：以点分隔的层级键名，如 "sync.mode"
_CONFIG_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)*$")

# 版本号格式：语义化版本（主.次.补丁），可选预发布标签
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$")

# 通用最大长度
_MAX_ID_LENGTH = 64
_MAX_NAME_LENGTH = 128
_MAX_STATUS_LENGTH = 32
_MAX_SCOPE_LENGTH = 64
_MAX_RESOLUTION_LENGTH = 32
_MAX_SYNC_SCOPES = 20
_MAX_CONFLICT_IDS = 100
_MAX_PUSH_CHANGES = 500
_MAX_CONFIG_UPDATES = 100
_MAX_CONFIG_KEY_LENGTH = 256
_MAX_CONFIG_VALUE_LENGTH = 65536  # 64KB


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class ConflictResolution(str, Enum):
    """冲突解决策略枚举.

    Attributes:
        LOCAL: 保留本地版本.
        REMOTE: 接受远端版本.
        MERGE: 合并双方版本.
    """

    LOCAL = "local"
    REMOTE = "remote"
    MERGE = "merge"


class ConflictStrategy(str, Enum):
    """同步冲突策略枚举.

    Attributes:
        NEWEST_WINS: 最新版本胜出.
        LOCAL_WINS: 本地版本胜出.
        REMOTE_WINS: 远端版本胜出.
        MANUAL: 手动解决.
    """

    NEWEST_WINS = "newest_wins"
    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    MANUAL = "manual"


class DeviceStatus(str, Enum):
    """设备状态枚举.

    Attributes:
        ONLINE: 在线.
        OFFLINE: 离线.
        UNKNOWN: 未知.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class DeviceType(str, Enum):
    """设备类型枚举.

    Attributes:
        DESKTOP: 桌面端.
        LAPTOP: 笔记本.
        MOBILE: 移动端.
        TABLET: 平板.
        SMARTWATCH: 智能手表.
        DRONE: 无人机.
        RING: 智能戒指.
        UNKNOWN: 未知类型.
    """

    DESKTOP = "desktop"
    LAPTOP = "laptop"
    MOBILE = "mobile"
    TABLET = "tablet"
    SMARTWATCH = "smartwatch"
    DRONE = "drone"
    RING = "ring"
    UNKNOWN = "unknown"


class SyncScope(str, Enum):
    """同步范围枚举.

    Attributes:
        CONVERSATION: 对话数据.
        MEMORY: 记忆数据.
        CONFIG: 配置数据.
        ALL: 全部数据.
    """

    CONVERSATION = "conversation"
    MEMORY = "memory"
    CONFIG = "config"
    ALL = "all"


# ---------------------------------------------------------------------------
# 同步相关请求模型
# ---------------------------------------------------------------------------


class SyncSessionCreateRequest(EdgeCloudBaseModel):
    """创建同步会话请求.

    Attributes:
        device_id: 设备唯一标识.
        scopes: 需要同步的数据范围列表.
    """

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_ID_LENGTH,
        description="设备唯一标识",
    )
    scopes: list[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=_MAX_SYNC_SCOPES,
        description="同步数据范围列表",
    )

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        """校验 device_id 格式.

        Args:
            v: 设备 ID 字符串.

        Returns:
            校验后的设备 ID.

        Raises:
            ValueError: 格式不合法.
        """
        if not _ID_PATTERN.match(v):
            raise ValueError(
                f"device_id 必须以字母或数字开头，仅包含字母、数字、下划线、短横线，"
                f"长度 2-{_MAX_ID_LENGTH}"
            )
        return v

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        """校验 scopes 列表中每个元素的格式和长度.

        Args:
            v: 同步范围列表.

        Returns:
            校验后的范围列表.

        Raises:
            ValueError: 元素格式不合法.
        """
        for scope in v:
            if not scope or len(scope) > _MAX_SCOPE_LENGTH:
                raise ValueError(
                    f"scope 长度必须在 1-{_MAX_SCOPE_LENGTH} 之间"
                )
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", scope):
                raise ValueError(
                    "scope 必须以字母开头，仅包含字母、数字、下划线"
                )
        # 去重
        return list(dict.fromkeys(v))


class SyncPushRequest(EdgeCloudBaseModel):
    """推送同步数据请求.

    Attributes:
        changes: 本地变更增量列表.
        version_vector: 各数据类型的本地版本向量.
    """

    changes: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=_MAX_PUSH_CHANGES,
        description="本地变更增量列表",
    )
    version_vector: dict[str, int] = Field(
        default_factory=dict,
        description="本地版本向量 {scope: version}",
    )

    @field_validator("changes")
    @classmethod
    def validate_changes(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """校验每条变更记录必须包含关键字段.

        Args:
            v: 变更记录列表.

        Returns:
            校验后的变更列表.

        Raises:
            ValueError: 变更记录缺少必要字段.
        """
        required_fields = {"item_id", "item_type", "content_hash", "timestamp", "version"}
        for i, change in enumerate(v):
            if not isinstance(change, dict):
                raise ValueError(f"changes[{i}] 必须是对象")
            missing = required_fields - change.keys()
            if missing:
                raise ValueError(
                    f"changes[{i}] 缺少必要字段: {', '.join(sorted(missing))}"
                )
            item_id = change.get("item_id", "")
            if not isinstance(item_id, str) or not item_id:
                raise ValueError(f"changes[{i}].item_id 必须是非空字符串")
            if len(item_id) > _MAX_ID_LENGTH:
                raise ValueError(
                    f"changes[{i}].item_id 长度不能超过 {_MAX_ID_LENGTH}"
                )
            version = change.get("version", 0)
            if not isinstance(version, int) or version < 1:
                raise ValueError(
                    f"changes[{i}].version 必须是大于等于 1 的整数"
                )
        return v

    @field_validator("version_vector")
    @classmethod
    def validate_version_vector(cls, v: dict[str, int]) -> dict[str, int]:
        """校验版本向量的键值格式.

        Args:
            v: 版本向量字典.

        Returns:
            校验后的版本向量.

        Raises:
            ValueError: 键或值格式不合法.
        """
        if len(v) > _MAX_SYNC_SCOPES:
            raise ValueError(
                f"version_vector 最多包含 {_MAX_SYNC_SCOPES} 个条目"
            )
        for key, val in v.items():
            if not key or len(key) > _MAX_SCOPE_LENGTH:
                raise ValueError(
                    f"version_vector 键长度必须在 1-{_MAX_SCOPE_LENGTH} 之间"
                )
            if not isinstance(val, int) or val < 0:
                raise ValueError(
                    f"version_vector['{key}'] 必须是非负整数"
                )
        return v


class SyncPullRequest(EdgeCloudBaseModel):
    """拉取同步数据请求（查询参数模型）.

    Attributes:
        since_version: 客户端本地版本向量.
    """

    since_version: dict[str, int] = Field(
        default_factory=dict,
        description="客户端本地版本向量 {scope: version}",
    )

    @field_validator("since_version")
    @classmethod
    def validate_since_version(cls, v: dict[str, int]) -> dict[str, int]:
        """校验 since_version 的键值格式.

        Args:
            v: 版本向量字典.

        Returns:
            校验后的版本向量.

        Raises:
            ValueError: 键或值格式不合法.
        """
        if len(v) > _MAX_SYNC_SCOPES:
            raise ValueError(
                f"since_version 最多包含 {_MAX_SYNC_SCOPES} 个条目"
            )
        for key, val in v.items():
            if not key or len(key) > _MAX_SCOPE_LENGTH:
                raise ValueError(
                    f"since_version 键长度必须在 1-{_MAX_SCOPE_LENGTH} 之间"
                )
            if not isinstance(val, int) or val < 0:
                raise ValueError(
                    f"since_version['{key}'] 必须是非负整数"
                )
        return v


class SyncResolveRequest(EdgeCloudBaseModel):
    """解决冲突请求.

    Attributes:
        resolution: 解决策略.
        conflict_ids: 待解决的冲突 ID 列表（可选，兼容 path 参数方式）.
    """

    resolution: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_RESOLUTION_LENGTH,
        description="解决策略: local|remote|merge",
    )
    conflict_ids: list[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=_MAX_CONFLICT_IDS,
        description="待解决的冲突 ID 列表",
    )

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v: str) -> str:
        """校验 resolution 必须是合法的策略值.

        Args:
            v: 解决策略字符串.

        Returns:
            校验后的策略.

        Raises:
            ValueError: 策略不合法.
        """
        valid = {item.value for item in ConflictResolution}
        if v not in valid:
            raise ValueError(
                f"resolution 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v

    @field_validator("conflict_ids")
    @classmethod
    def validate_conflict_ids(cls, v: list[str]) -> list[str]:
        """校验 conflict_ids 中每个 ID 的格式.

        Args:
            v: 冲突 ID 列表.

        Returns:
            校验后的 ID 列表.

        Raises:
            ValueError: ID 格式不合法.
        """
        for cid in v:
            if not _ID_PATTERN.match(cid):
                raise ValueError(
                    f"conflict_id '{cid}' 格式不合法，"
                    f"必须以字母或数字开头，仅包含字母、数字、下划线、短横线"
                )
        # 去重
        return list(dict.fromkeys(v))


class SyncTriggerRequest(EdgeCloudBaseModel):
    """触发同步请求.

    Attributes:
        scope: 同步范围列表.
        conflict_strategy: 冲突解决策略.
    """

    scope: list[str] | None = Field(
        None,
        min_length=0,
        max_length=_MAX_SYNC_SCOPES,
        description="同步范围，如 ['conversation', 'memory']",
    )
    conflict_strategy: str = Field(
        "newest_wins",
        min_length=1,
        max_length=_MAX_RESOLUTION_LENGTH,
        description="冲突解决策略",
    )

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: list[str] | None) -> list[str] | None:
        """校验 scope 列表元素格式.

        Args:
            v: 同步范围列表.

        Returns:
            校验后的范围列表.

        Raises:
            ValueError: 元素格式不合法.
        """
        if v is None:
            return None
        for s in v:
            if not s or len(s) > _MAX_SCOPE_LENGTH:
                raise ValueError(
                    f"scope 元素长度必须在 1-{_MAX_SCOPE_LENGTH} 之间"
                )
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", s):
                raise ValueError(
                    "scope 元素必须以字母开头，仅包含字母、数字、下划线"
                )
        # 去重
        return list(dict.fromkeys(v))

    @field_validator("conflict_strategy")
    @classmethod
    def validate_conflict_strategy(cls, v: str) -> str:
        """校验 conflict_strategy 必须是合法值.

        Args:
            v: 冲突策略字符串.

        Returns:
            校验后的策略.

        Raises:
            ValueError: 策略不合法.
        """
        valid = {item.value for item in ConflictStrategy}
        if v not in valid:
            raise ValueError(
                f"conflict_strategy 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v


# ---------------------------------------------------------------------------
# 配置相关请求模型
# ---------------------------------------------------------------------------


class ConfigUpdateRequest(EdgeCloudBaseModel):
    """更新配置请求（点路径方式）.

    Attributes:
        updates: 点路径的更新字典，如 {"sync.mode": "manual"}.
    """

    updates: dict[str, Any] = Field(
        ...,
        description="点路径的更新字典，如 {'sync.mode': 'manual'}",
    )

    @field_validator("updates")
    @classmethod
    def validate_updates(cls, v: dict[str, Any]) -> dict[str, Any]:
        """校验 updates 的键名格式和值长度.

        Args:
            v: 更新字典.

        Returns:
            校验后的更新字典.

        Raises:
            ValueError: 键格式不合法或值超限.
        """
        if len(v) == 0:
            raise ValueError("updates 不能为空")
        if len(v) > _MAX_CONFIG_UPDATES:
            raise ValueError(
                f"updates 最多包含 {_MAX_CONFIG_UPDATES} 个条目"
            )
        for key in v:
            if not key or len(key) > _MAX_CONFIG_KEY_LENGTH:
                raise ValueError(
                    f"updates 键 '{key}' 长度必须在 1-{_MAX_CONFIG_KEY_LENGTH} 之间"
                )
            if not _CONFIG_KEY_PATTERN.match(key):
                raise ValueError(
                    f"updates 键 '{key}' 格式不合法，"
                    f"必须以字母开头，使用点分隔层级，如 'sync.interval'"
                )
            val = v[key]
            # 对字符串值做长度限制
            if isinstance(val, str) and len(val) > _MAX_CONFIG_VALUE_LENGTH:
                raise ValueError(
                    f"updates['{key}'] 字符串长度不能超过 {_MAX_CONFIG_VALUE_LENGTH}"
                )
            # 对列表值做长度限制
            if isinstance(val, list) and len(val) > 1000:
                raise ValueError(
                    f"updates['{key}'] 列表长度不能超过 1000"
                )
        return v


class ConfigBatchUpdateRequest(EdgeCloudBaseModel):
    """批量更新配置请求.

    Attributes:
        updates: 点路径的更新字典.
        validate_only: 是否仅校验不应用.
    """

    updates: dict[str, Any] = Field(
        ...,
        description="点路径的更新字典",
    )
    validate_only: bool = Field(
        False,
        description="是否仅校验不实际应用更新",
    )

    @field_validator("updates")
    @classmethod
    def validate_updates(cls, v: dict[str, Any]) -> dict[str, Any]:
        """复用 ConfigUpdateRequest 的校验逻辑.

        Args:
            v: 更新字典.

        Returns:
            校验后的更新字典.
        """
        # 复用 ConfigUpdateRequest 的 validator
        return ConfigUpdateRequest.validate_updates(v)


# ---------------------------------------------------------------------------
# 设备相关请求模型
# ---------------------------------------------------------------------------


class DeviceRegisterRequest(EdgeCloudBaseModel):
    """注册设备请求.

    Attributes:
        device_id: 设备唯一标识.
        name: 设备名称.
        device_type: 设备类型.
        metadata: 附加元数据.
    """

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_ID_LENGTH,
        description="设备唯一标识",
    )
    name: str = Field(
        "",
        max_length=_MAX_NAME_LENGTH,
        description="设备名称",
    )
    device_type: str = Field(
        "unknown",
        max_length=_MAX_STATUS_LENGTH,
        description="设备类型",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="附加元数据",
    )

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        """校验 device_id 格式.

        Args:
            v: 设备 ID.

        Returns:
            校验后的设备 ID.
        """
        if not _ID_PATTERN.match(v):
            raise ValueError(
                f"device_id 必须以字母或数字开头，仅包含字母、数字、下划线、短横线，"
                f"长度 2-{_MAX_ID_LENGTH}"
            )
        return v

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str) -> str:
        """校验 device_type 必须是合法的设备类型.

        Args:
            v: 设备类型字符串.

        Returns:
            校验后的设备类型.
        """
        valid = {item.value for item in DeviceType}
        if v not in valid:
            raise ValueError(
                f"device_type 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v


class DeviceUpdateRequest(EdgeCloudBaseModel):
    """更新设备请求.

    Attributes:
        name: 设备名称（可选）.
        device_type: 设备类型（可选）.
        status: 设备状态（可选）.
        metadata: 附加元数据（可选）.
    """

    name: str | None = Field(
        None,
        max_length=_MAX_NAME_LENGTH,
        description="设备名称",
    )
    device_type: str | None = Field(
        None,
        max_length=_MAX_STATUS_LENGTH,
        description="设备类型",
    )
    status: str | None = Field(
        None,
        max_length=_MAX_STATUS_LENGTH,
        description="设备状态",
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="附加元数据",
    )

    @field_validator("device_type")
    @classmethod
    def validate_device_type(cls, v: str | None) -> str | None:
        """校验 device_type（如果提供）.

        Args:
            v: 设备类型或 None.

        Returns:
            校验后的设备类型.
        """
        if v is None:
            return None
        valid = {item.value for item in DeviceType}
        if v not in valid:
            raise ValueError(
                f"device_type 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        """校验 status（如果提供）.

        Args:
            v: 设备状态或 None.

        Returns:
            校验后的状态.
        """
        if v is None:
            return None
        valid = {item.value for item in DeviceStatus}
        if v not in valid:
            raise ValueError(
                f"status 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v


class DeviceQueryRequest(EdgeCloudBaseModel):
    """查询设备请求（查询参数模型）.

    Attributes:
        page: 页码.
        page_size: 每页条数.
        status: 按状态过滤.
    """

    page: int = Field(1, ge=1, le=10000, description="页码（从 1 开始）")
    page_size: int = Field(20, ge=1, le=100, description="每页条数")
    status: str | None = Field(None, description="按设备状态过滤")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        """校验 status（如果提供）.

        Args:
            v: 状态字符串或 None.

        Returns:
            校验后的状态.
        """
        if v is None:
            return None
        valid = {item.value for item in DeviceStatus}
        if v not in valid:
            raise ValueError(
                f"status 必须是以下之一: {', '.join(sorted(valid))}"
            )
        return v


# ---------------------------------------------------------------------------
# 健康检查相关请求模型
# ---------------------------------------------------------------------------


class HealthCheckRequest(EdgeCloudBaseModel):
    """健康检查请求.

    健康检查通常不需要请求体，此模型用于扩展场景
    （如带参数的深度健康检查）。

    Attributes:
        deep: 是否执行深度检查.
        include_metrics: 是否包含性能指标.
    """

    deep: bool = Field(False, description="是否执行深度健康检查")
    include_metrics: bool = Field(False, description="是否包含性能指标")


# ---------------------------------------------------------------------------
# Path 参数校验辅助函数（供路由层使用）
# ---------------------------------------------------------------------------


def validate_conflict_id(conflict_id: str) -> str:
    """校验冲突 ID 格式（用于 Path 参数）.

    Args:
        conflict_id: 冲突 ID.

    Returns:
        校验后的冲突 ID.

    Raises:
        ValueError: 格式不合法.
    """
    if not _ID_PATTERN.match(conflict_id):
        raise ValueError(
            f"conflict_id 格式不合法，必须以字母或数字开头，"
            f"仅包含字母、数字、下划线、短横线，长度 2-{_MAX_ID_LENGTH}"
        )
    return conflict_id


def validate_device_id_path(device_id: str) -> str:
    """校验设备 ID 格式（用于 Path 参数）.

    Args:
        device_id: 设备 ID.

    Returns:
        校验后的设备 ID.

    Raises:
        ValueError: 格式不合法.
    """
    if not _ID_PATTERN.match(device_id):
        raise ValueError(
            f"device_id 格式不合法，必须以字母或数字开头，"
            f"仅包含字母、数字、下划线、短横线，长度 2-{_MAX_ID_LENGTH}"
        )
    return device_id


def validate_session_id(session_id: str) -> str:
    """校验会话 ID 格式（UUID，用于 Path 参数）.

    Args:
        session_id: 会话 ID.

    Returns:
        校验后的会话 ID.

    Raises:
        ValueError: 格式不合法.
    """
    # UUID 格式：8-4-4-4-12 十六进制字符
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )
    if not uuid_pattern.match(session_id):
        raise ValueError(
            "session_id 格式不合法，必须是标准 UUID 格式"
        )
    return session_id


__all__ = [
    # 枚举
    "ConflictResolution",
    "ConflictStrategy",
    "DeviceStatus",
    "DeviceType",
    "SyncScope",
    # 同步相关
    "SyncSessionCreateRequest",
    "SyncPushRequest",
    "SyncPullRequest",
    "SyncResolveRequest",
    "SyncTriggerRequest",
    # 配置相关
    "ConfigUpdateRequest",
    "ConfigBatchUpdateRequest",
    # 设备相关
    "DeviceRegisterRequest",
    "DeviceUpdateRequest",
    "DeviceQueryRequest",
    # 健康检查
    "HealthCheckRequest",
    # Path 参数校验函数
    "validate_conflict_id",
    "validate_device_id_path",
    "validate_session_id",
]
