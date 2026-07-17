from __future__ import annotations

"""【DEPRECATED】Function Schema 生成器已迁移.

本模块已迁移至 :mod:`skill_cluster.core.function_schema`，
请使用 ``from skill_cluster.core.function_schema import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.function_schema 已迁移至 skill_cluster.core.function_schema，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.core.function_schema import (
    ActionSignature,
    FunctionParameter,
    FunctionSchema,
    SkillSchemaRegistry,
    build_signatures_from_function,
)

__all__ = [
    "SkillSchemaRegistry",
    "FunctionSchema",
    "FunctionParameter",
    "ActionSignature",
    "build_signatures_from_function",
]
