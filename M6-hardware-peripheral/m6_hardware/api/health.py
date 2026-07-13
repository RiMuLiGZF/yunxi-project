"""
M6 硬件外设 - 健康检查 API
服务健康状态、统计信息
"""

import uuid
import time
from fastapi import APIRouter, Depends

from .deps import get_config, get_device_manager, get_data_collector, get_sse_manager
from ..config import M6Config
from ..services.device_manager import DeviceManager
from ..services.data_collector import DataCollector
from ..realtime.sse_manager import SSEManager

router = APIRouter()


def _success(data=None, message: str = "ok"):
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": uuid.uuid4().hex[:16],
        "timestamp": time.time(),
    }


_start_time = time.time()


@router.get("", summary="健康检查")
async def health_check(config: M6Config = Depends(get_config)):
    """服务健康检查端点"""
    return _success({
        "status": "healthy",
        "module": "m6-hardware",
        "version": "1.0.0",
        "simulation_mode": config.simulation_mode,
        "uptime_seconds": int(time.time() - _start_time),
    })


@router.get("/stats", summary="服务统计")
async def service_stats(
    dm: DeviceManager = Depends(get_device_manager),
    dc: DataCollector = Depends(get_data_collector),
    sse: SSEManager = Depends(get_sse_manager),
    config: M6Config = Depends(get_config),
):
    """获取服务运行统计信息"""
    device_stats = dm.get_stats()

    return _success({
        "module": "m6-hardware",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - _start_time),
        "simulation_mode": config.simulation_mode,
        "devices": device_stats,
        "sse_clients": sse.client_count,
        "collection_interval": config.collection_interval,
        "database_path": config.database_path,
        "data_retention_days": config.data_retention_days,
    })
