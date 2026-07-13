"""L1 浅水层 - 短期记忆（SQLite持久化）"""

from __future__ import annotations

from ..core.models import MemoryLayer
from .base import BaseSQLLayer


class ShallowLayer(BaseSQLLayer):
    """
    L1 浅水层 - 短期记忆
    - 中等容量
    - 保留时间：小时~天
    - SQLite 存储
    """

    _layer_enum = MemoryLayer.L1_SHALLOW

    def __init__(self, config: dict = None):
        config = config or {}
        # L1 默认配置
        config.setdefault("max_items", 1000)
        config.setdefault("retention_days", 1)
        config.setdefault("access_priority", 7)
        config.setdefault("db_path", "./data/memory/l1_shallow.db")
        super().__init__(config)
# vim: set et ts=4 sw=4:
