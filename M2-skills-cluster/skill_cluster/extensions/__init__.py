"""M2 技能集群 - 扩展层.

提供 A2A 协议、MCP 桥接、插件加载、语音润色等扩展能力。
"""

from __future__ import annotations

from skill_cluster.extensions.a2a import (
    A2AAgentCard,
    A2AArtifact,
    A2ABus,
    A2AMessage,
    A2APart,
    A2ATask,
)
from skill_cluster.extensions.mcp import (
    MCPClientBridge,
    MCPNotification,
    MCPRequest,
    MCPResponse,
    MCPServerBridge,
    MCPTransport,
    MCPTransportError,
)
from skill_cluster.extensions.plugins import PluginInfo, PluginLoadError, PluginLoader
from skill_cluster.extensions.voice_polish import (
    VoicePolishConfig,
    VoicePolisher,
)

__all__ = [
    # A2A
    "A2ABus",
    "A2AAgentCard",
    "A2AArtifact",
    "A2AMessage",
    "A2APart",
    "A2ATask",
    # MCP
    "MCPTransport",
    "MCPRequest",
    "MCPResponse",
    "MCPNotification",
    "MCPTransportError",
    "MCPServerBridge",
    "MCPClientBridge",
    # 插件
    "PluginLoader",
    "PluginInfo",
    "PluginLoadError",
    # 语音润色
    "VoicePolisher",
    "VoicePolishConfig",
]
