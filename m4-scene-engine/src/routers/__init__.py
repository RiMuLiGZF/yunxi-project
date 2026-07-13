"""路由模块.

统一导出所有 API 路由，供主应用注册使用。

使用方式:
    from src.routers import all_routers
    for router in all_routers:
        app.include_router(router)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


# ---------------------------------------------------------------------------
# 导入各模块路由
# ---------------------------------------------------------------------------
# 统一使用 src.xxx 绝对导入风格
# 注：路由模块必须在导入时立即加载，因为 all_routers 需要实例化的 router 对象
from src.routers.scene import router as scene_router
from src.routers.config_route import router as config_router
from src.routers.admin import router as admin_router
from src.routers.workspace import router as workspace_router
from src.routers.mcp_tools import router as mcp_tools_router
from src.routers.skills import router as skills_router
from src.routers.modes import router as modes_router


# ---------------------------------------------------------------------------
# 所有路由列表
# ---------------------------------------------------------------------------

#: 全部路由列表，按推荐注册顺序排列
all_routers: list["APIRouter"] = [
    scene_router,       # 场景管理
    config_router,      # 场景配置
    admin_router,       # 系统管理
    workspace_router,   # 工作空间（VS Code 等）
    mcp_tools_router,   # MCP 工具管理
    skills_router,      # 技能管理
    modes_router,       # 业务模式
]


# ---------------------------------------------------------------------------
# 按名称获取路由
# ---------------------------------------------------------------------------

#: 路由名称映射
_router_map: dict[str, "APIRouter"] = {
    "scene": scene_router,
    "config": config_router,
    "admin": admin_router,
    "workspace": workspace_router,
    "mcp_tools": mcp_tools_router,
    "skills": skills_router,
    "modes": modes_router,
}


def get_router(name: str) -> "APIRouter | None":
    """根据名称获取路由.

    Args:
        name: 路由名称 (scene/config/admin/workspace)

    Returns:
        对应的 APIRouter 实例，不存在返回 None
    """
    return _router_map.get(name)


def register_all_routers(app) -> None:
    """将所有路由注册到 FastAPI 应用.

    Args:
        app: FastAPI 应用实例
    """
    for router in all_routers:
        app.include_router(router)


__all__ = [
    "all_routers",
    "scene_router",
    "config_router",
    "admin_router",
    "workspace_router",
    "mcp_tools_router",
    "skills_router",
    "modes_router",
    "get_router",
    "register_all_routers",
]
