"""工作空间路由.

提供 VS Code 管理、常用项目列表等工作空间相关接口。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

try:
    from src.models import make_response
except ImportError:
    from models import make_response  # type: ignore

router = APIRouter(prefix="/api/v1/workspace", tags=["工作空间"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class VSCodeLaunchRequest(BaseModel):
    """VS Code 启动请求体."""
    project_path: str = Field("", description="项目目录路径（可选）")
    new_window: bool = Field(True, description="是否在新窗口打开")


class VSCodeOpenRequest(BaseModel):
    """打开指定项目请求体."""
    project_path: str = Field(..., description="项目目录路径")
    new_window: bool = Field(True, description="是否在新窗口打开")


class VSCodeExtensionRequest(BaseModel):
    """VS Code 扩展操作请求体."""
    extension_id: str = Field(..., description="扩展ID（如 ms-python.python）")


class VSCodeOpenFileRequest(BaseModel):
    """打开文件请求体."""
    file_path: str = Field(..., description="文件路径")
    line: int | None = Field(None, description="行号（可选）")


class VSCodeRunCommandRequest(BaseModel):
    """执行命令请求体."""
    command: str = Field(..., description="要执行的命令")
    cwd: str = Field("", description="工作目录（可选）")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_vscode_launcher(request: Request) -> Any:
    """从 request state 获取 VS Code 启动器实例.

    如果 state 中没有，则创建单例。
    """
    launcher = getattr(request.app.state, "vscode_launcher", None)
    if launcher is None:
        try:
            from src.services.vscode_launcher import get_vscode_launcher
        except ImportError:
            from services.vscode_launcher import get_vscode_launcher  # type: ignore
        launcher = get_vscode_launcher()
        request.app.state.vscode_launcher = launcher
    return launcher


def _get_common_projects() -> list[dict[str, Any]]:
    """获取常用项目列表.

    扫描用户主目录、桌面、工作区等常见位置的项目目录。
    项目目录判定标准：包含 .git 文件夹、package.json、requirements.txt 等项目标志文件。
    """
    projects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    # 常见项目搜索位置
    home = Path.home()
    search_dirs = [
        home / "Projects",
        home / "projects",
        home / "Desktop",
        home / "桌面",
        home / "Documents",
        home / "文档",
        home / "workspace",
        home / "Workspaces",
        home / "Code",
        home / "code",
        Path(r"C:\云汐\工作台"),
    ]

    # 项目标志文件/目录
    project_markers = [
        ".git",
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        ".vscode",
        ".idea",
    ]

    def _is_project_dir(path: Path) -> bool:
        """判断目录是否为项目目录."""
        for marker in project_markers:
            if (path / marker).exists():
                return True
        return False

    def _scan_dir(base_dir: Path, depth: int = 2) -> None:
        """递归扫描目录，查找项目."""
        if not base_dir.exists() or not base_dir.is_dir():
            return

        try:
            entries = list(base_dir.iterdir())
        except (PermissionError, OSError):
            return

        for entry in entries:
            if not entry.is_dir():
                continue
            # 跳过隐藏目录
            if entry.name.startswith("."):
                continue
            # 跳过 node_modules 等大目录
            if entry.name in ("node_modules", "venv", "__pycache__", "dist", "build"):
                continue

            resolved = str(entry.resolve())
            if resolved in seen_paths:
                continue

            if _is_project_dir(entry):
                seen_paths.add(resolved)
                # 读取项目描述（尝试从 package.json 或 README）
                desc = ""
                readme = entry / "README.md"
                if readme.exists():
                    try:
                        with open(readme, "r", encoding="utf-8") as f:
                            first_line = f.readline().strip()
                            if first_line.startswith("#"):
                                desc = first_line.lstrip("# ").strip()
                    except Exception:
                        pass

                projects.append({
                    "name": entry.name,
                    "path": resolved,
                    "description": desc,
                    "type": _detect_project_type(entry),
                })
            elif depth > 0:
                _scan_dir(entry, depth - 1)

    def _detect_project_type(path: Path) -> str:
        """检测项目类型."""
        if (path / "package.json").exists():
            return "nodejs"
        if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists():
            return "python"
        if (path / "Cargo.toml").exists():
            return "rust"
        if (path / "go.mod").exists():
            return "go"
        if (path / "pom.xml").exists() or (path / "build.gradle").exists():
            return "java"
        if (path / ".git").exists():
            return "git"
        return "unknown"

    for search_dir in search_dirs:
        _scan_dir(search_dir)

    # 按项目名称排序
    projects.sort(key=lambda x: x["name"])
    return projects


# ---------------------------------------------------------------------------
# VS Code 状态查询
# ---------------------------------------------------------------------------

@router.get("/vscode/status", summary="查询 VS Code 状态")
async def get_vscode_status(request: Request):
    """查询 VS Code 的安装和运行状态."""
    launcher = _get_vscode_launcher(request)

    detect_result = launcher.detect_vscode()
    running = launcher.is_running()

    return make_response(data={
        "installed": detect_result["installed"],
        "install_path": detect_result["path"],
        "version": detect_result["version"],
        "detect_source": detect_result["source"],
        "running": running,
    })


# ---------------------------------------------------------------------------
# 启动 VS Code
# ---------------------------------------------------------------------------

@router.post("/vscode/launch", summary="启动 VS Code")
async def launch_vscode(request: Request, body: VSCodeLaunchRequest):
    """启动 VS Code，可选择打开指定项目.

    请求体:
        - project_path: 项目目录路径（可选）
        - new_window: 是否在新窗口打开
    """
    launcher = _get_vscode_launcher(request)

    # 检查是否已安装
    detect_result = launcher.detect_vscode()
    if not detect_result["installed"]:
        return make_response(
            code=40001,
            message="未检测到 VS Code 安装",
            data={"install_path": "", "running": False},
        )

    result = launcher.launch_vscode(
        project_path=body.project_path if body.project_path else None,
        new_window=body.new_window,
    )

    if not result.get("success", False):
        return make_response(
            code=40002,
            message=result.get("message", "VS Code 启动失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 关闭 VS Code
# ---------------------------------------------------------------------------

@router.post("/vscode/close", summary="关闭 VS Code")
async def close_vscode(request: Request):
    """关闭正在运行的 VS Code."""
    launcher = _get_vscode_launcher(request)

    if not launcher.is_running():
        return make_response(
            code=40003,
            message="VS Code 未在运行",
            data={"running": False},
        )

    success = launcher.close_vscode()

    if not success:
        return make_response(
            code=40004,
            message="关闭 VS Code 失败",
            data={"running": launcher.is_running()},
        )

    return make_response(data={
        "success": True,
        "running": False,
        "message": "VS Code 已关闭",
    })


# ---------------------------------------------------------------------------
# 打开指定项目
# ---------------------------------------------------------------------------

@router.post("/vscode/open", summary="打开指定项目")
async def open_project(request: Request, body: VSCodeOpenRequest):
    """使用 VS Code 打开指定项目目录.

    请求体:
        - project_path: 项目目录路径
        - new_window: 是否在新窗口打开
    """
    launcher = _get_vscode_launcher(request)

    # 检查路径是否存在
    if not os.path.exists(body.project_path):
        return make_response(
            code=40005,
            message=f"项目路径不存在: {body.project_path}",
            data={"project_path": body.project_path},
        )

    if not os.path.isdir(body.project_path):
        return make_response(
            code=40006,
            message="项目路径必须是目录",
            data={"project_path": body.project_path},
        )

    result = launcher.launch_vscode(
        project_path=body.project_path,
        new_window=body.new_window,
    )

    if not result.get("success", False):
        return make_response(
            code=40007,
            message=result.get("message", "打开项目失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 常用项目列表
# ---------------------------------------------------------------------------

@router.get("/projects", summary="获取常用项目列表")
async def list_projects(
    request: Request,
    limit: int = 50,
    offset: int = 0,
):
    """获取系统中常用的项目列表.

    自动扫描常见位置的项目目录，支持多种语言项目识别。

    参数:
        - limit: 返回条数限制，默认 50
        - offset: 偏移量，默认 0
    """
    projects = _get_common_projects()
    total = len(projects)

    # 分页
    end = min(offset + limit, total)
    page_projects = projects[offset:end]

    return make_response(data={
        "total": total,
        "limit": limit,
        "offset": offset,
        "projects": page_projects,
    })


# ---------------------------------------------------------------------------
# VS Code 扩展管理
# ---------------------------------------------------------------------------

@router.get("/vscode/extensions", summary="列出已安装扩展")
async def list_extensions(request: Request):
    """列出 VS Code 已安装的扩展列表."""
    launcher = _get_vscode_launcher(request)

    result = launcher.list_extensions()

    if not result.get("success", False):
        return make_response(
            code=40010,
            message=result.get("message", "获取扩展列表失败"),
            data=result.get("data", {}),
        )

    return make_response(data=result.get("data", {}))


@router.post("/vscode/extensions/install", summary="安装 VS Code 扩展")
async def install_extension(request: Request, body: VSCodeExtensionRequest):
    """安装指定的 VS Code 扩展.

    请求体:
        - extension_id: 扩展ID（如 ms-python.python）
    """
    launcher = _get_vscode_launcher(request)

    # 检查是否已安装
    detect_result = launcher.detect_vscode()
    if not detect_result["installed"]:
        return make_response(
            code=40001,
            message="未检测到 VS Code 安装",
            data={"extension_id": body.extension_id},
        )

    result = launcher.install_extension(body.extension_id)

    if not result.get("success", False):
        return make_response(
            code=40011,
            message=result.get("message", "扩展安装失败"),
            data=result.get("data", {}),
        )

    return make_response(data=result.get("data", {}))


@router.post("/vscode/extensions/uninstall", summary="卸载 VS Code 扩展")
async def uninstall_extension(request: Request, body: VSCodeExtensionRequest):
    """卸载指定的 VS Code 扩展.

    请求体:
        - extension_id: 扩展ID（如 ms-python.python）
    """
    launcher = _get_vscode_launcher(request)

    # 检查是否已安装
    detect_result = launcher.detect_vscode()
    if not detect_result["installed"]:
        return make_response(
            code=40001,
            message="未检测到 VS Code 安装",
            data={"extension_id": body.extension_id},
        )

    result = launcher.uninstall_extension(body.extension_id)

    if not result.get("success", False):
        return make_response(
            code=40012,
            message=result.get("message", "扩展卸载失败"),
            data=result.get("data", {}),
        )

    return make_response(data=result.get("data", {}))


# ---------------------------------------------------------------------------
# VS Code 打开文件
# ---------------------------------------------------------------------------

@router.post("/vscode/open-file", summary="打开指定文件")
async def open_file(request: Request, body: VSCodeOpenFileRequest):
    """使用 VS Code 打开指定文件，可跳转到行号.

    请求体:
        - file_path: 文件路径
        - line: 行号（可选）
    """
    launcher = _get_vscode_launcher(request)

    # 检查是否已安装
    detect_result = launcher.detect_vscode()
    if not detect_result["installed"]:
        return make_response(
            code=40001,
            message="未检测到 VS Code 安装",
            data={"file_path": body.file_path},
        )

    result = launcher.open_file(body.file_path, line=body.line)

    if not result.get("success", False):
        return make_response(
            code=40013,
            message=result.get("message", "打开文件失败"),
            data=result.get("data", {}),
        )

    return make_response(data=result.get("data", {}))


# ---------------------------------------------------------------------------
# VS Code 命令执行
# ---------------------------------------------------------------------------

@router.post("/vscode/run-command", summary="执行命令")
async def run_command(request: Request, body: VSCodeRunCommandRequest):
    """在终端中执行指定命令.

    请求体:
        - command: 要执行的命令
        - cwd: 工作目录（可选）
    """
    launcher = _get_vscode_launcher(request)

    result = launcher.run_command(
        command=body.command,
        cwd=body.cwd if body.cwd else None,
    )

    if not result.get("success", False):
        return make_response(
            code=40014,
            message=result.get("message", "命令执行失败"),
            data=result.get("data", {}),
        )

    return make_response(data=result.get("data", {}))
