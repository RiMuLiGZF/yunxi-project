"""
M6 硬件外设 - 实时推送模块
SSE (Server-Sent Events) 实时数据推送
"""

from .sse_manager import SSEManager, get_sse_manager

__all__ = ["SSEManager", "get_sse_manager"]
