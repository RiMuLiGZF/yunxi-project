"""M11 MCP Bus - MCP 协议端点路由.

提供标准的 MCP JSON-RPC 2.0 端点，以及 REST 风格的工具接口。
聚合所有已注册 MCP 服务器的工具，统一对外暴露。

支持的传输方式：
- POST /mcp: 传统的 HTTP JSON-RPC 端点
- GET /mcp/sse + POST /mcp/sse/{session_id}: SSE 传输协议
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..models import McpCallRequest, McpToolListResponse, McpToolResponse
from ..services.registry import mcp_registry
from ..services.router import mcp_router
from ..services.sse_manager import sse_manager

router = APIRouter(tags=["mcp"])


# ============================================================
# MCP JSON-RPC 2.0 端点（HTTP POST）
# ============================================================

@router.post("/mcp", summary="MCP JSON-RPC 2.0 端点")
async def mcp_endpoint(request: Request) -> Dict[str, Any]:
    """MCP 协议标准端点（JSON-RPC 2.0）.

    支持的方法：
    - `initialize`: 初始化握手
    - `notifications/initialized`: 初始化完成通知
    - `tools/list`: 获取工具列表
    - `tools/call`: 调用工具
    - `resources/list`: 获取资源列表
    - `resources/read`: 读取资源内容
    - `prompts/list`: 获取提示词列表
    - `prompts/get`: 获取提示词详情
    """
    try:
        body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error")

    jsonrpc = body.get("jsonrpc")
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    # 校验 JSON-RPC 版本
    if jsonrpc != "2.0":
        return _jsonrpc_error(request_id, -32600, "Invalid Request: jsonrpc must be 2.0")

    # 处理通知（没有 id）
    is_notification = request_id is None

    # 路由到对应方法
    try:
        result = await _dispatch_method(method, params)
    except Exception as e:
        if is_notification:
            return {}
        return _jsonrpc_error(request_id, -32603, f"Internal error: {str(e)}")

    # 返回成功响应
    if is_notification:
        return {}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


async def _dispatch_method(method: str, params: Dict[str, Any]) -> Any:
    """根据方法名分发到对应处理函数.

    Args:
        method: MCP 方法名
        params: 方法参数

    Returns:
        处理结果

    Raises:
        ValueError: 方法不存在（对于通知类方法不抛异常）
    """
    # 工具相关
    if method == "initialize":
        return await _handle_initialize(params)
    elif method == "notifications/initialized":
        return None  # 通知，空处理
    elif method == "tools/list":
        return await _handle_tools_list(params)
    elif method == "tools/call":
        return await _handle_tools_call(params)
    # 资源相关
    elif method == "resources/list":
        return await _handle_resources_list(params)
    elif method == "resources/read":
        return await _handle_resources_read(params)
    # 提示词相关
    elif method == "prompts/list":
        return await _handle_prompts_list(params)
    elif method == "prompts/get":
        return await _handle_prompts_get(params)
    else:
        raise ValueError(f"Method not found: {method}")


def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    """构建 JSON-RPC 错误响应.

    Args:
        request_id: 请求 ID
        code: 错误码
        message: 错误信息

    Returns:
        JSON-RPC 错误响应
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


# ============================================================
# initialize 方法
# ============================================================

