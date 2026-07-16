"""
M6 硬件外设 - 可穿戴设备 API
==========================

提供可穿戴设备、健康数据、通知推送、设备配置的 CRUD 接口。

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6
"""

from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException, Request

from .deps import get_config
from .utils import success_response
from ..config import M6Config
from ..database.connection import DatabaseConnection
from ..database.wearable_repository import (
    WearableDeviceRepository,
    WearableHealthRepository,
    WearableNotificationRepository,
    WearableSettingsRepository,
)
from ..models.wearable import (
    WearableDeviceCreate,
    WearableDeviceUpdate,
    WearableHealthDataCreate,
    HealthDataQuery,
    WearableNotificationCreate,
    WearableSettingsUpdate,
    WearableDeviceType,
    WearableDeviceStatus,
    HealthDataType,
    NotificationStatus,
)

router = APIRouter()


# ============================================================================
# 依赖：获取数据库连接
# ============================================================================

def get_db_conn(request: Request) -> DatabaseConnection:
    """从配置获取数据库连接工厂"""
    config: M6Config = request.app.state.config
    return DatabaseConnection(config.database_path)


# ============================================================================
# 可穿戴设备管理
# ============================================================================

@router.get("/devices", summary="获取可穿戴设备列表")
async def list_wearable_devices(
    user_id: Optional[str] = Query(None, description="按用户过滤"),
    device_type: Optional[str] = Query(None, description="按设备类型过滤: watch/ring/band/glasses"),
    status: Optional[str] = Query(None, description="按状态过滤: online/offline/charging/warning"),
    limit: int = Query(100, ge=1, le=500, description="分页大小"),
    offset: int = Query(0, ge=0, description="偏移量"),
    config: M6Config = Depends(get_config),
):
    """获取可穿戴设备列表，支持多条件筛选"""
    with DatabaseConnection(config.database_path) as conn:
        devices, total = WearableDeviceRepository.list_devices(
            user_id=user_id,
            device_type=device_type,
            status=status,
            limit=limit,
            offset=offset,
            conn=conn,
        )
    return success_response({
        "total": total,
        "limit": limit,
        "offset": offset,
        "devices": devices,
    })


@router.get("/devices/{device_id}", summary="获取可穿戴设备详情")
async def get_wearable_device(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """根据 device_id 获取单个可穿戴设备详情"""
    with DatabaseConnection(config.database_path) as conn:
        device = WearableDeviceRepository.get_by_device_id(device_id, conn=conn)
    if not device:
        raise HTTPException(status_code=404, detail=f"可穿戴设备不存在: {device_id}")
    return success_response(device)


@router.post("/devices", summary="创建可穿戴设备")
async def create_wearable_device(
    body: WearableDeviceCreate,
    config: M6Config = Depends(get_config),
):
    """创建新的可穿戴设备记录"""
    with DatabaseConnection(config.database_path) as conn:
        # 检查 device_id 是否已存在
        existing = WearableDeviceRepository.get_by_device_id(body.device_id, conn=conn)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"设备 ID 已存在: {body.device_id}",
            )

        device_db_id = WearableDeviceRepository.create(
            device_id=body.device_id,
            user_id=body.user_id,
            name=body.name,
            device_type=body.device_type.value,
            brand=body.brand,
            model=body.model,
            mac_address=body.mac_address,
            status=body.status.value,
            battery_level=body.battery_level,
            firmware_version=body.firmware_version,
            conn=conn,
        )
        device = WearableDeviceRepository.get_by_id(device_db_id, conn=conn)

    return success_response(device, "设备创建成功")


@router.put("/devices/{device_id}", summary="更新可穿戴设备")
async def update_wearable_device(
    device_id: str,
    body: WearableDeviceUpdate,
    config: M6Config = Depends(get_config),
):
    """更新可穿戴设备信息"""
    updates = body.model_dump(exclude_none=True)
    # 枚举转 value
    if "device_type" in updates and updates["device_type"] is not None:
        updates["device_type"] = updates["device_type"].value
    if "status" in updates and updates["status"] is not None:
        updates["status"] = updates["status"].value
    # datetime 转 iso
    if "last_sync_at" in updates and updates["last_sync_at"] is not None:
        updates["last_sync_at"] = updates["last_sync_at"].isoformat()

    if not updates:
        raise HTTPException(status_code=400, detail="没有提供有效的更新字段")

    with DatabaseConnection(config.database_path) as conn:
        success = WearableDeviceRepository.update(device_id, updates, conn=conn)
        if not success:
            raise HTTPException(status_code=404, detail=f"可穿戴设备不存在: {device_id}")
        device = WearableDeviceRepository.get_by_device_id(device_id, conn=conn)

    return success_response(device, "设备更新成功")


