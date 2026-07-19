from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.security.ast_scanner.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.security.ast_scanner import ...
"""

import warnings

warnings.warn(
    "skill_cluster.ast_scanner 已废弃，请使用 skill_cluster.security.ast_scanner",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.security.ast_scanner import (  # noqa: F401
    ASTSecurityScanner,
    ScanResult,
    SecurityFinding,
    Severity,
)
