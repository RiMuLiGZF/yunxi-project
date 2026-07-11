"""
M10 系统卫士 - 系统状态 API

系统指标查询、历史数据、资源摘要等接口。
"""

from __future__ import annotations

import time
import uuid
from fastapi import APIRouter, Query

from ..config import get_config
from ..system_monitor import get_system_monitor
from ..models import make_response, AggregationLevel

router = APIRouter()


def _success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


@router.get("", summary="系统状态摘要")
async def system_status():
    """获取系统状态摘要信息."""
    monitor = get_system_monitor()
    config = get_config()
    summary = monitor.get_summary()
    return _success({
        "module": "m10-system-guard",
        "version": config.basic.version,
        "sandbox_mode": config.sandbox.enabled,
        "status": "running",
        "sample_interval": config.sandbox.sample_interval_seconds,
        "data_counts": {
            "raw": summary["raw_data_count"],
            "minute": summary["minute_data_count"],
            "hour": summary["hour_data_count"],
            "day": summary["day_data_count"],
        },
        "latest_metric": summary["latest"],
    })


@router.get("/metrics", summary="最新系统指标")
async def latest_metrics():
    """获取最新的系统指标快照."""
    monitor = get_system_monitor()
    metric = monitor.get_latest()
    return _success(metric.to_dict())


@router.get("/metrics/{metric_type}", summary="指定类型指标")
async def metric_value(metric_type: str):
    """获取指定类型的指标值.

    - **metric_type**: cpu / memory / disk / network / gpu / temperature / battery
    """
    from ..models import MetricType
    monitor = get_system_monitor()
    try:
        mtype = MetricType(metric_type.lower())
        value = monitor.get_metric_value(mtype)
        return _success({
            "metric_type": metric_type,
            "value": value,
            "timestamp": time.time(),
        })
    except ValueError:
        return make_response(code=400, message=f"未知的指标类型: {metric_type}")


@router.get("/history", summary="历史数据")
async def history_data(
    level: str = Query("raw", description="聚合级别: raw/minute/hour/day"),
    limit: int = Query(60, ge=1, le=1000, description="返回数量"),
):
    """获取历史指标数据."""
    monitor = get_system_monitor()
    try:
        agg_level = AggregationLevel(level.lower())
    except ValueError:
        return make_response(code=400, message=f"无效的聚合级别: {level}")

    data = monitor.get_history(agg_level, limit=limit)
    return _success({
        "level": level,
        "count": len(data),
        "data": [m.to_dict() for m in data],
    })


@router.get("/summary", summary="资源使用摘要")
async def resource_summary():
    """获取资源使用概览摘要."""
    monitor = get_system_monitor()
    latest = monitor.get_latest()

    return _success({
        "cpu": {
            "usage_percent": latest.cpu.usage_percent,
            "core_count": latest.cpu.core_count,
            "load_avg_1min": latest.cpu.load_avg_1min,
        },
        "memory": {
            "usage_percent": latest.memory.usage_percent,
            "total_mb": latest.memory.total_mb,
            "used_mb": latest.memory.used_mb,
            "available_mb": latest.memory.available_mb,
        },
        "disk": {
            "usage_percent": latest.disk.usage_percent,
            "total_gb": latest.disk.total_gb,
            "used_gb": latest.disk.used_gb,
            "free_gb": latest.disk.free_gb,
        },
        "gpu": {
            "count": latest.gpu.count,
            "usage_percent": latest.gpu.usage_percent,
            "memory_percent": latest.gpu.memory_percent,
            "temperature": latest.gpu.temperature_celsius,
        },
        "temperature": {
            "highest": latest.temperature.highest_temp_celsius,
            "source": latest.temperature.highest_temp_source,
            "cpu": latest.temperature.cpu_temp_celsius,
        },
        "battery": {
            "percent": latest.battery.percent,
            "is_charging": latest.battery.is_charging,
            "remaining_minutes": latest.battery.remaining_minutes,
        },
    })



@router.get("/gpu/summary", summary="GPU 状态摘要")
async def gpu_summary():
    """获取 GPU 状态摘要信息（汇总值）."""
    monitor = get_system_monitor()
    latest = monitor.get_latest_metric()
    gpu = latest.gpu if latest else None

    if gpu is None:
        return _success(data={
            "count": 0,
            "available": False,
            "usage_percent": 0,
            "memory_used_mb": 0,
            "memory_total_mb": 0,
            "temperature_celsius": 0,
            "power_watt": 0,
        })

    return _success(data={
        "count": gpu.count,
        "available": gpu.count > 0,
        "usage_percent": gpu.usage_percent,
        "memory_used_mb": gpu.memory_used_mb,
        "memory_total_mb": gpu.memory_total_mb,
        "memory_percent": gpu.memory_percent,
        "temperature_celsius": gpu.temperature_celsius,
        "power_watt": gpu.power_watt,
        "driver_version": gpu.driver_version,
        "cuda_version": gpu.cuda_version,
    })


