from __future__ import annotations
"""[DEPRECATED] 已迁移至 skill_cluster.security.code_exec.renderer.

本文件为向后兼容存根，将从新路径导入并发出废弃警告。
请更新为: from skill_cluster.security.code_exec.renderer import ...
"""

import warnings

warnings.warn(
    "skill_cluster.result_renderer 已废弃，请使用 skill_cluster.security.code_exec.renderer",
    DeprecationWarning,
    stacklevel=2,
)

from skill_cluster.security.code_exec.renderer import (  # noqa: F401
    ChartRenderer,
    ErrorRenderer,
    RenderedOutput,
    ResultRenderer,
    TableRenderer,
    TextRenderer,
)
