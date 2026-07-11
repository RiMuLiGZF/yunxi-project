"""MCP 工具管理路由.

提供 MCP 工具列表查询、详情获取、工具调用，以及场景 MCP 工具绑定管理接口。
MCP 服务不可用时自动降级，返回友好错误信息。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request

try:
    from src.models import (
        SCENE_DEFINITIONS,
        McpToolCallRequest,
        SceneMcpToolsUpdateRequest,
        make_response,
    )
    from src.services.mcp_client import get_mcp_client
except ImportError:
    from models import (  # type: ignore
        SCENE_DEFINITIONS,
        McpToolCallRequest,
        SceneMcpToolsUpdateRequest,
        make_response,
    )
    from services.mcp_client import get_mcp_client  # type: ignore


router = APIRouter(prefix="/api/v1", tags=["MCP 工具"])


# ---------------------------------------------------------------------------
# 场景 MCP 工具绑定存储（内存）
# ---------------------------------------------------------------------------

#: 场景 MCP 工具绑定配置: {scene_id: [tool_config, ...]}
_scene_mcp_tools: dict[str, list[dict[str, Any]]] = {}


def _init_scene_mcp_tools() -> None:
    """初始化场景 MCP 工具绑定配置.

    从场景定义中读取默认的 mcp_tools 配置。
    """
    global _scene_mcp_tools
    for scene_id, scene_def in SCENE_DEFINITIONS.items():
        default_tools = scene_def.get("mcp_tools", [])
        _scene_mcp_tools[scene_id] = [
            {
                "name": t.get("name", ""),
                "params": t.get("params", {}),
                "trigger": t.get("trigger", "manual"),
                "required": t.get("required", False),
            }
            for t in default_tools
        ]


_init_scene_mcp_tools()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_mcp_client(request: Request):
    """从 request state 获取 MCP 客户端，没有则使用全局单例."""
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None:
        mcp_client = get_mcp_client()
    return mcp_client


# ---------------------------------------------------------------------------
# MCP 工具 - 列表（透传 M9）
# ---------------------------------------------------------------------------

@router.get("/mcp/tools", summary="获取可用 MCP 工具列表")
async def list_mcp_tools(
    request: Request,
    category: str = Query("", description="工具分类筛选（可选）"),
):
    """获取可用的 MCP 工具列表（透传 M9 MCP 服务）.

    查询参数:
        category: 工具分类筛选（可选）
    """
    mcp_client = _get_mcp_client(request)

    if not mcp_client.enabled:
        return make_response(
            code=50301,
            message="MCP 服务已禁用",
            data={"tools": [], "enabled": False},
        )

    tools = mcp_client.list_tools(category=category or None)

    # 服务不可用时返回降级信息
    if not tools and not mcp_client.service_available:
        return make_response(
            code=50302,
            message="MCP 服务不可用（已降级）",
            data={
                "tools": [],
                "enabled": True,
                "available": False,
                "base_url": mcp_client.base_url,
            },
        )

    return make_response(data={
        "tools": tools,
        "total": len(tools),
        "enabled": True,
        "available": mcp_client.service_available,
        "base_url": mcp_client.base_url,
    })


# ---------------------------------------------------------------------------
# MCP 工具 - 详情
# ---------------------------------------------------------------------------

@router.get("/mcp/tools/{tool_name}", summary="获取 MCP 工具详情")
async def get_mcp_tool(
    request: Request,
    tool_name: str = Path(..., description="工具名称"),
):
    """获取指定 MCP 工具的详细信息（透传 M9 MCP 服务）.

    路径参数:
        tool_name: 工具名称
    """
    mcp_client = _get_mcp_client(request)

    if not mcp_client.enabled:
        return make_response(
            code=50301,
            message="MCP 服务已禁用",
            data={"name": tool_name, "enabled": False},
        )

    result = mcp_client.get_tool(tool_name)

    if not result.get("success", False):
        return make_response(
            code=50303,
            message=result.get("error", "获取工具详情失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# MCP 工具 - 调用
# ---------------------------------------------------------------------------

@router.post("/mcp/tools/{tool_name}/call", summary="调用 MCP 工具")
async def call_mcp_tool(
    request: Request,
    tool_name: str = Path(..., description="工具名称"),
    body: McpToolCallRequest = None,
):
    """调用指定的 MCP 工具（透传 M9 MCP 服务）.

    路径参数:
        tool_name: 工具名称
    请求体:
        arguments: 工具调用参数字典
    """
    mcp_client = _get_mcp_client(request)

    if not mcp_client.enabled:
        return make_response(
            code=50301,
            message="MCP 服务已禁用",
            data={"tool_name": tool_name, "enabled": False},
        )

    arguments = body.arguments if body else {}

    result = mcp_client.call_tool(
        tool_name=tool_name,
        arguments=arguments,
    )

    if not result.get("success", False):
        return make_response(
            code=50304,
            message=result.get("error", "工具调用失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 场景 MCP 工具绑定 - 获取
# ---------------------------------------------------------------------------

@router.get("/scene/{scene_id}/tools", summary="获取场景绑定的 MCP 工具")
async def get_scene_mcp_tools(
    request: Request,
    scene_id: str = Path(..., description="场景ID"),
):
    """获取指定场景绑定的 MCP 工具列表.

    路径参数:
        scene_id: 场景ID
    """
    global _scene_mcp_tools

    # 验证场景
    if scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    tools = _scene_mcp_tools.get(scene_id, [])

    return make_response(data={
        "scene_id": scene_id,
        "mcp_tools": tools,
        "total": len(tools),
    })


# ---------------------------------------------------------------------------
# 场景 MCP 工具绑定 - 更新
# ---------------------------------------------------------------------------

@router.post("/scene/{scene_id}/tools", summary="为场景绑定 MCP 工具")
async def update_scene_mcp_tools(
    request: Request,
    scene_id: str = Path(..., description="场景ID"),
    body: SceneMcpToolsUpdateRequest = None,
):
    """为指定场景绑定 MCP 工具（全量更新）.

    路径参数:
        scene_id: 场景ID
    请求体:
        mcp_tools: MCP 工具配置列表
    """
    global _scene_mcp_tools

    # 验证场景
    if scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    if body is None:
        return make_response(
            code=40001,
            message="请求体不能为空",
            data={},
        )

    # 验证并格式化工具配置
    formatted_tools = []
    for tool_cfg in body.mcp_tools:
        # 验证 trigger 取值
        trigger = tool_cfg.trigger
        if trigger not in ("on_enter", "on_leave", "manual"):
            return make_response(
                code=40002,
                message=f"无效的触发时机: {trigger}，必须是 on_enter / on_leave / manual",
                data={},
            )

        formatted_tools.append({
            "name": tool_cfg.name,
            "params": tool_cfg.params or {},
            "trigger": trigger,
            "required": tool_cfg.required,
        })

    # 更新绑定
    _scene_mcp_tools[scene_id] = formatted_tools

    # 同步更新场景定义中的 mcp_tools（影响切换钩子）
    if scene_id in SCENE_DEFINITIONS:
        SCENE_DEFINITIONS[scene_id]["mcp_tools"] = formatted_tools

    return make_response(data={
        "scene_id": scene_id,
        "mcp_tools": formatted_tools,
        "total": len(formatted_tools),
        "success": True,
    })


# ---------------------------------------------------------------------------
# MCP 服务健康检查
# ---------------------------------------------------------------------------

@router.get("/mcp/health", summary="MCP 服务健康检查")
async def mcp_health_check(request: Request):
    """检查 M9 MCP 服务是否可用."""
    mcp_client = _get_mcp_client(request)

    if not mcp_client.enabled:
        return make_response(data={
            "enabled": False,
            "available": False,
            "base_url": mcp_client.base_url,
            "status": "disabled",
        })

    available = mcp_client.health_check()

    return make_response(data={
        "enabled": True,
        "available": available,
        "base_url": mcp_client.base_url,
        "status": "available" if available else "unavailable",
    })
