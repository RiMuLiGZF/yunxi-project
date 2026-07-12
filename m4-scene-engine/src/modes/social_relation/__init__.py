"""人际关系模式.

社交技巧、关系维护、沟通提升，经营美好人际关系。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class SocialRelationMode(BaseMode):
    """人际关系模式类.

    提供社交技巧建议、关系维护指导、
    沟通能力提升等人际关系相关功能。
    """

    mode_id = "social_relation"
    mode_name = "人际关系"
    mode_description = "社交技巧、关系维护、沟通提升，经营美好人际关系"
    icon = "👥"
    category = "social"
    priority = 6
    is_enabled = True
