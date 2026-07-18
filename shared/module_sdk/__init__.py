"""
云汐系统模块间通信 SDK
========================

统一的模块间通信 SDK 和服务注册发现机制。

核心组件：
- ModuleClient: 统一模块调用客户端（服务发现、负载均衡、重试、熔断）
- ServiceRegistryClient: 服务注册中心客户端
- EventBus: 全局事件总线（发布/订阅、通配符、历史记录）
- ModuleAutoRegister: 模块自动注册启动器
- ApiResponse / ServiceInstance / Event: 数据模型

使用方式：
    from shared.module_sdk import ModuleClient, get_event_bus

    # 调用其他模块
    client = ModuleClient("m1")
    result = await client.get("/users")

    # 发布事件
    bus = get_event_bus()
    bus.publish("user.created", {"user_id": "123"}, source="m1")
"""

from .models import (
    ApiResponse,
    ServiceInstance,
    ServiceStatus,
    Event,
    SdkErrorCode,
    LoadBalanceStrategy,
    CircuitState,
)
from .registry import (
    ServiceRegistryClient,
    InMemoryRegistry,
    get_registry_client,
    reset_registry_client,
)
from .event_bus import (
    EventBus,
    InMemoryEventBus,
    get_event_bus,
    reset_event_bus,
)
from .module_client import (
    ModuleClient,
    CircuitBreaker,
    LoadBalancer,
)
from .auto_register import (
    ModuleAutoRegister,
    setup_module_registration,
    setup_module_registration_lifespan,
    auto_register_module,
)

__all__ = [
    # 模型
    "ApiResponse",
    "ServiceInstance",
    "ServiceStatus",
    "Event",
    "SdkErrorCode",
    "LoadBalanceStrategy",
    "CircuitState",
    # 注册中心
    "ServiceRegistryClient",
    "InMemoryRegistry",
    "get_registry_client",
    "reset_registry_client",
    # 事件总线
    "EventBus",
    "InMemoryEventBus",
    "get_event_bus",
    "reset_event_bus",
    # 模块客户端
    "ModuleClient",
    "CircuitBreaker",
    "LoadBalancer",
    # 自动注册
    "ModuleAutoRegister",
    "setup_module_registration",
    "setup_module_registration_lifespan",
    "auto_register_module",
]

__version__ = "1.0.0"
