"""
云汐 M10 系统卫士 - 进程管理 API
提供进程列表、进程树、Top N排行、启动检查、黑白名单等接口
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..services.process_monitor import get_process_monitor
    from ..services.startup_check import get_startup_check_service
    from ..models import make_response, make_error_response
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.process_monitor import get_process_monitor
    from services.startup_check import get_startup_check_service
    from models import make_response, make_error_response

router = APIRouter(prefix="/api/m10/process", tags=["M10-进程管理"])


# ===== 进程列表 =====

@router.get("/list", summary="获取进程列表")
def get_process_list(
    category: Optional[str] = Query(None, description="进程分类筛选"),
    sort_by: str = Query("cpu_percent", description="排序字段"),
    limit: int = Query(100, description="返回数量限制", ge=1, le=500),
    search: Optional[str] = Query(None, description="搜索关键词"),
):
    """
    获取系统进程列表，支持分类筛选、排序和搜索"""
    try:
        monitor = get_process_monitor()
        processes = monitor.get_process_list(
            category=category,
            sort_by=sort_by,
            limit=limit,
            search=search,
        )
        return make_response(data={
            "count": len(processes),
            "sort_by": sort_by,
            "category": category,
            "processes": processes,
        })
    except Exception as e:
        return make_error_response(f"获取进程列表失败: {str(e)}")


# ===== 进程树 =====

@router.get("/tree", summary="获取进程树")
def get_process_tree():
    """
    获取以父子关系构建的进程树结构
    """
    try:
        monitor = get_process_monitor()
        tree = monitor.get_process_tree()
        return make_response(data=tree)
    except Exception as e:
        return make_error_response(f"获取进程树失败: {str(e)}")


# ===== Top N 排行 =====

@router.get("/top", summary="Top N 进程排行")
def get_top_processes(
    n: int = Query(20, description="排名数量", ge=1, le=100),
    sort_by: str = Query("cpu_percent", description="排序字段"),
):
    """
    获取资源占用Top N的进程排行
    """
    try:
        monitor = get_process_monitor()
        top_list = monitor.get_top_n(n=n, sort_by=sort_by)
        return make_response(data={
            "count": len(top_list),
            "sort_by": sort_by,
            "top_list": top_list,
        })
    except Exception as e:
        return make_error_response(f"获取Top N进程失败: {str(e)}")


# ===== 启动安全检查 =====

@router.get("/startup-check", summary="启动安全检查")
def startup_check(
    module: str = Query(..., description="调用模块标识，如 m9, m4, m8"),
    task_type: str = Query(..., description="任务类型，如 vscode-instance, model-load"),
    expected_memory_mb: int = Query(0, description="预期新增内存占用(MB)", ge=0),
    expected_cpu_percent: float = Query(0.0, description="预期新增CPU占用(%)", ge=0, le=100),
    instance_count: int = Query(1, description="启动实例数量", ge=1, le=100),
    priority: str = Query("normal", description="优先级: high/normal/low"),
):
    """
    启动前安全检查，评估当前系统资源是否允许启动新进程
    """
    try:
        service = get_startup_check_service()
        result = service.check(
            module=module,
            task_type=task_type,
            expected_memory_mb=expected_memory_mb,
            expected_cpu_percent=expected_cpu_percent,
            instance_count=instance_count,
            priority=priority,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"启动安全检查失败: {str(e)}")


# ===== 云汐进程 =====

@router.get("/yunxi-processes", summary="云汐系统进程列表")
def get_yunxi_processes():
    """
    获取云汐系统各模块的进程列表和资源占用统计
    """
    try:
        monitor = get_process_monitor()
        yunxi = monitor.get_yunxi_processes()
        return make_response(data=yunxi)
    except Exception as e:
        return make_error_response(f"获取云汐进程失败: {str(e)}")


# ===== 进程事件 =====

@router.get("/events", summary="进程事件历史")
def get_process_events(
    limit: int = Query(50, description="返回数量限制", ge=1, le=200),
):
    """
    获取进程启动/退出事件历史记录
    """
    try:
        monitor = get_process_monitor()
        events = monitor.get_process_events(limit=limit)
        return make_response(data={
            "count": len(events),
            "events": events,
        })
    except Exception as e:
        return make_error_response(f"获取进程事件失败: {str(e)}")


# ===== 白名单管理 =====

@router.get("/whitelist", summary="获取进程白名单")
def get_whitelist():
    """
    获取进程白名单列表
    """
    try:
        monitor = get_process_monitor()
        whitelist = monitor.get_whitelist()
        return make_response(data={
            "count": len(whitelist),
            "whitelist": whitelist,
        })
    except Exception as e:
        return make_error_response(f"获取白名单失败: {str(e)}")


@router.post("/whitelist", summary="添加白名单")
def add_whitelist(
    process_name: str = Query(..., description="进程名"),
    process_path: str = Query("", description="进程路径"),
    category: str = Query("custom", description="分类"),
    description: str = Query("", description="说明"),
):
    """
    添加进程到白名单
    """
    try:
        monitor = get_process_monitor()
        result = monitor.add_whitelist(
            process_name=process_name,
            process_path=process_path,
            category=category,
            description=description,
        )
        if result["success"]:
            return make_response(data={"id": result["id"]}, message=result["message"])
        else:
            return make_error_response(result["message"])
    except Exception as e:
        return make_error_response(f"添加白名单失败: {str(e)}")


@router.delete("/whitelist/{item_id}", summary="删除白名单")
def remove_whitelist(item_id: int):
    """
    从白名单中删除进程（仅支持删除用户自定义项）
    """
    try:
        monitor = get_process_monitor()
        success = monitor.remove_whitelist(item_id)
        if success:
            return make_response(data={"deleted": True}, message="删除成功")
        else:
            return make_error_response("删除失败，可能是内置项或不存在")
    except Exception as e:
        return make_error_response(f"删除白名单失败: {str(e)}")


# ===== 黑名单管理 =====

@router.get("/blacklist", summary="获取进程黑名单")
def get_blacklist():
    """
    获取进程黑名单列表
    """
    try:
        monitor = get_process_monitor()
        blacklist = monitor.get_blacklist()
        return make_response(data={
            "count": len(blacklist),
            "blacklist": blacklist,
        })
    except Exception as e:
        return make_error_response(f"获取黑名单失败: {str(e)}")


@router.post("/blacklist", summary="添加黑名单")
def add_blacklist(
    process_name: str = Query(..., description="进程名"),
    process_path: str = Query("", description="进程路径"),
    threat_level: str = Query("medium", description="威胁等级: low/medium/high/critical"),
    description: str = Query("", description="威胁说明"),
):
    """
    添加进程到黑名单
    """
    try:
        monitor = get_process_monitor()
        result = monitor.add_blacklist(
            process_name=process_name,
            process_path=process_path,
            threat_level=threat_level,
            description=description,
        )
        if result["success"]:
            return make_response(data={"id": result["id"]}, message=result["message"])
        else:
            return make_error_response(result["message"])
    except Exception as e:
        return make_error_response(f"添加黑名单失败: {str(e)}")


@router.delete("/blacklist/{item_id}", summary="删除黑名单")
def remove_blacklist(item_id: int):
    """
    从黑名单中删除进程（仅支持删除用户自定义项）
    """
    try:
        monitor = get_process_monitor()
        success = monitor.remove_blacklist(item_id)
        if success:
            return make_response(data={"deleted": True}, message="删除成功")
        else:
            return make_error_response("删除失败，可能是内置项或不存在")
    except Exception as e:
        return make_error_response(f"删除黑名单失败: {str(e)}")


# ===== 进程详情（动态路由放在最后，避免与固定路径冲突） =====

@router.get("/{pid}", summary="获取进程详情")
def get_process_detail(pid: int):
    """
    根据PID获取单个进程的详细信息
    """
    try:
        monitor = get_process_monitor()
        detail = monitor.get_process_detail(pid)
        if not detail:
            return make_error_response(f"未找到PID为 {pid} 的进程", code=404)
        return make_response(data=detail)
    except Exception as e:
        return make_error_response(f"获取进程详情失败: {str(e)}")
