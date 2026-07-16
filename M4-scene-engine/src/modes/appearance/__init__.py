"""形象工坊模式.

穿搭建议、形象设计、风格探索，打造个人独特形象。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.appearance.mode import AppearanceMode

__all__ = ["AppearanceMode"]
