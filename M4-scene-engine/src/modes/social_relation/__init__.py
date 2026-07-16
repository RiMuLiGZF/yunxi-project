"""人际关系模式.

社交技巧、关系维护、沟通提升，经营美好人际关系。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.social_relation.mode import SocialRelationMode

__all__ = ["SocialRelationMode"]
