"""
M10 系统卫士 - 进程管理 API

进程列表、进程树、Top N、云汐进程、VS Code 检测等接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import M10ErrorCode
from ..models import make_response
from ..process_manager import get_process_manager

from .response import success as _success

router = APIRouter()





@router.get("", summary="进程列表")
async def process_list(
    refresh: bool = Query(False, description="是否强制刷新"),
):
    """获取全量进程快照列表."""
    pm = get_process_manager()
    processes = pm.get_all_processes(refresh=refresh)
    return _success({
        "total": len(processes),
        "processes": [p.to_dict() for p in processes],
    })


@router.get("/tree", summary="进程树")
async def process_tree():
    """获取进程树结构."""
    pm = get_process_manager()
    roots = pm.get_process_tree()

    def tree_to_dict(node):
        return {
            "process": node.process.to_dict(),
            "children": [tree_to_dict(child) for child in node.children],
        }

    return _success({
        "root_count": len(roots),
        "tree": [tree_to_dict(r) for r in roots],
    })


@router.get("/top-cpu", summary="CPU Top N")
async def top_cpu(n: int = Query(10, ge=1, le=100, description="返回数量")):
    """获取 CPU 使用率 Top N 进程."""
    pm = get_process_manager()
    processes = pm.get_top_by_cpu(n)
    return _success({
        "n": n,
        "processes": [p.to_dict() for p in processes],
    })


@router.get("/top-memory", summary="内存 Top N")
async def top_memory(n: int = Query(10, ge=1, le=100, description="返回数量")):
    """获取内存使用 Top N 进程."""
    pm = get_process_manager()
    processes = pm.get_top_by_memory(n)
    return _success({
        "n": n,
        "processes": [p.to_dict() for p in processes],
    })


@router.get("/yunxi", summary="云汐进程")
async def yunxi_processes():
    """获取云汐系统进程列表."""
    pm = get_process_manager()
    processes = pm.get_yunxi_processes()
    by_module = pm.get_yunxi_processes_by_module()
    return _success({
        "total": len(processes),
        "by_module": {k: [p.to_dict() for p in v] for k, v in by_module.items()},
        "processes": [p.to_dict() for p in processes],
    })


@router.get("/vscode", summary="VS Code 进程")
async def vscode_processes():
    """获取 VS Code 进程及限制检查结果."""
    pm = get_process_manager()
    processes = pm.get_vscode_processes()
    check_result = pm.check_vscode_limit()
    return _success({
        "process_count": len(processes),
        "processes": [p.to_dict() for p in processes],
        "limit_check": check_result,
    })


@router.get("/search", summary="搜索进程")
async def search_process(keyword: str = Query(..., description="搜索关键词")):
    """按名称或路径搜索进程."""
    pm = get_process_manager()
    processes = pm.search_processes(keyword)
    return _success({
        "keyword": keyword,
        "count": len(processes),
        "processes": [p.to_dict() for p in processes],
    })


@router.get("/{pid}", summary="进程详情")
async def process_detail(pid: int):
    """根据 PID 获取进程详情."""
    pm = get_process_manager()
    proc = pm.get_process_by_pid(pid)
    if proc is None:
        return make_response(code=M10ErrorCode.PROCESS_NOT_FOUND, message=f"进程 PID={pid} 不存在")
    return _success(proc.to_dict())


@router.get("/stats/summary", summary="进程统计")
async def process_stats():
    """获取进程统计摘要."""
    pm = get_process_manager()
    stats = pm.get_process_stats()
    return _success(stats)
