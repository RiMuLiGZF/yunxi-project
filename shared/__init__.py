"""
云汐项目共享模块

包含跨模块复用的通用工具与客户端。
"""

from .a2a_client import A2AClient, A2AError, A2AConnectionError, A2AResponseError

__all__ = [
    "A2AClient",
    "A2AError",
    "A2AConnectionError",
    "A2AResponseError",
]
