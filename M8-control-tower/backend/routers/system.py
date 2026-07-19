"""
向后兼容存根：system

此文件已迁移至 routers.core.system
请使用新的导入路径：from routers.core.system import router, get_module_actions, get_system_actions
"""

import warnings

warnings.warn(
    "routers.system is deprecated, use routers.core.system instead",
    DeprecationWarning,
    stacklevel=2
)

from .core.system import router as system_router  # noqa: E402, F401
from .core.system import router  # noqa: E402, F401
from .core.system import get_module_actions, get_system_actions  # noqa: E402, F401
