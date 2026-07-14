"""
M6 穿戴设备代理路由
将 M6 硬件外设模块的设备管理、传感器数据、设备控制等 API
通过 ModuleClient 代理到 M8 管理工作台，统一响应格式。

如果 M6 模块不可用，则返回 mock 数据（从 life_management 的 _devices 扩展而来），
确保在 M6 未启动时接口也能正常工作。
"""

import sys
import uuid
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from shared.module_client import get_module_registry
from shared.logger import get_logger

logger = get_logger("m8.m6_devices")

router = APIRouter()
registry = get_module_registry()


# ==================== Mock 数据 ====================

# 设备 mock 数据（与 life_management.py 中的 _devices 保持兼容并扩展）
_mock_devices = [
    {
        "device_id": "dev_watch_001",
        "name": "智能手表",
        "device_type": "watch",
        "status": "online",
        "battery": 78,
        "firmware_version": "v2.3.1",
        "last_sync": (datetime.now() - timedelta(minutes=5)).isoformat(),
        "icon_type": "watch",
        "position": {"x": 50, "y": 30},
        "features": ["heart_rate", "steps", "sleep", "notification"],
        "paired": True,
    },
    {
        "device_id": "dev_ring_001",
        "name": "智能戒指",
        "device_type": "ring",
        "status": "online",
        "battery": 92,
        "firmware_version": "v1.5.0",
        "last_sync": (datetime.now() - timedelta(minutes=2)).isoformat(),
        "icon_type": "ring",
        "position": {"x": 20, "y": 50},
        "features": ["heart_rate", "sleep", "temperature", "spo2"],
        "paired": True,
    },
    {
        "device_id": "dev_desktop_001",
        "name": "桌面终端",
        "device_type": "desktop",
        "status": "online",
        "battery": 100,
        "firmware_version": "v3.0.0",
        "last_sync": (datetime.now() - timedelta(seconds=30)).isoformat(),
        "icon_type": "monitor",
        "position": {"x": 80, "y": 30},
        "features": ["display", "video_call", "notification", "ambient_light"],
        "paired": True,
    },
    {
        "device_id": "dev_glasses_001",
        "name": "AR眼镜",
        "device_type": "ar",
        "status": "warning",
        "battery": 35,
        "firmware_version": "v1.2.0",
        "last_sync": (datetime.now() - timedelta(minutes=15)).isoformat(),
        "icon_type": "glasses",
        "position": {"x": 50, "y": 60},
        "features": ["navigation", "translation", "display_info"],
        "paired": True,
    },
    {
        "device_id": "dev_drone_001",
        "name": "改装无人机",
        "device_type": "drone",
        "status": "offline",
        "battery": None,
        "firmware_version": "v2.1.0",
        "last_sync": (datetime.now() - timedelta(hours=2)).isoformat(),
        "icon_type": "drone",
        "position": {"x": 20, "y": 20},
        "features": ["photo", "video", "navigation", "deliver"],
        "paired": True,
    },
    {
        "device_id": "dev_laptop_001",
        "name": "笔记本电脑",
        "device_type": "laptop",
        "status": "online",
        "battery": 65,
        "firmware_version": "v4.5.2",
        "last_sync": (datetime.now() - timedelta(minutes=10)).isoformat(),
        "icon_type": "laptop",
        "position": {"x": 80, "y": 70},
        "features": ["focus_mode", "work_tracking", "notification"],
        "paired": True,
    },
]


def _get_mock_device(device_id: str) -> Optional[dict]:
    """根据 ID 获取 mock 设备"""
    for d in _mock_devices:
        if d["device_id"] == device_id:
            return d
    return None


