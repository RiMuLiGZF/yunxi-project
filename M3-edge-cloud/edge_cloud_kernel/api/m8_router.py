"""M8 标准对接接口路由.

提供 M8 管理平台标准对接接口（/m8/* 路径）：
- GET /m8/health   - M8 标准健康检查
- GET /m8/metrics  - M8 标准性能指标
- GET /m8/config   - M8 标准配置查询

所有接口需要 M8 Token 鉴权（通过 X-M8-Token 或 Authorization: Bearer 请求头）。
Token 从环境变量 M3_M8_TOKEN 或 M8_TOKEN 读取。
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

# M8 标准接口常量
M3_MODULE_NAME = "m3-edge-cloud"
M3_MODULE_LABEL = "端云协同内核"
M3_VERSION = "2.1.2"

router = APIRouter(prefix="/m8", tags=["M8-标准接口"])


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _count_edge_nodes(kernel: KernelManager) -> int:
    """统计已注册的端侧设备数量.

    Args:
        kernel: 内核管理器.

    Returns:
        端侧设备数量.
    """
    device_registry = kernel.get_component("device_registry")
    if device_registry is None or kernel.is_mock("device_registry"):
        return 0
    try:
        # 同步获取设备数量（device_registry.list_devices 是协程）
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在事件循环内时，无法直接 await，返回 0 作为降级
            return 0
        devices = loop.run_until_complete(device_registry.list_devices())
        return len(devices)
    except Exception:
        return 0


async def _count_edge_nodes_async(kernel: KernelManager) -> int:
    """异步统计已注册的端侧设备数量.

    Args:
        kernel: 内核管理器.

    Returns:
        端侧设备数量.
    """
    device_registry = kernel.get_component("device_registry")
    if device_registry is None or kernel.is_mock("device_registry"):
        return 0
    try:
        devices = await device_registry.list_devices()
        return len(devices)
    except Exception:
        return 0


def _count_cloud_nodes(kernel: KernelManager) -> int:
    """统计云端节点数量（健康探测端点数）.

    Args:
        kernel: 内核管理器.

    Returns:
        云端节点数量.
    """
    health_checker = kernel.get_component("health_checker")
    if health_checker is None or kernel.is_mock("health_checker"):
        return 0
    try:
        endpoints = health_checker.get_all_status()
        return len(endpoints) if endpoints else 0
    except Exception:
        return 0


async def _get_sync_status(kernel: KernelManager) -> str:
    """获取当前同步状态.

    Args:
        kernel: 内核管理器.

    Returns:
        同步状态字符串（idle/syncing/error）.
    """
    m8_api = kernel.get_component("m8_api")
    if m8_api is None or kernel.is_mock("m8_api"):
        return "idle"
    try:
        result = await m8_api.get_sync_status(trace_id="m8_metrics")
        if hasattr(result, "data") and isinstance(result.data, dict):
            return result.data.get("status", "idle")
        return "idle"
    except Exception:
        return "idle"


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/health", summary="M8标准健康检查")
async def m8_std_health(
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准健康检查接口.

    返回 M8 标准格式的健康检查数据：
    - module: 模块名称（m3-edge-cloud）
    - version: 模块版本
    - status: 健康状态（healthy/degraded/unhealthy）
    - timestamp: 当前时间戳

    Args:
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准健康检查响应.
    """
    request_id = uuid.uuid4().hex[:16]
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics:
        try:
            health_data = await health_metrics.get_health(request_id=request_id)
        except Exception as e:
            logger.error("m8_health.failed", error=str(e), trace_id=request_id)
            health_data = {}
    else:
        health_data = {}

    # 统一覆盖为 M8 标准字段
    status = health_data.get("status", "degraded")
    if not isinstance(status, str) or status not in ("healthy", "degraded", "unhealthy"):
        status = "degraded"

    result_data = {
        "module": M3_MODULE_NAME,
        "module_name": M3_MODULE_LABEL,
        "version": M3_VERSION,
        "status": status,
        "timestamp": time.time(),
        "uptime_seconds": health_data.get(
            "uptime_seconds", kernel.uptime_seconds
        ),
    }

    # 保留 checks 子项（如果存在）
    if "checks" in health_data:
        result_data["checks"] = health_data["checks"]

    logger.info("m8_health.ok", trace_id=request_id, status=status)
    return {
        "code": 0,
        "message": "ok",
        "data": result_data,
    }


@router.get("/metrics", summary="M8标准性能指标")
async def m8_std_metrics(
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准性能指标接口.

    返回 M8 标准格式的性能指标数据，包含：
    - sync_status: 同步状态（idle/syncing/error）
    - edge_nodes: 端侧设备数量
    - cloud_nodes: 云端节点数量
    - sync_queue_size: 同步队列大小
    - cpu_usage: CPU 使用率
    - memory_mb: 内存使用量（MB）

    同时保留兼容字段和新字段，确保向后兼容。

    Args:
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准性能指标响应.
    """
    request_id = uuid.uuid4().hex[:16]
    health_metrics = kernel.get_component("health_metrics")

    if health_metrics:
        try:
            metrics_data = await health_metrics.get_metrics(request_id=request_id)
        except Exception as e:
            logger.error("m8_metrics.failed", error=str(e), trace_id=request_id)
            metrics_data = {}
    else:
        metrics_data = {}

    # 获取 M8 标准字段
    sync_status = await _get_sync_status(kernel)
    edge_nodes = await _count_edge_nodes_async(kernel)
    cloud_nodes = _count_cloud_nodes(kernel)

    compatible_data = {
        # M8 标准字段
        "sync_status": sync_status,
        "edge_nodes": edge_nodes,
        "cloud_nodes": cloud_nodes,
        "sync_queue_size": metrics_data.get("pending_sync_items", 0),
        "cpu_usage": metrics_data.get("cpu_percent", 0.0),
        "memory_mb": int(metrics_data.get("memory_mb", 0)),
        # 兼容字段（旧字段名）
        "devices_connected": metrics_data.get("conflict_count", 0),
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

    logger.info(
        "m8_metrics.ok",
        trace_id=request_id,
        sync_status=sync_status,
        edge_nodes=edge_nodes,
        cloud_nodes=cloud_nodes,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }


@router.get("/config", summary="M8标准配置查询")
async def m8_std_config(
    _auth: bool = Depends(verify_m8_token),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """M8 标准配置查询接口.

    返回脱敏后的配置信息，包含环境、同步模式等关键字段。
    敏感字段（如 encryption_key、admin_token）已脱敏为 ***。

    Args:
        _auth: 鉴权结果（依赖注入）.
        kernel: 内核管理器.

    Returns:
        M8 标准配置响应.
    """
    request_id = uuid.uuid4().hex[:16]
    config_manager = kernel.get_component("config_manager")

    if config_manager:
        try:
            config_data = config_manager.get_config_sanitized(request_id=request_id)
        except Exception as e:
            logger.error("m8_config.failed", error=str(e), trace_id=request_id)
            config_data = {}
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
        # M8 标准字段
        "module": M3_MODULE_NAME,
        "version": M3_VERSION,
        "env": env,
        "sync_mode": sync_cfg.get("mode", "auto"),
        "offline_enabled": offline_cfg.get("enabled", True),
        # 完整配置（已脱敏）
        "config": config_data,
    }

    logger.info("m8_config.ok", trace_id=request_id, env=env)
    return {
        "code": 0,
        "message": "ok",
        "data": compatible_data,
    }
