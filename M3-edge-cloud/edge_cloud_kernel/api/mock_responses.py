"""统一 Mock 响应层.

集中管理所有 API 路由的 Mock 响应逻辑，消除路由层重复代码。
提供标准 M8 响应格式包装器和各模块的 Mock 数据生成器。

使用方式：
    from edge_cloud_kernel.api.mock_responses import mock_response, mock_config_data

    # 标准包装
    return mock_response(data={"key": "value"})

    # 组件调用失败时自动降级
    result = try_call_component()
    if result is None:
        return mock_response(data=mock_config_data())
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from edge_cloud_kernel.core.kernel_manager import KernelManager


# ---------------------------------------------------------------------------
# 标准响应包装器
# ---------------------------------------------------------------------------

def mock_response(
    data: Any = None,
    code: int = 0,
    message: str = "Success",
    trace_id: str = "",
) -> dict[str, Any]:
    """Mock M8 标准响应格式（带 mock 标识）.

    Args:
        data: 响应数据.
        code: 错误码.
        message: 消息.
        trace_id: 追踪 ID，为空则自动生成.

    Returns:
        标准 M8 响应字典.
    """
    if isinstance(data, dict):
        data = {"mode": "mock", **data}
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": trace_id or uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


def real_response(
    data: Any,
    code: int = 0,
    message: str = "Success",
    trace_id: str = "",
) -> dict[str, Any]:
    """真实模式标准响应格式（带 real 标识）.

    Args:
        data: 响应数据.
        code: 错误码.
        message: 消息.
        trace_id: 追踪 ID.

    Returns:
        标准 M8 响应字典.
    """
    if isinstance(data, dict):
        data = {"mode": "real", **data}
    return {
        "code": code,
        "message": message,
        "data": data,
        "trace_id": trace_id or uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# 配置模块 Mock 数据
# ---------------------------------------------------------------------------

def mock_config_data() -> dict[str, Any]:
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


def mock_config_update_result(updates: dict[str, Any]) -> dict[str, Any]:
    """Mock 配置更新结果.

    Args:
        updates: 更新的键值对.

    Returns:
        Mock 更新结果字典.
    """
    return {
        "updated_keys": list(updates.keys()),
        "rejected_keys": [],
        "restart_required": False,
    }


# ---------------------------------------------------------------------------
# 设备模块 Mock 数据
# ---------------------------------------------------------------------------

def mock_device_list(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """Mock 设备列表数据.

    Args:
        page: 页码.
        page_size: 每页条数.
        status: 状态过滤.

    Returns:
        Mock 设备列表字典.
    """
    return {
        "total": 0,
        "page": page,
        "page_size": page_size,
        "devices": [],
    }


def mock_device_remove_result(device_id: str) -> dict[str, Any]:
    """Mock 设备移除结果.

    Args:
        device_id: 设备 ID.

    Returns:
        Mock 移除结果字典.
    """
    return {
        "device_id": device_id,
        "removed": True,
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# 同步模块 Mock 数据
# ---------------------------------------------------------------------------

def mock_sync_status() -> dict[str, Any]:
    """Mock 同步状态数据.

    Returns:
        Mock 同步状态字典.
    """
    return {
        "status": "idle",
        "last_sync_at": None,
        "last_sync_result": None,
        "pending_changes": 0,
        "conflict_count": 0,
        "queue_depth": 0,
        "network_state": "unknown",
        "health_endpoints": [],
    }


def mock_sync_trigger_result(
    scope: list[str] | None = None,
    conflict_strategy: str = "newest_wins",
) -> dict[str, Any]:
    """Mock 同步触发结果.

    Args:
        scope: 同步范围.
        conflict_strategy: 冲突策略.

    Returns:
        Mock 触发结果字典.
    """
    return {
        "sync_id": uuid.uuid4().hex[:16],
        "scope": scope or ["all"],
        "conflict_strategy": conflict_strategy,
        "status": "triggered",
        "triggered_at": time.time(),
    }


def mock_conflict_list(page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """Mock 冲突列表数据.

    Args:
        page: 页码.
        page_size: 每页条数.

    Returns:
        Mock 冲突列表字典.
    """
    return {
        "total": 0,
        "page": page,
        "page_size": page_size,
        "conflicts": [],
    }


def mock_conflict_resolve_result(
    conflict_id: str,
    resolution: dict[str, Any],
) -> dict[str, Any]:
    """Mock 冲突解决结果.

    Args:
        conflict_id: 冲突 ID.
        resolution: 解决数据.

    Returns:
        Mock 解决结果字典.
    """
    return {
        "conflict_id": conflict_id,
        "resolved": True,
        "resolution": resolution,
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# 健康检查 Mock 数据
# ---------------------------------------------------------------------------

def mock_health_data(kernel: KernelManager) -> dict[str, Any]:
    """Mock 健康检查数据.

    Args:
        kernel: 内核管理器实例.

    Returns:
        Mock 健康数据字典.
    """
    return {
        "mode": "mock",
        "status": "healthy",
        "version": "2.1.2",
        "uptime_seconds": kernel.uptime_seconds,
        "module": "m3",
        "checks": {
            "database": "healthy",
            "storage": "healthy",
            "network": "unknown",
            "sync_engine": "healthy",
        },
    }


def mock_metrics_data() -> dict[str, Any]:
    """Mock 性能指标数据.

    Returns:
        Mock 性能指标字典.
    """
    return {
        "mode": "mock",
        "cpu_percent": 0.0,
        "memory_mb": 0.0,
        "disk_usage_mb": 0.0,
        "requests_total": 0,
        "requests_per_second": 0.0,
        "avg_response_ms": 0.0,
        "error_rate": 0.0,
        "sync_tasks_total": 0,
        "sync_success_rate": 1.0,
        "pending_sync_items": 0,
        "conflict_count": 0,
        "offline_queue_size": 0,
    }


# ---------------------------------------------------------------------------
# 便捷工具：组件调用 + 自动降级
# ---------------------------------------------------------------------------

async def call_or_mock(
    kernel: KernelManager,
    component_name: str,
    method_name: str,
    mock_data: Any,
    trace_id: str = "",
    **kwargs,
) -> dict[str, Any]:
    """尝试调用真实组件，失败则返回 Mock 响应.

    统一封装路由层中重复的 "真实调用 + 异常捕获 + Mock 降级" 模式。

    Args:
        kernel: 内核管理器.
        component_name: 组件名称（需在 KernelManager 中注册）.
        method_name: 要调用的方法名.
        mock_data: Mock 时返回的数据.
        trace_id: 追踪 ID.
        **kwargs: 传递给组件方法的参数.

    Returns:
        标准响应字典（真实或 Mock）.
    """
    component = kernel.get_component(component_name)

    if component is not None and not kernel.is_mock(component_name):
        try:
            method = getattr(component, method_name)
            result = await method(**kwargs)
            # 处理不同返回类型
            if hasattr(result, "to_dict"):
                data = result.to_dict()
            elif isinstance(result, dict):
                data = result
            else:
                data = {"value": result}
            return real_response(data=data, trace_id=trace_id)
        except Exception as e:
            import structlog
            logger = structlog.get_logger(__name__)
            logger.error(
                f"{component_name}.{method_name}.failed",
                error=str(e),
                trace_id=trace_id,
            )

    # Mock 降级
    if callable(mock_data):
        data = mock_data()
    else:
        data = mock_data
    return mock_response(data=data, trace_id=trace_id)
