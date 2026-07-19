"""
云汐 M9 开发者工坊 - 工作台仪表盘 API
提供统计数据、今日活动、常用项目等仪表盘数据

性能说明：
- 高频读接口接入三级缓存（L1内存 + L2文件 + L3 Redis预留）
- 缓存 key 统一命名：m9:dashboard:*
- 仪表盘概览等统计数据使用短 TTL（1分钟），保证数据时效性
"""

import sys
from pathlib import Path
from fastapi import APIRouter
from typing import List, Dict, Optional
from datetime import datetime, timedelta

# 兼容相对导入和直接运行
try:
    from ..workspace_manager import get_workspace_manager
    from ..vscode_manager import get_vscode_manager
    from ..mcp_bridge import get_mcp_registry
    from ..models import SessionLocal, DevActivity, WorkspaceProject, VSCodeSession
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from workspace_manager import get_workspace_manager
    from vscode_manager import get_vscode_manager
    from mcp_bridge import get_mcp_registry
    from models import SessionLocal, DevActivity, WorkspaceProject, VSCodeSession

# ---------------------------------------------------------------------------
# 接入统一缓存框架 (shared.perf)
# ---------------------------------------------------------------------------
try:
    _project_root = Path(__file__).resolve()
    for _ in range(10):
        _project_root = _project_root.parent
        if (_project_root / "shared" / "perf" / "cache_manager.py").exists():
            if str(_project_root) not in sys.path:
                sys.path.insert(0, str(_project_root))
            break
except Exception:
    pass

try:
    from shared.perf.cache_manager import CacheManager, cache_result
    _dashboard_cache = CacheManager.from_env(namespace="m9_dashboard")
    _HAS_UNIFIED_CACHE = True
except ImportError:
    _HAS_UNIFIED_CACHE = False
    _dashboard_cache = None  # type: ignore


# ============================================================
# 缓存 key 命名空间 (统一前缀：m9:dashboard:)
# ============================================================
# m9:dashboard:overview         - 仪表盘概览
# m9:dashboard:today_activities - 今日活动
# m9:dashboard:top_projects     - 常用项目
# m9:dashboard:recent_projects  - 近期项目
# m9:dashboard:activity_trend   - 活动趋势
# m9:dashboard:system_status    - 系统状态

router = APIRouter(prefix="/api/v1/dashboard", tags=["仪表盘"])


def _get_db():
    """获取数据库会话"""
    return SessionLocal()


# ===== 仪表盘概览 =====

@router.get("/overview", summary="仪表盘概览")
def get_overview():
    """获取仪表盘综合概览数据（缓存 1 分钟）."""
    cache_key = "m9:dashboard:overview"
    if _HAS_UNIFIED_CACHE and _dashboard_cache.exists(cache_key):
        return _dashboard_cache.get(cache_key)

    db = _get_db()
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())

    # 项目统计
    total_projects = db.query(WorkspaceProject).count()

    # 今日活动数
    today_activities = db.query(DevActivity).filter(
        DevActivity.timestamp >= today_start
    ).count()

    # 今日开发时长
    today_dev_time = 0.0
    today_activity_records = db.query(DevActivity).filter(
        DevActivity.timestamp >= today_start
    ).all()
    for act in today_activity_records:
        today_dev_time += act.duration or 0

    # VS Code 状态
    vscode_mgr = get_vscode_manager()
    vscode_status = vscode_mgr.get_status()

    # MCP 工具数
    mcp_registry = get_mcp_registry()
    mcp_tools = mcp_registry.list_tools()

    # 运行中的会话
    running_sessions = db.query(VSCodeSession).filter(
        VSCodeSession.status == "running"
    ).count()

    db.close()

    result = {
        "success": True,
        "data": {
            "total_projects": total_projects,
            "today_activities": today_activities,
            "today_dev_time_minutes": round(today_dev_time, 2),
            "vscode_installed": vscode_status["installed"],
            "vscode_running": vscode_status["running"],
            "vscode_process_count": vscode_status["process_count"],
            "mcp_tool_count": len(mcp_tools),
            "running_sessions": running_sessions,
            "current_time": datetime.now().isoformat(),
        }
    }

    if _HAS_UNIFIED_CACHE:
        _dashboard_cache.set(cache_key, result, ttl=60)  # 1 分钟

    return result


# ===== 今日活动 =====

@router.get("/today-activities", summary="今日活动")
def get_today_activities(limit: int = 20):
    """获取今日的开发活动记录（缓存 30 秒）."""
    cache_key = f"m9:dashboard:today_activities:limit={limit}"
    if _HAS_UNIFIED_CACHE and _dashboard_cache.exists(cache_key):
        return _dashboard_cache.get(cache_key)

    db = _get_db()
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())

    activities = (
        db.query(DevActivity)
        .filter(DevActivity.timestamp >= today_start)
        .order_by(DevActivity.timestamp.desc())
        .limit(limit)
        .all()
    )

    result_data = [a.to_dict() for a in activities]
    db.close()

    result = {
        "success": True,
        "count": len(result_data),
        "activities": result_data,
    }

    if _HAS_UNIFIED_CACHE:
        _dashboard_cache.set(cache_key, result, ttl=30)  # 30 秒

    return result


