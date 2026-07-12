"""情绪陪伴模式.

情绪疏导、心理支持、温暖陪伴，守护心理健康。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class EmotionComfortMode(BaseMode):
    """情绪陪伴模式类.

    提供情绪疏导、心理支持、温暖陪伴、
    心理健康建议等情绪相关功能。
    """

    mode_id = "emotion_comfort"
    mode_name = "情绪陪伴"
    mode_description = "情绪疏导、心理支持、温暖陪伴，守护心理健康"
    icon = "💗"
    category = "emotion"
    priority = 7
    is_enabled = True