async def _handle_initialize(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 initialize 方法.

    MCP 协议初始化握手，返回服务器支持的能力。

    Args:
        params: 初始化参数

    Returns:
        初始化结果
    """
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {
                "listChanges": True,
            },
            "resources": {
                "subscribe": False,
                "listChanges": False,
            },
            "prompts": {
                "listChanges": False,
            },
        },
        "serverInfo": {
            "name": "M11 MCP Bus",
            "version": "0.2.0",
        },
    }


# ============================================================
# tools 相关方法
# ============================================================

async def _handle_tools_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tools/list 方法.

    返回所有已注册服务器的聚合工具列表。

    Args:
        params: 参数

    Returns:
        工具列表
    """
    # 获取所有工具（不分页）
    tools, total, _ = mcp_registry.get_all_tools(
        page=1,
        page_size=1000,
    )

    # 转换为 MCP 工具格式
    mcp_tools = []
    for tool in tools:
        mcp_tools.append({
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.input_schema or {
                "type": "object",
                "properties": {},
            },
        })

    return {
        "tools": mcp_tools,
    }


async def _handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tools/call 方法.

    根据工具名路由到对应服务器执行。

    Args:
        params: 调用参数，包含 name 和 arguments

    Returns:
        调用结果
    """
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if not tool_name:
        raise ValueError("缺少工具名称参数")

    # 调用路由转发
    result = mcp_router.call_tool(
        tool_name=tool_name,
        arguments=arguments,
        consumer="mcp-endpoint",
    )

    if not result["success"]:
        raise ValueError(result.get("error", "调用失败"))

    # 标准化返回格式
    call_result = result["result"]

    # 如果结果不是 MCP 标准格式，包装一下
    if isinstance(call_result, dict) and "content" in call_result:
        return call_result

    # 将结果包装为 MCP text content 格式
    import json as _json
    result_text = _json.dumps(call_result, ensure_ascii=False) if not isinstance(call_result, str) else call_result

    return {
        "content": [
            {
                "type": "text",
                "text": result_text,
            }
        ],
    }


# ============================================================
# resources 相关方法
# ============================================================

async def _handle_resources_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 resources/list 方法.

    返回可用的资源列表。
    当前为基础框架实现，返回空列表，后续可接入各 MCP 服务器的资源。

    Args:
        params: 参数

    Returns:
        资源列表
    """
    # TODO: 从各 MCP 服务器聚合 resources
    # 目前返回空列表作为占位实现
    return {
        "resources": [],
    }


async def _handle_resources_read(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 resources/read 方法.

    读取指定资源的内容。
    当前为基础框架实现，返回方法未找到错误，后续可接入各 MCP 服务器的资源读取。

    Args:
        params: 参数，包含 uri

    Returns:
        资源内容

    Raises:
        ValueError: 资源不存在或不支持
    """
    uri = params.get("uri", "")
    if not uri:
        raise ValueError("缺少资源 URI 参数")

    # TODO: 路由到对应 MCP 服务器读取资源
    # 目前为占位实现
    raise ValueError(f"资源不可用（占位实现）: {uri}")


# ============================================================
# prompts 相关方法
# ============================================================

async def _handle_prompts_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 prompts/list 方法.

    返回可用的提示词列表。
    当前为基础框架实现，返回空列表，后续可接入各 MCP 服务器的提示词。

    Args:
        params: 参数

    Returns:
        提示词列表
    """
    # TODO: 从各 MCP 服务器聚合 prompts
    # 目前返回空列表作为占位实现
    return {
        "prompts": [],
    }


async def _handle_prompts_get(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 prompts/get 方法.

    获取指定提示词的详细信息。
    当前为基础框架实现，返回方法未找到错误，后续可接入各 MCP 服务器的提示词。

    Args:
        params: 参数，包含 name 和 arguments

    Returns:
        提示词详情

    Raises:
        ValueError: 提示词不存在或不支持
    """
    prompt_name = params.get("name", "")
    if not prompt_name:
        raise ValueError("缺少提示词名称参数")

    # TODO: 路由到对应 MCP 服务器获取提示词
    # 目前为占位实现
    raise ValueError(f"提示词不可用（占位实现）: {prompt_name}")


# ============================================================
# SSE 传输端点
# ============================================================

@router.get("/mcp/sse", summary="MCP SSE 连接端点")
async def mcp_sse_endpoint() -> StreamingResponse:
    """MCP SSE 传输协议端点.

    客户端通过 GET 请求建立 SSE 长连接，
    服务端通过 SSE 推送 JSON-RPC 响应和通知。
    客户端通过 POST /mcp/sse/{session_id} 发送请求。

    消息格式：
    - 连接建立后，首条消息为 endpoint 事件，包含 session_id
    - 后续通过 message 事件推送 JSON-RPC 响应
    - 定期发送心跳注释保持连接
    """
    # 创建会话
    session = await sse_manager.create_session()
    if not session:
        raise HTTPException(
            status_code=503,
            detail="SSE 连接数已达上限，请稍后再试",
        )

    session_id = session.session_id

    async def event_generator() -> AsyncIterator[str]:
        """SSE 事件生成器.

        持续从消息队列读取消息并推送给客户端，
        同时定期发送心跳保活。
        """
        try:
            # 1. 发送 endpoint 事件（MCP SSE 规范要求）
            # 告知客户端用于发送消息的 POST 端点
            endpoint_event = sse_manager.format_sse_message(
                data=f'{{"endpoint":"/mcp/sse/{session_id}"}}',
                event="endpoint",
            )
            yield endpoint_event

            # 2. 持续推送消息
            heartbeat_interval = sse_manager._settings.sse_heartbeat_interval
            while session.connected:
                try:
                    # 等待消息，分段等待以便插入心跳
                    message = await session.get_message(timeout=heartbeat_interval)
                    if message:
                        yield sse_manager.format_sse_message(data=message, event="message")
                    else:
                        # 超时，发送心跳
                        yield sse_manager.format_heartbeat()
                except asyncio.CancelledError:
                    break
                except Exception:
                    break
        finally:
            # 清理会话
            await sse_manager.remove_session(session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/mcp/sse/{session_id}", summary="MCP SSE 消息发送端点")
async def mcp_sse_message(session_id: str, request: Request) -> Dict[str, Any]:
    """SSE 模式下客户端发送请求的端点.

    客户端通过 POST 向此端点发送 JSON-RPC 请求，
    服务端处理后通过 SSE 连接推送响应。

    Args:
        session_id: SSE 会话 ID
        request: HTTP 请求对象

    Returns:
        空响应（202 Accepted），实际响应通过 SSE 推送
    """
    # 验证会话
    session = await sse_manager.get_session(session_id)
    if not session or not session.connected:
        raise HTTPException(status_code=404, detail="SSE 会话不存在或已断开")

    # 解析请求体
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的 JSON 请求体")

    jsonrpc = body.get("jsonrpc")
    method = body.get("method")
    params = body.get("params", {})
    request_id = body.get("id")

    # 校验 JSON-RPC 版本
    if jsonrpc != "2.0":
        error_resp = _jsonrpc_error(request_id, -32600, "Invalid Request: jsonrpc must be 2.0")
        await sse_manager.send_to_session(session_id, error_resp)
        return {"accepted": True}

    is_notification = request_id is None

    # 异步处理请求并通过 SSE 推送响应
    async def _process_and_push():
        """后台处理请求并推送 SSE 响应."""
        try:
            result = await _dispatch_method(method, params)

            # 通知不需要响应
            if is_notification:
                return

            # 构建成功响应并推送
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
            await sse_manager.send_to_session(session_id, response)
        except Exception as e:
            if is_notification:
                return

            # 构建错误响应并推送
            error_resp = _jsonrpc_error(request_id, -32603, f"Internal error: {str(e)}")
            await sse_manager.send_to_session(session_id, error_resp)

    # 在后台任务中处理
    asyncio.create_task(_process_and_push())

    return {"accepted": True, "session_id": session_id}


# ============================================================
# REST 风格 API
# ============================================================

@router.get("/api/v1/tools", response_model=McpToolListResponse, summary="REST 获取工具列表")
async def rest_list_tools(
    server_id: Optional[int] = Query(None, description="按服务器过滤"),
    category: Optional[str] = Query(None, description="按分类过滤"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
) -> McpToolListResponse:
    """REST 风格获取工具列表.

    工具名格式：{server_name}.{tool_name}
    支持分页、过滤、搜索。
    """
    tools, total, categories = mcp_registry.get_all_tools(
        server_id=server_id,
        category=category,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )

    items = []
    for tool in tools:
        items.append(McpToolResponse(
            id=tool.id,
            server_id=tool.server_id,
            server_name=tool.server.name if tool.server else "",
            name=tool.name,
            description=tool.description or "",
            category=tool.category or "general",
            input_schema=tool.input_schema or {},
            cached_at=tool.cached_at,
        ))

    return McpToolListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        categories=categories,
    )


@router.post("/api/v1/tools/{tool_name}/call", summary="REST 调用工具")
async def rest_call_tool(tool_name: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """REST 风格调用工具.

    工具名格式：{server_name}.{tool_name}

    请求体为工具调用参数（JSON 对象）。
    返回执行结果和元数据。
    """
    arguments = body or {}

    result = mcp_router.call_tool(
        tool_name=tool_name,
        arguments=arguments,
        consumer="rest-api",
    )

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "工具调用失败"),
        )

    return {
        "tool_name": result["tool_name"],
        "success": result["success"],
        "result": result["result"],
        "duration_ms": result["duration_ms"],
        "call_id": result["call_id"],
        "from_cache": result.get("from_cache", False),
    }


@router.get("/api/v1/tools/{tool_name}", response_model=McpToolResponse, summary="REST 获取工具详情")
async def rest_get_tool(tool_name: str) -> McpToolResponse:
    """REST 风格获取工具详情.

    工具名格式：{server_name}.{tool_name}
    """
    result = mcp_registry.get_tool_by_name(tool_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"工具不存在: {tool_name}")

    tool, server = result
    return McpToolResponse(
        id=tool.id,
        server_id=tool.server_id,
        server_name=server.name,
        name=tool.name,
        description=tool.description or "",
        category=tool.category or "general",
        input_schema=tool.input_schema or {},
        cached_at=tool.cached_at,
    )
