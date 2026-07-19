"""
向后兼容存根：backup_scheduler

此文件已迁移至 routers.data.backup_scheduler
请使用新的导入路径：from routers.data.backup_scheduler import router
"""

import warnings

warnings.warn(
    "routers.backup_scheduler is deprecated, use routers.data.backup_scheduler instead",
    DeprecationWarning,
    stacklevel=2
)

from .data.backup_scheduler import router as backup_scheduler_router  # noqa: E402, F401
from .data.backup_scheduler import router  # noqa: E402, F401
