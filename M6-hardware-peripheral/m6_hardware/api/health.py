"""
M6 硬件外设 - 健康检查 API
服务健康状态、统计信息
"""

import uuid
import time
from fastapi import APIRouter

from ..config import get_config
from ..services.device_manager import get_device_manager
from ..services.data_collector import get_data_collector
from ..realtime.sse_manager import get_sse_manager

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
async def health_check():
    """服务健康检查端点"""
    config = get_config()
    return _success({
        "status": "healthy",
        "module": "m6-hardware",
        "version": "1.0.0",
        "simulation_mode": config.simulation_mode,
        "uptime_seconds": int(time.time() - _start_time),
    })


@router.get("/stats", summary="服务统计")
async def service_stats():
    """获取服务运行统计信息"""
    dm = get_device_manager()
    dc = get_data_collector()
    sse = get_sse_manager()
    config = get_config()

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
        "history_retention_days": config.history_retention_days,
    })
