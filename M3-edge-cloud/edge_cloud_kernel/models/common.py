"""通用模型.

定义跨领域使用的通用请求/响应模型。
整合自原 api/ 目录中的路由请求模型。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from edge_cloud_kernel.models.base import EdgeCloudBaseModel


class ConfigUpdateRequest(EdgeCloudBaseModel):
    """配置更新请求体.

    Attributes:
        updates: 点路径的更新字典，如 {"sync.mode": "manual"}.
    """

    updates: dict[str, Any] = Field(..., description="点路径的更新字典")


class SyncTriggerRequest(EdgeCloudBaseModel):
    """同步触发请求体.

    Attributes:
        scope: 同步范围，如 ['conversation', 'memory'].
        conflict_strategy: 冲突解决策略.
    """

    scope: list[str] | None = Field(
        None, description="同步范围，如 ['conversation', 'memory']"
    )
    conflict_strategy: str = Field(
        "newest_wins", description="冲突解决策略"
    )
