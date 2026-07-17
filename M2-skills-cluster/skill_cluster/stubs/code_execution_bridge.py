from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.security.code_exec.bridge.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.security.code_exec.bridge import ...
"""

import warnings

warnings.warn(
    "skill_cluster.code_execution_bridge 已废弃，请使用 skill_cluster.security.code_exec.bridge",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.security.code_exec.bridge import (  # noqa: F401
    CodeExecutionBridge,
    ErrorType,
    ExecutionResult,
    ExecutionStatus,
    PackageInstallResult,
    ReplSessionInfo,
    SubprocessSandbox,
    classify_error,
    detect_dependencies,
    detect_language,
)
