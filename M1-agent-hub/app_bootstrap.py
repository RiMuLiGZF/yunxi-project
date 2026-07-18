"""
[兼容存根] app_bootstrap 已迁移至 src/core/bootstrap.py

迁移说明：
- 原模块：app_bootstrap.py（根目录）
- 新位置：src/core/bootstrap.py
- 推荐导入：from src.core.bootstrap import YunxiApplication

本文件为向后兼容存根，保留旧导入路径的可用性，
后续版本将移除，请尽快迁移到新的导入路径。
"""

from __future__ import annotations

import warnings

# 发出弃用警告
warnings.warn(
    "app_bootstrap 模块已迁移至 src.core.bootstrap，"
    "请更新导入路径为 'from src.core.bootstrap import YunxiApplication'。"
    "当前存根将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

from src.core.bootstrap import (  # noqa: F401
    YunxiApplication,
    main,
)

__all__ = ["YunxiApplication", "main"]
