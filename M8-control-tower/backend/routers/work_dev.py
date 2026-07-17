"""
工作开发 路由 - M9 代理版

工作开发已迁移到 M9 开发工坊（迁移脚本：migrate_work_m8_to_m9.py）

原本地实现已迁移至 M9 模块。
所有请求通过路由层直接代理转发到 M9。

代理路径映射：
  M8 /api/work-dev/*  →  M9 /api/v1/work-dev/*

回滚方式：
  从 _archive/m8_migrated/routers/ 恢复原文件即可
"""

import os
from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
import httpx

from ..auth import get_current_user
from ..schemas import ApiResponse

router = APIRouter()

# M9 服务配置
MODULE_BASE_URL = os.environ.get("M9_BASE_URL", "http://localhost:8009")
MODULE_ADMIN_TOKEN = os.environ.get("M9_ADMIN_TOKEN", "")
MODULE_TIMEOUT = float(os.environ.get("M9_TIMEOUT", "30"))


def _get_client() -> httpx.AsyncClient:
    """获取 HTTP 客户端"""
    return httpx.AsyncClient(
        base_url=MODULE_BASE_URL,
        timeout=MODULE_TIMEOUT,
        follow_redirects=True,
    )


@router.get("/health", summary=f"工作开发服务状态（M9代理）")
async def module_health(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """检查 M9 服务健康状态"""
    try:
        async with _get_client() as client:
            response = await client.get("/health")
            data = response.json()
            return ApiResponse.success(data={
                **data,
                "proxied": True,
                "service": "work_dev",
                "service_name": "工作开发",
                "target_module": "m9",
                "target_url": MODULE_BASE_URL,
            })
    except Exception as e:
        return ApiResponse(
            code=503,
            message="M9 服务不可用",
            data={"status": "unavailable", "error": str(e), "proxied": True},
        )


@router.get("/proxy-info", summary="代理转发信息")
async def proxy_info(
    current_user: Optional[dict] = Depends(get_current_user),
):
    """获取代理转发配置"""
    return ApiResponse.success(data={
        "service": "work_dev",
        "service_name": "工作开发",
        "target_module": "m9",
        "target_base_url": MODULE_BASE_URL,
        "target_prefix": "/api/v1/work-dev",
        "m8_prefix": "/api/work-dev",
        "timeout": MODULE_TIMEOUT,
        "migrated": True,
        "migration_phase": "phase-1",
    })


# 通用代理接口（捕获所有子路径，转发到目标模块）
@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def generic_proxy(
    path: str,
    request: Request,
    current_user: Optional[dict] = Depends(get_current_user),
):
    """通用代理接口，将请求转发到 M9 /api/v1/work-dev/<path>"""
    user_id = "default"
    if current_user:
        if isinstance(current_user, dict):
            user_id = str(current_user.get("user_id", current_user.get("id", "default")))
        elif hasattr(current_user, "id"):
            user_id = str(current_user.id)
    
    # 构建请求头
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in ("host", "content-length"):
            continue
        headers[key] = value
    headers["X-M8-Proxy"] = "true"
    headers["X-M8-User-Id"] = user_id
    headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
    if MODULE_ADMIN_TOKEN:
        headers["X-M8-Token"] = MODULE_ADMIN_TOKEN
    
    # 构建查询参数
    query_params = dict(request.query_params)
    if "user_id" not in query_params:
        query_params["user_id"] = user_id
    
    # 获取请求体
    try:
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None
    except Exception:
        body = None
    
    # 构建目标路径
    target_path = f"/api/v1/work-dev/{path}" if path else "/api/v1/work-dev"
    
    try:
        async with _get_client() as client:
            kwargs = {"params": query_params, "headers": headers}
            if body is not None:
                kwargs["content"] = body
            
            response = await client.request(request.method, target_path, **kwargs)
            
            # 构建响应
            response_headers = {}
            for key, value in response.headers.items():
                if key.lower() in ("content-encoding", "transfer-encoding", "content-length"):
                    continue
                response_headers[key] = value
            response_headers["X-M9-Proxied"] = "true"
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "M9 服务不可用", "data": None},
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"code": 504, "message": "M9 请求超时", "data": None},
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"code": 502, "message": f"M9 代理失败: {str(e)}", "data": None},
        )
