"""
voice_preset_manager 模块（已归档）

.. deprecated:: 1.3.0
   本模块已在 shared 库瘦身第一步中归档至 shared._deprecated。
   模块已迁移至新路径，具体请查看 shared/_deprecated/voice_preset_manager.py。

   请尽快更新 import 路径到对应的新模块位置。

归档时间: 2026-07-19
"""

import warnings as _warnings

_warnings.warn(
    f"模块 shared.voice_preset_manager 已归档至 shared._deprecated，"
    f"请迁移到新的 import 路径。"
    f"旧路径将在 v2.0.0 中彻底移除。",
    DeprecationWarning,
    stacklevel=2,
)

# 从归档位置 re-export 所有内容（保持向后兼容）
from shared._deprecated.voice_preset_manager import *  # noqa: F401,F403
try:
    from shared._deprecated.voice_preset_manager import __all__ as _deprecated_all  # noqa: F401
    __all__ = _deprecated_all
except ImportError:
    pass
