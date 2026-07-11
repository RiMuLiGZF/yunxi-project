"""M11 MCP Bus - SDK 客户端模块.

提供 M11 总线的 Python 客户端 SDK，供其他模块（如 M7）
方便地调用总线上的 MCP 工具。
"""

from .mcp_bus_client import McpBusClient

__all__ = [
    "McpBusClient",
]
