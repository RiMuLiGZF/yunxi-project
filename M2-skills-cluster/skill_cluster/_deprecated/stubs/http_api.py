from __future__ import annotations

"""【DEPRECATED】HTTP API 已迁移.

本模块已迁移至 :mod:`skill_cluster.api.http`，
请使用 ``from skill_cluster.api.http import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.http_api 已迁移至 skill_cluster.api.http，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.api.http import (
    HealthResponse,
    InvokeRequest,
    SearchResponse,
    SkillInfo,
    create_http_app,
    manifest_to_skill_info,
    result_to_dict,
)

# 向后兼容：create_app 是 create_http_app 的别名
create_app = create_http_app

__all__ = [
    "create_app",
    "create_http_app",
    "InvokeRequest",
    "SkillInfo",
    "SearchResponse",
    "HealthResponse",
    "manifest_to_skill_info",
    "result_to_dict",
]
