from __future__ import annotations

"""【DEPRECATED】M8 鉴权中间件已迁移.

本模块已迁移至 :mod:`skill_cluster.api.middleware.m8_auth`，
请使用 ``from skill_cluster.api.middleware.m8_auth import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.m8_auth_middleware 已迁移至 skill_cluster.api.middleware.m8_auth，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.api.middleware.m8_auth import (
    M8TokenAuthMiddleware,
    WHITE_LIST_PATHS,
    check_production_requirements,
    get_admin_token_from_env,
)

__all__ = [
    "M8TokenAuthMiddleware",
    "get_admin_token_from_env",
    "check_production_requirements",
    "WHITE_LIST_PATHS",
]
