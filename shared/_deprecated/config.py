"""
全局配置模块（向后兼容存根）

.. deprecated:: 1.0.0
   模块已迁移至 `shared.core.config`。
   旧路径 `shared.config` 将在未来版本中移除，请尽快更新 import。

推荐用法：
    from shared.core.config import ...
"""

import warnings as _warnings

_warnings.warn(
    f"模块 {__name__} 已弃用，已迁移至 shared.core.config。"
    f"请更新 import 路径为 'from shared.core.config import ...'。"
    f"旧路径将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

# 从新路径 re-export 所有内容
from shared.core.config import *  # noqa: F401,F403
try:
    from shared.core.config import __all__ as _new_all  # noqa: F401
    __all__ = _new_all
except ImportError:
    pass
