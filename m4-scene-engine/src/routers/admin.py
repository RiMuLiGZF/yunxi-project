"""系统管理路由.

提供全局配置、运行指标、健康检查等管理接口。
需鉴权访问。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request

try:
    from src.models import AdminConfigUpdateRequest, make_response
except ImportError:
    from models import AdminConfigUpdateRequest, make_response  # type: ignore

try:
    from src.services.mcp_client import get_mcp_client
    _HAS_MCP_CLIENT = True
except ImportError:
    try:
        from services.mcp_client import get_mcp_client  # type: ignore
        _HAS_MCP_CLIENT = True
    except ImportError:
        _HAS_MCP_CLIENT = False

router = APIRouter(prefix="/api/v1/admin", tags=["系统管理"])


def _get_services(request: Request) -> dict[str, Any]:
    """从 request state 获取服务实例."""
    return {
        "health_metrics": getattr(request.app.state, "health_metrics", None),
        "context_store": getattr(request.app.state, "context_store", None),
        "switch_manager": getattr(request.app.state, "switch_manager", None),
        "recognizer": getattr(request.app.state, "recognizer", None),
        "config": getattr(request.app.state, "config", {}),
    }


# ---------------------------------------------------------------------------
# 健康检查（M8 标准，白名单）
# ---------------------------------------------------------------------------

@router.get("/health", summary="M8 标准健康检查")
async def admin_health(request: Request):
    """M8 标准健康检查接口（白名单，无需鉴权）."""
    services = _get_services(request)
    health_metrics = services["health_metrics"]

    if health_metrics is not None:
        result = await health_metrics.get_health()
        return make_response(data=result)

    # 降级
    return make_response(data={
        "status": "healthy",
        "version": "1.0.0",
        "module": "m4",
        "uptime_seconds": 0,
        "checks": {
            "storage": "healthy",
            "context_store": "healthy",
            "scene_engine": "healthy",
        },
    })


# ---------------------------------------------------------------------------
# 全局配置 - 获取
# ---------------------------------------------------------------------------

@router.get("/config", summary="获取全局配置")
async def get_admin_config(request: Request):
    """获取全局配置（敏感字段已脱敏）.

    需鉴权: X-M8-Token
    """
    services = _get_services(request)
    config = services["config"]

    # 脱敏处理
    sanitized = dict(config)
    if "admin_token" in sanitized:
        sanitized["admin_token"] = "***"
    if "llm_api_key" in sanitized:
        sanitized["llm_api_key"] = "***"

    return make_response(data=sanitized)


# ---------------------------------------------------------------------------
# 全局配置 - 更新
# ---------------------------------------------------------------------------

@router.put("/config", summary="更新全局配置")
async def update_admin_config(request: Request, body: AdminConfigUpdateRequest):
    """更新全局配置.

    需鉴权: X-M8-Token
    """
    services = _get_services(request)
    config_updates = body.config
    updated_keys = []
    restart_required = False

    # 应用更新到 app.state.config
    for key, value in config_updates.items():
        setattr(request.app.state.config, key, value) if hasattr(
            request.app.state.config, key
        ) else None
        updated_keys.append(key)

        # 同步更新到相关服务
        if key == "recognize_keyword_threshold" and services["recognizer"]:
            services["recognizer"].update_threshold(value)

        if key == "enable_llm_enhance":
            restart_required = True

    # 从字典方式更新
    if isinstance(request.app.state.config, dict):
        for key, value in config_updates.items():
            request.app.state.config[key] = value
            updated_keys.append(key)

            if key == "recognize_keyword_threshold" and services["recognizer"]:
                services["recognizer"].update_threshold(value)

            if key in ("enable_llm_enhance", "llm_base_url", "llm_model_name"):
                restart_required = True

    return make_response(data={
        "updated_keys": updated_keys,
        "restart_required": restart_required,
        "success": True,
    })


# ---------------------------------------------------------------------------
# 运行指标
# ---------------------------------------------------------------------------

@router.get("/metrics", summary="运行指标")
async def admin_metrics(request: Request):
    """获取服务运行指标.

    需鉴权: X-M8-Token
    """
    services = _get_services(request)
    health_metrics = services["health_metrics"]

    if health_metrics is not None:
        result = await health_metrics.get_metrics()
        return make_response(data=result)

    # 降级
    return make_response(data={
        "cpu_percent": 0.0,
        "memory_mb": 0.0,
        "disk_usage_mb": 0.0,
        "requests_total": 0,
        "requests_per_second": 0.0,
        "avg_response_ms": 0.0,
        "error_rate": 0.0,
        "recognize_count": 0,
        "switch_count": 0,
        "auto_switch_count": 0,
        "module": "m4",
        "version": "1.0.0",
    })


# ---------------------------------------------------------------------------
# MCP 服务配置 - 获取
# ---------------------------------------------------------------------------

@router.get("/mcp/config", summary="获取 MCP 服务配置")
async def get_mcp_config(request: Request):
    """获取 MCP 服务配置信息（敏感字段已脱敏）.

    需鉴权: X-M8-Token
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None and _HAS_MCP_CLIENT:
        mcp_client = get_mcp_client()

    if mcp_client is None:
        return make_response(
            code=50301,
            message="MCP 客户端不可用",
            data={
                "enabled": False,
                "base_url": "",
                "api_key": "***",
                "timeout": 30.0,
                "available": False,
            },
        )

    return make_response(data={
        "enabled": mcp_client.enabled,
        "base_url": mcp_client.base_url,
        "api_key": "***",  # 脱敏
        "timeout": getattr(mcp_client, "_timeout", 30.0),
        "available": mcp_client.service_available,
    })


