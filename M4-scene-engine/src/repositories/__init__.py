"""仓储模块.

统一导出仓储基类和各业务模式的仓储类。

使用方式:
    from src.repositories import BaseRepository
"""

from __future__ import annotations

from src.repositories.base_repository import BaseRepository


__all__ = [
    "BaseRepository",
]
