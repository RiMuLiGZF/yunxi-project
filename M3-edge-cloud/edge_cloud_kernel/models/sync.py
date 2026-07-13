"""同步相关模型.

定义上下文同步条目、同步结果、会话状态以及同步 API 的请求/响应模型。
整合自原 sync_models.py 和 sync/sync_api.py 中的 Pydantic 模型。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import Field

from edge_cloud_kernel.models.base import EdgeCloudBaseModel


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class SyncOperation(str, Enum):
    """同步操作类型枚举.

    Attributes:
        UPLOAD: 上传本地数据到云端.
        DOWNLOAD: 从云端下载到本地.
        BIDIRECTIONAL: 双向同步（合并）.
    """

    UPLOAD = "upload"
    DOWNLOAD = "download"
    BIDIRECTIONAL = "bidirectional"


class SyncStatus(str, Enum):
    """同步结果状态枚举.

    Attributes:
        SUCCESS: 同步成功.
        CONFLICT: 存在冲突，需解决.
        SKIPPED: 跳过（无需同步）.
        FAILED: 同步失败.
    """

    SUCCESS = "success"
    CONFLICT = "conflict"
    SKIPPED = "skipped"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 核心同步模型
# ---------------------------------------------------------------------------


class SyncItem(EdgeCloudBaseModel):
    """上下文同步条目.

    表示需要同步的一条数据记录。

    Attributes:
        item_id: 条目唯一标识.
        sync_type: 同步操作类型.
        category: 数据分类（conversation/memory/config）.
        key: 数据键.
        value: 数据值.
        version: 本地版本号.
        checksum: 数据校验和.
        timestamp: 最后修改时间戳.
        synced_at: 上次同步时间戳.
    """

    item_id: str = Field(..., description="条目唯一标识")
    sync_type: SyncOperation = Field(default=SyncOperation.BIDIRECTIONAL)
    category: str = Field(default="conversation", description="数据分类")
    key: str = Field(..., description="数据键")
    value: Any = Field(default=None, description="数据值")
    version: int = Field(default=1, ge=1, description="版本号")
    checksum: str | None = Field(default=None, description="校验和")
    timestamp: float = Field(default_factory=time.time, description="修改时间戳")
    synced_at: float | None = Field(default=None, description="上次同步时间")


class SyncResult(EdgeCloudBaseModel):
    """同步操作结果.

    Attributes:
        item_id: 关联的同步条目 ID.
        status: 同步结果状态.
        resolved_version: 解决冲突后的版本号（如有冲突）.
        error_message: 错误信息（失败时）.
        remote_checksum: 远端校验和（成功时）.
    """

    item_id: str = Field(..., description="关联条目 ID")
    status: SyncStatus = Field(default=SyncStatus.SUCCESS)
    resolved_version: int | None = Field(default=None, description="解决后版本号")
    error_message: str | None = Field(default=None, description="错误信息")
    remote_checksum: str | None = Field(default=None, description="远端校验和")


class SessionState(EdgeCloudBaseModel):
    """会话状态快照.

    用于在端云之间同步会话上下文。

    Attributes:
        session_id: 会话唯一标识.
        agent_name: 关联的 Agent 名称.
        total_turns: 总对话轮次.
        last_active_at: 最后活跃时间戳.
        context_summary: 上下文摘要.
        pending_tasks: 待处理任务 ID 列表.
        local_token_budget: 本地剩余 token 预算.
        sync_version: 同步版本号.
    """

    session_id: str = Field(..., description="会话 ID")
    agent_name: str = Field(default="", description="Agent 名称")
    total_turns: int = Field(default=0, ge=0, description="总对话轮次")
    last_active_at: float = Field(default_factory=time.time, description="最后活跃时间")
    context_summary: str = Field(default="", description="上下文摘要")
    pending_tasks: list[str] = Field(default_factory=list, description="待处理任务 ID")
    local_token_budget: int = Field(default=4096, ge=0, description="本地 token 预算")
    sync_version: int = Field(default=1, ge=1, description="同步版本号")


# ---------------------------------------------------------------------------
# 同步 API 请求/响应模型
# ---------------------------------------------------------------------------


class SyncSessionRequest(EdgeCloudBaseModel):
    """创建同步会话请求.

    Attributes:
        device_id: 设备唯一标识.
        scopes: 需要同步的数据范围列表.
    """

    device_id: str = Field(..., description="设备唯一标识")
    scopes: list[str] = Field(default_factory=list, description="同步数据范围")


class SyncSessionResponse(EdgeCloudBaseModel):
    """创建同步会话响应.

    Attributes:
        session_id: 会话唯一标识（UUID）.
        server_version: 服务端版本号.
    """

    session_id: str = Field(..., description="会话 UUID")
    server_version: str = Field(default="2.1.0", description="服务端版本")


class SyncDelta(EdgeCloudBaseModel):
    """同步增量数据单元.

    表示一条待同步或已同步的数据变更记录。

    Attributes:
        item_id: 条目唯一标识.
        item_type: 数据类型（conversation/memory/config）.
        content_hash: 内容 SHA-256 哈希（用于去重和一致性校验）.
        content: 原始内容字节（pull 时可选填充）.
        metadata: 附加元数据字典.
        timestamp: 变更时间戳（Unix 秒）.
        version: 数据版本号（单调递增）.
    """

    item_id: str = Field(..., description="条目唯一标识")
    item_type: str = Field(..., description="数据类型")
    content_hash: str = Field(..., description="内容 SHA-256 哈希")
    content: bytes | None = Field(default=None, description="原始内容字节")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")
    timestamp: float = Field(..., description="变更时间戳")
    version: int = Field(default=1, ge=1, description="数据版本号")


class SyncPushRequest(EdgeCloudBaseModel):
    """推送变更请求.

    Attributes:
        changes: 本地变更增量列表.
        version_vector: 各数据类型的本地版本向量.
    """

    changes: list[SyncDelta] = Field(..., description="本地变更增量列表")
    version_vector: dict[str, int] = Field(
        default_factory=dict, description="本地版本向量"
    )


class SyncPushResponse(EdgeCloudBaseModel):
    """推送变更响应.

    Attributes:
        accepted: 已被服务端接受的 item_id 列表.
        rejected: 被服务端拒绝的 item_id 列表.
        conflicts: 检测到冲突的详细信息列表.
    """

    accepted: list[str] = Field(default_factory=list, description="已接受条目 ID")
    rejected: list[str] = Field(default_factory=list, description="被拒绝条目 ID")
    conflicts: list[dict[str, Any]] = Field(
        default_factory=list, description="冲突详情列表"
    )


class SyncPullResponse(EdgeCloudBaseModel):
    """拉取变更响应.

    Attributes:
        changes: 服务端变更增量列表.
        server_version: 服务端当前版本号.
    """

    changes: list[SyncDelta] = Field(
        default_factory=list, description="服务端变更增量列表"
    )
    server_version: str = Field(default="2.1.0", description="服务端版本")


class SyncResolveRequest(EdgeCloudBaseModel):
    """冲突解决请求.

    Attributes:
        conflict_ids: 待解决的冲突条目 ID 列表.
        resolution: 解决策略（local / remote / merge）.
    """

    conflict_ids: list[str] = Field(..., description="冲突条目 ID 列表")
    resolution: str = Field(..., description="解决策略: local|remote|merge")


class SyncResolveResponse(EdgeCloudBaseModel):
    """冲突解决响应.

    Attributes:
        resolved: 成功解决的冲突 ID 列表.
        failed: 解决失败的冲突 ID 列表.
    """

    resolved: list[str] = Field(default_factory=list, description="已解决冲突 ID")
    failed: list[str] = Field(default_factory=list, description="解决失败冲突 ID")


# ---------------------------------------------------------------------------
# 离线回放模型
# ---------------------------------------------------------------------------


class OfflineReplayDetail(EdgeCloudBaseModel):
    """单条回放结果详情.

    Attributes:
        queue_id: 队列记录 ID.
        operation: 操作类型.
        session_id: 关联会话 ID.
        success: 是否成功.
        error: 失败时的错误信息.
    """

    queue_id: int = Field(..., description="队列记录 ID")
    operation: str = Field(..., description="操作类型")
    session_id: str = Field(default="", description="关联会话 ID")
    success: bool = Field(default=True, description="是否成功")
    error: str = Field(default="", description="失败错误信息")


class OfflineReplayResult(EdgeCloudBaseModel):
    """批量回放结果汇总.

    Attributes:
        success_count: 成功回放的操作数.
        failed_count: 回放失败的操作数.
        skipped_count: 跳过的操作数（如过期会话）.
        details: 每条操作的详细结果列表.
    """

    success_count: int = Field(default=0, description="成功数")
    failed_count: int = Field(default=0, description="失败数")
    skipped_count: int = Field(default=0, description="跳过数")
    details: list[OfflineReplayDetail] = Field(
        default_factory=list, description="详细结果列表"
    )
