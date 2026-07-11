"""
M6 硬件外设 - 设备控制 API
设备动作指令、通知推送
"""

import uuid
import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.device_manager import get_device_manager
from ..services.notification import get_notification_service

router = APIRouter()


def _success(data=None, message: str = "ok"):
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


# 请求模型
class DeviceActionRequest(BaseModel):
    """设备动作请求"""
    action: str = Field(..., description="动作名称，如 take_photo, start_exercise 等")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="动作参数")


class NotifyRequest(BaseModel):
    """通知推送请求"""
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    notification_type: str = Field("info", description="通知类型: info/warning/error")


@router.post("/{device_id}/action", summary="发送设备动作指令")
async def send_device_action(device_id: str, body: DeviceActionRequest):
    """向设备发送动作指令

    支持的动作因设备类型而异：
    - 手表: start_exercise, stop_exercise, find_device
    - 戒指: meditation, sleep_tracking
    - 桌面屏: display_schedule, video_call, toggle_screen
    - AR眼镜: start_navigation, translate, display_info, power_off
    - 无人机: takeoff, return_home, take_photo, start_video, stop_video, deliver
    - 笔记本: start_work, focus_mode, sleep
    """
    dm = get_device_manager()
    sim = dm.get_simulator(device_id)
    if not sim:
        raise HTTPException(status_code=404, detail=f"设备不存在: {device_id}")

    result = sim.execute_action(body.action, body.params)

    if not result.get("success", False):
        raise HTTPException(status_code=400, detail=result.get("message", "动作执行失败"))

    return _success(result, "指令已发送")


@router.post("/{device_id}/notify", summary="向设备推送通知")
async def push_notification(device_id: str, body: NotifyRequest):
    """向指定设备推送通知消息"""
    dm = get_device_manager()
    device = dm.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"设备不存在: {device_id}")

    ns = get_notification_service()
    result = ns.push_to_device(
        device_id=device_id,
        title=body.title,
        content=body.content,
        notification_type=body.notification_type,
    )

    if not result.get("success", False):
        raise HTTPException(status_code=400, detail=result.get("message", "推送失败"))

    return _success(result, "通知已推送")


@router.get("/{device_id}/alerts", summary="获取设备告警列表")
async def get_device_alerts(
    device_id: str,
    limit: int = 20,
    clear: bool = False,
):
    """获取设备的告警列表"""
    dm = get_device_manager()
    device = dm.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"设备不存在: {device_id}")

    ns = get_notification_service()
    alerts = ns.get_recent_alerts(device_id=device_id, limit=limit, clear=clear)

    return _success({
        "device_id": device_id,
        "total": len(alerts),
        "alerts": alerts,
    })


@router.get("/{device_id}/notifications", summary="获取设备通知历史")
async def get_device_notifications(
    device_id: str,
    limit: int = 50,
):
    """获取设备的通知历史"""
    dm = get_device_manager()
    device = dm.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"设备不存在: {device_id}")

    ns = get_notification_service()
    notifications = ns.get_recent_notifications(device_id=device_id, limit=limit)

    return _success({
        "device_id": device_id,
        "total": len(notifications),
        "notifications": notifications,
    })