def _generate_mock_sensor_data(device_id: str) -> dict:
    """生成 mock 传感器数据"""
    device = _get_mock_device(device_id)
    if not device:
        return {}
    
    device_type = device.get("device_type", "")
    data = {
        "device_id": device_id,
        "timestamp": datetime.now().isoformat(),
    }
    
    if device_type == "watch":
        data.update({
            "heart_rate": random.randint(65, 85),
            "steps": random.randint(3000, 8000),
            "calories": random.randint(200, 500),
            "battery_level": device.get("battery", 0),
        })
    elif device_type == "ring":
        data.update({
            "heart_rate": random.randint(60, 80),
            "hrv": random.randint(30, 60),
            "temperature": round(36.0 + random.random(), 1),
            "spo2": random.randint(95, 99),
            "battery_level": device.get("battery", 0),
        })
    elif device_type == "desktop":
        data.update({
            "ambient_light": random.randint(200, 800),
            "temperature": round(22 + random.random() * 5, 1),
            "humidity": round(40 + random.random() * 20, 1),
            "power_status": "charging",
        })
    elif device_type == "ar":
        data.update({
            "battery_level": device.get("battery", 0),
            "usage_time": random.randint(30, 120),
            "brightness": random.randint(50, 100),
        })
    elif device_type == "drone":
        data.update({
            "battery_level": 0,
            "flight_time": 0,
            "altitude": 0,
            "speed": 0,
        })
    elif device_type == "laptop":
        data.update({
            "battery_level": device.get("battery", 0),
            "cpu_usage": random.randint(20, 70),
            "memory_usage": random.randint(40, 80),
            "active_time": random.randint(60, 240),
        })
    
    return data


def _generate_mock_history(device_id: str, hours: int = 1, limit: int = 60) -> list:
    """生成 mock 历史传感器数据"""
    device = _get_mock_device(device_id)
    if not device:
        return []
    
    device_type = device.get("device_type", "")
    history = []
    now = datetime.now()
    
    for i in range(min(limit, hours * 60)):
        ts = now - timedelta(minutes=i)
        point = {"timestamp": ts.isoformat()}
        
        if device_type in ("watch", "ring"):
            point["heart_rate"] = random.randint(60, 90)
            if device_type == "ring":
                point["temperature"] = round(36.0 + random.random(), 1)
        elif device_type == "desktop":
            point["ambient_light"] = random.randint(200, 800)
            point["temperature"] = round(22 + random.random() * 5, 1)
        
        history.append(point)
    
    return history


# ==================== 内部工具函数 ====================

async def _check_m6_available() -> bool:
    """检查 M6 模块是否可用"""
    try:
        client = registry.get_client("m6")
        return await client.health_check()
    except Exception:
        return False


