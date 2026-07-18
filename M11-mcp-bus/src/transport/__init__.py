"""M11 MCP Bus - Transport 传输层.

提供统一的传输层抽象，支持多种传输方式：
- HTTP：请求-响应模式，适用于无状态服务
- SSE：长连接模式，支持服务器推送
- stdio：子进程管道通信，适用于本地服务

所有传输实现继承自 BaseTransport，提供一致的接口。
使用 TransportFactory 根据配置创建传输实例。

使用方式:
    from src.transport import create_transport, BaseTransport

    # 创建 HTTP 传输
    transport = create_transport("http", {"endpoint": "http://localhost:8000/mcp"})

    # 使用工厂
    from src.transport import TransportFactory
    factory = TransportFactory()
    transport = factory.create_transport("http", {"endpoint": "..."})

架构定位:
    Transport 层位于 Protocol 层之上、Services 层之下，
    负责具体的网络/进程通信，将 Protocol 层的消息对象
    传递到远端并接收响应。
"""

from .base import (
    BaseTransport,
    ConnectCallback,
    DisconnectCallback,
    ErrorCallback,
    MessageCallback,
    TransportState,
)
from .factory import (
    SUPPORTED_TRANSPORTS,
    TransportFactory,
    create_transport,
    get_transport_factory,
)
from .http_transport import HttpTransport
from .sse_transport import SseTransport
from .stdio_transport import StdioTransport

__all__ = [
    # 基类与状态
    "BaseTransport",
    "TransportState",
    # 回调类型
    "MessageCallback",
    "ConnectCallback",
    "DisconnectCallback",
    "ErrorCallback",
    # 具体实现
    "HttpTransport",
    "SseTransport",
    "StdioTransport",
    # 工厂
    "TransportFactory",
    "get_transport_factory",
    "create_transport",
    "SUPPORTED_TRANSPORTS",
]
