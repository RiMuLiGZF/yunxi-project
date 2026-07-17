"""
shared.middleware（向后兼容存根包）

.. deprecated:: 1.0.0
   包已迁移至 `shared.core.middleware`。
   旧路径 `shared.middleware` 将在未来版本中移除，请尽快更新 import。

推荐用法：
    from shared.core.middleware import ...
"""

import warnings as _warnings

_warnings.warn(
    "包 shared.middleware 已弃用，已迁移至 shared.core.middleware。"
    "请更新 import 路径为 'from shared.core.middleware import ...'。"
    "旧路径将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

# 从新路径 re-export 所有内容
from shared.core.middleware import *  # noqa: F401,F403
try:
    from shared.core.middleware import __all__ as _new_all  # noqa: F401
    __all__ = _new_all
except ImportError:
    pass
