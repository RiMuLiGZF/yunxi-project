"""
M6 硬件外设 - 可穿戴设备 API
==========================

P1 优化版：
- 接入 M6 统一错误码体系 (P1-4)
- 请求日志埋点与耗时统计 (P1-6)
- 输入参数增强校验
- 业务异常统一抛出 M6Exception

提供可穿戴设备、健康数据、通知推送、设备配置的 CRUD 接口。

P0 批次迁移：手表/可穿戴数据从 M8 迁到 M6
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Depends, Request

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
from ..models.errors import ErrorCode, M6Exception
from ..models.wearable import (
    WearableDeviceCreate,
    WearableDeviceUpdate,
    WearableHealthDataCreate,
    WearableNotificationCreate,
    WearableSettingsUpdate,
    WearableDeviceType,
    WearableDeviceStatus,
    HealthDataType,
    NotificationStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# 常量配置
# ============================================================================

# 批量上报最大条数（P1-防刷保护）
MAX_BATCH_SIZE = 500

# MAC 地址正则
MAC_PATTERN = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')

# 支持的设备类型值
VALID_DEVICE_TYPES = {t.value for t in WearableDeviceType}
VALID_DEVICE_STATUSES = {s.value for s in WearableDeviceStatus}
VALID_HEALTH_TYPES = {t.value for t in HealthDataType}
VALID_NOTIF_STATUSES = {s.value for s in NotificationStatus}


# ============================================================================
# 工具函数：日志与校验
# ============================================================================

def _log_request(endpoint: str, **kwargs) -> dict:
    """记录请求入口日志，返回用于计算耗时的上下文"""
    ctx = {"endpoint": endpoint, "start_time": time.time()}
    logger.info(f"wearable_api_request endpoint={endpoint}", extra={
        "endpoint": endpoint,
        **{k: v for k, v in kwargs.items() if v is not None},
    })
    return ctx


def _log_response(ctx: dict, status: str = "success", **kwargs) -> None:
    """记录请求完成日志，包含耗时"""
    duration_ms = round((time.time() - ctx["start_time"]) * 1000, 2)
    logger.info(
        f"wearable_api_response endpoint={ctx['endpoint']} status={status} duration_ms={duration_ms}",
        extra={
            "endpoint": ctx["endpoint"],
            "status": status,
            "duration_ms": duration_ms,
            **kwargs,
        },
    )


def _validate_mac_address(mac: str) -> None:
    """校验 MAC 地址格式"""
    if mac and not MAC_PATTERN.match(mac):
        raise M6Exception(
            code=ErrorCode.WEARABLE_MAC_ADDRESS_INVALID,
            message=f"无效的 MAC 地址格式: {mac}",
            details={"mac_address": mac, "expected_format": "AA:BB:CC:DD:EE:FF"},
        )


def _validate_batch_size(size: int) -> None:
    """校验批量操作数量"""
    if size > MAX_BATCH_SIZE:
        raise M6Exception(
            code=ErrorCode.WEARABLE_BATCH_SIZE_EXCEEDED,
            message=f"批量上报数量超过限制: {size} > {MAX_BATCH_SIZE}",
            details={"actual": size, "max_allowed": MAX_BATCH_SIZE},
        )


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
    ctx = _log_request("list_devices", user_id=user_id, device_type=device_type, status=status)

    # P1-参数校验：device_type 和 status 必须在枚举范围内
    if device_type and device_type not in VALID_DEVICE_TYPES:
        _log_response(ctx, "invalid_device_type")
        raise M6Exception(
            code=ErrorCode.WEARABLE_DEVICE_TYPE_INVALID,
            message=f"无效的设备类型: {device_type}",
            details={"valid_types": sorted(VALID_DEVICE_TYPES)},
        )
    if status and status not in VALID_DEVICE_STATUSES:
        _log_response(ctx, "invalid_status")
        raise M6Exception(
            code=ErrorCode.BAD_REQUEST,
            message=f"无效的设备状态: {status}",
            details={"valid_statuses": sorted(VALID_DEVICE_STATUSES)},
        )

    try:
        with DatabaseConnection(config.database_path) as conn:
            devices, total = WearableDeviceRepository.list_devices(
                user_id=user_id,
                device_type=device_type,
                status=status,
                limit=limit,
                offset=offset,
                conn=conn,
            )
        _log_response(ctx, "success", total=total, returned=len(devices))
        return success_response({
            "total": total,
            "limit": limit,
            "offset": offset,
            "devices": devices,
        })
    except M6Exception:
        _log_response(ctx, "business_error")
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"可穿戴设备列表查询失败: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="设备列表查询失败",
            details={"error": str(e)},
        )


@router.get("/devices/{device_id}", summary="获取可穿戴设备详情")
async def get_wearable_device(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """根据 device_id 获取单个可穿戴设备详情"""
    ctx = _log_request("get_device", device_id=device_id)

    try:
        with DatabaseConnection(config.database_path) as conn:
            device = WearableDeviceRepository.get_by_device_id(device_id, conn=conn)
        if not device:
            _log_response(ctx, "not_found")
            raise M6Exception(
                code=ErrorCode.WEARABLE_DEVICE_NOT_FOUND,
                message=f"可穿戴设备不存在: {device_id}",
                details={"device_id": device_id},
            )
        _log_response(ctx, "success")
        return success_response(device)
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"获取设备详情失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="获取设备详情失败",
            details={"error": str(e)},
        )


@router.post("/devices", summary="创建可穿戴设备")
async def create_wearable_device(
    body: WearableDeviceCreate,
    config: M6Config = Depends(get_config),
):
    """创建新的可穿戴设备记录"""
    ctx = _log_request("create_device", device_id=body.device_id, device_type=body.device_type.value)

    # P1-参数校验
    _validate_mac_address(body.mac_address)

    try:
        with DatabaseConnection(config.database_path) as conn:
            # 检查 device_id 是否已存在
            existing = WearableDeviceRepository.get_by_device_id(body.device_id, conn=conn)
            if existing:
                _log_response(ctx, "already_exists")
                raise M6Exception(
                    code=ErrorCode.WEARABLE_DEVICE_ALREADY_EXISTS,
                    message=f"设备 ID 已存在: {body.device_id}",
                    details={"device_id": body.device_id},
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

        _log_response(ctx, "success", device_db_id=device_db_id)
        return success_response(device, "设备创建成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"创建设备失败 device_id={body.device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="创建设备失败",
            details={"error": str(e)},
        )


@router.put("/devices/{device_id}", summary="更新可穿戴设备")
async def update_wearable_device(
    device_id: str,
    body: WearableDeviceUpdate,
    config: M6Config = Depends(get_config),
):
    """更新可穿戴设备信息"""
    ctx = _log_request("update_device", device_id=device_id)

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
        _log_response(ctx, "empty_update")
        raise M6Exception(
            code=ErrorCode.BAD_REQUEST,
            message="没有提供有效的更新字段",
            details={"valid_fields": list(body.model_fields.keys())},
        )

    # P1-MAC 地址校验
    if "mac_address" in updates and updates["mac_address"]:
        _validate_mac_address(updates["mac_address"])

    try:
        with DatabaseConnection(config.database_path) as conn:
            success = WearableDeviceRepository.update(device_id, updates, conn=conn)
            if not success:
                _log_response(ctx, "not_found")
                raise M6Exception(
                    code=ErrorCode.WEARABLE_DEVICE_NOT_FOUND,
                    message=f"可穿戴设备不存在: {device_id}",
                    details={"device_id": device_id},
                )
            device = WearableDeviceRepository.get_by_device_id(device_id, conn=conn)

        _log_response(ctx, "success", updated_fields=list(updates.keys()))
        return success_response(device, "设备更新成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"更新设备失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="更新设备失败",
            details={"error": str(e)},
        )


@router.delete("/devices/{device_id}", summary="删除可穿戴设备")
async def delete_wearable_device(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """删除可穿戴设备记录"""
    ctx = _log_request("delete_device", device_id=device_id)

    try:
        with DatabaseConnection(config.database_path) as conn:
            success = WearableDeviceRepository.delete(device_id, conn=conn)
        if not success:
            _log_response(ctx, "not_found")
            raise M6Exception(
                code=ErrorCode.WEARABLE_DEVICE_NOT_FOUND,
                message=f"可穿戴设备不存在: {device_id}",
                details={"device_id": device_id},
            )
        _log_response(ctx, "success")
        return success_response(None, "设备删除成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"删除设备失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="删除设备失败",
            details={"error": str(e)},
        )


@router.get("/devices/stats/summary", summary="可穿戴设备统计")
async def get_wearable_stats(
    config: M6Config = Depends(get_config),
):
    """获取可穿戴设备统计概览"""
    ctx = _log_request("get_stats")

    try:
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

        stats = {
            "total": total,
            "online_count": len(online),
            "offline_count": len(offline),
            "watch_count": len(watch),
        }
        _log_response(ctx, "success", total=total)
        return success_response(stats)
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"获取设备统计失败: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="获取设备统计失败",
            details={"error": str(e)},
        )


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
    ctx = _log_request("query_health", device_id=device_id, data_type=data_type)

    # P1-参数校验
    if data_type and data_type not in VALID_HEALTH_TYPES:
        _log_response(ctx, "invalid_data_type")
        raise M6Exception(
            code=ErrorCode.WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED,
            message=f"不支持的健康数据类型: {data_type}",
            details={"valid_types": sorted(VALID_HEALTH_TYPES)},
        )

    try:
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
        _log_response(ctx, "success", total=total, returned=len(data))
        return success_response({
            "total": total,
            "limit": limit,
            "offset": offset,
            "data": data,
        })
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"健康数据查询失败: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="健康数据查询失败",
            details={"error": str(e)},
        )


@router.post("/health/data", summary="上报健康数据")
async def report_health_data(
    body: WearableHealthDataCreate,
    config: M6Config = Depends(get_config),
):
    """上报一条健康数据"""
    ctx = _log_request("report_health", device_id=body.device_id, data_type=body.data_type.value)

    # P1-数据合法性校验
    if body.value < 0:
        _log_response(ctx, "invalid_value")
        raise M6Exception(
            code=ErrorCode.WEARABLE_HEALTH_DATA_INVALID,
            message=f"健康数据值不能为负: {body.value}",
            details={"data_type": body.data_type.value, "value": body.value},
        )

    try:
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

        _log_response(ctx, "success", record_id=record_id)
        return success_response({"id": record_id}, "健康数据上报成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"健康数据上报失败 device_id={body.device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="健康数据上报失败",
            details={"error": str(e)},
        )


@router.post("/health/data/batch", summary="批量上报健康数据")
async def batch_report_health_data(
    records: list[WearableHealthDataCreate],
    config: M6Config = Depends(get_config),
):
    """批量上报健康数据"""
    ctx = _log_request("batch_report_health", batch_size=len(records))

    # P1-批量大小限制
    _validate_batch_size(len(records))

    # P1-数据合法性校验（逐条校验，第一条错误即返回）
    for i, record in enumerate(records):
        if record.value < 0:
            _log_response(ctx, "invalid_value", index=i)
            raise M6Exception(
                code=ErrorCode.WEARABLE_HEALTH_DATA_INVALID,
                message=f"第 {i + 1} 条数据值不能为负: {record.value}",
                details={"index": i, "data_type": record.data_type.value, "value": record.value},
            )

    try:
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

        _log_response(ctx, "success", inserted=count)
        return success_response({"inserted": count}, f"批量上报成功，共 {count} 条")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"批量健康数据上报失败: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="批量健康数据上报失败",
            details={"error": str(e)},
        )


@router.get("/health/latest/{device_id}", summary="获取最新健康数据")
async def get_latest_health_data(
    device_id: str,
    data_type: Optional[str] = Query(None, description="指定数据类型，不传则返回所有类型最新值"),
    config: M6Config = Depends(get_config),
):
    """获取设备最新的健康数据（每类一条）"""
    ctx = _log_request("get_latest_health", device_id=device_id, data_type=data_type)

    # P1-参数校验
    if data_type and data_type not in VALID_HEALTH_TYPES:
        _log_response(ctx, "invalid_data_type")
        raise M6Exception(
            code=ErrorCode.WEARABLE_HEALTH_DATA_TYPE_UNSUPPORTED,
            message=f"不支持的健康数据类型: {data_type}",
            details={"valid_types": sorted(VALID_HEALTH_TYPES)},
        )

    try:
        with DatabaseConnection(config.database_path) as conn:
            data = WearableHealthRepository.get_latest(
                device_id=device_id,
                data_type=data_type,
                conn=conn,
            )
        _log_response(ctx, "success", types_count=len(data))
        return success_response({
            "device_id": device_id,
            "data": data,
        })
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"获取最新健康数据失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="获取最新健康数据失败",
            details={"error": str(e)},
        )


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
    ctx = _log_request("list_notifications", device_id=device_id, status=status)

    # P1-参数校验
    if status and status not in VALID_NOTIF_STATUSES:
        _log_response(ctx, "invalid_status")
        raise M6Exception(
            code=ErrorCode.BAD_REQUEST,
            message=f"无效的通知状态: {status}",
            details={"valid_statuses": sorted(VALID_NOTIF_STATUSES)},
        )

    try:
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
        _log_response(ctx, "success", total=total, returned=len(notifications))
        return success_response({
            "total": total,
            "limit": limit,
            "offset": offset,
            "notifications": notifications,
        })
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"通知列表查询失败: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="通知列表查询失败",
            details={"error": str(e)},
        )


@router.get("/notifications/{notification_id}", summary="获取通知详情")
async def get_notification(
    notification_id: str,
    config: M6Config = Depends(get_config),
):
    """根据通知 ID 获取详情"""
    ctx = _log_request("get_notification", notification_id=notification_id)

    try:
        with DatabaseConnection(config.database_path) as conn:
            notification = WearableNotificationRepository.get_by_notification_id(
                notification_id, conn=conn,
            )
        if not notification:
            _log_response(ctx, "not_found")
            raise M6Exception(
                code=ErrorCode.WEARABLE_NOTIFICATION_NOT_FOUND,
                message=f"通知不存在: {notification_id}",
                details={"notification_id": notification_id},
            )
        _log_response(ctx, "success")
        return success_response(notification)
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"获取通知详情失败 notification_id={notification_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="获取通知详情失败",
            details={"error": str(e)},
        )


@router.post("/notifications", summary="发送通知")
async def send_notification(
    body: WearableNotificationCreate,
    config: M6Config = Depends(get_config),
):
    """创建并发送一条通知"""
    ctx = _log_request("send_notification", device_id=body.device_id, type=body.type)

    try:
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

        _log_response(ctx, "success", notification_id=notification_id)
        return success_response(notification, "通知创建成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"创建通知失败 device_id={body.device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="创建通知失败",
            details={"error": str(e)},
        )


@router.put("/notifications/{notification_id}/status", summary="更新通知状态")
async def update_notification_status(
    notification_id: str,
    status: str = Query(..., description="新状态: pending/sent/delivered/failed/read"),
    config: M6Config = Depends(get_config),
):
    """更新通知的发送/送达状态"""
    ctx = _log_request("update_notification_status", notification_id=notification_id, status=status)

    # P1-状态值校验
    if status not in VALID_NOTIF_STATUSES:
        _log_response(ctx, "invalid_status")
        raise M6Exception(
            code=ErrorCode.BAD_REQUEST,
            message=f"无效的通知状态: {status}",
            details={"valid_statuses": sorted(VALID_NOTIF_STATUSES)},
        )

    try:
        delivered_at = datetime.now().isoformat() if status in ("delivered", "sent") else None

        with DatabaseConnection(config.database_path) as conn:
            success = WearableNotificationRepository.update_status(
                notification_id,
                status,
                delivered_at=delivered_at,
                conn=conn,
            )
            if not success:
                _log_response(ctx, "not_found")
                raise M6Exception(
                    code=ErrorCode.WEARABLE_NOTIFICATION_NOT_FOUND,
                    message=f"通知不存在: {notification_id}",
                    details={"notification_id": notification_id},
                )
            notification = WearableNotificationRepository.get_by_notification_id(
                notification_id, conn=conn,
            )

        _log_response(ctx, "success")
        return success_response(notification, "通知状态已更新")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"更新通知状态失败 notification_id={notification_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="更新通知状态失败",
            details={"error": str(e)},
        )


# ============================================================================
# 设备配置
# ============================================================================

@router.get("/settings/{device_id}", summary="获取设备配置")
async def get_device_settings(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """获取指定设备的配置"""
    ctx = _log_request("get_settings", device_id=device_id)

    try:
        with DatabaseConnection(config.database_path) as conn:
            settings = WearableSettingsRepository.get_by_device_id(device_id, conn=conn)
        if not settings:
            # 返回默认空配置（幂等友好）
            _log_response(ctx, "not_found_return_default")
            return success_response({
                "device_id": device_id,
                "settings_json": {},
                "updated_at": None,
            })
        _log_response(ctx, "success")
        return success_response(settings)
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"获取设备配置失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="获取设备配置失败",
            details={"error": str(e)},
        )


@router.put("/settings/{device_id}", summary="更新设备配置")
async def update_device_settings(
    device_id: str,
    body: WearableSettingsUpdate,
    config: M6Config = Depends(get_config),
):
    """更新设备配置（Upsert 模式）"""
    ctx = _log_request("update_settings", device_id=device_id)

    try:
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

        _log_response(ctx, "success", record_id=record_id)
        return success_response(settings, "配置更新成功")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"更新设备配置失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="更新设备配置失败",
            details={"error": str(e)},
        )


@router.delete("/settings/{device_id}", summary="删除设备配置")
async def delete_device_settings(
    device_id: str,
    config: M6Config = Depends(get_config),
):
    """删除设备配置"""
    ctx = _log_request("delete_settings", device_id=device_id)

    try:
        with DatabaseConnection(config.database_path) as conn:
            success = WearableSettingsRepository.delete(device_id, conn=conn)
        if not success:
            _log_response(ctx, "not_found")
            raise M6Exception(
                code=ErrorCode.WEARABLE_SETTINGS_NOT_FOUND,
                message=f"设备配置不存在: {device_id}",
                details={"device_id": device_id},
            )
        _log_response(ctx, "success")
        return success_response(None, "配置已删除")
    except M6Exception:
        raise
    except Exception as e:
        _log_response(ctx, "system_error")
        logger.error(f"删除设备配置失败 device_id={device_id}: {e}", exc_info=True)
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message="删除设备配置失败",
            details={"error": str(e)},
        )
