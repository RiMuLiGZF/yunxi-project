"""
云汐 M9 开发者工坊 - VS Code 管理 API
提供 VS Code 启动、关闭、状态查询、扩展管理等接口
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

# 兼容相对导入和直接运行
try:
    from ..vscode_manager import get_vscode_manager
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from vscode_manager import get_vscode_manager

router = APIRouter(prefix="/api/vscode", tags=["VS Code 管理"])


# ===== 请求模型 =====

class StartRequest(BaseModel):
    """启动 VS Code 请求"""
    project_path: Optional[str] = None
    new_window: bool = False


class OpenPathRequest(BaseModel):
    """打开路径请求"""
    path: str
    new_window: bool = False


class OpenFileRequest(BaseModel):
    """打开文件请求"""
    file_path: str
    line: Optional[int] = None


class CloseRequest(BaseModel):
    """关闭请求"""
    pid: Optional[int] = None
    force: bool = False


class ExtensionRequest(BaseModel):
    """扩展操作请求"""
    extension_id: str


# ===== 接口定义 =====

@router.get("/status", summary="获取 VS Code 状态")
def get_status():
    """获取 VS Code 安装、运行、扩展等综合状态"""
    mgr = get_vscode_manager()
    return {
        "success": True,
        "data": mgr.get_status()
    }


@router.get("/version", summary="获取 VS Code 版本")
def get_version():
    """获取 VS Code 版本号"""
    mgr = get_vscode_manager()
    version = mgr.get_version()
    if not version:
        raise HTTPException(status_code=404, detail="VS Code 未安装或无法获取版本")
    return {"success": True, "version": version}


@router.post("/start", summary="启动 VS Code")
def start_vscode(req: StartRequest):
    """启动 VS Code，可指定打开的项目路径"""
    mgr = get_vscode_manager()
    result = mgr.start(
        project_path=req.project_path,
        new_window=req.new_window,
    )
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/close", summary="关闭 VS Code")
def close_vscode(req: CloseRequest = CloseRequest()):
    """关闭 VS Code，可指定进程 ID 或全部关闭"""
    mgr = get_vscode_manager()
    result = mgr.close(pid=req.pid, force=req.force)
    return result


@router.post("/open-path", summary="打开项目/文件夹")
def open_path(req: OpenPathRequest):
    """在 VS Code 中打开指定路径（项目或文件夹）"""
    mgr = get_vscode_manager()
    result = mgr.open_path(path=req.path, new_window=req.new_window)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/open-file", summary="打开文件")
def open_file(req: OpenFileRequest):
    """在 VS Code 中打开指定文件，可跳转到行号"""
    mgr = get_vscode_manager()
    result = mgr.open_file(file_path=req.file_path, line=req.line)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/processes", summary="获取运行进程列表")
def get_processes():
    """获取所有正在运行的 VS Code 进程"""
    mgr = get_vscode_manager()
    processes = mgr.get_running_processes()
    return {
        "success": True,
        "count": len(processes),
        "processes": processes,
    }


@router.get("/extensions", summary="列出已安装扩展")
def list_extensions():
    """列出所有已安装的 VS Code 扩展"""
    mgr = get_vscode_manager()
    extensions = mgr.list_extensions()
    return {
        "success": True,
        "count": len(extensions),
        "extensions": extensions,
    }


@router.post("/extensions/install", summary="安装扩展")
def install_extension(req: ExtensionRequest):
    """安装指定的 VS Code 扩展"""
    mgr = get_vscode_manager()
    result = mgr.install_extension(req.extension_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.post("/extensions/uninstall", summary="卸载扩展")
def uninstall_extension(req: ExtensionRequest):
    """卸载指定的 VS Code 扩展"""
    mgr = get_vscode_manager()
    result = mgr.uninstall_extension(req.extension_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return result


@router.get("/sessions", summary="获取会话记录")
def get_sessions(limit: int = 20, status: Optional[str] = None):
    """获取 VS Code 会话历史记录"""
    mgr = get_vscode_manager()
    sessions = mgr.get_sessions(limit=limit, status=status)
    return {
        "success": True,
        "count": len(sessions),
        "sessions": sessions,
    }