async def _proxy_m6_get(path: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """
    代理 GET 请求到 M6 模块
    
    Returns:
        成功返回解析后的 JSON，失败返回 None
    """
    try:
        client = registry.get_client("m6")
        result = await client.get(path, params=params)
        return result
    except Exception as exc:
        logger.warning(f"Proxy GET m6{path} failed: {exc}")
        return None


async def _proxy_m6_post(path: str, json_data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """
    代理 POST 请求到 M6 模块
    
    Returns:
        成功返回解析后的 JSON，失败返回 None
    """
    try:
        client = registry.get_client("m6")
        result = await client.post(path, json_data=json_data)
        return result
    except Exception as exc:
        logger.warning(f"Proxy POST m6{path} failed: {exc}")
        return None


async def _proxy_m6_put(path: str, json_data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """
    代理 PUT 请求到 M6 模块
    
    Returns:
        成功返回解析后的 JSON，失败返回 None
    """
    try:
        client = registry.get_client("m6")
        result = await client.put(path, json_data=json_data)
        return result
    except Exception as exc:
        logger.warning(f"Proxy PUT m6{path} failed: {exc}")
        return None


def _m6_unavailable(detail: str = "") -> ApiResponse:
    """M6 不可用时的友好响应（返回 mock 数据前的说明）"""
    return ApiResponse(
        code=0,
        message="M6 模块暂不可用，返回模拟数据",
        data={
            "module": "m6",
            "status": "stopped",
            "detail": detail,
            "mock_mode": True,
        },
    )


# ==================== 请求模型 ====================

class DeviceActionRequest(BaseModel):
    """设备动作请求"""
    action: str = Field(..., description="动作名称，如 take_photo, start_exercise 等")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="动作参数")


class NotifyRequest(BaseModel):
    """通知推送请求"""
    title: str = Field(..., description="通知标题")
    content: str = Field(..., description="通知内容")
    notification_type: str = Field("info", description="通知类型: info/warning/error")


# ==================== 设备管理接口 ====================

@router.get("/devices")
async def list_devices(
    status: Optional[str] = Query(None, description="按状态过滤: online/offline/warning/charging"),
    device_type: Optional[str] = Query(None, description="按类型过滤: watch/ring/desktop/ar/drone/laptop"),
    current_user: dict = Depends(get_current_user),
):
    """获取设备列表（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        params = {}
        if status:
            params["status"] = status
        if device_type:
            params["device_type"] = device_type
        
        result = await _proxy_m6_get("/api/v1/devices", params=params if params else None)
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                "total": data.get("total", len(data.get("devices", []))),
                "devices": data.get("devices", data),
                "source": "m6",
            })
    
    # Mock 模式
    devices = _mock_devices
    if status:
        devices = [d for d in devices if d.get("status") == status]
    if device_type:
        devices = [d for d in devices if d.get("device_type") == device_type]
    
    return ApiResponse.success(data={
        "total": len(devices),
        "devices": devices,
        "source": "mock",
    })


@router.get("/devices/stats")
async def get_device_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取设备统计（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_get("/api/v1/devices/stats")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })
    
    # Mock 模式
    devices = _mock_devices
    online = sum(1 for d in devices if d["status"] == "online")
    offline = sum(1 for d in devices if d["status"] == "offline")
    warning = sum(1 for d in devices if d["status"] == "warning")
    charging = sum(1 for d in devices if d.get("battery") == 100)
    
    return ApiResponse.success(data={
        "total": len(devices),
        "online": online,
        "offline": offline,
        "warning": warning,
        "charging": charging,
        "paired": sum(1 for d in devices if d.get("paired")),
        "source": "mock",
    })


@router.get("/devices/{device_id}")
async def get_device_detail(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取设备详情（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_get(f"/api/v1/devices/{device_id}")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    # 附加传感器数据
    sensor_data = _generate_mock_sensor_data(device_id)
    
    return ApiResponse.success(data={
        **device,
        "latest_sensor_data": sensor_data,
        "source": "mock",
    })


@router.post("/devices/{device_id}/pair")
async def pair_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """配对设备（代理到 M6，不可用时返回 mock 结果）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_post(f"/api/v1/devices/{device_id}/pair")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data=data, message=result.get("message", "配对成功"))
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    device["paired"] = True
    device["status"] = "online"
    device["last_sync"] = datetime.now().isoformat()
    
    return ApiResponse.success(
        message="配对成功",
        data={
            "device_id": device_id,
            "paired": True,
            "source": "mock",
        }
    )


@router.post("/devices/{device_id}/unpair")
async def unpair_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """取消配对（代理到 M6，不可用时返回 mock 结果）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_post(f"/api/v1/devices/{device_id}/unpair")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data=data, message=result.get("message", "已取消配对"))
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    device["paired"] = False
    
    return ApiResponse.success(
        message="已取消配对",
        data={
            "device_id": device_id,
            "paired": False,
            "source": "mock",
        }
    )


@router.post("/devices/scan")
async def scan_devices(
    current_user: dict = Depends(get_current_user),
):
    """扫描附近设备（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_post("/api/v1/devices/scan")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            }, message=result.get("message", "扫描完成"))
    
    # Mock 模式：模拟发现 1-2 个新设备
    found_devices = [
        {
            "device_id": "dev_earbuds_001",
            "name": "智能耳机",
            "device_type": "earbuds",
            "status": "discovered",
            "battery": None,
            "signal_strength": random.randint(-80, -40),
            "paired": False,
        },
    ]
    if random.random() > 0.5:
        found_devices.append({
            "device_id": "dev_scale_001",
            "name": "智能体重秤",
            "device_type": "scale",
            "status": "discovered",
            "battery": None,
            "signal_strength": random.randint(-80, -40),
            "paired": False,
        })
    
    return ApiResponse.success(
        message="扫描完成",
        data={
            "found_count": len(found_devices),
            "devices": found_devices,
            "source": "mock",
        }
    )


