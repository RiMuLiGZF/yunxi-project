"""
M6 硬件外设 - 设备管理 API
设备列表、详情、配对、扫描、注册等

P2 半真实化改造：
- 新增设备注册/发现/移除接口
- 集成延迟模拟
"""

from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field

from .deps import get_device_manager
from .utils import success_response, get_device_or_404
from ..services.device_manager import DeviceManager
from ..services.simulation_core import get_delay_simulator
from ..models.device import DeviceStatus, DeviceType

router = APIRouter()


# 请求模型
class DeviceConfigUpdate(BaseModel):
    """设备配置更新请求"""
    name: Optional[str] = Field(None, description="设备名称")
    position: Optional[dict] = Field(None, description="位置坐标")
    config: Optional[dict] = Field(None, description="其他配置")


class DeviceRegisterRequest(BaseModel):
    """设备注册请求"""
    device_id: Optional[str] = Field(None, description="设备ID（可选，自动生成）")
    name: str = Field(..., description="设备名称")
    device_type: str = Field(..., description="设备类型: smart_lamp/temp_humidity/smart_plug/curtain_motor/watch/ring/desktop/ar/drone/laptop")
    status: Optional[str] = Field("online", description="设备状态")
    battery: Optional[float] = Field(None, description="电量百分比")
    signal_strength: Optional[int] = Field(85, description="信号强度")
    firmware_version: Optional[str] = Field("1.0.0", description="固件版本")
    position: Optional[dict] = Field(None, description="位置坐标")
    paired: Optional[bool] = Field(True, description="是否已配对")


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
        # P2 半真实化：智能家居设备
        "smart_lamp": "智能台灯 - 亮度调节、色温切换、使用统计",
        "temp_humidity": "温湿度传感器 - 环境温度、湿度、体感温度",
        "smart_plug": "智能插座 - 功率计量、过载保护、用电统计",
        "curtain_motor": "窗帘电机 - 开合控制、位置记忆、电机温度监测",
        "air_quality": "空气质量传感器 - PM2.5、CO2、VOC、空气质量等级",
    }
    return desc_map.get(type_key, type_key)


@router.get("", summary="获取设备列表")
async def list_devices(
    status: Optional[str] = Query(None, description="按状态过滤: online/offline/warning/charging"),
    device_type: Optional[str] = Query(None, description="按类型过滤"),
    dm: DeviceManager = Depends(get_device_manager),
):
    """获取设备列表，支持按状态和类型筛选（读取类操作，含延迟模拟）"""
    # P2: 读取类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_read_delay()

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
    # P2: 读取类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_read_delay()

    stats = dm.get_stats()
    return success_response(stats)


@router.get("/{device_id}", summary="获取设备详情")
async def get_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """获取单个设备的详细信息（含最新传感器数据）（读取类操作，含延迟模拟）"""
    # P2: 读取类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_read_delay()

    device = get_device_or_404(dm, device_id)
    return success_response(device)


@router.post("/{device_id}/pair", summary="配对设备")
async def pair_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """配对指定设备（写入类操作，含延迟模拟）"""
    # P2: 写入类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_write_delay()

    result = dm.pair_device(device_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    # 保存状态
    dm.save_device_state(device_id)

    return success_response(result, "配对成功")


@router.post("/{device_id}/unpair", summary="取消配对")
async def unpair_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """取消设备配对（写入类操作，含延迟模拟）"""
    # P2: 写入类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_write_delay()

    result = dm.unpair_device(device_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    # 保存状态
    dm.save_device_state(device_id)

    return success_response(result, "已取消配对")


@router.put("/{device_id}/config", summary="更新设备配置")
async def update_device_config(device_id: str, body: DeviceConfigUpdate, dm: DeviceManager = Depends(get_device_manager)):
    """更新设备配置（名称、位置等）（写入类操作，含延迟模拟）"""
    # P2: 写入类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_write_delay()

    config_dict = body.model_dump(exclude_none=True)
    if not config_dict:
        raise HTTPException(status_code=400, detail="没有提供有效的配置项")

    result = dm.update_device_config(device_id, config_dict)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    # 保存状态
    dm.save_device_state(device_id)

    return success_response(result, "配置已更新")


@router.post("/scan", summary="扫描附近设备")
async def scan_devices(dm: DeviceManager = Depends(get_device_manager)):
    """扫描附近可发现的设备（模拟）（含扫描延迟模拟）"""
    # P2: 扫描类操作延迟模拟（较长）
    delay = get_delay_simulator()
    await delay.simulate_custom_delay(500, 1500)

    found = dm.scan_devices()
    return success_response({
        "found_count": len(found),
        "devices": found,
    }, "扫描完成")


# ------------------------------------------------------------------
# P2 半真实化改造：设备注册/发现/移除接口
# ------------------------------------------------------------------

@router.post("/register", summary="注册新设备")
async def register_device(
    body: DeviceRegisterRequest,
    dm: DeviceManager = Depends(get_device_manager),
):
    """注册新设备到系统中（模拟真实硬件的设备发现和注册）

    注册成功后设备将出现在设备列表中，状态持久化保存。
    """
    # P2: 写入类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_write_delay()

    device_data = body.model_dump(exclude_none=True)
    result = dm.register_device(device_data)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return success_response(result, "设备注册成功")


@router.get("/discover", summary="发现网络中的设备")
async def discover_devices(dm: DeviceManager = Depends(get_device_manager)):
    """发现网络中的可配对设备（模拟扫描过程）

    返回可发现但尚未注册的设备列表，模拟真实硬件的设备发现协议。
    """
    # P2: 扫描发现延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_custom_delay(1000, 3000)

    devices = dm.discover_devices()
    return success_response({
        "total": len(devices),
        "devices": devices,
    }, "设备发现完成")


@router.delete("/{device_id}", summary="移除设备")
async def remove_device(
    device_id: str,
    dm: DeviceManager = Depends(get_device_manager),
):
    """从系统中移除设备（同时删除持久化状态）"""
    # P2: 写入类操作延迟模拟
    delay = get_delay_simulator()
    await delay.simulate_write_delay()

    result = dm.remove_device(device_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])

    return success_response(result, "设备已移除")
