"""
GPU 算力管理 API 路由
前缀：/api/compute/gpu

提供 GPU 算力源管理、任务提交、状态查询等接口。
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import get_db
from ..services.gpu_compute_service import (
    get_gpu_compute_manager,
    GPUComputeSource,
    GPUDeviceStatus,
    GPUTask,
)

router = APIRouter()
gpu_mgr = get_gpu_compute_manager()


# ============================================================
# 请求体模型
# ============================================================

class GPUSourceCreate(BaseModel):
    """注册 GPU 算力源"""
    source_id: str = Field(..., description="算力源唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field("gpu_local", description="类型：gpu_local/gpu_remote")
    m10_base_url: str = Field("http://localhost:8700", description="M10 API 地址")
    m10_api_token: str = Field("", description="M10 认证 Token")
    max_concurrent_tasks: int = Field(10, description="最大并发任务数")
    supported_task_types: List[str] = Field(
        default_factory=lambda: ["inference", "embedding", "vector_search"],
        description="支持的任务类型"
    )
    config: Dict[str, Any] = Field(default_factory=dict, description="扩展配置")


class GPUSourceUpdate(BaseModel):
    """更新 GPU 算力源"""
    name: Optional[str] = None
    m10_base_url: Optional[str] = None
    m10_api_token: Optional[str] = None
    status: Optional[str] = None
    max_concurrent_tasks: Optional[int] = None
    supported_task_types: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None


class GPUTaskSubmit(BaseModel):
    """提交 GPU 任务"""
    name: str = Field(..., description="任务名称")
    task_type: str = Field("inference", description="任务类型")
    estimated_memory_mb: float = Field(1024.0, description="预估显存占用(MB)")
    estimated_duration_sec: float = Field(60.0, description="预估时长(秒)")
    priority: int = Field(5, ge=1, le=10, description="优先级 1-10")
    caller_module: str = Field("", description="调用模块")
    callback_url: str = Field("", description="回调 URL")
    task_data: Dict[str, Any] = Field(default_factory=dict, description="任务数据")


# ============================================================
# 工具函数
# ============================================================

def _source_to_dict(source: GPUComputeSource) -> Dict[str, Any]:
    """算力源转字典"""
    return {
        "source_id": source.source_id,
        "name": source.name,
        "type": source.type,
        "m10_base_url": source.m10_base_url,
        "status": source.status,
        "total_gpu_count": source.total_gpu_count,
        "total_memory_mb": source.total_memory_mb,
        "available_memory_mb": source.available_memory_mb,
        "last_sync_time": source.last_sync_time,
        "max_concurrent_tasks": source.max_concurrent_tasks,
        "supported_task_types": source.supported_task_types,
        "devices": [
            {
                "gpu_id": d.gpu_id,
                "name": d.name,
                "usage_percent": d.usage_percent,
                "memory_total_mb": d.memory_total_mb,
                "memory_used_mb": d.memory_used_mb,
                "memory_free_mb": d.memory_free_mb,
                "memory_percent": d.memory_percent,
                "temperature_celsius": d.temperature_celsius,
                "power_watt": d.power_watt,
                "fan_speed_percent": d.fan_speed_percent,
                "process_count": len(d.processes),
            }
            for d in source.devices
        ],
    }


def _task_to_dict(task: GPUTask) -> Dict[str, Any]:
    """任务转字典"""
    return {
        "task_id": task.task_id,
        "name": task.name,
        "source_id": task.source_id,
        "gpu_id": task.gpu_id,
        "status": task.status,
        "task_type": task.task_type,
        "estimated_memory_mb": task.estimated_memory_mb,
        "estimated_duration_sec": task.estimated_duration_sec,
        "priority": task.priority,
        "submit_time": task.submit_time,
        "start_time": task.start_time,
        "end_time": task.end_time,
        "progress": task.progress,
        "caller_module": task.caller_module,
        "error_message": task.error_message,
    }


# ============================================================
# 算力源管理接口
# ============================================================

@router.get("/sources", summary="列出 GPU 算力源")
async def list_gpu_sources(
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """列出所有 GPU 算力源"""
    sources = gpu_mgr.list_sources()
    if status:
        sources = [s for s in sources if s.status == status]

    return ApiResponse.success(data={
        "total": len(sources),
        "sources": [_source_to_dict(s) for s in sources],
    })


@router.post("/sources", summary="注册 GPU 算力源")
@require_role("admin")
async def create_gpu_source(
    req: GPUSourceCreate,
    current_user: dict = Depends(get_current_user),
):
    """注册新的 GPU 算力源"""
    if gpu_mgr.get_source(req.source_id):
        raise HTTPException(status_code=400, detail=f"算力源 {req.source_id} 已存在")

    source = GPUComputeSource(
        source_id=req.source_id,
        name=req.name,
        type=req.type,
        m10_base_url=req.m10_base_url,
        m10_api_token=req.m10_api_token,
        max_concurrent_tasks=req.max_concurrent_tasks,
        supported_task_types=req.supported_task_types,
        config=req.config,
    )
    gpu_mgr.register_source(source)

    # 尝试同步状态
    try:
        await gpu_mgr.sync_source_status(req.source_id)
    except Exception:
        pass

    return ApiResponse.success(data=_source_to_dict(source), message="算力源注册成功")


@router.get("/sources/{source_id}", summary="获取 GPU 算力源详情")
async def get_gpu_source(
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单个 GPU 算力源详情"""
    source = gpu_mgr.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="算力源不存在")

    return ApiResponse.success(data=_source_to_dict(source))


