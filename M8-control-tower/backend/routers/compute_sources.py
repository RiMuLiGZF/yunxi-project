"""
向后兼容存根：compute_sources

此文件已迁移至 routers.compute.compute_sources
请使用新的导入路径：from routers.compute.compute_sources import router
"""

import warnings

warnings.warn(
    "routers.compute_sources is deprecated, use routers.compute.compute_sources instead",
    DeprecationWarning,
    stacklevel=2
)

from .compute.compute_sources import router as compute_sources_router  # noqa: E402, F401
from .compute.compute_sources import router  # noqa: E402, F401
