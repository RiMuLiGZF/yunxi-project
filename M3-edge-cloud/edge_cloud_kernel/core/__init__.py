"""核心应用层.

包含内核组件管理器和 FastAPI 应用工厂。
"""

from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.core.app_factory import create_app, get_kernel_manager

__all__ = ["KernelManager", "create_app", "get_kernel_manager"]
