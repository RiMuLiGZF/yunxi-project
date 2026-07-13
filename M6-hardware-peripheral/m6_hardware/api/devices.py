"""
M6 硬件外设 - 设备管理 API
设备列表、详情、配对、扫描等
"""

from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import get_device_manager
from .utils import success_response, get_device_or_404
from ..services.device_manager import DeviceManager
from ..models.device import DeviceStatus, DeviceType

router = APIRouter()


# 请求模型
class DeviceConfigUpdate(BaseModel):
    """设备配置更新请求"""
    name: Optional[str] = Field(None, description="设备名称")
    position: Optional[dict] = Field(None, description="位置坐标")
    config: Optional[dict] = Field(None, description="其他配置")


@router.get("/types", summary="获取设备类型列表")
async def list_device_types():
    """获取所有支持的设备类型"""
    from ..models.device import DeviceType
    types = [
        {"key": t.value, "name": t.value, "description": _get_type_desc(t.value)}
        for t in DeviceType
    ]
    return success_response({
        "total": len(types),
        "types": types,
    })


def _get_type_desc(type_key: str) -> str:
    desc_map = {
        "watch": "智能手表 - 心率、步数、血氧等健康监测",
        "ring": "智能戒指 - 睡眠、体温、HRV 等精准监测",
        "desktop": "桌面终端 - 桌面显示屏、环境传感器",
        "ar": "AR 眼镜 - 增强现实、视觉交互",
        "drone": "无人机 - 空中拍摄、环境探测",
        "laptop": "笔记本电脑 - 算力终端、文件同步",
    }
    return desc_map.get(type_key, type_key)


@router.get("", summary="获取设备列表")
async def list_devices(
    status: Optional[str] = Query(None, description="按状态过滤: online/offline/warning/charging"),
    device_type: Optional[str] = Query(None, description="按类型过滤: watch/ring/desktop/ar/drone/laptop"),
    dm: DeviceManager = Depends(get_device_manager),
):
    """获取设备列表，支持按状态和类型筛选"""
    status_enum = DeviceStatus(status) if status else None
    type_enum = DeviceType(device_type) if device_type else None

    devices = dm.list_devices(status=status_enum, device_type=type_enum)
    return success_response({
        "total": len(devices),
        "devices": devices,
    })


@router.get("/stats", summary="获取设备统计")
async def get_device_stats(dm: DeviceManager = Depends(get_device_manager)):
    """获取设备统计数据"""
    stats = dm.get_stats()
    return success_response(stats)


@router.get("/{device_id}", summary="获取设备详情")
async def get_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """获取单个设备的详细信息（含最新传感器数据）"""
    device = get_device_or_404(dm, device_id)
    return success_response(device)


@router.post("/{device_id}/pair", summary="配对设备")
async def pair_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """配对指定设备"""
    result = dm.pair_device(device_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return success_response(result, "配对成功")


@router.post("/{device_id}/unpair", summary="取消配对")
async def unpair_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """取消设备配对"""
    result = dm.unpair_device(device_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return success_response(result, "已取消配对")


@router.put("/{device_id}/config", summary="更新设备配置")
async def update_device_config(device_id: str, body: DeviceConfigUpdate, dm: DeviceManager = Depends(get_device_manager)):
    """更新设备配置（名称、位置等）"""
    config_dict = body.model_dump(exclude_none=True)
    if not config_dict:
        raise HTTPException(status_code=400, detail="没有提供有效的配置项")

    result = dm.update_device_config(device_id, config_dict)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return success_response(result, "配置已更新")


@router.post("/scan", summary="扫描附近设备")
async def scan_devices(dm: DeviceManager = Depends(get_device_manager)):
    """扫描附近可发现的设备（模拟）"""
    found = dm.scan_devices()
    return success_response({
        "found_count": len(found),
        "devices": found,
    }, "扫描完成")
