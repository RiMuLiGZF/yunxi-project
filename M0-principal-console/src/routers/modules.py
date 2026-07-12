"""
M0 主理人管控台 - 模块管理路由

提供模块列表、详情、状态操作等接口。
数据通过 M8 客户端代理获取，M8 不可用时返回 mock。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from ..auth import get_principal_user
from ..errors import NotFoundError
from ..models import ApiResponse, ModuleDetail, ModuleStatusItem
from ..services.m8_client import m8_client

router = APIRouter(tags=["模块管理"])


@router.get("", summary="获取模块列表")
async def list_modules(
    status: Optional[str] = Query(None, description="按状态筛选"),
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[ModuleStatusItem]]:
    """
    获取所有模块列表

    Args:
        status: 可选，按状态筛选（running/stopped/degraded/unknown）
    """
    modules = await m8_client.get_modules()

    if status:
        modules = [m for m in modules if m.status == status]

    return ApiResponse.success(data=modules, message=f"共 {len(modules)} 个模块")


@router.get("/{module_key}", summary="获取模块详情")
async def get_module(
    module_key: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[ModuleDetail]:
    """
    获取单个模块的详细信息

    Args:
        module_key: 模块标识（如 m1, m8 等）
    """
    detail = await m8_client.get_module_detail(module_key)
    if not detail:
        raise NotFoundError(message=f"模块 {module_key} 不存在")

    return ApiResponse.success(data=detail, message="获取成功")


@router.post("/{module_key}/restart", summary="重启模块")
async def restart_module(
    module_key: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    重启指定模块（MVP 版本：模拟操作）

    Args:
        module_key: 模块标识
    """
    # MVP 版本：模拟重启操作，实际应调用 M8 接口
    return ApiResponse.success(
        data={"module_key": module_key, "action": "restart", "status": "success"},
        message=f"模块 {module_key} 重启指令已发送",
    )


@router.post("/{module_key}/stop", summary="停止模块")
async def stop_module(
    module_key: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    停止指定模块（MVP 版本：模拟操作）
    """
    return ApiResponse.success(
        data={"module_key": module_key, "action": "stop", "status": "success"},
        message=f"模块 {module_key} 停止指令已发送",
    )


@router.post("/{module_key}/start", summary="启动模块")
async def start_module(
    module_key: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    启动指定模块（MVP 版本：模拟操作）
    """
    return ApiResponse.success(
        data={"module_key": module_key, "action": "start", "status": "success"},
        message=f"模块 {module_key} 启动指令已发送",
    )


@router.get("/{module_key}/logs", summary="获取模块日志")
async def get_module_logs(
    module_key: str,
    lines: int = Query(100, ge=10, le=1000, description="日志行数"),
    user: dict = Depends(get_principal_user),
) -> ApiResponse[list]:
    """
    获取模块的最近日志（MVP 版本：返回 mock 数据）
    """
    # MVP 版本：模拟日志数据
    mock_logs = [
        {"timestamp": "2026-07-12T10:00:00", "level": "INFO", "message": f"[{module_key}] 服务启动完成"},
        {"timestamp": "2026-07-12T10:00:01", "level": "INFO", "message": f"[{module_key}] 数据库连接成功"},
        {"timestamp": "2026-07-12T10:00:02", "level": "INFO", "message": f"[{module_key}] 注册到 M8 控制塔"},
        {"timestamp": "2026-07-12T10:05:00", "level": "WARN", "message": f"[{module_key}] 检测到请求延迟升高"},
        {"timestamp": "2026-07-12T10:10:00", "level": "INFO", "message": f"[{module_key}] 处理请求 1000 次"},
    ]
    return ApiResponse.success(data=mock_logs[:lines], message="获取成功")
