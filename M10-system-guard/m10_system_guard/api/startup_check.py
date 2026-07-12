"""
M10 系统卫士 - 启动安全检查 API

供 M1 总控调用的启动前安全检查接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..models import make_response, StartupCheckRequest
from ..startup_check import get_startup_checker

router = APIRouter()


def _success(data=None, message: str = "ok"):
    """构造成功响应."""
    return make_response(data=data, message=message)


@router.post("/check", summary="执行启动检查")
async def startup_check(request: StartupCheckRequest):
    """执行启动前安全检查.

    供 M1 总控在重型任务执行前调用，评估当前系统状态是否适合启动新任务。
    返回三级评估结果：安全(safe) / 警告(warning) / 危险(danger)
    """
    checker = get_startup_checker()
    result = checker.check_before_start(
        task_name=request.task_name,
        task_level=request.task_level,
        estimated_cpu_percent=request.estimated_cpu_percent,
        estimated_memory_mb=request.estimated_memory_mb,
        same_process_name=request.same_process_name,
    )
    return _success(result.to_dict())


@router.get("/result/{check_id}", summary="检查结果")
async def check_result(check_id: str):
    """根据 ID 获取历史检查结果."""
    checker = get_startup_checker()
    history = checker.get_check_history(limit=200)
    for result in history:
        if result.check_id == check_id:
            return _success(result.to_dict())
    return make_response(code=404, message=f"检查记录不存在: {check_id}")


@router.get("/history", summary="检查历史")
async def check_history(limit: int = Query(50, ge=1, le=200, description="返回数量")):
    """获取启动检查历史记录."""
    checker = get_startup_checker()
    results = checker.get_check_history(limit=limit)
    return _success({
        "count": len(results),
        "results": [r.to_dict() for r in results],
    })


@router.get("/stats", summary="检查统计")
async def check_stats():
    """获取启动检查统计信息."""
    checker = get_startup_checker()
    stats = checker.get_stats()
    return _success(stats)


@router.get("/levels", summary="检查级别说明")
async def check_levels():
    """获取启动检查各级别说明."""
    return _success({
        "levels": {
            "safe": {
                "name": "安全",
                "description": "系统资源充足，可以安全启动任务",
                "allowed": True,
            },
            "warning": {
                "name": "警告",
                "description": "系统资源偏高，可以启动但建议关注",
                "allowed": True,
            },
            "danger": {
                "name": "危险",
                "description": "系统资源不足，不建议启动任务",
                "allowed": False,
            },
        },
        "task_levels": {
            "light": {"name": "轻量", "description": "低资源需求任务"},
            "normal": {"name": "普通", "description": "标准资源需求任务"},
            "heavy": {"name": "重型", "description": "高资源需求任务"},
            "super_heavy": {"name": "超重型", "description": "极高资源需求任务"},
        },
    })
