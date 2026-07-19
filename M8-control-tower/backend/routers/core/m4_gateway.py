"""
M8 管理工作台 - M4 代理网关

将 M8 中的业务模式请求代理转发到 M4 场景引擎。
M4 不可用时返回 fallback 错误，保持 M8 原有路由不变（向后兼容）。

代理路由映射：
- 形象工坊：/api/appearance/* → M4 /api/v1/appearance/*
- 情绪陪伴：/api/emotion-comfort/* → M4 /api/v1/emotion-comfort/*
- 人际关系：/api/social-relation/* → M4 /api/v1/social-relation/*
- 生活管理：/api/life-management/* → M4 /api/v1/life-management/*
- 学业规划：/api/study-plan/* → M4 /api/v1/study-plan/*
- 复盘总结：/api/review/* → M4 /api/v1/review/*
- 成长中心：/api/growth/* → M4 /api/v1/growth/*
- 工作开发：/api/work-dev/* → M4 /api/v1/work-dev/*
- 聊天：/api/chat/* → M4 /api/v1/chat/*
- 语音：/api/voice/* → M4 /api/v1/voice/*
- 手表：/api/watch/* → M4 /api/v1/watch/*

注意：此文件仅新增代理路由，不删除 M8 原有的业务路由，
      保持向后兼容。通过 /m4-gateway/ 前缀访问代理路由。
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Request, HTTPException, Header, Query, Depends
from fastapi.responses import JSONResponse

from ...auth import get_current_user


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

#: M4 服务地址（可通过环境变量配置）
M4_BASE_URL = os.environ.get("M4_BASE_URL", "http://localhost:8004")
#: M4 服务请求超时时间（秒）
M4_TIMEOUT = float(os.environ.get("M4_TIMEOUT", "10"))
#: 是否启用 M4 代理
M4_PROXY_ENABLED = os.environ.get("M4_PROXY_ENABLED", "true").lower() == "true"
#: M4 Admin Token（用于鉴权透传）
M4_ADMIN_TOKEN = os.environ.get("M4_ADMIN_TOKEN", "")


# ---------------------------------------------------------------------------
# 路由前缀映射
# ---------------------------------------------------------------------------

#: M8 业务模式 → M4 API 路径前缀映射
M4_ROUTE_MAP: dict[str, str] = {
    "appearance": "/api/v1/appearance",
    "emotion-comfort": "/api/v1/emotion-comfort",
    "social-relation": "/api/v1/social-relation",
    "life-management": "/api/v1/life-management",
    "study-plan": "/api/v1/study-plan",
    "review": "/api/v1/review",
    "growth": "/api/v1/growth",
    "work-dev": "/api/v1/work-dev",
    "chat": "/api/v1/chat",
    "voice": "/api/v1/voice",
    "watch": "/api/v1/watch",
}


router = APIRouter(tags=["M4代理网关"])


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

def _get_httpx_client() -> httpx.AsyncClient:
    """获取 httpx 异步客户端.

    Returns:
        httpx 异步客户端实例
    """
    return httpx.AsyncClient(
        base_url=M4_BASE_URL,
        timeout=M4_TIMEOUT,
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 代理核心逻辑
# ---------------------------------------------------------------------------

async def _proxy_to_m4(
    method: str,
    m4_path: str,
    request: Request,
    user_id: str = "default",
) -> JSONResponse:
    """将请求代理转发到 M4.

    Args:
        method: HTTP 方法
        m4_path: M4 目标路径
        request: FastAPI 请求对象
        user_id: 用户ID

    Returns:
        JSON 响应

    Raises:
        HTTPException: M4 不可用时返回 503
    """
    if not M4_PROXY_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="M4 代理已禁用",
        )

    # 构建查询参数（透传 user_id）
    query_params = dict(request.query_params)
    if "user_id" not in query_params:
        query_params["user_id"] = user_id

    # 构建请求头
    headers = {
        "X-M8-User-Id": user_id,
        "X-Forwarded-For": request.client.host if request.client else "unknown",
        "Content-Type": "application/json",
    }
    if M4_ADMIN_TOKEN:
        headers["X-M8-Token"] = M4_ADMIN_TOKEN

    # 获取请求体
    try:
        body = await request.json() if method in ("POST", "PUT", "PATCH") else None
    except Exception:
        body = None

    try:
        async with _get_httpx_client() as client:
            # 构建请求
            request_kwargs: dict[str, Any] = {
                "params": query_params,
                "headers": headers,
            }
            if body is not None:
                request_kwargs["json"] = body

            response = await client.request(method, m4_path, **request_kwargs)

            # 透传 M4 响应
            response_headers = dict(response.headers)
            # 移除可能导致问题的头
            response_headers.pop("content-encoding", None)
            response_headers.pop("transfer-encoding", None)
            # 添加代理标识
            response_headers["X-M4-Proxied"] = "true"

            return JSONResponse(
                status_code=response.status_code,
                content=response.json() if response.content else {},
                headers=response_headers,
            )

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"M4 场景引擎不可用（地址: {M4_BASE_URL}），请确认 M4 服务已启动",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"M4 场景引擎请求超时（{M4_TIMEOUT}秒）",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"M4 代理请求失败: {str(e)}",
        )


def _build_m4_path(mode_key: str, sub_path: str) -> str:
    """构建 M4 目标路径.

    Args:
        mode_key: 业务模式 key
        sub_path: 子路径

    Returns:
        M4 完整路径
    """
    prefix = M4_ROUTE_MAP.get(mode_key, f"/api/v1/{mode_key}")
    if not sub_path.startswith("/"):
        sub_path = "/" + sub_path
    return f"{prefix}{sub_path}"


# ---------------------------------------------------------------------------
# 网关状态
# ---------------------------------------------------------------------------


@router.get("/status", summary="M4 代理网关状态")
async def gateway_status():
    """获取 M4 代理网关的状态信息."""
    # 获取业务代理中间件状态
    try:
        from ...m4_proxy_middleware import get_proxy_status
        business_proxy = get_proxy_status()
    except Exception:
        business_proxy = {
            "mode": "unknown",
            "enabled": False,
        }

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "enabled": M4_PROXY_ENABLED,
            "m4_base_url": M4_BASE_URL,
            "timeout": M4_TIMEOUT,
            "supported_modes": list(M4_ROUTE_MAP.keys()),
            "route_map": M4_ROUTE_MAP,
            "business_proxy": business_proxy,
        },
    }


@router.get("/business-proxy/status", summary="业务代理模式状态")
async def business_proxy_status(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """获取业务代理中间件的当前状态."""
    from ...m4_proxy_middleware import get_proxy_status
    return {
        "code": 0,
        "message": "ok",
        "data": get_proxy_status(),
    }


@router.post("/business-proxy/mode", summary="切换业务代理模式")
async def set_business_proxy_mode(
    mode: str = Query(..., description="代理模式: off / fallback / on"),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """切换业务代理模式（运行时动态切换）.

    - off: 关闭代理，全部使用本地实现
    - fallback: 优先代理到 M4，M4 不可用时回退到本地
    - on: 强制使用 M4 代理，M4 不可用时返回 503

    注意：这是运行时切换，重启后会恢复为环境变量配置的值。
    """
    valid_modes = ["off", "fallback", "on"]
    if mode.lower() not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"无效的代理模式: {mode}，支持的模式: {valid_modes}",
        )

    # 动态修改全局变量（运行时切换）
    from ... import m4_proxy_middleware
    m4_proxy_middleware.M4_PROXY_MODE = mode.lower()

    mode_desc = {
        "off": "关闭代理（本地实现）",
        "fallback": "优先M4，失败回退本地",
        "on": "强制M4代理",
    }

    logger.info(f"业务代理模式已切换为: {mode} ({mode_desc.get(mode, mode)})")

    return {
        "code": 0,
        "message": f"代理模式已切换为: {mode}",
        "data": {
            "mode": mode.lower(),
            "description": mode_desc.get(mode, mode),
        },
    }


# ---------------------------------------------------------------------------
# 通用代理接口
# ---------------------------------------------------------------------------


@router.api_route("/{mode_key}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def generic_proxy(
    mode_key: str,
    path: str,
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """通用 M4 代理接口.

    将请求转发到 M4 场景引擎对应的业务模式。

    - mode_key: 业务模式 key（如 appearance, growth, chat 等）
    - path: 子路径（如 config, history, devices 等）

    示例：
        GET /m4-gateway/chat/history → M4 /api/v1/chat/history
        POST /m4-gateway/watch/devices → M4 /api/v1/watch/devices
    """
    if mode_key not in M4_ROUTE_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"不支持的业务模式: {mode_key}，支持的模式: {list(M4_ROUTE_MAP.keys())}",
        )

    # 获取用户ID
    user_id = "default"
    if current_user:
        if isinstance(current_user, dict):
            user_id = str(current_user.get("user_id", current_user.get("id", "default")))
        elif hasattr(current_user, "id"):
            user_id = str(current_user.id)

    m4_path = _build_m4_path(mode_key, path)
    method = request.method

    return await _proxy_to_m4(method, m4_path, request, user_id)


# ---------------------------------------------------------------------------
# 健康检查代理
# ---------------------------------------------------------------------------


@router.get("/health", summary="M4 健康检查（代理）")
async def m4_health_proxy():
    """代理检查 M4 场景引擎的健康状态."""
    try:
        async with _get_httpx_client() as client:
            response = await client.get("/health")
            data = response.json()
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    **data,
                    "proxied": True,
                    "m4_url": M4_BASE_URL,
                },
            }
    except Exception as e:
        return {
            "code": 503,
            "message": "M4 服务不可用",
            "data": {
                "status": "unavailable",
                "m4_url": M4_BASE_URL,
                "error": str(e),
                "proxied": False,
            },
        }


# ---------------------------------------------------------------------------
# 便捷代理：聊天服务
# ---------------------------------------------------------------------------


@router.get("/chat/history", summary="代理-获取聊天历史")
async def proxy_chat_history(
    request: Request,
    conversation_id: str = Query(..., description="会话ID"),
    limit: int = Query(50, description="消息数量"),
    current_user: Optional[dict] = Depends(get_current_user),
):
    """代理获取聊天历史（便捷路由）."""
    user_id = str(current_user.get("user_id", "default")) if current_user else "default"
    return await _proxy_to_m4("GET", "/api/v1/chat/history", request, user_id)


@router.post("/chat/send", summary="代理-发送聊天消息")
async def proxy_chat_send(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """代理发送聊天消息（便捷路由）."""
    user_id = str(current_user.get("user_id", "default")) if current_user else "default"
    return await _proxy_to_m4("POST", "/api/v1/chat/send", request, user_id)


# ---------------------------------------------------------------------------
# 便捷代理：手表设备
# ---------------------------------------------------------------------------


@router.get("/watch/devices", summary="代理-获取手表设备列表")
async def proxy_watch_devices(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """代理获取手表设备列表（便捷路由）."""
    user_id = str(current_user.get("user_id", "default")) if current_user else "default"
    return await _proxy_to_m4("GET", "/api/v1/watch/devices", request, user_id)


# ---------------------------------------------------------------------------
# 便捷代理：语音状态
# ---------------------------------------------------------------------------


@router.get("/voice/status", summary="代理-获取语音服务状态")
async def proxy_voice_status(
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """代理获取语音服务状态（便捷路由）."""
    user_id = str(current_user.get("user_id", "default")) if current_user else "default"
    return await _proxy_to_m4("GET", "/api/v1/voice/status", request, user_id)
