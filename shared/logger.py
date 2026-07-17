"""
统一日志工具（向后兼容入口）

.. deprecated:: 1.0.0
   模块已迁移至 `shared.core.observability`。
   旧路径 `shared.logger` 将在未来版本中移除，请尽快更新 import。

推荐用法：
    from shared.core.observability import get_logger

说明：
    本文件为向后兼容层，自动转发到新的统一日志系统。
    所有旧代码的 ``from shared.logger import get_logger`` 仍然可用。
"""

import warnings as _warnings

_warnings.warn(
    f"模块 {__name__} 已迁移至 shared.core.observability。"
    f"请更新 import 路径为 'from shared.core.observability import get_logger'。"
    f"旧路径将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

# 优先从 observability 导入（新实现），回退到 core.logger
try:
    from shared.core.observability import get_logger
    from shared.core.observability import (
        UnifiedLogger,
        set_log_context,
        clear_log_context,
        init_module_logger,
        mask_sensitive_data,
    )
    __all__ = [
        "get_logger",
        "UnifiedLogger",
        "set_log_context",
        "clear_log_context",
        "init_module_logger",
        "mask_sensitive_data",
    ]
except ImportError:
    from shared.core.logger import get_logger  # noqa: F401
    __all__ = ["get_logger"]
