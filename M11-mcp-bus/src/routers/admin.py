"""M11 MCP Bus - 管理 API 路由.

提供服务器管理、工具管理、调用日志、API Key 管理等管理接口。

Phase 1 安全加固：
- 所有管理接口接入 API Key 鉴权（Depends(get_current_api_key)）
- 关键操作接入审计日志（服务注册/注销、API Key 创建/撤销）
- 数据库会话统一使用 Depends(get_db) 依赖注入
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..middleware.auth import require_authenticated
from ..models import (
    ApiKeyCreate,
    ApiKeyListResponse,
    ApiKeyResponse,
    HeartbeatRequest,
    McpCallListResponse,
    McpCallRecordResponse,
    McpServerCreate,
    McpServerListResponse,
    McpServerResponse,
    McpToolListResponse,
    McpToolResponse,
    ToolRefreshRequest,
)
from ..models_db import ApiKey, McpCall, McpTool
from ..services.audit import audit_logger
from ..services.monitor import mcp_monitor
from ..services.registry import mcp_registry

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ============================================================
# 服务器管理
# ============================================================

@router.get("/servers", response_model=McpServerListResponse, summary="获取 MCP 服务器列表")
async def list_servers(
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    api_key: ApiKey = Depends(require_authenticated),
) -> McpServerListResponse:
    """获取 MCP 服务器列表.

    - 支持按状态过滤（online/offline）
    - 支持分页
    - 返回每台服务器的工具数量

    需要鉴权：通过 X-API-Key 或 Authorization: Bearer 提供有效 API Key。
    """
    all_servers = mcp_registry.list_servers(status=status)
    total = len(all_servers)

    # 分页
    start = (page - 1) * page_size
    end = start + page_size
    paged_servers = all_servers[start:end]

    # 组装响应（包含工具数量）
    items = []
    for server in paged_servers:
        tool_count = mcp_registry.get_server_tool_count(server.id)
        items.append(McpServerResponse(
            id=server.id,
            name=server.name,
            description=server.description or "",
            transport_type=server.transport_type,
            endpoint=server.endpoint or "",
            status=server.status,
            health_check_url=server.health_check_url or "",
            last_heartbeat=server.last_heartbeat,
            created_at=server.created_at,
            tool_count=tool_count,
        ))

    return McpServerListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/servers/{server_id}", response_model=McpServerResponse, summary="获取服务器详情")
async def get_server(
    server_id: int,
    api_key: ApiKey = Depends(require_authenticated),
) -> McpServerResponse:
    """获取指定服务器的详细信息.

    需要鉴权。
    """
    server = mcp_registry.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"服务器不存在: {server_id}")

    tool_count = mcp_registry.get_server_tool_count(server_id)
    return McpServerResponse(
        id=server.id,
        name=server.name,
        description=server.description or "",
        transport_type=server.transport_type,
        endpoint=server.endpoint or "",
        status=server.status,
        health_check_url=server.health_check_url or "",
        last_heartbeat=server.last_heartbeat,
        created_at=server.created_at,
        tool_count=tool_count,
    )


@router.post("/servers/register", summary="注册新服务器")
async def register_server(
    body: McpServerCreate,
    request: Request,
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """注册新的 MCP 服务器.

    自动生成 server_id 和 api_key，返回给调用方。
    服务器初始状态为 offline，等待心跳上报后变为 online。

    需要鉴权。注册成功后写入审计日志（事件类型：server.register）。
    """
    try:
        server, api_key_plain = mcp_registry.register_server(
            name=body.name,
            transport_type=body.transport_type.value,
            endpoint=body.endpoint,
            description=body.description,
            health_check_url=body.health_check_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 审计日志：服务器注册成功
    actor = api_key.name
    audit_logger.log_event(
        event_type="server.register",
        actor=actor,
        action="register",
        resource=f"server:{server.id}",
        metadata={
            "server_id": server.id,
            "server_name": server.name,
            "transport_type": server.transport_type,
        },
        description=f"服务器注册成功: {server.name}",
        ip_address=request.client.host if request.client else "",
    )

    tool_count = mcp_registry.get_server_tool_count(server.id)
    return {
        "server": McpServerResponse(
            id=server.id,
            name=server.name,
            description=server.description or "",
            transport_type=server.transport_type,
            endpoint=server.endpoint or "",
            status=server.status,
            health_check_url=server.health_check_url or "",
            last_heartbeat=server.last_heartbeat,
            created_at=server.created_at,
            tool_count=tool_count,
        ),
        "api_key": api_key_plain,
        "message": "注册成功，请妥善保管 api_key",
    }


@router.post("/servers/{server_id}/heartbeat", summary="服务器心跳")
async def server_heartbeat(
    server_id: int,
    body: HeartbeatRequest,
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """服务器心跳上报.

    更新服务器最后心跳时间和状态。
    建议每 10-30 秒上报一次。

    需要鉴权。
    """
    server = mcp_registry.heartbeat(server_id, body.status.value)
    if not server:
        raise HTTPException(status_code=404, detail=f"服务器不存在: {server_id}")

    return {
        "status": "ok",
        "server_id": server.id,
        "server_status": server.status,
        "last_heartbeat": server.last_heartbeat.isoformat() if server.last_heartbeat else None,
        "message": "心跳更新成功",
    }


@router.delete("/servers/{server_id}", summary="删除服务器")
async def delete_server(
    server_id: int,
    request: Request,
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """删除指定的 MCP 服务器.

    同时会删除该服务器的所有工具缓存。

    需要鉴权。删除成功后写入审计日志（事件类型：server.unregister）。
    """
    # 先获取服务器信息用于审计日志
    server = mcp_registry.get_server(server_id)
    server_name = server.name if server else f"server_{server_id}"

    success = mcp_registry.unregister_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"服务器不存在: {server_id}")

    # 审计日志：服务器注销
    actor = api_key.name
    audit_logger.log_event(
        event_type="server.unregister",
        actor=actor,
        action="unregister",
        resource=f"server:{server_id}",
        metadata={
            "server_id": server_id,
            "server_name": server_name,
        },
        description=f"服务器注销: {server_name}",
        ip_address=request.client.host if request.client else "",
    )

    return {
        "status": "ok",
        "server_id": server_id,
        "message": "服务器已删除",
    }


# ============================================================
# 工具管理
# ============================================================

@router.get("/tools", response_model=McpToolListResponse, summary="获取所有工具列表")
async def list_tools(
    server_id: Optional[int] = Query(None, description="按服务器过滤"),
    category: Optional[str] = Query(None, description="按分类过滤"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量"),
    api_key: ApiKey = Depends(require_authenticated),
) -> McpToolListResponse:
    """获取所有 MCP 服务器的聚合工具列表.

    工具名格式：{server_name}.{tool_name}
    支持按服务器、分类、关键词过滤。

    需要鉴权。
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


