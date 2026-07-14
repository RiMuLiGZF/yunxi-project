"""
M8 管理工作台 - 手表交互路由

提供手表设备管理、健康数据、通知推送等API接口。
数据库优先，内存 fallback 保留，确保向前兼容。
"""

import sys
import uuid
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import get_db
from ..repositories.watch_repository import (
    WatchDeviceRepository,
    WatchHealthRepository,
    WatchNotificationRepository,
    WatchSettingRepository,
)
from shared.logger import get_logger

logger = get_logger("m8.watch")

router = APIRouter()


# ==================== 内存 fallback 数据 ====================
# 当数据库不可用时使用，保持向前兼容

_mock_devices = [
    {
        "id": 1,
        "device_id": "watch_001",
        "name": "云汐智能手表 Pro",
        "device_type": "watch",
        "brand": "Yunxi",
        "model": "Watch Pro 2",
        "firmware_version": "v2.3.1",
        "status": "online",
        "battery": 78,
        "paired": True,
        "paired_at": (datetime.now() - timedelta(days=30)).isoformat(),
        "last_sync": (datetime.now() - timedelta(minutes=5)).isoformat(),
        "mac_address": "AA:BB:CC:DD:EE:01",
        "features": ["heart_rate", "steps", "sleep", "spo2", "notification", "find_device"],
    },
    {
        "id": 2,
        "device_id": "watch_002",
        "name": "云汐智能戒指",
        "device_type": "ring",
        "brand": "Yunxi",
        "model": "Ring Lite",
        "firmware_version": "v1.5.0",
        "status": "online",
        "battery": 92,
        "paired": True,
        "paired_at": (datetime.now() - timedelta(days=15)).isoformat(),
        "last_sync": (datetime.now() - timedelta(minutes=2)).isoformat(),
        "mac_address": "AA:BB:CC:DD:EE:02",
        "features": ["heart_rate", "sleep", "temperature", "spo2", "hrv"],
    },
]

_mock_notifications = [
    {
        "id": 1,
        "notification_id": "notif_001",
        "device_id": "watch_001",
        "title": "日程提醒",
        "content": "10分钟后有团队会议",
        "notification_type": "reminder",
        "status": "delivered",
        "delivered_at": (datetime.now() - timedelta(minutes=10)).isoformat(),
        "read_at": None,
        "action_type": "open_calendar",
        "action_data": {"event_id": "evt_001"},
        "created_at": (datetime.now() - timedelta(minutes=12)).isoformat(),
    },
    {
        "id": 2,
        "notification_id": "notif_002",
        "device_id": "watch_001",
        "title": "久坐提醒",
        "content": "您已坐了1小时，建议起身活动一下",
        "notification_type": "info",
        "status": "read",
        "delivered_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        "read_at": (datetime.now() - timedelta(minutes=55)).isoformat(),
        "action_type": "dismiss",
        "action_data": {},
        "created_at": (datetime.now() - timedelta(hours=1, minutes=2)).isoformat(),
    },
    {
        "id": 3,
        "notification_id": "notif_003",
        "device_id": "watch_001",
        "title": "心率异常",
        "content": "检测到静息心率偏高，请注意休息",
        "notification_type": "warning",
        "status": "delivered",
        "delivered_at": (datetime.now() - timedelta(hours=2)).isoformat(),
        "read_at": None,
        "action_type": "view_health",
        "action_data": {"data_type": "heart_rate"},
        "created_at": (datetime.now() - timedelta(hours=2, minutes=1)).isoformat(),
    },
]


def _get_mock_device(device_id: str) -> Optional[dict]:
    """根据ID获取模拟设备（fallback）"""
    for d in _mock_devices:
        if d["device_id"] == device_id:
            return d
    return None


def _generate_realtime_health(device_id: str, device_features: List[str]) -> dict:
    """生成实时健康数据（模拟）"""
    now = datetime.now().isoformat()
    data = {
        "device_id": device_id,
        "timestamp": now,
    }

    features = device_features
    if "heart_rate" in features:
        hr_val = random.randint(60, 90)
        data["heart_rate"] = {
            "value": hr_val,
            "unit": "bpm",
            "status": "normal" if 60 <= hr_val <= 100 else "warning",
        }
    if "steps" in features:
        data["steps"] = {
            "value": random.randint(1000, 12000),
            "unit": "steps",
            "goal": 10000,
        }
    if "spo2" in features:
        data["spo2"] = {
            "value": round(random.uniform(95, 99), 1),
            "unit": "%",
            "status": "normal",
        }
    if "sleep" in features:
        data["sleep"] = {
            "total_hours": round(random.uniform(6, 9), 1),
            "deep_sleep": round(random.uniform(1, 3), 1),
            "light_sleep": round(random.uniform(3, 5), 1),
            "rem_sleep": round(random.uniform(0.5, 2), 1),
        }
    if "calories" in features or "steps" in features:
        data["calories"] = {
            "value": random.randint(200, 800),
            "unit": "kcal",
        }

    return data


