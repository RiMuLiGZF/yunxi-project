"""M2 技能集群 - MCP 扩展.

Model Context Protocol 桥接与传输层。
"""

from __future__ import annotations

from skill_cluster.extensions.mcp.bridge import MCPClientBridge, MCPServerBridge
from skill_cluster.extensions.mcp.transport import (
    MCPNotification,
    MCPRequest,
    MCPResponse,
    MCPTransport,
    MCPTransportError,
)

__all__ = [
    "MCPTransport",
    "MCPRequest",
    "MCPResponse",
    "MCPNotification",
    "MCPTransportError",
    "MCPServerBridge",
    "MCPClientBridge",
]
