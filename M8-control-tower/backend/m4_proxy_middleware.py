"""
M8 业务模式 M4 代理中间件

根据配置将业务模式请求代理到 M4 场景引擎。
支持三种模式：
- off: 关闭代理，全部使用本地实现（默认）
- fallback: 优先代理到 M4，M4 不可用时回退到本地
- on: 强制使用 M4 代理，M4 不可用时返回 503

代理的业务路径前缀：
- /api/growth/*          → M4 /api/v1/growth/*
- /api/work-dev/*        → M4 /api/v1/work-dev/*
- /api/review/*          → M4 /api/v1/review/*
- /api/study-plan/*      → M4 /api/v1/study-plan/*
- /api/life-management/* → M4 /api/v1/life-management/*
- /api/emotion-comfort/* → M4 /api/v1/emotion-comfort/*
- /api/social-relation/* → M4 /api/v1/social-relation/*
- /api/appearance/*      → M4 /api/v1/appearance/*
- /api/chat/*            → M4 /api/v1/chat/*
- /api/voice/*           → M4 /api/v1/voice/*
- /api/watch/*           → M4 /api/v1/watch/*
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from shared.logger import get_logger

logger = get_logger("m8.m4_proxy_middleware")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

#: 代理模式: off / fallback / on
M4_PROXY_MODE = os.environ.get("M4_BUSINESS_PROXY_MODE", "off").lower()

#: M4 服务地址
M4_BASE_URL = os.environ.get("M4_BASE_URL", "http://localhost:8004")

#: M4 请求超时（秒）
M4_TIMEOUT = float(os.environ.get("M4_TIMEOUT", "10"))

#: M4 Admin Token（用于鉴权透传）
M4_ADMIN_TOKEN = os.environ.get("M4_ADMIN_TOKEN", "")

# ---------------------------------------------------------------------------
# 业务路径 → M4 路径映射
# ---------------------------------------------------------------------------

#: 需要代理的路径前缀映射（M8 前缀 → M4 前缀）
BUSINESS_PATH_MAP: dict[str, str] = {
    "/api/growth/": "/api/v1/growth/",
    "/api/work-dev/": "/api/v1/work-dev/",
    "/api/review/": "/api/v1/review/",
    "/api/study-plan/": "/api/v1/study-plan/",
    "/api/life-management/": "/api/v1/life-management/",
    "/api/emotion-comfort/": "/api/v1/emotion-comfort/",
    "/api/social-relation/": "/api/v1/social-relation/",
    "/api/appearance/": "/api/v1/appearance/",
    "/api/chat/": "/api/v1/chat/",
    "/api/voice/": "/api/v1/voice/",
    "/api/watch/": "/api/v1/watch/",
}


def _get_m4_target_path(m8_path: str) -> Optional[str]:
    """根据 M8 请求路径计算 M4 目标路径.

    Args:
        m8_path: M8 的请求路径（如 /api/growth/achievements）

    Returns:
        M4 目标路径，如果不在代理范围内返回 None
    """
    for m8_prefix, m4_prefix in BUSINESS_PATH_MAP.items():
        if m8_path.startswith(m8_prefix):
            sub_path = m8_path[len(m8_prefix):]
            return f"{m4_prefix}{sub_path}"
    return None


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

def _get_httpx_client() -> httpx.AsyncClient:
    """获取 httpx 异步客户端"""
    return httpx.AsyncClient(
        base_url=M4_BASE_URL,
        timeout=M4_TIMEOUT,
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 代理核心逻辑
# ---------------------------------------------------------------------------

async def _proxy_request(request: Request, m4_path: str) -> Optional[Response]:
    """将请求代理到 M4.

    Args:
        request: FastAPI 请求对象
        m4_path: M4 目标路径

    Returns:
        代理响应，如果失败返回 None
    """
    try:
        # 构建请求头
        headers = {}
        for key, value in request.headers.items():
            if key.lower() in ("host", "content-length"):
                continue
            headers[key] = value

        # 添加代理标识
        headers["X-M8-Proxy"] = "true"
        headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
        if M4_ADMIN_TOKEN:
            headers["X-M8-Token"] = M4_ADMIN_TOKEN

        # 构建查询参数
        params = dict(request.query_params)

        # 获取请求体
        body = await request.body()

        # 发送请求
        async with _get_httpx_client() as client:
            response = await client.request(
                method=request.method,
                url=m4_path,
                headers=headers,
                params=params,
                content=body if body else None,
            )

        # 构建响应
        response_headers = {}
        for key, value in response.headers.items():
            if key.lower() in ("content-encoding", "transfer-encoding", "content-length"):
                continue
            response_headers[key] = value

        # 添加代理来源标识
        response_headers["X-M4-Proxied"] = "true"

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )

    except httpx.TimeoutException:
        logger.warning(f"M4 代理超时: {request.method} {m4_path}")
        return None
    except httpx.ConnectError:
        logger.warning(f"M4 连接失败: {M4_BASE_URL}")
        return None
    except Exception as e:
        logger.warning(f"M4 代理异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------

class M4BusinessProxyMiddleware(BaseHTTPMiddleware):
    """M4 业务模式代理中间件

    根据 M4_PROXY_MODE 配置决定是否将业务请求代理到 M4。
    """

    async def dispatch(self, request: Request, call_next):
        # 代理关闭时直接放行
        if M4_PROXY_MODE == "off":
            return await call_next(request)

        # 检查是否是业务路径
        m4_path = _get_m4_target_path(request.url.path)
        if m4_path is None:
            # 不是业务路径，直接放行
            return await call_next(request)

        logger.debug(f"M4 代理模式={M4_PROXY_MODE}, 路径={request.url.path} -> {m4_path}")

        # 尝试代理
        proxy_response = await _proxy_request(request, m4_path)

        if proxy_response is not None:
            # 代理成功
            return proxy_response

        # 代理失败
        if M4_PROXY_MODE == "on":
            # 强制模式，返回 503
            return JSONResponse(
                status_code=503,
                content={
                    "code": 503,
                    "message": "M4 场景引擎暂不可用",
                    "data": None,
                },
            )

        # fallback 模式，继续走本地实现
        logger.info(f"M4 代理失败，回退到本地实现: {request.method} {request.url.path}")
        return await call_next(request)


# ---------------------------------------------------------------------------
# 注册中间件
# ---------------------------------------------------------------------------

def register_m4_proxy_middleware(app: FastAPI) -> None:
    """注册 M4 业务代理中间件到 FastAPI 应用.

    Args:
        app: FastAPI 应用实例
    """
    if M4_PROXY_MODE == "off":
        logger.info("M4 业务代理模式: off（使用本地实现）")
        return

    mode_desc = {
        "fallback": "fallback（优先M4，失败回退本地）",
        "on": "on（强制使用M4）",
    }.get(M4_PROXY_MODE, M4_PROXY_MODE)

    logger.info(f"M4 业务代理模式: {mode_desc}")
    logger.info(f"M4 服务地址: {M4_BASE_URL}")
    logger.info(f"代理业务路径: {len(BUSINESS_PATH_MAP)} 个前缀")

    app.add_middleware(M4BusinessProxyMiddleware)


# ---------------------------------------------------------------------------
# 获取代理状态
# ---------------------------------------------------------------------------

def get_proxy_status() -> dict:
    """获取 M4 代理状态信息.

    Returns:
        状态信息字典
    """
    return {
        "mode": M4_PROXY_MODE,
        "m4_base_url": M4_BASE_URL,
        "timeout": M4_TIMEOUT,
        "business_paths": list(BUSINESS_PATH_MAP.keys()),
        "enabled": M4_PROXY_MODE != "off",
    }