@router.put("/devices/{device_id}/config")
async def update_device_config(
    device_id: str,
    body: dict = Body(..., description="配置更新字典"),
    current_user: dict = Depends(get_current_user),
):
    """更新设备配置（代理到 M6，不可用时返回 mock 结果）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_put(
            f"/api/v1/devices/{device_id}/config",
            json_data=body
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data=data, message=result.get("message", "配置更新成功"))

    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")

    return ApiResponse.success(
        message="配置更新成功",
        data={
            "device_id": device_id,
            "config_updated": True,
            "config": body,
            "source": "mock",
        }
    )


# ==================== 传感器数据接口 ====================

@router.get("/sensors/{device_id}")
async def get_sensor_data(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取设备最新传感器数据（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_get(f"/api/v1/sensors/{device_id}")
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    sensor_data = _generate_mock_sensor_data(device_id)
    
    return ApiResponse.success(data={
        **sensor_data,
        "source": "mock",
    })


@router.get("/sensors/{device_id}/history")
async def get_sensor_history(
    device_id: str,
    sensor_type: Optional[str] = Query(None, description="传感器类型，如 heart_rate"),
    start_time: Optional[str] = Query(None, description="开始时间 ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO 格式"),
    limit: int = Query(100, ge=1, le=5000, description="返回条数"),
    current_user: dict = Depends(get_current_user),
):
    """获取传感器历史数据（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        params = {"limit": limit}
        if sensor_type:
            params["sensor_type"] = sensor_type
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        
        result = await _proxy_m6_get(f"/api/v1/sensors/{device_id}/history", params=params)
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    # 计算时间范围
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=1)
    hours = 1
    try:
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00").replace(" ", "T"))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00").replace(" ", "T"))
        hours = max(1, int((end_dt - start_dt).total_seconds() / 3600))
    except Exception:
        pass
    
    history = _generate_mock_history(device_id, hours=hours, limit=limit)
    
    return ApiResponse.success(data={
        "device_id": device_id,
        "sensor_type": sensor_type or "all",
        "total": len(history),
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "data": history,
        "source": "mock",
    })


