"""M8 标准对接接口路由.

提供 M8 管理平台标准对接接口（/m8/* 路径）：
- GET /m8/health   - M8 标准健康检查
- GET /m8/metrics  - M8 标准性能指标
- GET /m8/config   - M8 标准配置查询

所有接口需要 M8 Token 鉴权（通过 x-m8-token 请求头）。
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header

from edge_cloud_kernel.api.dependencies import get_kernel_manager, verify_m8_token
from edge_cloud_kernel.core.kernel_manager import KernelManager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/m8", tags=["M8-标准接口"])


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/health", summary="M8标准健康检查")
async def m8_std_health(
    x_m8_token: str = Header(default=""),
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准健康检查接口.

    Args:
        x_m8_token: M8 鉴权 Token.
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准健康检查响应.
    """
    request_id = uuid.uuid4().hex[:16]
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics:
        health_data = await health_metrics.get_health(request_id=request_id)
    else:
        health_data = {
            "status": "degraded",
            "module": "m3",
            "version": "2.1.2",
            "uptime_seconds": kernel.uptime_seconds,
        }

    health_data.setdefault("module_name", "端云协同内核")
    return {
        "code": 0,
        "message": "ok",
        "data": health_data,
    }


@router.get("/metrics", summary="M8标准性能指标")
async def m8_std_metrics(
    x_m8_token: str = Header(default=""),
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准性能指标接口.

    返回兼容格式的性能指标数据，包含旧字段名和新字段名。

    Args:
        x_m8_token: M8 鉴权 Token.
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准性能指标响应.
    """
    request_id = uuid.uuid4().hex[:16]
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics:
        metrics_data = await health_metrics.get_metrics(request_id=request_id)
    else:
        metrics_data = {}

    compatible_data = {
        # 兼容字段（旧字段名）
        "cpu_usage": metrics_data.get("cpu_percent", 0.0),
        "memory_mb": int(metrics_data.get("memory_mb", 0)),
        "devices_connected": metrics_data.get("conflict_count", 0),
        "sync_queue_size": metrics_data.get("pending_sync_items", 0),
        # 新字段（完整指标）
        "cpu_percent": metrics_data.get("cpu_percent", 0.0),
        "disk_usage_mb": metrics_data.get("disk_usage_mb", 0),
        "requests_total": metrics_data.get("requests_total", 0),
        "requests_per_second": metrics_data.get("requests_per_second", 0.0),
        "avg_response_ms": metrics_data.get("avg_response_ms", 0.0),
        "error_rate": metrics_data.get("error_rate", 0.0),
        "sync_tasks_total": metrics_data.get("sync_tasks_total", 0),
        "sync_success_rate": metrics_data.get("sync_success_rate", 0.0),
        "pending_sync_items": metrics_data.get("pending_sync_items", 0),
        "conflict_count": metrics_data.get("conflict_count", 0),
        "offline_queue_size": metrics_data.get("offline_queue_size", 0),
    }
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }


@router.get("/config", summary="M8标准配置查询")
async def m8_std_config(
    x_m8_token: str = Header(default=""),
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准配置查询接口.

    返回兼容格式的配置信息，包含环境、同步模式等关键字段。

    Args:
        x_m8_token: M8 鉴权 Token.
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准配置响应.
    """
    request_id = uuid.uuid4().hex[:16]
    config_manager = kernel.get_component("config_manager")

    if config_manager:
        config_data = config_manager.get_config_sanitized(request_id=request_id)
    else:
        config_data = {}

    env = os.environ.get("YUNXI_ENV", "development")
    sync_cfg = (
        config_data.get("sync", {})
        if isinstance(config_data.get("sync"), dict)
        else {}
    )
    offline_cfg = (
        config_data.get("offline", {})
        if isinstance(config_data.get("offline"), dict)
        else {}
    )
    compatible_data = {
        # 兼容字段
        "module": "m3",
        "version": "2.1.2",
        "env": env,
        "sync_mode": sync_cfg.get("mode", "auto"),
        "offline_enabled": offline_cfg.get("enabled", True),
        # 完整配置
        "config": config_data,
    }
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }
