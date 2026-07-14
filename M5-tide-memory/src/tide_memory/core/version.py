"""
统一版本获取模块

提供跨模块复用的版本号获取能力。
从 shared.version 导入系统版本，回退到 tide_memory.__version__。
"""

from __future__ import annotations

from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# 模块级缓存
_cached_version: Optional[str] = None


def get_module_version() -> str:
    """
    获取模块版本号

    优先从 shared.version 导入，导入失败则回退到 tide_memory.__version__，
    最终回退到硬编码默认值。

    Returns:
        版本号字符串
    """
    global _cached_version
    if _cached_version is not None:
        return _cached_version

    # 优先从 shared.version 导入
    try:
        from pathlib import Path
        current = Path(__file__).resolve()
        for _ in range(10):
            current = current.parent
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                from shared.version import SYSTEM_VERSION
                _cached_version = SYSTEM_VERSION
                return _cached_version
    except Exception:
        pass

    # 回退到本模块的 __version__
    try:
        from tide_memory import __version__
        _cached_version = __version__
    except Exception:
        _cached_version = "0.5.2"

    return _cached_version
# vim: set et ts=4 sw=4: