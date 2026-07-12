"""生活管理模式.

日程安排、待办事项、习惯养成，管理生活方方面面。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class LifeManagementMode(BaseMode):
    """生活管理模式类.

    提供日程管理、待办事项、习惯养成、
    生活记录等个人生活管理功能。
    """

    mode_id = "life_management"
    mode_name = "生活管理"
    mode_description = "日程安排、待办事项、习惯养成，管理生活方方面面"
    icon = "🏠"
    category = "life"
    priority = 5
    is_enabled = True
