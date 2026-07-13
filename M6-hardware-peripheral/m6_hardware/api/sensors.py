"""
M6 硬件外设 - 传感器数据 API
实时数据、历史数据查询
"""

from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Query, Depends

from .deps import get_device_manager, get_data_collector
from .utils import success_response, get_device_or_404
from ..services.data_collector import DataCollector
from ..services.device_manager import DeviceManager

router = APIRouter()


@router.get("/{device_id}", summary="获取设备最新传感器数据")
async def get_latest_sensor_data(
    device_id: str,
    dm: DeviceManager = Depends(get_device_manager),
    dc: DataCollector = Depends(get_data_collector),
):
    """获取指定设备的最新传感器数据"""
    get_device_or_404(dm, device_id)

    data = dc.get_latest_sensor_data(device_id)
    return success_response(data)


@router.get("/{device_id}/history", summary="获取传感器历史数据")
async def get_sensor_history(
    device_id: str,
    sensor_type: Optional[str] = Query(None, description="传感器类型，如 heart_rate"),
    start_time: Optional[str] = Query(None, description="开始时间 ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间 ISO 格式"),
    limit: int = Query(100, ge=1, le=5000, description="返回条数"),
    dm: DeviceManager = Depends(get_device_manager),
    dc: DataCollector = Depends(get_data_collector),
):
    """查询传感器历史数据，支持按时间范围和传感器类型筛选"""
    get_device_or_404(dm, device_id)

    # 解析时间
    start_dt = None
    end_dt = None
    try:
        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00").replace(" ", "T"))
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        raise HTTPException(status_code=400, detail="时间格式错误，请使用 ISO 格式")

    # 默认查最近 1 小时
    if not start_dt and not end_dt:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(hours=1)

    history = dc.get_sensor_history(
        device_id=device_id,
        sensor_type=sensor_type,
        start_time=start_dt,
        end_time=end_dt,
        limit=limit,
    )

    return success_response({
        "device_id": device_id,
        "sensor_type": sensor_type or "all",
        "total": len(history),
        "start_time": start_dt.isoformat() if start_dt else None,
        "end_time": end_dt.isoformat() if end_dt else None,
        "data": history,
    })


@router.get("/{device_id}/{sensor_type}", summary="获取特定传感器数据")
async def get_specific_sensor(
    device_id: str,
    sensor_type: str,
    limit: int = Query(100, ge=1, le=1000, description="返回条数"),
    hours: int = Query(1, ge=1, le=168, description="查询最近几小时"),
    dm: DeviceManager = Depends(get_device_manager),
    dc: DataCollector = Depends(get_data_collector),
):
    """获取指定设备特定传感器的历史数据"""
    get_device_or_404(dm, device_id)

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(hours=hours)

    history = dc.get_sensor_history(
        device_id=device_id,
        sensor_type=sensor_type,
        start_time=start_dt,
        end_time=end_dt,
        limit=limit,
    )

    return success_response({
        "device_id": device_id,
        "sensor_type": sensor_type,
        "total": len(history),
        "data": history,
    })