@router.get("/tools/{tool_name}", response_model=McpToolResponse, summary="获取工具详情")
async def get_tool(
    tool_name: str,
    api_key: ApiKey = Depends(require_authenticated),
) -> McpToolResponse:
    """获取指定工具的详细信息.

    工具名格式：{server_name}.{tool_name}

    需要鉴权。
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


@router.post("/tools/refresh", summary="手动刷新工具列表")
async def refresh_tools(
    body: ToolRefreshRequest,
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """手动刷新所有在线服务器的工具列表.

    遍历所有 online 状态的服务器，调用其 tools/list 接口，
    更新本地缓存的工具信息。

    需要鉴权。
    """
    result = mcp_registry.refresh_all_tools(force=body.force)
    return {
        "status": "ok",
        "total_servers": result["total_servers"],
        "refreshed": result["refreshed"],
        "failed": result["failed"],
        "total_tools": result["total_tools"],
        "errors": result["errors"],
        "message": f"刷新完成：成功 {result['refreshed']} 个，失败 {result['failed']} 个，共 {result['total_tools']} 个工具",
    }


# ============================================================
# 调用日志
# ============================================================

@router.get("/calls", response_model=McpCallListResponse, summary="调用日志列表")
async def list_calls(
    tool_name: Optional[str] = Query(None, description="按工具名过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    server_id: Optional[int] = Query(None, description="按服务器过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    api_key: ApiKey = Depends(require_authenticated),
) -> McpCallListResponse:
    """获取工具调用日志列表（分页）.

    支持按工具名、状态、服务器过滤。

    需要鉴权。
    """
    calls, total = mcp_monitor.get_call_history(
        tool_name=tool_name,
        status=status,
        server_id=server_id,
        page=page,
        page_size=page_size,
    )

    items = [
        McpCallRecordResponse(
            id=call.id,
            tool_name=call.tool_name,
            server_id=call.server_id,
            consumer=call.consumer or "",
            status=call.status,
            duration_ms=call.duration_ms,
            error_message=call.error_message or "",
            request_snippet=call.request_snippet or "",
            response_snippet=call.response_snippet or "",
            created_at=call.created_at,
        )
        for call in calls
    ]

    return McpCallListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/calls/{call_id}", response_model=McpCallRecordResponse, summary="调用详情")
async def get_call(
    call_id: int,
    api_key: ApiKey = Depends(require_authenticated),
) -> McpCallRecordResponse:
    """获取指定调用的详细信息.

    需要鉴权。
    """
    call = mcp_monitor.get_call_by_id(call_id)
    if not call:
        raise HTTPException(status_code=404, detail=f"调用记录不存在: {call_id}")

    return McpCallRecordResponse(
        id=call.id,
        tool_name=call.tool_name,
        server_id=call.server_id,
        consumer=call.consumer or "",
        status=call.status,
        duration_ms=call.duration_ms,
        error_message=call.error_message or "",
        request_snippet=call.request_snippet or "",
        response_snippet=call.response_snippet or "",
        created_at=call.created_at,
    )


# ============================================================
# API Key 管理
# ============================================================

def _hash_key(key: str) -> str:
    """对 API Key 进行哈希.

    Args:
        key: 明文密钥

    Returns:
        哈希后的字符串
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _generate_api_key() -> str:
    """生成新的 API Key.

    Returns:
        明文 API Key
    """
    alphabet = string.ascii_letters + string.digits
    return "m11_" + "".join(secrets.choice(alphabet) for _ in range(40))


