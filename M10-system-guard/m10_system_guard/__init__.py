"""
M10 系统卫士模块 - 系统防卫 System Guard

云汐系统模块十：系统资源监控、进程管理、阈值防护、启动安全检查、
审计日志、硬件保护报告、沙箱任务调度等系统安全与资源管理功能。

沙盒模式优先：默认使用模拟数据，不调用真实系统 API。
"""

from __future__ import annotations

__version__ = "1.2.0"
__module_name__ = "m10-system-guard"
__description__ = "云汐系统卫士 - 系统防卫模块"

# 模块标识常量
MODULE_ID = "M10"
MODULE_NAME = "system-guard"
MODULE_FULL_NAME = "M10 系统卫士"

# 沙盒模式标记（默认开启）
SANDBOX_MODE = True

# --- 子模块导出 ---
from . import errors          # noqa: F401, E402
from . import database        # noqa: F401, E402
from . import db_models       # noqa: F401, E402
from . import repositories    # noqa: F401, E402