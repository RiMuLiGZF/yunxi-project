from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.security.sandbox.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.security.sandbox import ...
"""

import warnings

warnings.warn(
    "skill_cluster.sandbox 已废弃，请使用 skill_cluster.security.sandbox",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.security.sandbox import (  # noqa: F401
    SandboxConfig,
    SandboxExecutor,
    SandboxMiddleware,
    SandboxPolicy,
    create_sandbox_middleware,
)