@router.get("/gpu/devices", summary="GPU 设备列表")
async def gpu_devices():
    """获取所有 GPU 设备的详细信息."""
    monitor = get_system_monitor()
    latest = monitor.get_latest_metric()
    gpu = latest.gpu if latest else None

    devices = []
    if gpu and gpu.devices:
        for dev in gpu.devices:
            if hasattr(dev, "to_dict"):
                devices.append(dev.to_dict())
            else:
                devices.append({
                    "gpu_id": getattr(dev, "gpu_id", 0),
                    "name": getattr(dev, "name", ""),
                    "usage_percent": getattr(dev, "usage_percent", 0),
                    "memory_used_mb": getattr(dev, "memory_used_mb", 0),
                    "memory_total_mb": getattr(dev, "memory_total_mb", 0),
                })

    return _success(data={
        "count": gpu.count if gpu else 0,
        "devices": devices,
    })


@router.get("/gpu/devices/{gpu_id}", summary="单 GPU 详情")
async def gpu_device_detail(gpu_id: int):
    """获取指定 GPU 设备的详细信息."""
    monitor = get_system_monitor()
    latest = monitor.get_latest_metric()
    gpu = latest.gpu if latest else None

    if gpu is None or not gpu.devices:
        return _success(data={}, message=f"GPU {gpu_id} not found")

    for dev in gpu.devices:
        dev_id = getattr(dev, "gpu_id", -1)
        if dev_id == gpu_id:
            if hasattr(dev, "to_dict"):
                return _success(data=dev.to_dict())
            return _success(data={
                "gpu_id": getattr(dev, "gpu_id", 0),
                "name": getattr(dev, "name", ""),
                "usage_percent": getattr(dev, "usage_percent", 0),
            })

    return _success(data={}, message=f"GPU {gpu_id} not found")


@router.get("/gpu/processes", summary="GPU 进程列表")
async def gpu_processes(gpu_id: int = -1):
    """获取运行在 GPU 上的进程列表.

    Args:
        gpu_id: 可选，指定 GPU ID，-1 表示全部
    """
    monitor = get_system_monitor()
    latest = monitor.get_latest_metric()
    gpu = latest.gpu if latest else None

    processes = []
    if gpu and gpu.processes:
        for proc in gpu.processes:
            if gpu_id >= 0 and getattr(proc, "gpu_id", -1) != gpu_id:
                continue
            if hasattr(proc, "to_dict"):
                processes.append(proc.to_dict())
            else:
                processes.append({
                    "pid": getattr(proc, "pid", 0),
                    "process_name": getattr(proc, "process_name", ""),
                    "memory_used_mb": getattr(proc, "memory_used_mb", 0),
                    "gpu_id": getattr(proc, "gpu_id", 0),
                })

    return _success(data={
        "total": len(processes),
        "processes": processes,
    })


@router.get("/gpu/history", summary="GPU 历史数据")
async def gpu_history(
    gpu_id: int = 0,
    metric: str = "usage",
    level: str = "raw",
    limit: int = 60,
):
    """获取 GPU 历史指标数据.

    Args:
        gpu_id: GPU 设备 ID
        metric: 指标类型: usage/memory/temperature/power
        level: 聚合级别: raw/minute/hour/day
        limit: 返回数据条数
    """
    monitor = get_system_monitor()
    try:
        agg_level = AggregationLevel(level)
    except ValueError:
        agg_level = AggregationLevel.RAW

    history = monitor.get_history(agg_level, limit)

    result = []
    for metric_data in history:
        gpu = metric_data.gpu
        value = 0.0
        # 从设备列表中找指定 GPU
        if gpu and gpu.devices and gpu_id < len(gpu.devices):
            dev = gpu.devices[gpu_id]
            if metric == "usage":
                value = getattr(dev, "usage_percent", 0)
            elif metric == "memory":
                value = getattr(dev, "memory_percent", 0)
            elif metric == "temperature":
                value = getattr(dev, "temperature_celsius", 0)
            elif metric == "power":
                value = getattr(dev, "power_watt", 0)
        else:
            # 降级使用汇总值
            if gpu:
                if metric == "usage":
                    value = gpu.usage_percent
                elif metric == "memory":
                    value = gpu.memory_percent
                elif metric == "temperature":
                    value = gpu.temperature_celsius
                elif metric == "power":
                    value = gpu.power_watt

        result.append({
            "timestamp": metric_data.timestamp,
            "value": value,
        })

    return _success(data={
        "gpu_id": gpu_id,
        "metric": metric,
        "level": level,
        "count": len(result),
        "data": result,
    })
