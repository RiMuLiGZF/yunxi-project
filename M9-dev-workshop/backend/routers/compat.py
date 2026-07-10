"""
云汐 M9 开发者工坊 - 前端兼容路由
提供前端代码中使用的API路径别名，确保前后端联调无缝对接
前端API_BASE: http://localhost:8000/api

路径映射:
  /stats/summary       → /dashboard/overview
  /stats/daily         → /dashboard/activity-trend
  /stats/projects      → /dashboard/top-projects
  /projects            → /workspace/projects
  /projects/recent     → /workspace/recent
  /projects/scan       → /workspace/scan
  /activities          → /workspace/activities
  /activities/recent   → /workspace/activities (limit=10)
  /vscode/stop         → /vscode/close
  /vscode/open         → /vscode/open-path
  /vscode/session      → /vscode/sessions
  /vscode/history      → /vscode/sessions (全部历史)
  /mcp/call            → /mcp/tools/call
"""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json

# 兼容相对导入和直接运行
try:
    from ..workspace_manager import get_workspace_manager
    from ..vscode_manager import get_vscode_manager
    from ..mcp_bridge import get_mcp_registry
    from ..models import SessionLocal, DevActivity, WorkspaceProject, VSCodeSession
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from workspace_manager import get_workspace_manager
    from vscode_manager import get_vscode_manager
    from mcp_bridge import get_mcp_registry
    from models import SessionLocal, DevActivity, WorkspaceProject, VSCodeSession

router = APIRouter(prefix="/api", tags=["前端兼容"])


def _get_db():
    """获取数据库会话"""
    return SessionLocal()


# ==================== Stats 兼容路由 ====================

@router.get("/stats/summary", summary="统计概览（兼容前端）")
def stats_summary():
    """仪表盘综合概览，兼容前端 /stats/summary 调用"""
    db = _get_db()
    from datetime import datetime
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())

    total_projects = db.query(WorkspaceProject).count()
    today_activities = db.query(DevActivity).filter(
        DevActivity.timestamp >= today_start
    ).count()
    today_dev_time = sum(
        (a.duration or 0) for a in db.query(DevActivity).filter(
            DevActivity.timestamp >= today_start
        ).all()
    )

    vscode_mgr = get_vscode_manager()
    vscode_status = vscode_mgr.get_status()
    mcp_registry = get_mcp_registry()
    mcp_tools = mcp_registry.list_tools()
    running_sessions = db.query(VSCodeSession).filter(
        VSCodeSession.status == "running"
    ).count()

    db.close()

    return {
        "success": True,
        "data": {
            "total_projects": total_projects,
            "today_activities": today_activities,
            "today_dev_time_minutes": round(today_dev_time, 2),
            "vscode_installed": vscode_status["installed"],
            "vscode_running": vscode_status["running"],
            "mcp_tool_count": len(mcp_tools),
            "running_sessions": running_sessions,
        }
    }


@router.get("/stats/daily", summary="每日活动统计（兼容前端）")
def stats_daily(days: int = Query(7, description="统计天数")):
    """近N天活动趋势，兼容前端 /stats/daily 调用"""
    db = _get_db()
    from datetime import datetime, timedelta

    trend_data = []
    today = datetime.now().date()

    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        day_start = datetime.combine(date, datetime.min.time())
        day_end = datetime.combine(date, datetime.max.time())

        activities = db.query(DevActivity).filter(
            DevActivity.timestamp >= day_start,
            DevActivity.timestamp <= day_end,
        ).all()

        total_duration = sum(a.duration or 0 for a in activities)
        activity_count = len(activities)

        type_counts = {}
        for act in activities:
            act_type = act.activity_type or "other"
            type_counts[act_type] = type_counts.get(act_type, 0) + 1

        trend_data.append({
            "date": date.isoformat(),
            "activity_count": activity_count,
            "total_duration_minutes": round(total_duration, 2),
            "type_distribution": type_counts,
        })

    db.close()

    return {
        "success": True,
        "days": days,
        "trend": trend_data,
    }


@router.get("/stats/projects", summary="项目统计（兼容前端）")
def stats_projects(limit: int = Query(10, description="返回数量")):
    """常用项目排名，兼容前端 /stats/projects 调用"""
    db = _get_db()

    projects = (
        db.query(WorkspaceProject)
        .order_by(WorkspaceProject.open_count.desc())
        .limit(limit)
        .all()
    )

    result = []
    for p in projects:
        result.append({
            "id": p.id,
            "name": p.name,
            "path": p.path,
            "icon": p.icon,
            "open_count": p.open_count,
            "total_dev_time": round(p.total_dev_time or 0, 2),
            "last_opened": p.last_opened.isoformat() if p.last_opened else None,
        })

    db.close()

    return {
        "success": True,
        "count": len(result),
        "projects": result,
    }


# ==================== Projects 兼容路由 ====================