@router.put("/sources/{source_id}", summary="更新 GPU 算力源")
@require_role("admin")
async def update_gpu_source(
    source_id: str,
    req: GPUSourceUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新 GPU 算力源配置"""
    source = gpu_mgr.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="算力源不存在")

    if req.name is not None:
        source.name = req.name
    if req.m10_base_url is not None:
        source.m10_base_url = req.m10_base_url
    if req.m10_api_token is not None:
        source.m10_api_token = req.m10_api_token
    if req.status is not None:
        source.status = req.status
    if req.max_concurrent_tasks is not None:
        source.max_concurrent_tasks = req.max_concurrent_tasks
    if req.supported_task_types is not None:
        source.supported_task_types = req.supported_task_types
    if req.config is not None:
        source.config.update(req.config)

    return ApiResponse.success(data=_source_to_dict(source), message="更新成功")


@router.delete("/sources/{source_id}", summary="删除 GPU 算力源")
@require_role("admin")
async def delete_gpu_source(
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除 GPU 算力源"""
    if not gpu_mgr.unregister_source(source_id):
        raise HTTPException(status_code=404, detail="算力源不存在")

    return ApiResponse.success(message="删除成功")


@router.post("/sources/{source_id}/sync", summary="同步 GPU 算力源状态")
async def sync_gpu_source(
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    """从 M10 同步算力源实时状态"""
    source = gpu_mgr.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="算力源不存在")

    success = await gpu_mgr.sync_source_status(source_id)

    return ApiResponse.success(
        data=_source_to_dict(source),
        message="同步成功" if success else "同步失败，请检查 M10 连接",
    )


@router.post("/sync-all", summary="同步所有 GPU 算力源")
async def sync_all_gpu_sources(
    current_user: dict = Depends(get_current_user),
):
    """同步所有 GPU 算力源状态"""
    count = await gpu_mgr.sync_all_sources()
    return ApiResponse.success(data={
        "synced_count": count,
        "total_sources": len(gpu_mgr.list_sources()),
    })


# ============================================================
# 任务管理接口
# ============================================================

@router.post("/tasks", summary="提交 GPU 任务")
async def submit_gpu_task(
    req: GPUTaskSubmit,
    current_user: dict = Depends(get_current_user),
):
    """提交一个 GPU 计算任务"""
    task = GPUTask(
        name=req.name,
        task_type=req.task_type,
        estimated_memory_mb=req.estimated_memory_mb,
        estimated_duration_sec=req.estimated_duration_sec,
        priority=req.priority,
        caller_module=req.caller_module,
        callback_url=req.callback_url,
        task_data=req.task_data,
    )

    task_id = gpu_mgr.submit_task(task)
    return ApiResponse.success(
        data=_task_to_dict(task),
        message="任务提交成功",
    )


@router.get("/tasks", summary="列出 GPU 任务")
async def list_gpu_tasks(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
):
    """列出 GPU 任务列表"""
    tasks = gpu_mgr.list_tasks(status=status, limit=limit)
    return ApiResponse.success(data={
        "total": len(tasks),
        "tasks": [_task_to_dict(t) for t in tasks],
    })


@router.get("/tasks/{task_id}", summary="获取 GPU 任务详情")
async def get_gpu_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单个 GPU 任务状态"""
    task = gpu_mgr.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return ApiResponse.success(data=_task_to_dict(task))


@router.post("/tasks/{task_id}/cancel", summary="取消 GPU 任务")
async def cancel_gpu_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """取消 GPU 任务"""
    success = gpu_mgr.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务无法取消")

    task = gpu_mgr.get_task(task_id)
    return ApiResponse.success(data=_task_to_dict(task) if task else {}, message="已取消")


# ============================================================
# 统计与总览
# ============================================================

@router.get("/stats", summary="GPU 算力统计")
async def gpu_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取 GPU 算力整体统计信息"""
    stats = gpu_mgr.get_stats()
    return ApiResponse.success(data=stats)


@router.get("/overview", summary="GPU 算力总览")
async def gpu_overview(
    current_user: dict = Depends(get_current_user),
):
    """GPU 算力总览（含所有设备详情）"""
    stats = gpu_mgr.get_stats()
    sources = gpu_mgr.list_active_sources()

    all_devices = []
    for source in sources:
        for dev in source.devices:
            all_devices.append({
                "source_id": source.source_id,
                "source_name": source.name,
                "gpu_id": dev.gpu_id,
                "name": dev.name,
                "usage_percent": dev.usage_percent,
                "memory_total_mb": dev.memory_total_mb,
                "memory_used_mb": dev.memory_used_mb,
                "memory_free_mb": dev.memory_free_mb,
                "memory_percent": dev.memory_percent,
                "temperature_celsius": dev.temperature_celsius,
                "power_watt": dev.power_watt,
                "fan_speed_percent": dev.fan_speed_percent,
                "process_count": len(dev.processes),
            })

    return ApiResponse.success(data={
        "stats": stats,
        "devices": all_devices,
        "sources": [_source_to_dict(s) for s in sources],
    })
