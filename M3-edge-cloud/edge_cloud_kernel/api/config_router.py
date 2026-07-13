"""配置管理路由.

提供配置管理相关的 API 端点：
- GET  /api/v3/config          - 获取配置（敏感字段脱敏）
- POST /api/v3/config/update   - 更新配置（点路径，热更新）
- GET  /api/v1/config          - v1 别名
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.core.kernel_manager import KernelManager
from edge_cloud_kernel.models.api_requests import ConfigUpdateRequest

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Config"])


# ---------------------------------------------------------------------------
# Mock 数据辅助函数
# ---------------------------------------------------------------------------

def _mock_m8_response(
    data: Any = None,
    code: int = 0,
    message: str = "Success",
) -> dict[str, Any]:
    """Mock M8 标准响应格式（带 mock 标识）.

    Args:
        data: 响应数据.
        code: 错误码.
        message: 消息.

    Returns:
        标准 M8 响应字典.
    """
    if isinstance(data, dict):
        data = {"mode": "mock", **data}
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


def _mock_config_data() -> dict[str, Any]:
    """Mock 配置数据（脱敏，带 mock 标识）.

    Returns:
        Mock 配置字典.
    """
    return {
        "mode": "mock",
        "basic": {
            "name": "m3-sync",
            "version": "2.1.2",
            "port": 8003,
            "log_level": "info",
            "env": "production",
        },
        "security": {
            "encryption_key": "***",
            "admin_token": "***",
            "cors_origins": ["http://localhost:3000"],
            "e2ee": {"enabled": True, "algorithm": "AES-256-GCM"},
        },
        "sync": {
            "mode": "auto",
            "interval": 60,
            "conflict_strategy": "newest_wins",
            "max_concurrent": 10,
            "max_file_size": 100,
        },
        "storage": {
            "local_path": "./data/sync",
            "cloud_type": "local",
            "cloud_path": "./data/cloud",
            "cache_size": 512,
        },
        "offline": {
            "queue_size": 1000,
            "retry": {"max_attempts": 5, "backoff": "exponential"},
        },
        "database": {"type": "sqlite", "path": "./data/m3.db"},
        "logging": {
            "format": "json",
            "level": "info",
            "file": "./logs/m3.log",
            "max_size": "100MB",
            "max_files": 10,
            "sensitive_fields": ["encryption_key", "password"],
        },
        "devices": {"registry_type": "memory", "db_path": "./data/devices.db"},
    }


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------

@router.get("/api/v3/config", summary="获取配置")
async def get_config(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取配置（敏感字段脱敏）.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        配置数据响应.
    """
    config_manager = kernel.get_component("config_manager")

    if config_manager is not None and not kernel.is_mock("config_manager"):
        try:
            result = config_manager.get_config_sanitized(request_id=trace_id)
            return _mock_m8_response(data=result)
        except Exception as e:
            logger.error("config.get.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return _mock_m8_response(data=_mock_config_data())


@router.post("/api/v3/config/update", summary="更新配置")
async def update_config(
    request: Request,
    body: ConfigUpdateRequest,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """更新配置（点路径方式，热更新）.

    Args:
        request: FastAPI 请求对象.
        body: 配置更新请求体.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        更新结果响应.
    """
    config_manager = kernel.get_component("config_manager")

    if config_manager is not None and not kernel.is_mock("config_manager"):
        try:
            success, result = config_manager.update_config(
                updates=body.updates,
                request_id=trace_id,
            )
            if not success:
                raise HTTPException(status_code=400, detail=result)
            return _mock_m8_response(data=result)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("config.update.failed", error=str(e), trace_id=trace_id)
            raise HTTPException(status_code=500, detail=str(e))

    # Mock 模式
    return _mock_m8_response(data={
        "updated_keys": list(body.updates.keys()),
        "rejected_keys": [],
        "restart_required": False,
    })


# ---------------------------------------------------------------------------
# v1 别名路由
# ---------------------------------------------------------------------------

@router.get("/api/v1/config", tags=["V1 Alias"], summary="v1获取配置（别名）")
async def v1_config(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """v1 获取配置别名，转发到 v3 接口."""
    return await get_config(request, trace_id=trace_id, kernel=kernel)
