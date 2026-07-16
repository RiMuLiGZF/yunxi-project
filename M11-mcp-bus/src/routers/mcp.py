"""M11 MCP Bus - MCP 协议端点路由.

提供标准的 MCP JSON-RPC 2.0 端点，以及 REST 风格的工具接口。
聚合所有已注册 MCP 服务器的工具，统一对外暴露。

支持的传输方式：
- POST /mcp: 传统的 HTTP JSON-RPC 端点
- GET /mcp/sse + POST /mcp/sse/{session_id}: SSE 传输协议
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from ..models import McpCallRequest, McpToolListResponse, McpToolResponse
from ..services.registry import mcp_registry
from ..services.router import mcp_router
from ..services.sse_manager import sse_manager
from ..middleware.auth import get_current_api_key, ApiKey

router = APIRouter(tags=["mcp"])

logger = logging.getLogger(__name__)

# MCP 端点是否需要鉴权（默认需要，可通过环境变量关闭用于纯内部部署）
MCP_REQUIRE_AUTH = os.getenv("MCP_REQUIRE_AUTH", "true").lower() in ("true", "1", "yes")


def _check_mcp_auth(request: Request) -> Optional[ApiKey]:
    """检查 MCP 请求鉴权.
    
    如果 MCP_REQUIRE_AUTH=false，则允许匿名访问（仅内部部署建议）。
    否则要求有效的 API Key。
    
    Returns:
        ApiKey 对象或 None（未鉴权）
    """
    if not MCP_REQUIRE_AUTH:
        # 匿名模式，返回一个虚拟的 anonymous key
        return ApiKey(
            id=0,
            name="anonymous",
            key_hash="",
            scopes=["mcp:read", "mcp:call"],
            is_active=True,
            created_at=0,
        )
    
    # 从 header 中提取 API Key（同步方式，因为 get_current_api_key 是 async）
    # 这里手动实现一次简单检查
    api_key_header = request.headers.get("x-api-key", "")
    auth_header = request.headers.get("authorization", "")
    
    token = api_key_header
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    
    if not token:
        return None
    
    # 调用注册中心验证
    from ..services.api_key_store import api_key_store
    return api_key_store.validate_key(token)


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
    
    安全：需要有效的 API Key（X-API-Key 或 Authorization: Bearer）。
    可通过 MCP_REQUIRE_AUTH=false 关闭鉴权（仅纯内部部署建议）。
    """
    # 鉴权检查
    api_key = _check_mcp_auth(request)
    if api_key is None:
        return _jsonrpc_error(
            None, -32099,
            "Unauthorized: Valid API Key required (X-API-Key header or Authorization: Bearer token)"
        )
    
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
# 内部辅助函数
# ============================================================

