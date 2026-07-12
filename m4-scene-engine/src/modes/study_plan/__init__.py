"""学业规划模式.

学习计划、课程安排、知识管理，助力学业进步。
（占位实现，后续迁移 M8 业务逻辑）
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode


class StudyPlanMode(BaseMode):
    """学业规划模式类.

    提供学习计划制定、课程管理、知识体系构建、
    考试备考等学业相关功能。
    """

    mode_id = "study_plan"
    mode_name = "学业规划"
    mode_description = "学习计划、课程安排、知识管理，助力学业进步"
    icon = "🎓"
    category = "study"
    priority = 4
    is_enabled = True
