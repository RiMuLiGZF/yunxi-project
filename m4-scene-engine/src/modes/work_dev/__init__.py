"""工作开发模式.

编程开发、代码编写、项目管理等工作场景。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class WorkDevMode(BaseMode):
    """工作开发模式类.

    提供编程开发辅助、代码生成、项目管理、
    工作流优化等工作相关的功能。
    """

    mode_id = "work_dev"
    mode_name = "工作开发"
    mode_description = "编程开发、代码编写、项目调试，提升工作效率"
    icon = "💻"
    category = "work"
    priority = 2
    is_enabled = True
