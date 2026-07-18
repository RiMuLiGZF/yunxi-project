"""M11 MCP Bus - 传输工厂.

根据配置创建对应的传输层实例，使用工厂模式。
支持根据传输类型（HTTP/SSE/stdio）自动创建合适的传输实例。

使用方式:
    from src.transport import TransportFactory

    factory = TransportFactory()
    transport = factory.create_transport(
        transport_type="http",
        config={"endpoint": "http://localhost:8000/mcp", "api_key": "xxx"}
    )
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseTransport
from .http_transport import HttpTransport
from .sse_transport import SseTransport
from .stdio_transport import StdioTransport


# 支持的传输类型
SUPPORTED_TRANSPORTS = {"http", "sse", "stdio"}


class TransportFactory:
    """传输工厂.

    根据配置创建对应的传输层实例。
    支持的传输类型: http, sse, stdio

    各传输类型的配置参数:

    http:
        endpoint: str - MCP 服务端点 URL
        api_key: str - API Key（可选）
        timeout: float - 超时时间（秒，可选）
        extra_headers: dict - 额外请求头（可选）

    sse:
        sse_endpoint: str - SSE 连接端点
        post_endpoint: str - 消息发送端点（可选，默认使用 sse_endpoint）
        api_key: str - API Key（可选）
        timeout: float - 超时时间（秒，可选）
        extra_headers: dict - 额外请求头（可选）

    stdio:
        command: str - 要执行的命令
        args: list - 命令参数列表（可选）
        env: dict - 额外环境变量（可选）
        cwd: str - 工作目录（可选）
        timeout: float - 请求超时时间（秒，可选）
        start_timeout: float - 启动超时时间（秒，可选）
        stop_timeout: float - 停止超时时间（秒，可选）
    """

    def __init__(self) -> None:
        """初始化传输工厂."""
        self._transports: Dict[str, type[BaseTransport]] = {
            "http": HttpTransport,
            "sse": SseTransport,
            "stdio": StdioTransport,
        }

    def register_transport(
        self, transport_type: str, transport_class: type[BaseTransport]
    ) -> None:
        """注册自定义传输类型.

        Args:
            transport_type: 传输类型标识
            transport_class: 传输类（必须继承 BaseTransport）
        """
        if not issubclass(transport_class, BaseTransport):
            raise ValueError(
                f"Transport class must inherit from BaseTransport"
            )
        self._transports[transport_type.lower()] = transport_class

    def create_transport(
        self,
        transport_type: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> BaseTransport:
        """创建传输实例.

        Args:
            transport_type: 传输类型（http/sse/stdio）
            config: 传输配置参数

        Returns:
            传输层实例

        Raises:
            ValueError: 不支持的传输类型
        """
        transport_type = transport_type.lower()
        config = config or {}

        transport_class = self._transports.get(transport_type)
        if transport_class is None:
            raise ValueError(
                f"Unsupported transport type: {transport_type}. "
                f"Supported: {', '.join(self._transports.keys())}"
            )

        return self._create_instance(transport_type, transport_class, config)

    def _create_instance(
        self,
        transport_type: str,
        transport_class: type[BaseTransport],
        config: Dict[str, Any],
    ) -> BaseTransport:
        """根据传输类型创建实例.

        各传输类型的构造参数不同，需要分别处理。

        Args:
            transport_type: 传输类型
            transport_class: 传输类
            config: 配置参数

        Returns:
            传输实例
        """
        if transport_type == "http":
            return HttpTransport(
                endpoint=config.get("endpoint", ""),
                api_key=config.get("api_key", ""),
                timeout=config.get("timeout", 30.0),
                extra_headers=config.get("extra_headers"),
            )
        elif transport_type == "sse":
            return SseTransport(
                sse_endpoint=config.get("sse_endpoint", config.get("endpoint", "")),
                post_endpoint=config.get("post_endpoint", ""),
                api_key=config.get("api_key", ""),
                timeout=config.get("timeout", 30.0),
                extra_headers=config.get("extra_headers"),
            )
        elif transport_type == "stdio":
            return StdioTransport(
                command=config.get("command", ""),
                args=config.get("args"),
                env=config.get("env"),
                cwd=config.get("cwd"),
                timeout=config.get("timeout", 30.0),
                start_timeout=config.get("start_timeout", 10.0),
                stop_timeout=config.get("stop_timeout", 5.0),
            )
        else:
            # 自定义传输类型，尝试通用构造
            try:
                return transport_class(**config)
            except TypeError as e:
                raise ValueError(
                    f"Failed to create {transport_type} transport: {e}"
                ) from e

    def get_supported_types(self) -> list[str]:
        """获取支持的传输类型列表.

        Returns:
            传输类型列表
        """
        return list(self._transports.keys())

    def is_supported(self, transport_type: str) -> bool:
        """检查传输类型是否受支持.

        Args:
            transport_type: 传输类型

        Returns:
            True 表示受支持
        """
        return transport_type.lower() in self._transports


# 全局单例
_transport_factory: Optional[TransportFactory] = None


def get_transport_factory() -> TransportFactory:
    """获取全局传输工厂单例.

    Returns:
        传输工厂实例
    """
    global _transport_factory
    if _transport_factory is None:
        _transport_factory = TransportFactory()
    return _transport_factory


def create_transport(
    transport_type: str,
    config: Optional[Dict[str, Any]] = None,
) -> BaseTransport:
    """便捷函数：创建传输实例.

    使用全局单例工厂创建传输实例。

    Args:
        transport_type: 传输类型
        config: 配置参数

    Returns:
        传输实例
    """
    return get_transport_factory().create_transport(transport_type, config)


__all__ = [
    "TransportFactory",
    "get_transport_factory",
    "create_transport",
    "SUPPORTED_TRANSPORTS",
]
