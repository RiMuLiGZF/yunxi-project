"""
部署中心路由 - 模块管理
支持模块的真实启停、进程监控
"""

import sys
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry, ModuleStatus
from shared.process_manager import get_process_manager, ProcessStatus
from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()
registry = get_module_registry()
process_mgr = get_process_manager()


class ModuleActionRequest(BaseModel):
    module_key: str
    force: Optional[bool] = False


@router.get("/modules")
async def list_modules(current_user: dict = Depends(get_current_user)):
    """获取所有模块列表（含进程信息）"""
    modules = registry.get_all_modules()
    processes = process_mgr.get_all_processes()
    
    result = []
    for m in modules:
        info = m.to_dict()
        proc = processes.get(m.key)
        if proc:
            info["process"] = proc.to_dict()
            # 用进程状态覆盖模块状态（更准确）
            if proc.status == ProcessStatus.RUNNING:
                info["status"] = "running"
            elif proc.status == ProcessStatus.STARTING:
                info["status"] = "starting"
            elif proc.status == ProcessStatus.STOPPING:
                info["status"] = "stopping"
            elif proc.status == ProcessStatus.ERROR:
                info["status"] = "error"
            elif proc.status == ProcessStatus.STOPPED:
                info["status"] = "stopped"
        result.append(info)
    
    return ApiResponse.success(data=result)


@router.get("/modules/{module_key}")
async def get_module(module_key: str, current_user: dict = Depends(get_current_user)):
    """获取单个模块详情"""
    module = registry.get_module(module_key)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_key} 不存在")
    
    info = module.to_dict()
    proc = process_mgr.get_process_info(module_key)
    if proc:
        info["process"] = proc.to_dict()
    
    return ApiResponse.success(data=info)


@router.post("/modules/{module_key}/start")
async def start_module(
    module_key: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """启动模块"""
    module = registry.get_module(module_key)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_key} 不存在")
    
    # M8 自己不能启动自己
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台自身已在运行",
            data=module.to_dict(),
        )
    
    proc_info = process_mgr.start_module(module_key)
    
    if proc_info.status == ProcessStatus.ERROR:
        return ApiResponse.error(
            message=f"模块 {module_key} 启动失败",
            data={"error": proc_info.error_message, "process": proc_info.to_dict()},
        )
    
    module.status = ModuleStatus.RUNNING if proc_info.status == ProcessStatus.RUNNING else ModuleStatus.UNKNOWN
    
    return ApiResponse.success(
        message=f"模块 {module_key} 启动指令已发送" if proc_info.status == ProcessStatus.STARTING else f"模块 {module_key} 已启动",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )


@router.post("/modules/{module_key}/stop")
async def stop_module(
    module_key: str,
    request: ModuleActionRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """停止模块"""
    module = registry.get_module(module_key)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_key} 不存在")
    
    # M8 自己不能停止自己
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台无法自行停止，请使用停止脚本",
            data=module.to_dict(),
        )
    
    force = request.force if request else False
    proc_info = process_mgr.stop_module(module_key, force=force)
    
    module.status = ModuleStatus.STOPPED
    
    return ApiResponse.success(
        message=f"模块 {module_key} 停止指令已发送",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )


@router.post("/modules/{module_key}/restart")
async def restart_module(
    module_key: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """重启模块"""
    module = registry.get_module(module_key)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_key} 不存在")
    
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台无法自行重启",
            data=module.to_dict(),
        )
    
    proc_info = process_mgr.restart_module(module_key)
    
    return ApiResponse.success(
        message=f"模块 {module_key} 重启指令已发送",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )


@router.post("/health-check")
async def health_check_all(current_user: dict = Depends(get_current_user)):
    """对所有模块执行健康检查"""
    results = await registry.check_all_health()
    summary = registry.get_status_summary()
    
    # 同步进程状态
    processes = process_mgr.get_all_processes()
    
    return ApiResponse.success(
        message="健康检查完成",
        data={
            "results": results,
            "summary": summary,
            "processes": {k: v.to_dict() for k, v in processes.items()},
        },
    )


@router.get("/repository")
async def get_repository(current_user: dict = Depends(get_current_user)):
    """获取模块仓库列表"""
    modules = registry.get_all_modules()
    processes = process_mgr.get_all_processes()
    
    items = []
    for m in modules:
        info = m.to_dict()
        proc = processes.get(m.key)
        if proc:
            info["process"] = proc.to_dict()
        info["can_start"] = m.key != "m8" and m.key in ["m1", "m2", "m3", "m5", "m6", "m7"]
        items.append(info)
    
    return ApiResponse.success(
        data={
            "total": len(modules),
            "items": items,
        }
    )


@router.get("/modules/{module_key}/logs")
async def get_module_logs(
    module_key: str,
    lines: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """获取模块运行日志"""
    module = registry.get_module(module_key)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_key} 不存在")
    
    logs = process_mgr.get_logs(module_key, lines)
    
    return ApiResponse.success(
        data={
            "module_key": module_key,
            "lines": len(logs),
            "logs": logs,
        }
    )
