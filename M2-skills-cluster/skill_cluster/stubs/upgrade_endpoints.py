from __future__ import annotations

"""【DEPRECATED】升级管理接口已迁移.

本模块已迁移至 :mod:`skill_cluster.api.upgrade`，
请使用 ``from skill_cluster.api.upgrade import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.upgrade_endpoints 已迁移至 skill_cluster.api.upgrade，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.api.upgrade import (
    CodeSnapshotData,
    UpgradeApplyRequest,
    UpgradeManager,
    UpgradePreviewRequest,
    UpgradeTaskResponse,
    register_upgrade_routes,
)

__all__ = [
    "UpgradeManager",
    "UpgradePreviewRequest",
    "UpgradeApplyRequest",
    "UpgradeTaskResponse",
    "CodeSnapshotData",
    "register_upgrade_routes",
]
