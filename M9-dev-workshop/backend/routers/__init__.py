"""
云汐 M9 开发者工坊 - API 路由包
统一导出所有路由
"""

from .vscode import router as vscode_router
from .workspace import router as workspace_router
from .mcp import router as mcp_router
from .dashboard import router as dashboard_router

__all__ = [
    "vscode_router",
    "workspace_router",
    "mcp_router",
    "dashboard_router",
]
