"""生活管理模式.

日程安排、待办事项、习惯养成，管理生活方方面面。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.life_management.mode import LifeManagementMode

__all__ = ["LifeManagementMode"]
