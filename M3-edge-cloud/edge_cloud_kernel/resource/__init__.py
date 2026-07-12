"""资源管理子包.

包含显存监控和缓存管理。
"""

from __future__ import annotations

from edge_cloud_kernel.resource.cache_manager import CacheManager
from edge_cloud_kernel.resource.vram_monitor import VRAMMonitor

__all__ = [
    "VRAMMonitor",
    "CacheManager",
]