@router.get("/projects", summary="获取项目列表（兼容前端）")
def compat_list_projects(
    tag: Optional[str] = Query(None, description="按标签过滤"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(50, description="数量限制"),
    offset: int = Query(0, description="偏移量"),
):
    """获取工作区项目列表，兼容前端 /projects 调用"""
    mgr = get_workspace_manager()
    projects = mgr.list_projects(tag=tag, keyword=keyword, limit=limit, offset=offset)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


@router.get("/projects/recent", summary="最近项目（兼容前端）")
def compat_recent_projects(limit: int = Query(10, description="返回数量")):
    """最近打开的项目，兼容前端 /projects/recent 调用"""
    mgr = get_workspace_manager()
    projects = mgr.get_recent_projects(limit=limit)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


@router.post("/projects/scan", summary="扫描项目（兼容前端）")
async def compat_scan_projects(request: Request):
    """扫描目录中的项目，兼容前端 /projects/scan 调用"""
    try:
        body = await request.json()
    except Exception:
        body = {}

    mgr = get_workspace_manager()
    result = mgr.scan_projects(
        scan_dirs=body.get("scan_dirs"),
        max_depth=body.get("max_depth", 3),
    )
    return {"success": True, **result}


# ==================== Activities 兼容路由 ====================

@router.get("/activities", summary="活动记录（兼容前端）")
def compat_activities(
    project: Optional[str] = Query(None, description="项目名称"),
    activity_type: Optional[str] = Query(None, description="活动类型"),
    days: int = Query(7, description="最近天数"),
    limit: int = Query(50, description="数量限制"),
):
    """获取开发活动记录，兼容前端 /activities 调用"""
    mgr = get_workspace_manager()
    activities = mgr.get_activities(
        project=project,
        activity_type=activity_type,
        days=days,
        limit=limit,
    )
    return {
        "success": True,
        "count": len(activities),
        "activities": activities,
    }


@router.get("/activities/recent", summary="最近活动（兼容前端）")
def compat_recent_activities(limit: int = Query(10, description="返回数量")):
    """最近的开发活动，兼容前端 /activities/recent 调用"""
    mgr = get_workspace_manager()
    activities = mgr.get_activities(limit=limit)
    return {
        "success": True,
        "count": len(activities),
        "activities": activities,
    }


# ==================== VS Code 兼容路由 ====================

class _OpenRequest(BaseModel):
    path: Optional[str] = None
    project_path: Optional[str] = None
    new_window: bool = False


class _StopRequest(BaseModel):
    pid: Optional[int] = None
    force: bool = False


@router.post("/vscode/stop", summary="关闭 VS Code（兼容前端）")
def compat_vscode_stop(req: _StopRequest = _StopRequest()):
    """关闭 VS Code，兼容前端 /vscode/stop 调用（实际映射到 /vscode/close）"""
    mgr = get_vscode_manager()
    result = mgr.close(pid=req.pid, force=req.force)
    return result


@router.post("/vscode/open", summary="打开项目（兼容前端）")
def compat_vscode_open(req: _OpenRequest):
    """在 VS Code 中打开路径，兼容前端 /vscode/open 调用（实际映射到 /vscode/open-path）"""
    mgr = get_vscode_manager()
    path = req.path or req.project_path
    if not path:
        raise HTTPException(status_code=400, detail="请指定打开路径")
    result = mgr.open_path(path=path, new_window=req.new_window)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/vscode/session", summary="会话状态（兼容前端）")
def compat_vscode_session(limit: int = Query(20)):
    """获取 VS Code 会话，兼容前端 /vscode/session 调用（实际映射到 /vscode/sessions）"""
    mgr = get_vscode_manager()
    sessions = mgr.get_sessions(limit=limit, status="running")
    # 前端期望单会话格式，返回第一个运行中的会话
    if sessions:
        return {"success": True, "session": sessions[0], "sessions": sessions}
    return {"success": True, "session": None, "sessions": []}


@router.get("/vscode/history", summary="会话历史（兼容前端）")
def compat_vscode_history(limit: int = Query(20)):
    """VS Code 会话历史，兼容前端 /vscode/history 调用"""
    mgr = get_vscode_manager()
    sessions = mgr.get_sessions(limit=limit)
    return {
        "success": True,
        "count": len(sessions),
        "history": sessions,
    }


# ==================== MCP 兼容路由 ====================

class _MCPCallRequest(BaseModel):
    tool_name: Optional[str] = None
    tool: Optional[str] = None
    arguments: Dict[str, Any] = {}
    args: Dict[str, Any] = {}


@router.post("/mcp/call", summary="调用 MCP 工具（兼容前端）")
def compat_mcp_call(req: _MCPCallRequest):
    """调用 MCP 工具，兼容前端 /mcp/call 调用（实际映射到 /mcp/tools/call）"""
    registry = get_mcp_registry()
    tool_name = req.tool_name or req.tool
    if not tool_name:
        raise HTTPException(status_code=400, detail="请指定工具名称")

    arguments = req.arguments or req.args
    response = registry.call_tool(tool_name, arguments)

    if response.error:
        raise HTTPException(
            status_code=500,
            detail={
                "code": response.error.get("code", -1),
                "message": response.error.get("message", "未知错误"),
            }
        )

    return {
        "success": True,
        "tool": tool_name,
        "result": response.result,
    }