async def _send_mcp_request_async(
    server: Any,
    method: str,
    params: Dict[str, Any],
) -> Any:
    """向指定 MCP 服务器发送异步 JSON-RPC 请求.

    支持 http 和 stdio 两种传输类型，统一返回 result 字段内容。

    Args:
        server: MCP 服务器对象
        method: JSON-RPC 方法名
        params: 请求参数

    Returns:
        JSON-RPC 响应的 result 字段

    Raises:
        ValueError: 服务器配置错误或类型不支持
        Exception: 请求失败或响应包含错误
    """
    if server.transport_type == "http":
        if not server.endpoint:
            raise ValueError("服务器未配置端点地址")

        payload = {
            "jsonrpc": "2.0",
            "id": secrets.randbelow(100000),
            "method": method,
            "params": params,
        }
        headers = {"Content-Type": "application/json"}
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(server.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            error = data["error"]
            raise RuntimeError(
                f"JSON-RPC 错误: {error.get('message', '未知错误')} "
                f"(code: {error.get('code', -1)})"
            )
        return data.get("result")

    elif server.transport_type == "stdio":
        from ..services.stdio_manager import stdio_manager

        stdio_service = None
        for svc in stdio_manager.list_services():
            if svc.name == server.name:
                stdio_service = svc
                break

        if not stdio_service:
            raise ValueError(f"stdio 服务未运行: {server.name}")

        return await stdio_manager.send_request(
            service_id=stdio_service.service_id,
            method=method,
            params=params,
            timeout=10.0,
        )
    else:
        raise ValueError(f"不支持的传输类型: {server.transport_type}")


# ============================================================
# resources 相关方法
# ============================================================

async def _handle_resources_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 resources/list 方法.

    遍历所有已注册的在线 MCP 服务器，并发调用 resources/list，
    聚合结果并按 uri 去重后返回。

    Args:
        params: 参数

    Returns:
        资源列表
    """
    servers = mcp_registry.list_servers(status="online")
    if not servers:
        return {"resources": []}

    async def _fetch(server: Any) -> List[Dict[str, Any]]:
        try:
            result = await _send_mcp_request_async(server, "resources/list", {})
            if isinstance(result, dict):
                return result.get("resources", [])
            return []
        except Exception:
            return []

    results = await asyncio.gather(*(_fetch(s) for s in servers), return_exceptions=True)

    seen: Dict[str, Dict[str, Any]] = {}
    for res_list in results:
        if isinstance(res_list, Exception):
            continue
        for resource in res_list:
            if isinstance(resource, dict):
                uri = resource.get("uri")
                if uri and uri not in seen:
                    seen[uri] = resource

    return {
        "resources": list(seen.values()),
    }


async def _handle_resources_read(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 resources/read 方法.

    解析 URI scheme 作为服务器名，路由到对应 MCP 服务器读取资源。
    若 scheme 未匹配到服务器，则 fallback 遍历所有在线服务器尝试读取。

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

    # 1. 尝试解析 URI scheme 作为服务器名
    target_server = None
    scheme = ""
    if "://" in uri:
        scheme = uri.split("://")[0]
    if scheme:
        candidate = mcp_registry.get_server_by_name(scheme)
        if candidate and candidate.status == "online":
            target_server = candidate

    # 2. scheme 匹配成功，直接转发
    if target_server:
        try:
            result = await _send_mcp_request_async(
                target_server, "resources/read", {"uri": uri}
            )
            if isinstance(result, dict):
                return result
            return {"contents": [result]} if result is not None else {}
        except Exception as e:
            raise ValueError(f"读取资源失败 ({target_server.name}): {e}")

    # 3. Fallback：遍历所有在线服务器并发尝试读取
    servers = mcp_registry.list_servers(status="online")
    if not servers:
        raise ValueError(f"资源不可用: {uri}")

    async def _try_read(server: Any) -> Optional[Dict[str, Any]]:
        try:
            result = await _send_mcp_request_async(
                server, "resources/read", {"uri": uri}
            )
            if isinstance(result, dict):
                return result
            return {"contents": [result]} if result is not None else {}
        except Exception:
            return None

    tasks = [asyncio.create_task(_try_read(s)) for s in servers]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result is not None:
            # 取消剩余任务
            for t in tasks:
                t.cancel()
            return result

    raise ValueError(f"资源不可用: {uri}")


# ============================================================
# prompts 相关方法
# ============================================================

async def _handle_prompts_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 prompts/list 方法.

    遍历所有已注册的在线 MCP 服务器，并发调用 prompts/list，
    给每个提示词名称加上服务器前缀以保证唯一性，按 name 去重后返回。

    Args:
        params: 参数

    Returns:
        提示词列表
    """
    servers = mcp_registry.list_servers(status="online")
    if not servers:
        return {"prompts": []}

    async def _fetch(server: Any) -> List[Dict[str, Any]]:
        try:
            result = await _send_mcp_request_async(server, "prompts/list", {})
            if isinstance(result, dict):
                prompts = result.get("prompts", [])
                # 给 prompt name 加上服务器前缀，保证唯一性和可路由性
                processed = []
                for p in prompts:
                    if isinstance(p, dict):
                        new_p = dict(p)
                        if "name" in new_p:
                            new_p["name"] = f"{server.name}.{new_p['name']}"
                        processed.append(new_p)
                return processed
            return []
        except Exception:
            return []

    results = await asyncio.gather(*(_fetch(s) for s in servers), return_exceptions=True)

    seen: Dict[str, Dict[str, Any]] = {}
    for prompt_list in results:
        if isinstance(prompt_list, Exception):
            continue
        for prompt in prompt_list:
            if isinstance(prompt, dict):
                name = prompt.get("name")
                if name and name not in seen:
                    seen[name] = prompt

    return {
        "prompts": list(seen.values()),
    }


async def _handle_prompts_get(params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 prompts/get 方法.

    解析提示词名称前缀（格式：server_name.prompt_name）路由到对应 MCP 服务器。
    若前缀未匹配到服务器，则 fallback 遍历所有在线服务器尝试获取。

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

    # 1. 解析服务器前缀，格式：server_name.prompt_name
    server_name = ""
    raw_name = prompt_name
    if "." in prompt_name:
        parts = prompt_name.split(".", 1)
        server_name = parts[0]
        raw_name = parts[1]

    target_server = None
    if server_name:
        candidate = mcp_registry.get_server_by_name(server_name)
        if candidate and candidate.status == "online":
            target_server = candidate

    # 2. 前缀匹配成功，直接转发（使用原始 name）
    if target_server:
        try:
            result = await _send_mcp_request_async(
                target_server,
                "prompts/get",
                {"name": raw_name, "arguments": params.get("arguments", {})},
            )
            if isinstance(result, dict):
                return result
            return {"prompt": result} if result is not None else {}
        except Exception as e:
            raise ValueError(f"获取提示词失败 ({target_server.name}): {e}")

    # 3. Fallback：遍历所有在线服务器并发尝试获取
    servers = mcp_registry.list_servers(status="online")
    if not servers:
        raise ValueError(f"提示词不可用: {prompt_name}")

    async def _try_get(server: Any) -> Optional[Dict[str, Any]]:
        try:
            result = await _send_mcp_request_async(
                server,
                "prompts/get",
                {"name": prompt_name, "arguments": params.get("arguments", {})},
            )
            if isinstance(result, dict):
                return result
            return {"prompt": result} if result is not None else {}
        except Exception:
            return None

    tasks = [asyncio.create_task(_try_get(s)) for s in servers]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result is not None:
            # 取消剩余任务
            for t in tasks:
                t.cancel()
            return result

    raise ValueError(f"提示词不可用: {prompt_name}")


# ============================================================
# SSE 传输端点
# ============================================================

@router.get("/mcp/sse", summary="MCP SSE 连接端点")
async def mcp_sse_endpoint(request: Request) -> StreamingResponse:
    """MCP SSE 传输协议端点.

    客户端通过 GET 请求建立 SSE 长连接，
    服务端通过 SSE 推送 JSON-RPC 响应和通知。
    客户端通过 POST /mcp/sse/{session_id} 发送请求。

    消息格式：
    - 连接建立后，首条消息为 endpoint 事件，包含 session_id
    - 后续通过 message 事件推送 JSON-RPC 响应
    - 定期发送心跳注释保持连接
    
    安全：需要有效的 API Key。
    """
    # 鉴权检查
    api_key = _check_mcp_auth(request)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid API Key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
    request: Request,
    server_id: Optional[int] = Query(None, description="按服务器过滤"),
    category: Optional[str] = Query(None, description="按分类过滤"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
) -> McpToolListResponse:
    """REST 风格获取工具列表.

    工具名格式：{server_name}.{tool_name}
    支持分页、过滤、搜索。
    
    安全：需要有效的 API Key。
    """
    # 鉴权检查
    api_key = _check_mcp_auth(request)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid API Key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
async def rest_call_tool(
    tool_name: str,
    request: Request,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """REST 风格调用工具.

    工具名格式：{server_name}.{tool_name}

    请求体为工具调用参数（JSON 对象）。
    返回执行结果和元数据。
    
    安全：需要有效的 API Key。
    """
    # 鉴权检查
    api_key = _check_mcp_auth(request)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid API Key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
async def rest_get_tool(tool_name: str, request: Request) -> McpToolResponse:
    """REST 风格获取工具详情.

    工具名格式：{server_name}.{tool_name}
    
    安全：需要有效的 API Key。
    """
    # 鉴权检查
    api_key = _check_mcp_auth(request)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Valid API Key required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
