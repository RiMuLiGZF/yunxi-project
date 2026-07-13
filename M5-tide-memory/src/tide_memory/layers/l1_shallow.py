"""L1 浅水层 - 短期记忆（SQLite持久化）"""

from __future__ import annotations

from ..core.models import MemoryLayer
from ..common.constants import (
    L1_MAX_ITEMS,
    L1_RETENTION_DAYS,
    L1_ACCESS_PRIORITY,
    DEFAULT_L1_DB_PATH,
)
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
        config.setdefault("max_items", L1_MAX_ITEMS)
        config.setdefault("retention_days", L1_RETENTION_DAYS)
        config.setdefault("access_priority", L1_ACCESS_PRIORITY)
        config.setdefault("db_path", DEFAULT_L1_DB_PATH)
        super().__init__(config)
# vim: set et ts=4 sw=4:
