"""M9 VSCode 管理接口"""

from fastapi import APIRouter, HTTPException
from typing import List
from ..models import VSCodeInstance
from ..vscode_manager import vscode_manager

router = APIRouter()


@router.get("/", response_model=List[VSCodeInstance])
async def list_vscode_instances() -> List[VSCodeInstance]:
    """列出所有VSCode实例"""
    return vscode_manager.list_instances()


@router.get("/{instance_id}", response_model=VSCodeInstance)
async def get_vscode_instance(instance_id: str) -> VSCodeInstance:
    """获取VSCode实例详情"""
    instance = vscode_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="VSCode实例不存在")
    return instance


@router.post("/", response_model=VSCodeInstance)
async def start_vscode(name: str, workspace: str = None) -> VSCodeInstance:
    """启动新的VSCode实例"""
    if workspace:
        from ..path_safety import is_path_safe
        safe_ws = workspace.replace("~", "").replace("\\", "/")
        # 只做基本校验，不阻止绝对路径（用户可能指向任意工作区）
        if ".." in workspace:
            raise HTTPException(status_code=400, detail="工作空间路径不允许包含 '..'")
    return vscode_manager.start_instance(name, workspace)


@router.delete("/{instance_id}")
async def stop_vscode(instance_id: str) -> dict:
    """停止VSCode实例"""
    if vscode_manager.stop_instance(instance_id):
        return {"status": "stopped"}
    raise HTTPException(status_code=404, detail="VSCode实例不存在")


@router.post("/{instance_id}/open-file")
async def open_file(instance_id: str, file_path: str) -> dict:
    """在VSCode中打开文件"""
    if ".." in file_path:
        raise HTTPException(status_code=400, detail="文件路径不允许包含 '..'")
    if vscode_manager.open_file(instance_id, file_path):
        return {"status": "opened"}
    raise HTTPException(status_code=400, detail="无法打开文件")
