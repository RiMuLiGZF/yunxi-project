"""
安全相关路由 - 紧急制动等安全功能
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ...schemas import ApiResponse
from ...auth import get_current_user, has_role
from ...audit import add_audit_log

router = APIRouter()

# ==================== 紧急制动状态存储 ====================

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


BRAKE_FILE = _get_yunxi_dir() / "emergency_brake.json"


def _load_brake_status() -> dict:
    """加载紧急制动状态"""
    if BRAKE_FILE.exists():
        try:
            with open(BRAKE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active": False,
        "reason": "",
        "triggered_by": "",
        "triggered_at": "",
        "released_by": "",
        "released_at": "",
    }


def _save_brake_status(status: dict) -> None:
    """保存紧急制动状态"""
    with open(BRAKE_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def is_emergency_brake_active() -> bool:
    """检查紧急制动是否激活"""
    status = _load_brake_status()
    return status.get("active", False)


# ==================== Pydantic 模型 ====================

class EmergencyBrakeRequest(BaseModel):
    reason: str = ""


class ReleaseBrakeRequest(BaseModel):
    reason: str = ""


# ==================== 接口 ====================

@router.get("/brake-status")
async def get_brake_status(current_user: dict = Depends(get_current_user)):
    """获取紧急制动状态（所有登录用户可查看）"""
    status = _load_brake_status()
    return ApiResponse.success(
        data={
            "active": status.get("active", False),
            "reason": status.get("reason", ""),
            "triggered_by": status.get("triggered_by", ""),
            "triggered_at": status.get("triggered_at", ""),
            "released_by": status.get("released_by", ""),
            "released_at": status.get("released_at", ""),
        }
    )


@router.post("/emergency-brake")
async def trigger_emergency_brake(
    req: EmergencyBrakeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """触发紧急制动（仅 owner）
    
    制动后所有写操作（POST/PUT/DELETE）将被禁止，系统进入只读模式。
    """
    # 仅 owner 可触发紧急制动
    if not has_role(current_user.get("role", ""), "owner"):
        return ApiResponse.error(code=403, message="无权限触发紧急制动，需要主理人角色")

    status = _load_brake_status()

    if status.get("active", False):
        return ApiResponse.error(code=400, message="紧急制动已处于激活状态")

    # 激活制动
    status["active"] = True
    status["reason"] = req.reason or "未提供原因"
    status["triggered_by"] = current_user.get("username", "")
    status["triggered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status["released_by"] = ""
    status["released_at"] = ""
    _save_brake_status(status)

    # 记录审计日志
    ip = request.client.host if request.client else "unknown"
    add_audit_log(
        action="emergency_brake",
        module="security",
        result="success",
        username=current_user.get("username", ""),
        ip=ip,
        user_agent=request.headers.get("User-Agent", ""),
        details={"reason": req.reason},
    )

    return ApiResponse.success(
        message="紧急制动已激活，系统进入只读模式",
        data={
            "active": True,
            "reason": status["reason"],
            "triggered_by": status["triggered_by"],
            "triggered_at": status["triggered_at"],
        },
    )


@router.post("/emergency-brake/release")
async def release_emergency_brake(
    req: ReleaseBrakeRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """解除紧急制动（仅 owner）"""
    # 仅 owner 可解除紧急制动
    if not has_role(current_user.get("role", ""), "owner"):
        return ApiResponse.error(code=403, message="无权限解除紧急制动，需要主理人角色")

    status = _load_brake_status()

    if not status.get("active", False):
        return ApiResponse.error(code=400, message="紧急制动未处于激活状态")

    # 解除制动
    status["active"] = False
    status["released_by"] = current_user.get("username", "")
    status["released_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_brake_status(status)

    # 记录审计日志
    ip = request.client.host if request.client else "unknown"
    add_audit_log(
        action="release_brake",
        module="security",
        result="success",
        username=current_user.get("username", ""),
        ip=ip,
        user_agent=request.headers.get("User-Agent", ""),
        details={"reason": req.reason},
    )

    return ApiResponse.success(
        message="紧急制动已解除，系统恢复正常模式",
        data={
            "active": False,
            "released_by": status["released_by"],
            "released_at": status["released_at"],
        },
    )


@router.get("/security/overview")
async def security_overview(current_user: dict = Depends(get_current_user)):
    """安全概览（仅 owner 可查看完整信息）"""
    user_role = current_user.get("role", "")
    is_owner = has_role(user_role, "owner")

    brake_status = _load_brake_status()

    overview = {
        "emergency_brake_active": brake_status.get("active", False),
        "emergency_brake_reason": brake_status.get("reason", ""),
    }

    if is_owner:
        # owner 可以看到更多安全信息
        overview.update({
            "triggered_by": brake_status.get("triggered_by", ""),
            "triggered_at": brake_status.get("triggered_at", ""),
            "released_by": brake_status.get("released_by", ""),
            "released_at": brake_status.get("released_at", ""),
        })

    return ApiResponse.success(data=overview)
