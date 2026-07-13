"""手表交互服务 - FastAPI 路由.

提供手表交互的 REST API 接口，包括设备管理、健康数据、
通知推送、手表端配置等。
"""

from __future__ import annotations

from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.models.db import get_session
from src.models import make_response
from src.services.watch_service import WatchService


router = APIRouter(prefix="/api/v1/watch", tags=["手表交互"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class BindDeviceRequest(BaseModel):
    """绑定设备请求体."""

    device_id: str = Field(..., description="设备ID")
    name: str = Field(..., description="设备名称")
    device_type: str = Field("watch", description="设备类型：watch/ring/band")
    mac_address: Optional[str] = Field("", description="MAC地址")


class SendNotificationRequest(BaseModel):
    """发送通知请求体."""

    device_id: str = Field(..., description="设备ID")
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    notification_type: str = Field("info", description="通知类型：info/warning/error/reminder")
    action_type: Optional[str] = Field("", description="动作类型")
    action_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="动作数据")


class HealthSyncRequest(BaseModel):
    """健康数据同步请求体."""

    device_id: str = Field(..., description="设备ID")
    data_type: Optional[str] = Field(None, description="数据类型，不传则同步全部")
    days: int = Field(7, ge=1, le=90, description="同步天数")


class WatchSettingsUpdate(BaseModel):
    """手表配置更新请求体."""

    settings: Dict[str, Any] = Field(..., description="配置项字典")


class DeviceUpdateRequest(BaseModel):
    """设备信息更新请求体."""

    name: Optional[str] = Field(None, description="设备名称")
    status: Optional[str] = Field(None, description="设备状态")
    battery: Optional[int] = Field(None, description="电量")
    features: Optional[List[str]] = Field(None, description="支持的功能列表")
    settings: Optional[Dict[str, Any]] = Field(None, description="设备配置")


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_watch_service(
    db: Session = Depends(get_session),
    user_id: str = Query("default", description="用户ID"),
) -> WatchService:
    """获取手表服务实例.

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        手表服务实例
    """
    return WatchService(db, user_id=user_id)


# ---------------------------------------------------------------------------
# 设备管理
# ---------------------------------------------------------------------------


@router.get("/devices", summary="获取设备列表")
async def list_devices(
    status: Optional[str] = Query(None, description="按状态过滤：online/offline"),
    device_type: Optional[str] = Query(None, description="按类型过滤：watch/ring/band"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    service: WatchService = Depends(get_watch_service),
):
    """获取已绑定的手表设备列表."""
    result = service.list_devices(
        status=status,
        device_type=device_type,
        page=page,
        page_size=page_size,
    )
    return make_response(data=result, message="ok")


@router.get("/devices/{device_id}", summary="获取设备详情")
async def get_device(
    device_id: str,
    service: WatchService = Depends(get_watch_service),
):
    """获取单个设备的详细信息."""
    result = service.get_device(device_id)
    if result is None:
        return make_response(code=404, message="设备不存在", data={})
    return make_response(data=result, message="ok")


@router.post("/devices", summary="绑定设备")
async def bind_device(
    req: BindDeviceRequest,
    service: WatchService = Depends(get_watch_service),
):
    """绑定一个新的手表设备."""
    try:
        result = service.bind_device(
            device_id=req.device_id,
            name=req.name,
            device_type=req.device_type,
            mac_address=req.mac_address or "",
        )
        return make_response(data=result, message="设备绑定成功")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.delete("/devices/{device_id}", summary="解绑设备")
async def unbind_device(
    device_id: str,
    service: WatchService = Depends(get_watch_service),
):
    """解绑指定的手表设备."""
    success = service.unbind_device(device_id)
    if not success:
        return make_response(code=404, message="设备不存在", data={})
    return make_response(data={"unbound": True}, message="设备解绑成功")


@router.put("/devices/{device_id}", summary="更新设备信息")
async def update_device(
    device_id: str,
    req: DeviceUpdateRequest,
    service: WatchService = Depends(get_watch_service),
):
    """更新设备信息（名称、状态、电量等）."""
    update_data = req.dict(exclude_unset=True)
    result = service.update_device(device_id, update_data)
    if result is None:
        return make_response(code=404, message="设备不存在", data={})
    return make_response(data=result, message="设备信息已更新")


# ---------------------------------------------------------------------------
# 健康数据
# ---------------------------------------------------------------------------


@router.get("/health/realtime", summary="获取实时健康数据")
async def get_realtime_health(
    device_id: str = Query(..., description="设备ID"),
    service: WatchService = Depends(get_watch_service),
):
    """获取设备的实时健康数据（心率/步数/血氧等）."""
    try:
        result = service.get_realtime_health(device_id)
        return make_response(data=result, message="ok")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.post("/health/sync", summary="同步健康数据")
async def sync_health_data(
    req: HealthSyncRequest,
    service: WatchService = Depends(get_watch_service),
):
    """同步健康数据到数据库（生成 mock 历史数据）."""
    try:
        result = service.sync_health_data(
            device_id=req.device_id,
            data_type=req.data_type,
            days=req.days,
        )
        return make_response(data=result, message="健康数据同步完成")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.get("/health/history", summary="获取健康数据历史")
async def get_health_history(
    device_id: str = Query(..., description="设备ID"),
    data_type: str = Query("heart_rate", description="数据类型：heart_rate/steps/spo2/sleep"),
    days: int = Query(7, ge=1, le=90, description="天数"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    start_time: Optional[str] = Query(None, description="开始时间（ISO格式）"),
    end_time: Optional[str] = Query(None, description="结束时间（ISO格式）"),
    service: WatchService = Depends(get_watch_service),
):
    """获取健康数据历史记录，支持时间范围查询和分页."""
    try:
        result = service.get_health_history(
            device_id=device_id,
            data_type=data_type,
            days=days,
            page=page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
        )
        return make_response(data=result, message="ok")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


# ---------------------------------------------------------------------------
# 通知推送
# ---------------------------------------------------------------------------


@router.post("/notification/send", summary="发送通知到手表")
async def send_notification(
    req: SendNotificationRequest,
    service: WatchService = Depends(get_watch_service),
):
    """向指定手表设备发送通知."""
    try:
        result = service.send_notification(
            device_id=req.device_id,
            title=req.title,
            content=req.content,
            notification_type=req.notification_type,
            action_type=req.action_type or "",
            action_data=req.action_data,
        )
        return make_response(data=result, message="通知发送成功")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.get("/notification/history", summary="获取通知历史")
async def get_notification_history(
    device_id: Optional[str] = Query(None, description="设备ID，不传则返回所有设备"),
    notification_type: Optional[str] = Query(None, description="按类型过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: WatchService = Depends(get_watch_service),
):
    """获取通知发送历史记录."""
    result = service.list_notifications(
        device_id=device_id,
        notification_type=notification_type,
        status=status,
        page=page,
        page_size=page_size,
    )
    return make_response(data=result, message="ok")


@router.post("/notification/{notification_id}/read", summary="标记通知已读")
async def mark_notification_read(
    notification_id: str,
    service: WatchService = Depends(get_watch_service),
):
    """将指定通知标记为已读."""
    success = service.mark_notification_read(notification_id)
    if not success:
        return make_response(code=404, message="通知不存在", data={})
    return make_response(data={"read": True}, message="通知已标记为已读")


# ---------------------------------------------------------------------------
# 手表端配置
# ---------------------------------------------------------------------------


@router.get("/settings/{device_id}", summary="获取手表配置")
async def get_watch_settings(
    device_id: str,
    service: WatchService = Depends(get_watch_service),
):
    """获取指定设备的手表端配置."""
    try:
        result = service.get_watch_settings(device_id)
        return make_response(data=result, message="ok")
    except ValueError as e:
        return make_response(code=404, message=str(e), data={})


@router.put("/settings/{device_id}", summary="更新手表配置")
async def update_watch_settings(
    device_id: str,
    req: WatchSettingsUpdate,
    service: WatchService = Depends(get_watch_service),
):
    """更新手表端配置项."""
    try:
        result = service.update_watch_settings(device_id, req.settings)
        return make_response(data=result, message="配置已更新")
    except ValueError as e:
        return make_response(code=404, message=str(e), data={})
