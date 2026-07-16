"""工作开发模式.

编程开发、代码编写、项目管理等工作场景。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层
    - repository.py: 数据访问层
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.work_dev.mode import WorkDevMode

__all__ = ["WorkDevMode"]
