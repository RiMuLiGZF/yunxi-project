from __future__ import annotations

"""【DEPRECATED】MCP 桥接层已迁移.

本模块已迁移至 :mod:`skill_cluster.extensions.mcp.bridge`，
请使用 ``from skill_cluster.extensions.mcp import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.mcp_bridge 已迁移至 skill_cluster.extensions.mcp.bridge，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.extensions.mcp.bridge import MCPClientBridge, MCPServerBridge

__all__ = ["MCPServerBridge", "MCPClientBridge"]
