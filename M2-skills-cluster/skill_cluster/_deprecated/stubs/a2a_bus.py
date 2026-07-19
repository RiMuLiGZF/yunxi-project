from __future__ import annotations

"""【DEPRECATED】A2A 消息总线已迁移.

本模块已迁移至 :mod:`skill_cluster.extensions.a2a.bus`，
请使用 ``from skill_cluster.extensions.a2a import A2ABus`` 的新路径导入。

为保持向后兼容，本文件保留为存根，从新路径重新导出所有符号，
并在首次导入时发出 DeprecationWarning。
"""

import warnings

warnings.warn(
    "skill_cluster.a2a_bus 已迁移至 skill_cluster.extensions.a2a.bus，"
    "请更新 import 路径",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.extensions.a2a.bus import A2ABus

__all__ = ["A2ABus"]
