"""
M0 主理人管控台 - 系统升级与回滚路由

管理系统版本升级和回滚操作。
MVP 版本：提供接口骨架和模拟数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends

from ..auth import get_principal_user
from ..config import settings
from ..models import ApiResponse, VersionInfo

router = APIRouter(tags=["系统升级"])


# Mock 版本历史
VERSION_HISTORY: List[dict] = [
    {
        "version": "0.1.0",
        "release_date": "2026-07-10",
        "status": "current",
        "release_notes": "MVP 版本发布，包含仪表盘、模块管理、配置中心等核心功能。",
        "changes": [
            "新增：全局仪表盘",
            "新增：模块管理页面",
            "新增：全局配置中心",
            "新增：权限管理",
            "新增：审计日志",
            "新增：紧急操作中心",
            "新增：主理人专属工具",
        ],
    },
]


@router.get("/version", summary="获取当前版本信息")
async def get_version_info(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[VersionInfo]:
    """
    获取当前版本信息和可用更新

    MVP 版本：不实际检查更新，返回当前版本。
    """
    version_info = VersionInfo(
        current_version=settings.version,
        latest_version=settings.version,
        release_notes="当前已是最新版本",
        upgrade_available=False,
        last_check_time=datetime.now(),
    )

    return ApiResponse.success(data=version_info, message="获取成功")


@router.get("/history", summary="获取版本历史")
async def get_version_history(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[dict]]:
    """
    获取系统版本历史记录
    """
    return ApiResponse.success(data=VERSION_HISTORY, message=f"共 {len(VERSION_HISTORY)} 个版本")


@router.post("/check", summary="检查更新")
async def check_upgrade(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[VersionInfo]:
    """
    检查是否有新版本可用（MVP 版本：模拟）
    """
    version_info = VersionInfo(
        current_version=settings.version,
        latest_version=settings.version,
        release_notes="当前已是最新版本",
        upgrade_available=False,
        last_check_time=datetime.now(),
    )

    return ApiResponse.success(data=version_info, message="检查完成")


@router.post("/upgrade", summary="执行系统升级")
async def perform_upgrade(
    target_version: Optional[str] = None,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    执行系统升级（MVP 版本：模拟操作）

    Args:
        target_version: 目标版本，为空则升级到最新版本
    """
    # MVP 版本：模拟升级
    return ApiResponse.success(
        data={
            "action": "upgrade",
            "from_version": settings.version,
            "to_version": target_version or "latest",
            "status": "started",
            "message": "升级任务已启动，请在任务列表中查看进度",
        },
        message="升级任务已提交",
    )


@router.post("/rollback", summary="系统回滚")
async def perform_rollback(
    target_version: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    回滚到指定版本（MVP 版本：模拟操作）

    Args:
        target_version: 要回滚到的版本号
    """
    return ApiResponse.success(
        data={
            "action": "rollback",
            "from_version": settings.version,
            "to_version": target_version,
            "status": "started",
        },
        message="回滚任务已提交",
    )


@router.get("/tasks", summary="获取升级任务列表")
async def list_upgrade_tasks(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[list]:
    """
    获取升级/回滚任务列表（MVP 版本：空列表）
    """
    return ApiResponse.success(data=[], message="暂无任务")