@router.get("/sensors/{device_id}/{sensor_type}")
async def get_sensor_by_type(
    device_id: str,
    sensor_type: str,
    limit: int = Query(100, ge=1, le=5000, description="返回条数"),
    start_time: Optional[str] = Query(None, description="开始时间 ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO 格式"),
    current_user: dict = Depends(get_current_user),
):
    """获取特定传感器的历史数据（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        params = {"limit": limit}
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        result = await _proxy_m6_get(
            f"/api/v1/sensors/{device_id}/{sensor_type}",
            params=params
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })

    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")

    # 计算时间范围
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=1)
    hours = 1
    try:
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00").replace(" ", "T"))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00").replace(" ", "T"))
        hours = max(1, int((end_dt - start_dt).total_seconds() / 3600))
    except Exception:
        pass

    # 生成对应类型的历史数据
    history = []
    count = min(limit, hours * 60)
    now = datetime.now()

    for i in range(count):
        ts = now - timedelta(minutes=i)
        point = {"timestamp": ts.isoformat()}

        if sensor_type == "heart_rate":
            point["heart_rate"] = random.randint(60, 90)
        elif sensor_type == "steps":
            point["steps"] = random.randint(50, 150)
        elif sensor_type == "calories":
            point["calories"] = round(random.uniform(1, 5), 1)
        elif sensor_type == "temperature":
            point["temperature"] = round(36.0 + random.random(), 1)
        elif sensor_type == "spo2":
            point["spo2"] = random.randint(95, 99)
        elif sensor_type == "hrv":
            point["hrv"] = random.randint(30, 60)
        elif sensor_type == "sleep":
            point["sleep_stage"] = random.choice(["deep", "light", "rem", "awake"])
        elif sensor_type == "battery":
            point["battery_level"] = max(0, 100 - i // 60)
        elif sensor_type == "ambient_light":
            point["ambient_light"] = random.randint(200, 800)
        elif sensor_type == "humidity":
            point["humidity"] = round(40 + random.random() * 20, 1)
        elif sensor_type == "cpu_usage":
            point["cpu_usage"] = random.randint(20, 70)
        elif sensor_type == "memory_usage":
            point["memory_usage"] = random.randint(40, 80)
        else:
            point[sensor_type] = random.randint(0, 100)

        history.append(point)

    return ApiResponse.success(data={
        "device_id": device_id,
        "sensor_type": sensor_type,
        "total": len(history),
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "data": history,
        "source": "mock",
    })


# ==================== 设备控制接口 ====================

@router.post("/control/{device_id}/action")
async def send_device_action(
    device_id: str,
    body: DeviceActionRequest,
    current_user: dict = Depends(get_current_user),
):
    """发送设备动作指令（代理到 M6，不可用时返回 mock 结果）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_post(
            f"/api/v1/control/{device_id}/action",
            json_data={"action": body.action, "params": body.params}
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data=data, message=result.get("message", "指令已发送"))
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    if device["status"] == "offline":
        return ApiResponse.error(code=400, message="设备离线，无法执行指令")
    
    # 模拟动作执行结果
    action = body.action
    result_data = {
        "action": action,
        "success": True,
        "executed_at": datetime.now().isoformat(),
        "result": f"动作 {action} 已执行",
    }
    
    # 特殊动作处理
    if action == "find_device":
        result_data["result"] = "设备正在响铃"
    elif action == "start_exercise":
        result_data["result"] = "运动模式已启动"
    elif action == "stop_exercise":
        result_data["result"] = "运动模式已停止"
    elif action == "take_photo":
        result_data["result"] = "拍照完成"
        result_data["photo_id"] = f"photo_{uuid.uuid4().hex[:8]}"
    
    return ApiResponse.success(
        message="指令已发送",
        data={
            **result_data,
            "source": "mock",
        }
    )


@router.post("/control/{device_id}/notify")
async def push_notification(
    device_id: str,
    body: NotifyRequest,
    current_user: dict = Depends(get_current_user),
):
    """向设备推送通知（代理到 M6，不可用时返回 mock 结果）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        result = await _proxy_m6_post(
            f"/api/v1/control/{device_id}/notify",
            json_data={
                "title": body.title,
                "content": body.content,
                "notification_type": body.notification_type,
            }
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data=data, message=result.get("message", "通知已推送"))
    
    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")
    
    if device["status"] == "offline":
        return ApiResponse.error(code=400, message="设备离线，无法推送通知")
    
    return ApiResponse.success(
        message="通知已推送",
        data={
            "device_id": device_id,
            "title": body.title,
            "content": body.content,
            "notification_type": body.notification_type,
            "delivered": True,
            "delivered_at": datetime.now().isoformat(),
            "source": "mock",
        }
    )


@router.get("/control/{device_id}/alerts")
async def get_device_alerts(
    device_id: str,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    status: Optional[str] = Query(None, description="按状态过滤: active/resolved/ignored"),
    current_user: dict = Depends(get_current_user),
):
    """获取设备告警列表（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        params = {"limit": limit}
        if status:
            params["status"] = status

        result = await _proxy_m6_get(
            f"/api/v1/control/{device_id}/alerts",
            params=params
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })

    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")

    # 生成模拟告警列表（3-5条）
    alert_templates = [
        {
            "alert_type": "low_battery",
            "title": "电量不足",
            "message": "设备电量低于20%，请及时充电",
            "severity": "warning",
        },
        {
            "alert_type": "abnormal_heart_rate",
            "title": "心率异常",
            "message": "检测到心率超出正常范围（60-100 bpm）",
            "severity": "error",
        },
        {
            "alert_type": "device_offline",
            "title": "设备离线",
            "message": "设备已断开连接，请检查设备状态",
            "severity": "error",
        },
        {
            "alert_type": "high_temperature",
            "title": "体温偏高",
            "message": "检测到体温超过37.5度，请注意休息",
            "severity": "warning",
        },
        {
            "alert_type": "low_spo2",
            "title": "血氧偏低",
            "message": "血氧饱和度低于90%，建议深呼吸",
            "severity": "warning",
        },
    ]

    alerts = []
    count = min(limit, random.randint(3, 5))
    now = datetime.now()

    for i in range(count):
        template = alert_templates[i % len(alert_templates)]
        alert_status = random.choice(["active", "resolved", "ignored"])

        # 按状态过滤
        if status and alert_status != status:
            continue

        alerts.append({
            "alert_id": f"alert_{uuid.uuid4().hex[:8]}",
            "device_id": device_id,
            **template,
            "status": alert_status,
            "created_at": (now - timedelta(minutes=random.randint(5, 120))).isoformat(),
            "resolved_at": (
                (now - timedelta(minutes=random.randint(1, 30))).isoformat()
                if alert_status == "resolved" else None
            ),
        })

    return ApiResponse.success(data={
        "device_id": device_id,
        "total": len(alerts),
        "alerts": alerts,
        "source": "mock",
    })


