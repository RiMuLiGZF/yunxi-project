"""
向后兼容存根：monitor

此文件已迁移至 routers.ops.monitor
请使用新的导入路径：from routers.ops.monitor import router
"""

import warnings

warnings.warn(
    "routers.monitor is deprecated, use routers.ops.monitor instead",
    DeprecationWarning,
    stacklevel=2
)

from .ops.monitor import router as monitor_router  # noqa: E402, F401
from .ops.monitor import router  # noqa: E402, F401
from .ops.monitor import _get_system_metrics  # noqa: E402, F401