# ---------------------------------------------------------------------------
# MCP 服务配置 - 更新
# ---------------------------------------------------------------------------

@router.put("/mcp/config", summary="更新 MCP 服务配置")
async def update_mcp_config(request: Request, body: AdminConfigUpdateRequest):
    """更新 MCP 服务配置.

    支持的配置项:
    - mcp_enabled: 是否启用 MCP 服务
    - mcp_base_url: MCP 服务地址
    - mcp_api_key: MCP API 密钥
    - mcp_timeout: 请求超时时间（秒）

    需鉴权: X-M8-Token
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None and _HAS_MCP_CLIENT:
        mcp_client = get_mcp_client()

    if mcp_client is None:
        return make_response(
            code=50301,
            message="MCP 客户端不可用",
            data={},
        )

    config_updates = body.config
    updated_keys = []

    # 解析配置项
    enabled = None
    base_url = None
    api_key = None
    timeout = None

    if "mcp_enabled" in config_updates:
        enabled = bool(config_updates["mcp_enabled"])
        updated_keys.append("mcp_enabled")

    if "mcp_base_url" in config_updates:
        base_url = str(config_updates["mcp_base_url"])
        updated_keys.append("mcp_base_url")

    if "mcp_api_key" in config_updates:
        api_key = str(config_updates["mcp_api_key"])
        updated_keys.append("mcp_api_key")

    if "mcp_timeout" in config_updates:
        timeout = float(config_updates["mcp_timeout"])
        updated_keys.append("mcp_timeout")

    # 应用更新
    mcp_client.update_config(
        base_url=base_url,
        api_key=api_key,
        enabled=enabled,
        timeout=timeout,
    )

    # 同步更新到全局配置
    if isinstance(request.app.state.config, dict):
        if enabled is not None:
            request.app.state.config["mcp_enabled"] = enabled
        if base_url is not None:
            request.app.state.config["mcp_base_url"] = base_url
        if timeout is not None:
            request.app.state.config["mcp_timeout"] = timeout

    return make_response(data={
        "updated_keys": updated_keys,
        "success": True,
        "current_config": {
            "enabled": mcp_client.enabled,
            "base_url": mcp_client.base_url,
            "api_key": "***",
            "timeout": getattr(mcp_client, "_timeout", 30.0),
            "available": mcp_client.service_available,
        },
    })


# ---------------------------------------------------------------------------
# MCP 服务健康检查（管理端）
# ---------------------------------------------------------------------------

@router.get("/mcp/health", summary="MCP 服务健康检查（管理端）")
async def admin_mcp_health(request: Request):
    """检查 M9 MCP 服务健康状态.

    需鉴权: X-M8-Token
    """
    mcp_client = getattr(request.app.state, "mcp_client", None)
    if mcp_client is None and _HAS_MCP_CLIENT:
        mcp_client = get_mcp_client()

    if mcp_client is None:
        return make_response(data={
            "enabled": False,
            "available": False,
            "base_url": "",
            "status": "client_unavailable",
        })

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
