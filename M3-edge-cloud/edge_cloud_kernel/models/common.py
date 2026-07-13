"""通用模型.

定义跨领域使用的通用请求/响应模型。
整合自原 api/ 目录中的路由请求模型。

注意：ConfigUpdateRequest 和 SyncTriggerRequest 已迁移至
edge_cloud_kernel.models.api_requests，
此处保留向后兼容的重新导出。
"""

from __future__ import annotations

from edge_cloud_kernel.models.api_requests import (
    ConfigUpdateRequest,
    SyncTriggerRequest,
)

__all__ = [
    "ConfigUpdateRequest",
    "SyncTriggerRequest",
]
