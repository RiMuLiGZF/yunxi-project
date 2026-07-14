"""
云汐 M9 开发者工坊 - MCP 桥接 API
提供 MCP 工具列表查询、工具调用、连接状态等接口
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import json

# 兼容相对导入和直接运行
try:
    from ..mcp_bridge import get_mcp_registry, MCPResponse
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mcp_bridge import get_mcp_registry, MCPResponse

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP 桥接"])


# ===== 请求模型 =====

class ToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str = Field(..., min_length=1, max_length=255, description="工具名称")
    arguments: Dict[str, Any] = {}


class MCPRequestModel(BaseModel):
    """标准 MCP JSON-RPC 请求"""
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = {}
    id: Optional[str] = None


# ===== 连接状态 =====

@router.get("/status", summary="获取 MCP 服务状态")
def get_status():
    """获取 MCP 桥接服务的运行状态"""
    registry = get_mcp_registry()
    tools = registry.list_tools()
    return {
        "success": True,
        "status": "connected",
        "enabled": registry.settings.mcp_enabled,
        "tool_count": len(tools),
        "categories": sorted(set(t["category"] for t in tools)),
    }


# ===== 工具发现 =====

@router.get("/tools", summary="获取工具列表")
def list_tools(
    category: Optional[str] = None,
    enabled_only: bool = True,
):
    """获取所有已注册的 MCP 工具列表"""
    registry = get_mcp_registry()
    tools = registry.list_tools(category=category, enabled_only=enabled_only)
    return {
        "success": True,
        "count": len(tools),
        "tools": tools,
    }


@router.get("/tools/{tool_name}", summary="获取工具详情")
def get_tool(tool_name: str):
    """获取指定 MCP 工具的详细信息"""
    registry = get_mcp_registry()
    tool = registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")
    return {"success": True, "tool": tool}


# ===== 工具调用 =====

@router.post("/tools/call", summary="调用 MCP 工具")
def call_tool(req: ToolCallRequest):
    """调用指定的 MCP 工具"""
    registry = get_mcp_registry()
    response = registry.call_tool(req.tool_name, req.arguments)

    if response.error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": response.error.get("code", -1),
                "message": response.error.get("message", "未知错误"),
            }
        )

    return {
        "success": True,
        "tool": req.tool_name,
        "result": response.result,
    }


@router.post("/tools/{tool_name}/call", summary="调用指定工具")
def call_tool_by_name(tool_name: str, arguments: Dict[str, Any] = {}):
    """通过路径参数调用指定工具"""
    registry = get_mcp_registry()
    response = registry.call_tool(tool_name, arguments)

    if response.error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": response.error.get("code", -1),
                "message": response.error.get("message", "未知错误"),
            }
        )

    return {
        "success": True,
        "tool": tool_name,
        "result": response.result,
    }


# ===== 标准 MCP 协议端点 =====

@router.post("/endpoint", summary="MCP 标准协议端点")
def mcp_endpoint(req: MCPRequestModel):
    """
    标准 MCP JSON-RPC 协议端点
    支持 methods: tools/list, tools/call
    """
    registry = get_mcp_registry()
    result = registry.handle_request(req.dict())
    return result


# ===== SSE 流式响应（预留） =====

@router.get("/stream/{tool_name}", summary="流式调用工具（SSE）")
async def stream_tool_call(tool_name: str, args: Optional[str] = None):
    """
    流式调用 MCP 工具，使用 SSE 协议返回结果
    预留接口，当前返回模拟的流式进度
    """
    registry = get_mcp_registry()
    arguments = {}
    if args:
        try:
            arguments = json.loads(args)
        except json.JSONDecodeError:
            pass

    async def event_generator():
        for event in registry.stream_tool_call(tool_name, arguments):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== 工具注册管理 =====

@router.post("/tools/register", summary="注册 MCP 工具")
def register_tool(
    name: str,
    description: str = "",
    category: str = "general",
    endpoint: str = "",
    input_schema: Dict[str, Any] = {},
):
    """注册新的 MCP 工具（框架级别，实际 handler 需代码注册）"""
    registry = get_mcp_registry()
    # 检查是否已存在
    existing = registry.get_tool(name)
    if existing:
        raise HTTPException(status_code=400, detail=f"工具已存在: {name}")

    # 注意：通过 API 注册的工具没有 handler 函数，仅记录元数据
    # 如需完整功能需在代码中 register_tool 并传入 handler
    try:
        from ..models import SessionLocal, MCPTool
        from datetime import datetime
        db = SessionLocal()
        tool = MCPTool(
            name=name,
            description=description,
            endpoint=endpoint,
            category=category,
            enabled=True,
            input_schema=input_schema,
            registered_at=datetime.now(),
        )
        db.add(tool)
        db.commit()
        db.refresh(tool)
        result = tool.to_dict()
        db.close()
        return {"success": True, "message": "工具注册成功", "tool": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tools/{tool_name}", summary="注销 MCP 工具")
def unregister_tool(tool_name: str):
    """注销指定的 MCP 工具"""
    registry = get_mcp_registry()
    success = registry.unregister_tool(tool_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")
    return {"success": True, "message": f"工具 {tool_name} 已注销"}
