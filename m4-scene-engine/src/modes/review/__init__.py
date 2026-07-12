"""复盘总结模式.

每日复盘、周总结、目标回顾，沉淀经验。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class ReviewMode(BaseMode):
    """复盘总结模式类.

    提供每日复盘、周总结、月度回顾、目标管理等功能，
    帮助用户沉淀经验、持续改进。
    """

    mode_id = "review"
    mode_name = "复盘总结"
    mode_description = "每日复盘、周总结、目标回顾，沉淀经验持续成长"
    icon = "📝"
    category = "growth"
    priority = 3
    is_enabled = True
