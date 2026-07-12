"""本地数据管理子包.

包含本地数据管理器、同步客户端和冲突解决器。
"""

from __future__ import annotations

from edge_cloud_kernel.local_data.conflict_resolver import ConflictResolver
from edge_cloud_kernel.local_data.local_data_manager import LocalDataManager
from edge_cloud_kernel.local_data.sync_client import SyncClient

__all__ = [
    "LocalDataManager",
    "SyncClient",
    "ConflictResolver",
]
