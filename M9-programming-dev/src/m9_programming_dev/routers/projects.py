"""M9 项目管理接口"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict
from ..models import ProjectInfo
from ..project_manager import project_manager

router = APIRouter()


@router.get("/", response_model=List[ProjectInfo])
async def list_projects():
    """列出所有项目"""
    return project_manager.list_projects()


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str):
    """获取项目详情"""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/", response_model=ProjectInfo)
async def create_project(name: str, description: str = "", language: str = ""):
    """创建新项目"""
    return project_manager.create_project(name, description, language)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目"""
    if project_manager.delete_project(project_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="项目不存在")


@router.get("/{project_id}/files")
async def list_project_files(project_id: str, path: str = ""):
    """列出项目文件"""
    project = project_manager.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project_manager.get_project_files(project_id, path)
