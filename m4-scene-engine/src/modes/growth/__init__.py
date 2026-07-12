"""成长中心模式.

记录成长轨迹，解锁成就天赋，见证每一步进步。
作为 M5 成长系统的业务壳层，封装 M5 API 并提供场景联动。

模块结构:
    - mode.py: 模式类（继承 BaseMode）
    - router.py: FastAPI 路由
    - service.py: 业务逻辑层（调用 M5 API，封装业务逻辑）
    - m5_client.py: M5 成长系统客户端（调用 M5 的 /api/v1/growth/*）
    - models.py: Pydantic 数据模型
"""

from __future__ import annotations

from src.modes.growth.mode import GrowthMode

__all__ = ["GrowthMode"]
