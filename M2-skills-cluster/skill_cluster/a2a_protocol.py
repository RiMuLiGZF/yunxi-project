from __future__ import annotations

"""【DEPRECATED】A2A 协议数据模型已迁移.

本模块已迁移至 :mod:`skill_cluster.models.a2a`，
请使用 ``from skill_cluster.models.a2a import ...`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.a2a_protocol 已迁移至 skill_cluster.models.a2a，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.models.a2a import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)

__all__ = [
    "A2AAgentCard",
    "A2AArtifact",
    "A2AMessage",
    "A2APart",
    "A2ATask",
]