def _generate_health_history(device_id: str, data_type: str, days: int = 7) -> list:
    """生成健康历史数据（模拟，fallback用）"""
    history = []
    now = datetime.now()

    if data_type == "heart_rate":
        for i in range(days * 24):
            ts = now - timedelta(hours=i)
            history.append({
                "timestamp": ts.isoformat(),
                "value": random.randint(55, 95),
                "unit": "bpm",
            })
    elif data_type == "steps":
        for i in range(days):
            ts = now - timedelta(days=i)
            history.append({
                "timestamp": ts.date().isoformat(),
                "value": random.randint(3000, 15000),
                "unit": "steps",
                "goal": 10000,
            })
    elif data_type == "spo2":
        for i in range(days * 24):
            ts = now - timedelta(hours=i)
            history.append({
                "timestamp": ts.isoformat(),
                "value": round(random.uniform(94, 99), 1),
                "unit": "%",
            })
    elif data_type == "sleep":
        for i in range(days):
            ts = now - timedelta(days=i)
            total = round(random.uniform(5.5, 9), 1)
            history.append({
                "timestamp": ts.date().isoformat(),
                "total_hours": total,
                "deep_sleep": round(total * 0.25, 1),
                "light_sleep": round(total * 0.55, 1),
                "rem_sleep": round(total * 0.2, 1),
                "score": random.randint(60, 95),
            })

    return history


def _get_user_id(current_user: dict) -> int:
    """从 current_user 获取用户ID"""
    if isinstance(current_user, dict):
        return current_user.get("id", 1)
    if hasattr(current_user, "id"):
        return current_user.id
    return 1


def _is_db_available(db: Session) -> bool:
    """检查数据库是否可用"""
    try:
        db.execute("SELECT 1")
        return True
    except Exception:
        return False


# ==================== 请求模型 ====================

class BindDeviceRequest(BaseModel):
    """绑定设备请求"""
    device_id: str = Field(..., description="设备ID")
    name: str = Field(..., description="设备名称")
    device_type: str = Field("watch", description="设备类型")
    mac_address: Optional[str] = Field("", description="MAC地址")


class SendNotificationRequest(BaseModel):
    """发送通知请求"""
    device_id: str = Field(..., description="设备ID")
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    notification_type: str = Field("info", description="通知类型：info/warning/error/reminder")
    action_type: Optional[str] = Field("", description="动作类型")
    action_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="动作数据")


class HealthSyncRequest(BaseModel):
    """健康数据同步请求"""
    device_id: str = Field(..., description="设备ID")
    data_type: Optional[str] = Field(None, description="数据类型，不传则同步全部")
    start_time: Optional[str] = Field(None, description="开始时间")
    end_time: Optional[str] = Field(None, description="结束时间")


# ==================== 设备管理接口 ====================

@router.get("/devices")
async def list_devices(
    status: Optional[str] = Query(None, description="按状态过滤"),
    device_type: Optional[str] = Query(None, description="按类型过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取手表设备列表"""
    user_id = _get_user_id(current_user)

    try:
        repo = WatchDeviceRepository(db, user_id=user_id)
        devices, total = repo.list_devices(
            status=status,
            device_type=device_type,
            page=page,
            page_size=page_size,
        )
        device_list = [d.to_dict() for d in devices]
        source = "database"
    except Exception as e:
        logger.warning(f"数据库读取设备列表失败，使用内存 fallback: {e}")
        # 内存 fallback
        devices = list(_mock_devices)
        if status:
            devices = [d for d in devices if d.get("status") == status]
        if device_type:
            devices = [d for d in devices if d.get("device_type") == device_type]
        total = len(devices)
        start = (page - 1) * page_size
        end = start + page_size
        device_list = devices[start:end]
        source = "memory_fallback"

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "devices": device_list,
        "source": source,
    })