@router.delete("/devices/{device_id}", summary="删除可穿戴设备")
async def delete_wearable_device(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """删除可穿戴设备记录"""
    with DatabaseConnection(config.database_path) as conn:
        success = WearableDeviceRepository.delete(device_id, conn=conn)
    if not success:
        raise HTTPException(status_code=404, detail=f"可穿戴设备不存在: {device_id}")
    return success_response(None, "设备删除成功")


@router.get("/devices/stats/summary", summary="可穿戴设备统计")
async def get_wearable_stats(
    config: M6Config = Depends(get_config),
):
    """获取可穿戴设备统计概览"""
    with DatabaseConnection(config.database_path) as conn:
        total = WearableDeviceRepository.count(conn=conn)
        online, _ = WearableDeviceRepository.list_devices(
            status="online", limit=1, conn=conn,
        )
        offline, _ = WearableDeviceRepository.list_devices(
            status="offline", limit=1, conn=conn,
        )
        watch, _ = WearableDeviceRepository.list_devices(
            device_type="watch", limit=1, conn=conn,
        )

    return success_response({
        "total": total,
        "online_count": len(online),
        "offline_count": len(offline),
        "watch_count": len(watch),
    })


# ============================================================================
# 健康数据
# ============================================================================

@router.get("/health/data", summary="查询健康数据")
async def query_health_data(
    device_id: Optional[str] = Query(None, description="设备 ID"),
    user_id: Optional[str] = Query(None, description="用户 ID"),
    data_type: Optional[str] = Query(None, description="数据类型: heart_rate/spo2/steps/sleep/temperature/calories"),
    start_time: Optional[str] = Query(None, description="开始时间 (ISO 格式)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO 格式)"),
    limit: int = Query(1000, ge=1, le=10000, description="分页大小"),
    offset: int = Query(0, ge=0, description="偏移量"),
    config: M6Config = Depends(get_config),
):
    """按条件查询健康数据"""
    with DatabaseConnection(config.database_path) as conn:
        data, total = WearableHealthRepository.query(
            device_id=device_id,
            user_id=user_id,
            data_type=data_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
            conn=conn,
        )
    return success_response({
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": data,
    })


@router.post("/health/data", summary="上报健康数据")
async def report_health_data(
    body: WearableHealthDataCreate,
    config: M6Config = Depends(get_config),
):
    """上报一条健康数据"""
    from datetime import datetime
    recorded_at = body.recorded_at.isoformat() if body.recorded_at else datetime.now().isoformat()

    with DatabaseConnection(config.database_path) as conn:
        record_id = WearableHealthRepository.insert(
            device_id=body.device_id,
            user_id=body.user_id,
            data_type=body.data_type.value,
            value=body.value,
            unit=body.unit,
            recorded_at=recorded_at,
            source=body.source.value,
            quality=body.quality.value,
            conn=conn,
        )

    return success_response({"id": record_id}, "健康数据上报成功")


@router.post("/health/data/batch", summary="批量上报健康数据")
async def batch_report_health_data(
    records: list[WearableHealthDataCreate],
    config: M6Config = Depends(get_config),
):
    """批量上报健康数据"""
    from datetime import datetime

    formatted_records = []
    for r in records:
        recorded_at = r.recorded_at.isoformat() if r.recorded_at else datetime.now().isoformat()
        formatted_records.append({
            "device_id": r.device_id,
            "user_id": r.user_id,
            "data_type": r.data_type.value,
            "value": r.value,
            "unit": r.unit,
            "recorded_at": recorded_at,
            "source": r.source.value,
            "quality": r.quality.value,
        })

    with DatabaseConnection(config.database_path) as conn:
        count = WearableHealthRepository.insert_batch(formatted_records, conn=conn)

    return success_response({"inserted": count}, f"批量上报成功，共 {count} 条")


@router.get("/health/latest/{device_id}", summary="获取最新健康数据")
async def get_latest_health_data(
    device_id: str,
    data_type: Optional[str] = Query(None, description="指定数据类型，不传则返回所有类型最新值"),
    config: M6Config = Depends(get_config),
):
    """获取设备最新的健康数据（每类一条）"""
    with DatabaseConnection(config.database_path) as conn:
        data = WearableHealthRepository.get_latest(
            device_id=device_id,
            data_type=data_type,
            conn=conn,
        )
    return success_response({
        "device_id": device_id,
        "data": data,
    })


# ============================================================================
# 通知推送
# ============================================================================

@router.get("/notifications", summary="获取通知列表")
async def list_notifications(
    device_id: Optional[str] = Query(None, description="设备 ID"),
    user_id: Optional[str] = Query(None, description="用户 ID"),
    status: Optional[str] = Query(None, description="状态: pending/sent/delivered/failed/read"),
    type: Optional[str] = Query(None, description="通知类型"),
    limit: int = Query(100, ge=1, le=500, description="分页大小"),
    offset: int = Query(0, ge=0, description="偏移量"),
    config: M6Config = Depends(get_config),
):
    """获取通知列表，支持筛选"""
    with DatabaseConnection(config.database_path) as conn:
        notifications, total = WearableNotificationRepository.list_notifications(
            device_id=device_id,
            user_id=user_id,
            status=status,
            type_=type,
            limit=limit,
            offset=offset,
            conn=conn,
        )
    return success_response({
        "total": total,
        "limit": limit,
        "offset": offset,
        "notifications": notifications,
    })


@router.get("/notifications/{notification_id}", summary="获取通知详情")
async def get_notification(
    notification_id: str,
    config: M6Config = Depends(get_config),
):
    """根据通知 ID 获取详情"""
    with DatabaseConnection(config.database_path) as conn:
        notification = WearableNotificationRepository.get_by_notification_id(
            notification_id, conn=conn,
        )
    if not notification:
        raise HTTPException(status_code=404, detail=f"通知不存在: {notification_id}")
    return success_response(notification)


@router.post("/notifications", summary="发送通知")
async def send_notification(
    body: WearableNotificationCreate,
    config: M6Config = Depends(get_config),
):
    """创建并发送一条通知"""
    import uuid
    from datetime import datetime

    notification_id = uuid.uuid4().hex

    with DatabaseConnection(config.database_path) as conn:
        record_id = WearableNotificationRepository.create(
            notification_id=notification_id,
            device_id=body.device_id,
            user_id=body.user_id,
            title=body.title,
            content=body.content,
            type_=body.type,
            status="pending",
            source=body.source.value,
            conn=conn,
        )
        notification = WearableNotificationRepository.get_by_id(record_id, conn=conn)

    return success_response(notification, "通知创建成功")


@router.put("/notifications/{notification_id}/status", summary="更新通知状态")
async def update_notification_status(
    notification_id: str,
    status: str = Query(..., description="新状态: pending/sent/delivered/failed/read"),
    config: M6Config = Depends(get_config),
):
    """更新通知的发送/送达状态"""
    # 验证状态值
    valid_statuses = [s.value for s in NotificationStatus]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态值: {status}，有效值: {', '.join(valid_statuses)}",
        )

    from datetime import datetime
    delivered_at = datetime.now().isoformat() if status in ("delivered", "sent") else None

    with DatabaseConnection(config.database_path) as conn:
        success = WearableNotificationRepository.update_status(
            notification_id,
            status,
            delivered_at=delivered_at,
            conn=conn,
        )
        if not success:
            raise HTTPException(status_code=404, detail=f"通知不存在: {notification_id}")
        notification = WearableNotificationRepository.get_by_notification_id(
            notification_id, conn=conn,
        )

    return success_response(notification, "通知状态已更新")


