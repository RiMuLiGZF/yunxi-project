"""端云协同增强服务层.

包含数据同步引擎、离线管理、边缘调度、边缘函数、
通信协议、消息总线、设备管理等增强服务。

所有服务均为纯增量实现，不影响现有功能。
边缘计算框架可插拔，按需启用。
"""

from __future__ import annotations

from edge_cloud_kernel.services.sync_engine import (
    ConflictDetectResult,
    OperationLogEntry,
    SyncDirection,
    SyncEngine,
    SyncProgress,
    SyncQueueItem,
    SyncStrategy,
)
from edge_cloud_kernel.services.offline_manager import (
    OfflineManager,
    OfflineQueueEntry,
    OfflineStatus,
)
from edge_cloud_kernel.services.edge_scheduler import (
    DeviceComputeProfile,
    EdgeScheduler,
    SchedulingDecision,
    SchedulingStrategy,
    TaskFragment,
    TaskPriority,
    TaskStatus,
)
from edge_cloud_kernel.services.edge_functions import (
    EdgeFunction,
    EdgeFunctionSandbox,
    EdgeFunctionService,
    FunctionExecutionResult,
    FunctionStatus,
    FunctionVersion,
)
from edge_cloud_kernel.services.protocol import (
    HandshakeRequest,
    HandshakeResponse,
    HeartbeatMessage,
    MessageType,
    ProtocolVersion,
    SyncProtocol,
    TaskDistributionMessage,
)
from edge_cloud_kernel.services.message_bus import (
    Message,
    MessageAckStatus,
    MessageBus,
    MessagePriority,
    MessageStatus,
)
from edge_cloud_kernel.services.device_manager import (
    DeviceHealthScore,
    DeviceHealthStatus,
    DeviceManager,
    DeviceTrustLevel,
    HealthMetric,
)

__all__ = [
    # 数据同步引擎
    "SyncEngine",
    "SyncStrategy",
    "SyncDirection",
    "SyncProgress",
    "SyncQueueItem",
    "OperationLogEntry",
    "ConflictDetectResult",
    # 离线管理
    "OfflineManager",
    "OfflineStatus",
    "OfflineQueueEntry",
    # 边缘调度
    "EdgeScheduler",
    "SchedulingStrategy",
    "SchedulingDecision",
    "TaskStatus",
    "TaskPriority",
    "TaskFragment",
    "DeviceComputeProfile",
    # 边缘函数
    "EdgeFunctionService",
    "EdgeFunction",
    "FunctionVersion",
    "FunctionStatus",
    "FunctionExecutionResult",
    "EdgeFunctionSandbox",
    # 通信协议
    "SyncProtocol",
    "MessageType",
    "ProtocolVersion",
    "HandshakeRequest",
    "HandshakeResponse",
    "HeartbeatMessage",
    "TaskDistributionMessage",
    # 消息总线
    "MessageBus",
    "Message",
    "MessagePriority",
    "MessageStatus",
    "MessageAckStatus",
    # 设备管理
    "DeviceManager",
    "DeviceTrustLevel",
    "DeviceHealthStatus",
    "DeviceHealthScore",
    "HealthMetric",
]
