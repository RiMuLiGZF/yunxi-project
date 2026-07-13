"""数据模型子包.

导出所有同步、通信、资源监控相关的数据模型。
M3 仅保留同步/通信/监控相关模型，推理相关模型归板块1管理。

模型按领域组织：
- base: 基类 EdgeCloudBaseModel
- sync: 同步相关模型
- gateway: 网关相关模型
- local_data: 本地数据/冲突解决模型
- resource: 资源管理模型（VRAM、缓存）
- call_log: 调用日志模型
- vram_report: VRAM 报告模型
- common: 通用模型
- exceptions: 异常类（非数据模型）
"""

from __future__ import annotations

from edge_cloud_kernel.models.base import EdgeCloudBaseModel
from edge_cloud_kernel.models.call_log import CallLogRecord
from edge_cloud_kernel.models.common import ConfigUpdateRequest, SyncTriggerRequest
from edge_cloud_kernel.models.exceptions import (
    CircuitBreakerError,
    ProviderError,
    SyncError,
    SyncKernelError,
    VRAMOverflowError,
)
from edge_cloud_kernel.models.gateway import HealthCheckerStats, RateLimiterStats
from edge_cloud_kernel.models.local_data import VersionVector
from edge_cloud_kernel.models.sync import (
    OfflineReplayDetail,
    OfflineReplayResult,
    SessionState,
    SyncDelta,
    SyncItem,
    SyncOperation,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncResolveRequest,
    SyncResolveResponse,
    SyncResult,
    SyncSessionRequest,
    SyncSessionResponse,
    SyncStatus,
)
from edge_cloud_kernel.models.vram_report import VRAMLevel, VRAMReport

__all__ = [
    # 基类
    "EdgeCloudBaseModel",
    # 同步模型
    "SyncOperation",
    "SyncStatus",
    "SyncItem",
    "SyncResult",
    "SessionState",
    "SyncSessionRequest",
    "SyncSessionResponse",
    "SyncDelta",
    "SyncPushRequest",
    "SyncPushResponse",
    "SyncPullResponse",
    "SyncResolveRequest",
    "SyncResolveResponse",
    "OfflineReplayDetail",
    "OfflineReplayResult",
    # 网关模型
    "HealthCheckerStats",
    "RateLimiterStats",
    # 本地数据模型
    "VersionVector",
    # 资源模型
    "VRAMReport",
    "VRAMLevel",
    # 调用日志模型
    "CallLogRecord",
    # 通用模型
    "ConfigUpdateRequest",
    "SyncTriggerRequest",
    # 异常
    "SyncKernelError",
    "SyncError",
    "CircuitBreakerError",
    "VRAMOverflowError",
    "ProviderError",
]
