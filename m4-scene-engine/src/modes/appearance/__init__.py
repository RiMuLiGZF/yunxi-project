"""形象工坊模式.

穿搭建议、形象设计、风格探索，打造个人独特形象。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class AppearanceMode(BaseMode):
    """形象工坊模式类.

    提供穿搭建议、形象设计、风格探索、
    美妆护肤等个人形象相关功能。
    """

    mode_id = "appearance"
    mode_name = "形象工坊"
    mode_description = "穿搭建议、形象设计、风格探索，打造个人独特形象"
    icon = "👗"
    category = "appearance"
    priority = 8
    is_enabled = True
