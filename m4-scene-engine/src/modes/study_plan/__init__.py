"""学业规划模式.

学习目标、知识笔记、进度追踪，打造高效学习系统。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.study_plan.mode import StudyPlanMode

__all__ = ["StudyPlanMode"]
