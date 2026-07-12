"""M8 标准对接接口.

提供 M3 模块对 M8 的标准对接服务，包含：
- 统一错误码
- M8 API 服务（业务接口：同步/冲突/设备）
- 鉴权中间件
- 健康检查 + 性能指标
- 配置管理
- 升级管理（MVP Mock）
- 测试管理
- 设备注册表（内存 + SQLite 持久化）
"""

from edge_cloud_kernel.m8_api.error_codes import ErrorCode
from edge_cloud_kernel.m8_api.m8_api_service import M8APIResponse, M8APIService
from edge_cloud_kernel.m8_api.m8_auth_middleware import M8TokenAuthMiddleware, WHITE_LIST_PATHS
from edge_cloud_kernel.m8_api.health_endpoints import HealthMetricsService, MetricsCollector
from edge_cloud_kernel.m8_api.config_endpoints import ConfigManager
from edge_cloud_kernel.m8_api.upgrade_endpoints import UpgradeManager
from edge_cloud_kernel.m8_api.test_endpoints import TestManager
from edge_cloud_kernel.m8_api.device_registry import (
    DeviceInfo,
    DeviceRegistry,
    InMemoryDeviceRegistry,
    SqliteDeviceRegistry,
    create_device_registry,
)

__all__ = [
    "ErrorCode",
    "M8APIResponse",
    "M8APIService",
    "M8TokenAuthMiddleware",
    "WHITE_LIST_PATHS",
    "HealthMetricsService",
    "MetricsCollector",
    "ConfigManager",
    "UpgradeManager",
    "TestManager",
    "DeviceInfo",
    "DeviceRegistry",
    "InMemoryDeviceRegistry",
    "SqliteDeviceRegistry",
    "create_device_registry",
]