@router.get("/api-keys", response_model=ApiKeyListResponse, summary="API Key 列表")
async def list_api_keys(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_authenticated),
) -> ApiKeyListResponse:
    """获取 API Key 列表.

    注意：列表中不包含明文密钥。

    需要鉴权。
    """
    query = db.query(ApiKey)
    total = query.count()
    keys = (
        query.order_by(ApiKey.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        ApiKeyResponse(
            id=key.id,
            name=key.name or "",
            permissions=key.permissions or [],
            rate_limit=key.rate_limit,
            created_at=key.created_at,
            expires_at=key.expires_at,
            last_used_at=key.last_used_at,
            key=None,
        )
        for key in keys
    ]

    return ApiKeyListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/api-keys", summary="创建 API Key")
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """创建新的 API Key.

    返回明文密钥，仅创建时返回一次，请妥善保管。

    需要鉴权。创建成功后写入审计日志（事件类型：apikey.create）。
    """
    api_key_plain = _generate_api_key()
    key_hash = _hash_key(api_key_plain)

    expires_at = None
    if body.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_days)

    key = ApiKey(
        key_hash=key_hash,
        name=body.name,
        permissions=body.permissions,
        rate_limit=body.rate_limit,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
        last_used_at=None,
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    # 审计日志：API Key 创建
    actor = api_key.name
    audit_logger.log_event(
        event_type="apikey.create",
        actor=actor,
        action="create",
        resource=f"api_key:{key.id}",
        metadata={
            "key_id": key.id,
            "key_name": key.name or "",
            "permissions": key.permissions or [],
            "rate_limit": key.rate_limit,
            "expires_days": body.expires_days,
        },
        description=f"API Key 创建: {key.name or '未命名'}",
        ip_address=request.client.host if request.client else "",
    )

    return {
        "id": key.id,
        "name": key.name,
        "permissions": key.permissions or [],
        "rate_limit": key.rate_limit,
        "created_at": key.created_at,
        "expires_at": key.expires_at,
        "key": api_key_plain,
        "message": "创建成功，请妥善保管密钥，仅显示一次",
    }


@router.delete("/api-keys/{key_id}", summary="删除 API Key")
async def delete_api_key(
    key_id: int,
    request: Request,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(require_authenticated),
) -> Dict[str, Any]:
    """删除（撤销）指定的 API Key.

    需要鉴权。删除成功后写入审计日志（事件类型：apikey.revoke）。
    """
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail=f"API Key 不存在: {key_id}")

    key_name = key.name or ""

    db.delete(key)
    db.commit()

    # 审计日志：API Key 撤销
    actor = api_key.name
    audit_logger.log_event(
        event_type="apikey.revoke",
        actor=actor,
        action="revoke",
        resource=f"api_key:{key_id}",
        metadata={
            "key_id": key_id,
            "key_name": key_name,
        },
        description=f"API Key 撤销: {key_name}",
        ip_address=request.client.host if request.client else "",
    )

    return {
        "status": "ok",
        "key_id": key_id,
        "message": "API Key 已删除",
    }
