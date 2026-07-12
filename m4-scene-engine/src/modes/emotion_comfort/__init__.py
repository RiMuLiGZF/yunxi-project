"""情绪陪伴模式.

情绪疏导、心理支持、温暖陪伴，守护心理健康。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.emotion_comfort.mode import EmotionComfortMode

__all__ = ["EmotionComfortMode"]
