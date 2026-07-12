"""同步模型.

定义上下文同步条目、同步结果和会话状态。
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class SyncItem(BaseModel):
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


class SyncResult(BaseModel):
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


class SessionState(BaseModel):
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
