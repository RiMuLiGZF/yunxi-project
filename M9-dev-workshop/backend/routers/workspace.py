"""
云汐 M9 开发者工坊 - 工作区管理 API
提供项目 CRUD、最近项目、扫描、标签管理等接口
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

# 兼容相对导入和直接运行
try:
    from ..workspace_manager import get_workspace_manager
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from workspace_manager import get_workspace_manager

router = APIRouter(prefix="/api/workspace", tags=["工作区管理"])


# ===== 请求模型 =====

class ProjectCreateRequest(BaseModel):
    """创建项目请求"""
    name: str
    path: str
    description: str = ""
    icon: str = "folder"
    tags: List[str] = []


class ProjectUpdateRequest(BaseModel):
    """更新项目请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: Optional[List[str]] = None


class ScanRequest(BaseModel):
    """扫描项目请求"""
    scan_dirs: Optional[List[str]] = None
    max_depth: int = 3


class TagRequest(BaseModel):
    """标签操作请求"""
    tag: str


class ActivityRequest(BaseModel):
    """活动记录请求"""
    project: str
    activity_type: str
    duration: float = 0
    description: str = ""
    meta_data: dict = {}


# ===== 项目 CRUD =====

@router.get("/projects", summary="获取项目列表")
def list_projects(
    tag: Optional[str] = Query(None, description="按标签过滤"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(50, description="数量限制"),
    offset: int = Query(0, description="偏移量"),
):
    """获取工作区项目列表，支持标签过滤和关键词搜索"""
    mgr = get_workspace_manager()
    projects = mgr.list_projects(tag=tag, keyword=keyword, limit=limit, offset=offset)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


@router.get("/projects/{project_id}", summary="获取项目详情")
def get_project(project_id: int):
    """根据 ID 获取项目详情"""
    mgr = get_workspace_manager()
    project = mgr.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, "project": project}


@router.post("/projects", summary="创建项目")
def create_project(req: ProjectCreateRequest):
    """创建新项目记录"""
    mgr = get_workspace_manager()
    result = mgr.create_project(
        name=req.name,
        path=req.path,
        description=req.description,
        icon=req.icon,
        tags=req.tags,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.put("/projects/{project_id}", summary="更新项目")
def update_project(project_id: int, req: ProjectUpdateRequest):
    """更新项目信息"""
    mgr = get_workspace_manager()
    result = mgr.update_project(
        project_id,
        name=req.name,
        description=req.description,
        icon=req.icon,
        tags=req.tags,
    )
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.delete("/projects/{project_id}", summary="删除项目")
def delete_project(project_id: int, delete_files: bool = Query(False, description="是否同时删除文件")):
    """删除项目记录，可选删除文件"""
    mgr = get_workspace_manager()
    result = mgr.delete_project(project_id, delete_files=delete_files)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ===== 最近项目 =====

@router.get("/recent", summary="获取最近打开的项目")
def get_recent_projects(limit: int = Query(10, description="返回数量")):
    """获取最近打开的项目列表"""
    mgr = get_workspace_manager()
    projects = mgr.get_recent_projects(limit=limit)
    return {
        "success": True,
        "count": len(projects),
        "projects": projects,
    }


@router.post("/projects/{project_id}/open", summary="记录项目打开")
def open_project(project_id: int):
    """记录项目被打开（更新最后打开时间和打开次数）"""
    mgr = get_workspace_manager()
    result = mgr.open_project(project_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ===== 扫描 =====

@router.post("/scan", summary="扫描项目")
def scan_projects(req: ScanRequest = ScanRequest()):
    """扫描指定目录中的项目，自动添加到工作区"""
    mgr = get_workspace_manager()
    result = mgr.scan_projects(scan_dirs=req.scan_dirs, max_depth=req.max_depth)
    return {"success": True, **result}


# ===== 标签管理 =====

@router.get("/tags", summary="获取所有标签")
def get_all_tags():
    """获取所有项目使用的标签列表"""
    mgr = get_workspace_manager()
    tags = mgr.get_all_tags()
    return {"success": True, "tags": tags}


@router.post("/projects/{project_id}/tags", summary="添加标签")
def add_tag(project_id: int, req: TagRequest):
    """为项目添加标签"""
    mgr = get_workspace_manager()
    result = mgr.add_tag(project_id, req.tag)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.delete("/projects/{project_id}/tags/{tag}", summary="移除标签")
def remove_tag(project_id: int, tag: str):
    """移除项目的指定标签"""
    mgr = get_workspace_manager()
    result = mgr.remove_tag(project_id, tag)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ===== 项目统计 =====

@router.get("/projects/{project_id}/stats", summary="获取项目统计")
def get_project_stats(project_id: int):
    """获取单个项目的统计信息和近期活动"""
    mgr = get_workspace_manager()
    stats = mgr.get_project_stats(project_id)
    if not stats:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, "data": stats}


# ===== 开发活动 =====

@router.get("/activities", summary="获取开发活动记录")
def get_activities(
    project: Optional[str] = Query(None, description="项目名称"),
    activity_type: Optional[str] = Query(None, description="活动类型"),
    days: int = Query(7, description="最近天数"),
    limit: int = Query(50, description="数量限制"),
):
    """获取开发活动记录"""
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


@router.post("/activities", summary="记录开发活动")
def log_activity(req: ActivityRequest):
    """手动记录一条开发活动"""
    mgr = get_workspace_manager()
    result = mgr.log_activity(
        project=req.project,
        activity_type=req.activity_type,
        duration=req.duration,
        description=req.description,
        meta_data=req.meta_data,
    )
    return result
