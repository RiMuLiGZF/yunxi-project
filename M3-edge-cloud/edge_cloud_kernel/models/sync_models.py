"""同步模型（兼容层）.

所有模型已迁移至 edge_cloud_kernel.models.sync，
此文件保留向后兼容的 import 别名。

.. deprecated:: 2.1.0
   请使用 edge_cloud_kernel.models.sync 替代。
"""

from __future__ import annotations

from edge_cloud_kernel.models.sync import (
    SessionState,
    SyncItem,
    SyncOperation,
    SyncResult,
    SyncStatus,
)

__all__ = [
    "SyncOperation",
    "SyncItem",
    "SyncStatus",
    "SyncResult",
    "SessionState",
]