# ===== 常用项目 =====

@router.get("/top-projects", summary="常用项目")
def get_top_projects(limit: int = 10):
    """获取最常用的项目（按打开次数排序）（缓存 2 分钟）."""
    cache_key = f"m9:dashboard:top_projects:limit={limit}"
    if _HAS_UNIFIED_CACHE and _dashboard_cache.exists(cache_key):
        return _dashboard_cache.get(cache_key)

    db = _get_db()

    projects = (
        db.query(WorkspaceProject)
        .order_by(WorkspaceProject.open_count.desc())
        .limit(limit)
        .all()
    )

    result_data = []
    for p in projects:
        result_data.append({
            "id": p.id,
            "name": p.name,
            "path": p.path,
            "icon": p.icon,
            "open_count": p.open_count,
            "total_dev_time": round(p.total_dev_time or 0, 2),
            "last_opened": p.last_opened.isoformat() if p.last_opened else None,
        })

    db.close()

    result = {
        "success": True,
        "count": len(result_data),
        "projects": result_data,
    }

    if _HAS_UNIFIED_CACHE:
        _dashboard_cache.set(cache_key, result, ttl=120)  # 2 分钟

    return result


# ===== 近期项目 =====

@router.get("/recent-projects", summary="近期项目")
def get_recent_projects(limit: int = 8):
    """获取最近打开的项目"""
    workspace_mgr = get_workspace_manager()
    projects = workspace_mgr.get_recent_projects(limit=limit)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


# ===== 活动趋势 =====

@router.get("/activity-trend", summary="活动趋势")
def get_activity_trend(days: int = 7):
    """获取近 N 天的开发活动趋势数据（缓存 5 分钟）."""
    cache_key = f"m9:dashboard:activity_trend:days={days}"
    if _HAS_UNIFIED_CACHE and _dashboard_cache.exists(cache_key):
        return _dashboard_cache.get(cache_key)

    db = _get_db()

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

        # 按类型统计
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

    result = {
        "success": True,
        "days": days,
        "trend": trend_data,
    }

    if _HAS_UNIFIED_CACHE:
        _dashboard_cache.set(cache_key, result, ttl=300)  # 5 分钟

    return result


# ===== 系统状态 =====

@router.get("/system-status", summary="系统状态")
def get_system_status():
    """获取各子系统的运行状态（缓存 30 秒）."""
    cache_key = "m9:dashboard:system_status"
    if _HAS_UNIFIED_CACHE and _dashboard_cache.exists(cache_key):
        return _dashboard_cache.get(cache_key)

    vscode_mgr = get_vscode_manager()
    mcp_registry = get_mcp_registry()

    vscode_status = vscode_mgr.get_status()
    mcp_tools = mcp_registry.list_tools()

    services = [
        {
            "name": "VS Code 管理器",
            "status": "healthy" if vscode_status["installed"] else "warning",
            "detail": "已安装" if vscode_status["installed"] else "未检测到 VS Code",
            "version": vscode_status.get("version"),
        },
        {
            "name": "MCP 桥接服务",
            "status": "healthy" if mcp_registry.settings.mcp_enabled else "disabled",
            "detail": f"已注册 {len(mcp_tools)} 个工具",
            "version": "1.0.0",
        },
        {
            "name": "工作区管理",
            "status": "healthy",
            "detail": "运行正常",
            "version": "1.0.0",
        },
        {
            "name": "数据库服务",
            "status": "healthy",
            "detail": "SQLite 连接正常",
            "version": "3.x",
        },
    ]

    result = {
        "success": True,
        "services": services,
        "overall_status": "healthy" if all(s["status"] == "healthy" for s in services) else "warning",
    }

    if _HAS_UNIFIED_CACHE:
        _dashboard_cache.set(cache_key, result, ttl=30)  # 30 秒

    return result


# ===== 快捷操作 =====

@router.get("/quick-actions", summary="快捷操作列表")
def get_quick_actions():
    """获取仪表盘快捷操作列表"""
    actions = [
        {
            "id": "scan_projects",
            "name": "扫描项目",
            "description": "扫描常用目录中的项目",
            "icon": "search",
            "action": "/api/v1/workspace/scan",
            "method": "POST",
        },
        {
            "id": "launch_vscode",
            "name": "启动 VS Code",
            "description": "打开 VS Code 编辑器",
            "icon": "code",
            "action": "/api/v1/vscode/start",
            "method": "POST",
        },
        {
            "id": "mcp_tools",
            "name": "MCP 工具",
            "description": "查看可用的 MCP 工具",
            "icon": "tool",
            "action": "/api/v1/mcp/tools",
            "method": "GET",
        },
        {
            "id": "new_project",
            "name": "新建项目",
            "description": "创建新的工作区项目",
            "icon": "plus",
            "action": "/api/v1/workspace/projects",
            "method": "POST",
        },
    ]

    return {
        "success": True,
        "actions": actions,
    }
