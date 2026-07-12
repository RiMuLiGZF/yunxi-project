"""
M0 主理人管控台 - 紧急操作中心路由

提供系统级紧急操作，如紧急锁定、一键关停等。
所有操作均需要 Owner 角色，且会记录审计日志。
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Request

from ..auth import get_principal_user
from ..errors import ValidationError
from ..models import ApiResponse, EmergencyAction, EmergencyActionResult

router = APIRouter(tags=["紧急操作"])

# 系统紧急状态（内存态，MVP 版本）
_emergency_state: dict = {
    "locked": False,
    "locked_at": None,
    "locked_by": None,
    "lock_reason": "",
}

# 可用的紧急操作
EMERGENCY_ACTIONS: List[dict] = [
    {
        "key": "lockdown",
        "name": "系统紧急锁定",
        "description": "立即锁定整个系统，禁止所有非 Owner 用户访问",
        "danger_level": "critical",
        "confirm_required": True,
    },
    {
        "key": "stop_all_modules",
        "name": "一键关停所有模块",
        "description": "停止所有业务模块，仅保留 M0 和 M8 核心运行",
        "danger_level": "high",
        "confirm_required": True,
    },
    {
        "key": "reset_sessions",
        "name": "重置所有会话",
        "description": "强制所有用户重新登录，清除所有有效 Token",
        "danger_level": "medium",
        "confirm_required": True,
    },
    {
        "key": "emergency_backup",
        "name": "紧急数据备份",
        "description": "立即触发全量数据备份",
        "danger_level": "low",
        "confirm_required": False,
    },
]


@router.get("/status", summary="获取紧急状态")
async def get_emergency_status(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[dict]:
    """
    获取当前系统紧急状态
    """
    return ApiResponse.success(
        data={
            "locked": _emergency_state["locked"],
            "locked_at": _emergency_state["locked_at"],
            "locked_by": _emergency_state["locked_by"],
            "lock_reason": _emergency_state["lock_reason"],
        },
        message="获取成功",
    )


@router.get("/actions", summary="获取可用紧急操作")
async def list_emergency_actions(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[dict]]:
    """
    获取所有可用的紧急操作列表
    """
    return ApiResponse.success(data=EMERGENCY_ACTIONS, message=f"共 {len(EMERGENCY_ACTIONS)} 个操作")


@router.post("/lockdown", summary="系统紧急锁定")
async def emergency_lockdown(
    request: Request,
    action: EmergencyAction,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[EmergencyActionResult]:
    """
    执行系统紧急锁定

    锁定后所有非 Owner 用户将无法访问系统，
    直到手动解除锁定。
    """
    if _emergency_state["locked"]:
        raise ValidationError(message="系统已处于锁定状态")

    _emergency_state["locked"] = True
    _emergency_state["locked_at"] = datetime.now().isoformat()
    _emergency_state["locked_by"] = user["username"]
    _emergency_state["lock_reason"] = action.reason

    result = EmergencyActionResult(
        success=True,
        action="lockdown",
        message="系统已紧急锁定，所有非 Owner 用户已被禁止访问",
    )

    return ApiResponse.success(data=result, message="紧急锁定已执行")


@router.post("/unlock", summary="解除系统锁定")
async def emergency_unlock(
    action: EmergencyAction,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[EmergencyActionResult]:
    """
    解除系统紧急锁定
    """
    if not _emergency_state["locked"]:
        raise ValidationError(message="系统未处于锁定状态")

    _emergency_state["locked"] = False
    _emergency_state["locked_at"] = None
    _emergency_state["locked_by"] = None
    _emergency_state["lock_reason"] = ""

    result = EmergencyActionResult(
        success=True,
        action="unlock",
        message="系统已解除锁定，恢复正常运行",
    )

    return ApiResponse.success(data=result, message="锁定已解除")


@router.post("/stop-all-modules", summary="一键关停所有模块")
async def stop_all_modules(
    action: EmergencyAction,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[EmergencyActionResult]:
    """
    一键关停所有业务模块（MVP 版本：模拟操作）

    仅保留 M0 管控台和 M8 控制塔核心运行。
    """
    # MVP 版本：模拟操作
    result = EmergencyActionResult(
        success=True,
        action="stop_all_modules",
        message="已发送关停指令到所有业务模块",
    )

    return ApiResponse.success(data=result, message="操作已执行")


@router.post("/reset-sessions", summary="重置所有会话")
async def reset_all_sessions(
    action: EmergencyAction,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[EmergencyActionResult]:
    """
    重置所有用户会话（MVP 版本：模拟操作）

    强制所有用户重新登录。
    """
    result = EmergencyActionResult(
        success=True,
        action="reset_sessions",
        message="所有会话已重置，用户需重新登录",
    )

    return ApiResponse.success(data=result, message="操作已执行")


@router.post("/backup", summary="紧急数据备份")
async def emergency_backup(
    action: EmergencyAction,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[EmergencyActionResult]:
    """
    触发紧急数据备份（MVP 版本：模拟操作）
    """
    result = EmergencyActionResult(
        success=True,
        action="emergency_backup",
        message="备份任务已启动，请稍候查看结果",
    )

    return ApiResponse.success(data=result, message="备份任务已提交")
