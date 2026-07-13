from __future__ import annotations

"""【DEPRECATED】测试管理接口已迁移.

本模块已迁移至 :mod:`skill_cluster.api.test_endpoints`，
请使用 ``from skill_cluster.api.test_endpoints import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.test_endpoints 已迁移至 skill_cluster.api.test_endpoints，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.api.test_endpoints import (
    TestManager,
    TestResultData,
    TestRunRequest,
    TestTaskResponse,
    register_test_routes,
)

__all__ = [
    "TestManager",
    "TestRunRequest",
    "TestTaskResponse",
    "TestResultData",
    "register_test_routes",
]
