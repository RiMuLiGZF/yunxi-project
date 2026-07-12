"""成长中心模式.

记录成长轨迹，解锁成就天赋，追踪学习和进步。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class GrowthMode(BaseMode):
    """成长中心模式类.

    记录用户的成长轨迹、成就系统、天赋树等功能，
    帮助用户可视化自己的进步和成长。
    """

    mode_id = "growth"
    mode_name = "成长中心"
    mode_description = "记录成长轨迹，解锁成就天赋，见证每一步进步"
    icon = "🌱"
    category = "growth"
    priority = 1
    is_enabled = True