# ============================================================================
# 设备配置
# ============================================================================

@router.get("/settings/{device_id}", summary="获取设备配置")
async def get_device_settings(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """获取指定设备的配置"""
    with DatabaseConnection(config.database_path) as conn:
        settings = WearableSettingsRepository.get_by_device_id(device_id, conn=conn)
    if not settings:
        # 返回默认空配置
        return success_response({
            "device_id": device_id,
            "settings_json": {},
            "updated_at": None,
        })
    return success_response(settings)


@router.put("/settings/{device_id}", summary="更新设备配置")
async def update_device_settings(
    device_id: str,
    body: WearableSettingsUpdate,
    config: M6Config = Depends(get_config),
):
    """更新设备配置（Upsert 模式）"""
    with DatabaseConnection(config.database_path) as conn:
        # 先获取用户 ID（从设备表）
        device = WearableDeviceRepository.get_by_device_id(device_id, conn=conn)
        user_id = device["user_id"] if device else "default"

        record_id = WearableSettingsRepository.upsert(
            device_id=device_id,
            user_id=user_id,
            settings_json=body.settings_json,
            conn=conn,
        )
        settings = WearableSettingsRepository.get_by_device_id(device_id, conn=conn)

    return success_response(settings, "配置更新成功")


@router.delete("/settings/{device_id}", summary="删除设备配置")
async def delete_device_settings(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """删除设备配置"""
    with DatabaseConnection(config.database_path) as conn:
        success = WearableSettingsRepository.delete(device_id, conn=conn)
    if not success:
        raise HTTPException(status_code=404, detail=f"设备配置不存在: {device_id}")
    return success_response(None, "配置已删除")