@router.get("/control/{device_id}/notifications")
async def get_notification_history(
    device_id: str,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    notification_type: Optional[str] = Query(None, description="按类型过滤: info/warning/error"),
    current_user: dict = Depends(get_current_user),
):
    """获取设备通知历史（代理到 M6，不可用时返回 mock 数据）"""
    # 尝试从 M6 获取
    m6_available = await _check_m6_available()
    if m6_available:
        params = {"limit": limit}
        if notification_type:
            params["notification_type"] = notification_type

        result = await _proxy_m6_get(
            f"/api/v1/control/{device_id}/notifications",
            params=params
        )
        if result is not None:
            data = result.get("data", result)
            return ApiResponse.success(data={
                **data,
                "source": "m6",
            })

    # Mock 模式
    device = _get_mock_device(device_id)
    if not device:
        return ApiResponse.error(code=404, message="设备不存在")

    # 生成模拟通知历史
    notification_templates = [
        {"title": "日程提醒", "content": "10分钟后有会议", "notification_type": "info"},
        {"title": "久坐提醒", "content": "您已久坐1小时，建议起身活动", "notification_type": "info"},
        {"title": "电量不足", "content": "设备电量低于20%", "notification_type": "warning"},
        {"title": "运动目标达成", "content": "今日步数目标已完成！", "notification_type": "info"},
        {"title": "睡眠质量报告", "content": "昨晚深睡时长2.5小时", "notification_type": "info"},
        {"title": "心率异常提醒", "content": "检测到静息心率偏高", "notification_type": "warning"},
        {"title": "设备连接断开", "content": "设备已断开蓝牙连接", "notification_type": "error"},
        {"title": "固件更新可用", "content": "新版本v2.4.0已发布", "notification_type": "info"},
    ]

    notifications = []
    count = min(limit, random.randint(5, 15))
    now = datetime.now()

    for i in range(count):
        template = notification_templates[i % len(notification_templates)]

        # 按类型过滤
        if notification_type and template["notification_type"] != notification_type:
            continue

        notifications.append({
            "notification_id": f"notif_{uuid.uuid4().hex[:8]}",
            "device_id": device_id,
            **template,
            "sent_at": (now - timedelta(minutes=random.randint(5, 180))).isoformat(),
            "read": random.choice([True, False]),
        })

    return ApiResponse.success(data={
        "device_id": device_id,
        "total": len(notifications),
        "notifications": notifications,
        "source": "mock",
    })
