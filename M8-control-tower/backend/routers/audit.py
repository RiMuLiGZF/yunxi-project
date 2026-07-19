"""
向后兼容存根：audit

此文件已迁移至 routers.security.audit
请使用新的导入路径：from routers.security.audit import router
"""

import warnings

warnings.warn(
    "routers.audit is deprecated, use routers.security.audit instead",
    DeprecationWarning,
    stacklevel=2
)

from .security.audit import router as audit_router  # noqa: E402, F401
from .security.audit import router  # noqa: E402, F401