@router.post("/devices")
async def bind_device(
    body: BindDeviceRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定手表设备"""
    user_id = _get_user_id(current_user)

    try:
        repo = WatchDeviceRepository(db, user_id=user_id)
        existing = repo.get_by_device_id(body.device_id)
        if existing:
            return ApiResponse.error(code=400, message="设备已绑定")

        new_device = repo.bind_device(
            device_id=body.device_id,
            name=body.name,
            device_type=body.device_type,
            mac_address=body.mac_address or "",
        )
        return ApiResponse.success(
            message="设备绑定成功",
            data=new_device.to_dict(),
        )
    except Exception as e:
        logger.warning(f"数据库绑定设备失败，使用内存 fallback: {e}")
        # 内存 fallback
        existing = _get_mock_device(body.device_id)
        if existing:
            return ApiResponse.error(code=400, message="设备已绑定")

        new_device = {
            "id": len(_mock_devices) + 1,
            "device_id": body.device_id,
            "name": body.name,
            "device_type": body.device_type,
            "brand": "Unknown",
            "model": "Unknown",
            "firmware_version": "v1.0.0",
            "status": "online",
            "battery": 100,
            "paired": True,
            "paired_at": datetime.now().isoformat(),
            "last_sync": datetime.now().isoformat(),
            "mac_address": body.mac_address or "",
            "features": ["heart_rate", "steps", "notification"],
        }
        _mock_devices.append(new_device)

        return ApiResponse.success(
            message="设备绑定成功",
            data=new_device,
        )


@router.delete("/devices/{device_id}")
async def unbind_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑手表设备"""
    user_id = _get_user_id(current_user)

    try:
        repo = WatchDeviceRepository(db, user_id=user_id)
        device = repo.get_by_device_id(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        repo.unbind_device(device_id)
        return ApiResponse.success(message="设备解绑成功")
    except Exception as e:
        logger.warning(f"数据库解绑设备失败，使用内存 fallback: {e}")
        # 内存 fallback
        device = _get_mock_device(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        _mock_devices.remove(device)
        return ApiResponse.success(message="设备解绑成功")


# ==================== 健康数据接口 ====================

@router.get("/health/realtime")
async def get_realtime_health(
    device_id: str = Query(..., description="设备ID"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取实时健康数据（心率/步数/血氧）"""
    user_id = _get_user_id(current_user)

    try:
        device_repo = WatchDeviceRepository(db, user_id=user_id)
        device = device_repo.get_by_device_id(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        if device.status == "offline":
            return ApiResponse.error(code=400, message="设备离线，无法获取实时数据")

        # 实时数据从数据库读最新一条，缺失的部分用模拟生成
        health_repo = WatchHealthRepository(db, user_id=user_id)
        features = device.features or []
        realtime_data = {
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        }

        # 从数据库读取最新数据
        for data_type in ["heart_rate", "steps", "spo2"]:
            if data_type in features:
                latest = health_repo.get_latest(device_id, data_type)
                if latest:
                    if data_type == "heart_rate":
                        realtime_data["heart_rate"] = {
                            "value": int(latest.value),
                            "unit": latest.unit or "bpm",
                            "status": "normal" if 60 <= latest.value <= 100 else "warning",
                        }
                    elif data_type == "steps":
                        goal = (latest.extra or {}).get("goal", 10000)
                        realtime_data["steps"] = {
                            "value": int(latest.value),
                            "unit": latest.unit or "steps",
                            "goal": goal,
                        }
                    elif data_type == "spo2":
                        realtime_data["spo2"] = {
                            "value": latest.value,
                            "unit": latest.unit or "%",
                            "status": "normal" if latest.value >= 95 else "warning",
                        }

        # 睡眠数据单独处理
        if "sleep" in features:
            latest_sleep = health_repo.get_latest(device_id, "sleep")
            if latest_sleep and latest_sleep.extra:
                extra = latest_sleep.extra or {}
                realtime_data["sleep"] = {
                    "total_hours": extra.get("total_hours", latest_sleep.value),
                    "deep_sleep": extra.get("deep_sleep", 0),
                    "light_sleep": extra.get("light_sleep", 0),
                    "rem_sleep": extra.get("rem_sleep", 0),
                }

        # 卡路里（从步数估算或从 extra 读取）
        if "calories" in features or "steps" in features:
            if "steps" in realtime_data:
                cal = int(realtime_data["steps"]["value"] * 0.04)
                realtime_data["calories"] = {
                    "value": cal,
                    "unit": "kcal",
                }

        source = "database"
    except Exception as e:
        logger.warning(f"数据库读取实时健康数据失败，使用内存 fallback: {e}")
        # 内存 fallback
        device = _get_mock_device(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        if device["status"] == "offline":
            return ApiResponse.error(code=400, message="设备离线，无法获取实时数据")

        realtime_data = _generate_realtime_health(device_id, device.get("features", []))
        device_name = device["name"]
        source = "memory_fallback"
        return ApiResponse.success(data={
            "device_id": device_id,
            "device_name": device_name,
            "data": realtime_data,
            "source": source,
        })

    return ApiResponse.success(data={
        "device_id": device_id,
        "device_name": device.name,
        "data": realtime_data,
        "source": source,
    })


@router.post("/health/sync")
async def sync_health_data(
    body: HealthSyncRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """同步健康数据"""
    user_id = _get_user_id(current_user)

    try:
        device_repo = WatchDeviceRepository(db, user_id=user_id)
        device = device_repo.get_by_device_id(body.device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        health_repo = WatchHealthRepository(db, user_id=user_id)
        data_types = [body.data_type] if body.data_type else ["heart_rate", "steps", "spo2", "sleep"]
        synced_count = health_repo.sync_data(body.device_id, data_types, days=7)

        # 更新设备最后同步时间
        device_repo.update_last_sync(body.device_id)

        return ApiResponse.success(
            message="健康数据同步完成",
            data={
                "device_id": body.device_id,
                "data_types": data_types,
                "synced_count": synced_count,
                "sync_time": datetime.now().isoformat(),
                "source": "database",
            },
        )
    except Exception as e:
        logger.warning(f"数据库同步健康数据失败，使用内存 fallback: {e}")
        # 内存 fallback
        device = _get_mock_device(body.device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        data_types = [body.data_type] if body.data_type else ["heart_rate", "steps", "spo2", "sleep"]
        synced_count = 0
        for dt in data_types:
            history = _generate_health_history(body.device_id, dt, days=7)
            synced_count += len(history)

        return ApiResponse.success(
            message="健康数据同步完成",
            data={
                "device_id": body.device_id,
                "data_types": data_types,
                "synced_count": synced_count,
                "sync_time": datetime.now().isoformat(),
                "source": "memory_fallback",
            },
        )


@router.get("/health/history")
async def get_health_history(
    device_id: str = Query(..., description="设备ID"),
    data_type: str = Query("heart_rate", description="数据类型：heart_rate/steps/spo2/sleep"),
    days: int = Query(7, ge=1, le=90, description="天数"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=1000, description="每页数量"),
    start_time: Optional[str] = Query(None, description="开始时间（ISO格式）"),
    end_time: Optional[str] = Query(None, description="结束时间（ISO格式）"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取健康数据历史（支持时间范围查询）"""
    user_id = _get_user_id(current_user)

    try:
        device_repo = WatchDeviceRepository(db, user_id=user_id)
        device = device_repo.get_by_device_id(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        health_repo = WatchHealthRepository(db, user_id=user_id)

        # 解析时间范围
        start_dt = None
        end_dt = None
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except ValueError:
                pass
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            except ValueError:
                pass

        # 如果没有指定时间范围，按 days 计算
        if not start_dt and not end_dt:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)

        records, total = health_repo.get_history(
            device_id=device_id,
            data_type=data_type,
            start_time=start_dt,
            end_time=end_dt,
            page=page,
            page_size=page_size,
        )

        # 转换格式，对齐原有接口输出
        history_data = []
        values_for_stats = []

        for r in records:
            extra = r.extra or {}
            if data_type == "steps":
                item = {
                    "timestamp": r.timestamp.date().isoformat() if r.timestamp else "",
                    "value": int(r.value),
                    "unit": r.unit or "steps",
                    "goal": extra.get("goal", 10000),
                }
                values_for_stats.append(r.value)
            elif data_type == "sleep":
                item = {
                    "timestamp": r.timestamp.date().isoformat() if r.timestamp else "",
                    "total_hours": extra.get("total_hours", r.value),
                    "deep_sleep": extra.get("deep_sleep", 0),
                    "light_sleep": extra.get("light_sleep", 0),
                    "rem_sleep": extra.get("rem_sleep", 0),
                    "score": extra.get("score", 0),
                }
                values_for_stats.append(extra.get("score", r.value))
            else:
                item = {
                    "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                    "value": r.value,
                    "unit": r.unit or "",
                }
                values_for_stats.append(r.value)
            history_data.append(item)

        # 统计数据
        if values_for_stats:
            avg_value = sum(values_for_stats) / len(values_for_stats)
            max_value = max(values_for_stats)
            min_value = min(values_for_stats)
        else:
            avg_value = max_value = min_value = 0

        return ApiResponse.success(data={
            "device_id": device_id,
            "data_type": data_type,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": history_data,
            "statistics": {
                "avg": round(avg_value, 2),
                "max": max_value,
                "min": min_value,
                "days": days,
            },
            "source": "database",
        })
    except Exception as e:
        logger.warning(f"数据库读取健康历史失败，使用内存 fallback: {e}")
        # 内存 fallback
        device = _get_mock_device(device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        history = _generate_health_history(device_id, data_type, days=days)
        total = len(history)
        start = (page - 1) * page_size
        end_idx = start + page_size
        paged = history[start:end_idx]

        # 计算统计数据
        if data_type == "steps" and history:
            avg_value = sum(h["value"] for h in history) / len(history)
            max_value = max(h["value"] for h in history)
            min_value = min(h["value"] for h in history)
        elif history and "value" in history[0]:
            avg_value = sum(h["value"] for h in history) / len(history)
            max_value = max(h["value"] for h in history)
            min_value = min(h["value"] for h in history)
        else:
            avg_value = max_value = min_value = 0

        return ApiResponse.success(data={
            "device_id": device_id,
            "data_type": data_type,
            "total": total,
            "page": page,
            "page_size": page_size,
            "data": paged,
            "statistics": {
                "avg": round(avg_value, 2),
                "max": max_value,
                "min": min_value,
                "days": days,
            },
            "source": "memory_fallback",
        })


# ==================== 通知接口 ====================

@router.post("/notification/send")
async def send_notification(
    body: SendNotificationRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发送通知到手表"""
    user_id = _get_user_id(current_user)

    try:
        device_repo = WatchDeviceRepository(db, user_id=user_id)
        device = device_repo.get_by_device_id(body.device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        if device.status == "offline":
            return ApiResponse.error(code=400, message="设备离线，通知将在上线后推送")

        notif_repo = WatchNotificationRepository(db, user_id=user_id)
        notification = notif_repo.send_notification(
            device_id=body.device_id,
            title=body.title,
            content=body.content,
            notification_type=body.notification_type,
            action_type=body.action_type or "",
            action_data=body.action_data or {},
            source="api",
        )

        return ApiResponse.success(
            message="通知发送成功",
            data={
                "notification_id": notification.notification_id,
                "device_id": body.device_id,
                "status": notification.status,
                "delivered_at": notification.delivered_at.isoformat() if notification.delivered_at else None,
                "source": "database",
            },
        )
    except Exception as e:
        logger.warning(f"数据库发送通知失败，使用内存 fallback: {e}")
        # 内存 fallback
        device = _get_mock_device(body.device_id)
        if not device:
            return ApiResponse.error(code=404, message="设备不存在")

        if device["status"] == "offline":
            return ApiResponse.error(code=400, message="设备离线，通知将在上线后推送")

        notif_id = f"notif_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        notification = {
            "id": len(_mock_notifications) + 1,
            "notification_id": notif_id,
            "device_id": body.device_id,
            "title": body.title,
            "content": body.content,
            "notification_type": body.notification_type,
            "status": "delivered",
            "delivered_at": now,
            "read_at": None,
            "action_type": body.action_type or "",
            "action_data": body.action_data or {},
            "created_at": now,
        }
        _mock_notifications.insert(0, notification)

        return ApiResponse.success(
            message="通知发送成功",
            data={
                "notification_id": notif_id,
                "device_id": body.device_id,
                "status": "delivered",
                "delivered_at": now,
                "source": "memory_fallback",
            },
        )


@router.get("/notification/history")
async def get_notification_history(
    device_id: Optional[str] = Query(None, description="设备ID，不传则返回所有设备"),
    notification_type: Optional[str] = Query(None, description="按类型过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取通知历史"""
    user_id = _get_user_id(current_user)

    try:
        notif_repo = WatchNotificationRepository(db, user_id=user_id)
        notifications, total = notif_repo.list_notifications(
            device_id=device_id,
            notification_type=notification_type,
            status=status,
            page=page,
            page_size=page_size,
        )
        notif_list = [n.to_dict() for n in notifications]
        source = "database"
    except Exception as e:
        logger.warning(f"数据库读取通知历史失败，使用内存 fallback: {e}")
        # 内存 fallback
        notifications = list(_mock_notifications)
        if device_id:
            notifications = [n for n in notifications if n["device_id"] == device_id]
        if notification_type:
            notifications = [n for n in notifications if n["notification_type"] == notification_type]
        if status:
            notifications = [n for n in notifications if n["status"] == status]

        total = len(notifications)
        start = (page - 1) * page_size
        end_idx = start + page_size
        notif_list = notifications[start:end_idx]
        source = "memory_fallback"

    return ApiResponse.success(data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "notifications": notif_list,
        "source": source,
    })
