"""VS Code 启动器服务.

提供 VS Code 的检测、启动、状态检查、关闭等功能。
支持 Windows 平台多路径检测和项目目录打开。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any


# ---------------------------------------------------------------------------
# 尝试导入 psutil（可选依赖）
# ---------------------------------------------------------------------------
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ---------------------------------------------------------------------------
# VS Code 启动器
# ---------------------------------------------------------------------------

class VSCodeLauncher:
    """VS Code 启动与管理服务.

    功能：
    - 检测 VS Code 安装路径
    - 启动 VS Code（支持打开项目目录）
    - 检查运行状态
    - 关闭 VS Code
    """

    # Windows 平台默认安装路径（按优先级排序）
    _WINDOWS_DEFAULT_PATHS = [
        r"C:\Users\XiZho\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
    ]

    # VS Code 进程名（用于状态检测）
    _PROCESS_NAMES = ["Code.exe", "code", "code-oss", "vscode"]

    def __init__(self) -> None:
        """初始化 VS Code 启动器."""
        self._lock = Lock()
        self._cached_path: str | None = None
        self._launch_result: dict[str, Any] | None = None

    # -----------------------------------------------------------------------
    # 检测 VS Code
    # -----------------------------------------------------------------------

    def detect_vscode(self) -> dict[str, Any]:
        """检测 VS Code 安装信息.

        按优先级检测：
        1. 缓存路径
        2. Windows 默认安装路径
        3. 环境变量 PATH 中的 code 命令
        4. 注册表（Windows）

        Returns:
            检测结果字典:
            {
                "installed": True/False,    # 是否安装
                "path": "C:\\...\\Code.exe", # 可执行文件路径
                "version": "1.x.x",          # 版本号（如可获取）
                "source": "default_path",    # 检测来源
            }
        """
        # 1. 使用缓存
        if self._cached_path and os.path.exists(self._cached_path):
            return {
                "installed": True,
                "path": self._cached_path,
                "version": self._get_version(self._cached_path),
                "source": "cached",
            }

        # 2. Windows 默认安装路径
        if sys.platform == "win32":
            for path in self._WINDOWS_DEFAULT_PATHS:
                if os.path.exists(path):
                    self._cached_path = path
                    return {
                        "installed": True,
                        "path": path,
                        "version": self._get_version(path),
                        "source": "default_path",
                    }

        # 3. 通过 PATH 环境变量查找 code 命令
        code_cmd = shutil.which("code")
        if code_cmd:
            # code 命令通常是一个脚本/批处理，需要找到真正的可执行文件
            real_path = self._resolve_code_command(code_cmd)
            self._cached_path = real_path
            return {
                "installed": True,
                "path": real_path,
                "version": self._get_version(real_path),
                "source": "path_env",
            }

        # 4. 未找到
        return {
            "installed": False,
            "path": "",
            "version": "",
            "source": "not_found",
        }

    def _resolve_code_command(self, code_cmd: str) -> str:
        """解析 code 命令对应的真实可执行文件路径.

        Args:
            code_cmd: code 命令路径

        Returns:
            VS Code 可执行文件完整路径
        """
        try:
            code_path = Path(code_cmd).resolve()
            # 尝试在同级或上级目录查找 Code.exe
            parent = code_path.parent

            # Windows 下常见结构：.../Microsoft VS Code/bin/code.cmd
            # 可执行文件在 .../Microsoft VS Code/Code.exe
            possible_paths = [
                parent / "Code.exe",
                parent.parent / "Code.exe",
                parent / "code.exe",
                parent.parent / "code.exe",
            ]
            for p in possible_paths:
                if p.exists():
                    return str(p)
        except Exception:
            pass

        return code_cmd

    def _get_version(self, exe_path: str) -> str:
        """获取 VS Code 版本号.

        Args:
            exe_path: 可执行文件路径

        Returns:
            版本号字符串，获取失败返回空字符串
        """
        try:
            result = subprocess.run(
                [exe_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout:
                # 第一行通常是版本号
                lines = result.stdout.strip().splitlines()
                if lines:
                    return lines[0].strip()
        except Exception:
            pass
        return ""

    # -----------------------------------------------------------------------
    # 启动 VS Code
    # -----------------------------------------------------------------------

    def launch_vscode(
        self,
        project_path: str | None = None,
        new_window: bool = True,
    ) -> dict[str, Any]:
        """启动 VS Code.

        Args:
            project_path: 要打开的项目目录路径，为空则仅启动 VS Code
            new_window: 是否在新窗口中打开

        Returns:
            启动结果字典:
            {
                "success": True/False,
                "path": "C:\\...\\Code.exe",
                "project_path": "项目路径",
                "pid": 进程ID,
                "message": "描述信息",
            }
        """
        with self._lock:
            # 先检测安装
            detect_result = self.detect_vscode()
            if not detect_result["installed"]:
                return {
                    "success": False,
                    "path": "",
                    "project_path": project_path or "",
                    "pid": 0,
                    "message": "未检测到 VS Code 安装",
                }

            exe_path = detect_result["path"]
            cmd = [exe_path]

            # 新窗口参数
            if new_window:
                cmd.append("-n")

            # 项目路径
            if project_path:
                if not os.path.exists(project_path):
                    return {
                        "success": False,
                        "path": exe_path,
                        "project_path": project_path,
                        "pid": 0,
                        "message": f"项目路径不存在: {project_path}",
                    }
                cmd.append(project_path)

            try:
                # 启动进程（不阻塞，不等待）
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

                self._launch_result = {
                    "success": True,
                    "path": exe_path,
                    "project_path": project_path or "",
                    "pid": process.pid,
                    "message": "VS Code 启动成功",
                }
                return self._launch_result.copy()

            except Exception as e:
                return {
                    "success": False,
                    "path": exe_path,
                    "project_path": project_path or "",
                    "pid": 0,
                    "message": f"启动失败: {e}",
                }

    # -----------------------------------------------------------------------
    # 检查运行状态
    # -----------------------------------------------------------------------

    def is_running(self) -> bool:
        """检查 VS Code 是否正在运行.

        优先使用 psutil，回退到 tasklist（Windows）。

        Returns:
            True 表示正在运行，False 表示未运行
        """
        if _HAS_PSUTIL:
            return self._check_with_psutil()

        if sys.platform == "win32":
            return self._check_with_tasklist()

        # 其他平台尝试 ps 命令
        return self._check_with_ps()

    def _check_with_psutil(self) -> bool:
        """使用 psutil 检查 VS Code 进程."""
        try:
            for proc in psutil.process_iter(["name"]):
                try:
                    name = proc.info.get("name", "")
                    if name and name.lower() in [n.lower() for n in self._PROCESS_NAMES]:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return False

    def _check_with_tasklist(self) -> bool:
        """使用 tasklist 检查 VS Code 进程（Windows）."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Code.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # 如果输出中包含 Code.exe 说明进程存在
            return "Code.exe" in result.stdout
        except Exception:
            return False

    def _check_with_ps(self) -> bool:
        """使用 ps 命令检查 VS Code 进程（类 Unix）."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.lower()
            for name in self._PROCESS_NAMES:
                if name.lower() in output:
                    return True
        except Exception:
            pass
        return False

    # -----------------------------------------------------------------------
    # 打开文件（支持行号跳转）
    # -----------------------------------------------------------------------

    def open_file(self, file_path: str, line: int | None = None) -> dict[str, Any]:
        """使用 VS Code 打开指定文件，可跳转到指定行号.

        Args:
            file_path: 要打开的文件路径
            line: 行号（可选，从 1 开始）

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"file_path": "...", "line": 行号},
            }
        """
        # 检测安装
        detect_result = self.detect_vscode()
        if not detect_result["installed"]:
            return {
                "success": False,
                "message": "未检测到 VS Code 安装",
                "data": {"file_path": file_path, "line": line},
            }

        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                "success": False,
                "message": f"文件不存在: {file_path}",
                "data": {"file_path": file_path, "line": line},
            }

        exe_path = detect_result["path"]

        # 构造命令：code --goto file:line 或 code file
        try:
            if line is not None and line > 0:
                target = f"{file_path}:{line}"
                cmd = [exe_path, "--goto", target]
            else:
                cmd = [exe_path, file_path]

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            return {
                "success": True,
                "message": f"已打开文件: {file_path}" + (f" (第 {line} 行)" if line else ""),
                "data": {"file_path": file_path, "line": line},
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"打开文件失败: {e}",
                "data": {"file_path": file_path, "line": line},
            }

    # -----------------------------------------------------------------------
    # 扩展管理
    # -----------------------------------------------------------------------

    def install_extension(self, extension_id: str) -> dict[str, Any]:
        """安装 VS Code 扩展.

        Args:
            extension_id: 扩展ID（如 ms-python.python）

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"extension_id": "..."},
            }
        """
        detect_result = self.detect_vscode()
        if not detect_result["installed"]:
            return {
                "success": False,
                "message": "未检测到 VS Code 安装",
                "data": {"extension_id": extension_id},
            }

        exe_path = detect_result["path"]

        try:
            result = subprocess.run(
                [exe_path, "--install-extension", extension_id, "--force"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "message": f"扩展安装成功: {extension_id}",
                    "data": {"extension_id": extension_id, "output": result.stdout.strip()},
                }
            else:
                return {
                    "success": False,
                    "message": f"扩展安装失败: {result.stderr.strip() or result.stdout.strip()}",
                    "data": {"extension_id": extension_id, "error": result.stderr.strip()},
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "扩展安装超时",
                "data": {"extension_id": extension_id},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"扩展安装异常: {e}",
                "data": {"extension_id": extension_id},
            }

    def uninstall_extension(self, extension_id: str) -> dict[str, Any]:
        """卸载 VS Code 扩展.

        Args:
            extension_id: 扩展ID（如 ms-python.python）

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"extension_id": "..."},
            }
        """
        detect_result = self.detect_vscode()
        if not detect_result["installed"]:
            return {
                "success": False,
                "message": "未检测到 VS Code 安装",
                "data": {"extension_id": extension_id},
            }

        exe_path = detect_result["path"]

        try:
            result = subprocess.run(
                [exe_path, "--uninstall-extension", extension_id],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "message": f"扩展卸载成功: {extension_id}",
                    "data": {"extension_id": extension_id, "output": result.stdout.strip()},
                }
            else:
                return {
                    "success": False,
                    "message": f"扩展卸载失败: {result.stderr.strip() or result.stdout.strip()}",
                    "data": {"extension_id": extension_id, "error": result.stderr.strip()},
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "扩展卸载超时",
                "data": {"extension_id": extension_id},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"扩展卸载异常: {e}",
                "data": {"extension_id": extension_id},
            }

    def list_extensions(self) -> dict[str, Any]:
        """列出已安装的 VS Code 扩展.

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"extensions": [...], "count": 数量},
            }
        """
        detect_result = self.detect_vscode()
        if not detect_result["installed"]:
            return {
                "success": False,
                "message": "未检测到 VS Code 安装",
                "data": {"extensions": [], "count": 0},
            }

        exe_path = detect_result["path"]

        try:
            result = subprocess.run(
                [exe_path, "--list-extensions", "--show-versions"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                extensions: list[dict[str, str]] = []
                for line in lines:
                    if not line.strip():
                        continue
                    # 格式通常为 extension_id@version
                    if "@" in line:
                        ext_id, version = line.rsplit("@", 1)
                        extensions.append({"id": ext_id.strip(), "version": version.strip()})
                    else:
                        extensions.append({"id": line.strip(), "version": ""})

                return {
                    "success": True,
                    "message": f"已获取 {len(extensions)} 个扩展",
                    "data": {"extensions": extensions, "count": len(extensions)},
                }
            else:
                return {
                    "success": False,
                    "message": f"获取扩展列表失败: {result.stderr.strip()}",
                    "data": {"extensions": [], "count": 0},
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "获取扩展列表超时",
                "data": {"extensions": [], "count": 0},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"获取扩展列表异常: {e}",
                "data": {"extensions": [], "count": 0},
            }

    # -----------------------------------------------------------------------
    # 终端与命令执行
    # -----------------------------------------------------------------------

    def run_command(self, command: str, cwd: str | None = None) -> dict[str, Any]:
        """在 VS Code 集成终端中执行命令.

        实际通过独立终端进程执行命令（VS Code 无直接执行终端命令的 CLI 参数）。
        命令结果通过标准输出捕获返回。

        Args:
            command: 要执行的命令字符串
            cwd: 工作目录（可选）

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"command": "...", "stdout": "...", "stderr": "...", "returncode": 0},
            }
        """
        if not command.strip():
            return {
                "success": False,
                "message": "命令不能为空",
                "data": {"command": command, "stdout": "", "stderr": "", "returncode": -1},
            }

        try:
            # Windows 使用 cmd /c，其他使用 shell
            if sys.platform == "win32":
                cmd_list = ["cmd", "/c", command]
            else:
                cmd_list = ["sh", "-c", command]

            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=60,
            )

            success = result.returncode == 0
            return {
                "success": success,
                "message": "命令执行成功" if success else f"命令执行失败，返回码: {result.returncode}",
                "data": {
                    "command": command,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "cwd": cwd or "",
                },
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "命令执行超时",
                "data": {"command": command, "stdout": "", "stderr": "timeout", "returncode": -1, "cwd": cwd or ""},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"命令执行异常: {e}",
                "data": {"command": command, "stdout": "", "stderr": str(e), "returncode": -1, "cwd": cwd or ""},
            }

    def open_terminal(self, project_path: str | None = None) -> dict[str, Any]:
        """打开 VS Code 终端.

        通过启动 VS Code 并在指定目录打开的方式，间接打开集成终端。
        Windows 平台额外尝试直接打开系统终端到目标目录。

        Args:
            project_path: 项目路径（终端工作目录）

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {"project_path": "..."},
            }
        """
        try:
            # 优先使用 VS Code 打开项目目录（会自动显示集成终端区域）
            detect_result = self.detect_vscode()
            if detect_result["installed"]:
                exe_path = detect_result["path"]
                cmd = [exe_path]
                if project_path and os.path.exists(project_path):
                    cmd.append(project_path)

                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

                return {
                    "success": True,
                    "message": "VS Code 终端已打开",
                    "data": {"project_path": project_path or ""},
                }

            # 回退：直接打开系统终端
            if sys.platform == "win32":
                terminal_cmd = ["cmd.exe"]
                if project_path and os.path.exists(project_path):
                    subprocess.Popen(
                        terminal_cmd,
                        cwd=project_path,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                else:
                    subprocess.Popen(
                        terminal_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )

                return {
                    "success": True,
                    "message": "系统终端已打开",
                    "data": {"project_path": project_path or ""},
                }

            return {
                "success": False,
                "message": "无法打开终端：未检测到 VS Code 且不支持当前平台",
                "data": {"project_path": project_path or ""},
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"打开终端失败: {e}",
                "data": {"project_path": project_path or ""},
            }

    # -----------------------------------------------------------------------
    # 综合状态
    # -----------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """获取 VS Code 综合状态.

        包括：安装状态、版本、运行状态、已安装扩展数量等。

        Returns:
            结果字典:
            {
                "success": True/False,
                "message": "描述信息",
                "data": {
                    "installed": True/False,
                    "install_path": "...",
                    "version": "...",
                    "running": True/False,
                    "extensions_count": 数量,
                    "detect_source": "...",
                },
            }
        """
        try:
            detect_result = self.detect_vscode()
            running = self.is_running()

            extensions_count = 0
            if detect_result["installed"]:
                list_result = self.list_extensions()
                if list_result["success"]:
                    extensions_count = list_result["data"].get("count", 0)

            return {
                "success": True,
                "message": "状态获取成功",
                "data": {
                    "installed": detect_result["installed"],
                    "install_path": detect_result["path"],
                    "version": detect_result["version"],
                    "running": running,
                    "extensions_count": extensions_count,
                    "detect_source": detect_result["source"],
                },
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"获取状态失败: {e}",
                "data": {
                    "installed": False,
                    "install_path": "",
                    "version": "",
                    "running": False,
                    "extensions_count": 0,
                    "detect_source": "error",
                },
            }

    # -----------------------------------------------------------------------
    # 关闭 VS Code
    # -----------------------------------------------------------------------

    def close_vscode(self) -> bool:
        """关闭 VS Code.

        优先使用优雅关闭（taskkill /IM），失败则强制终止。

        Returns:
            True 表示关闭成功，False 表示失败或进程不存在
        """
        with self._lock:
            if not self.is_running():
                return False

            try:
                if sys.platform == "win32":
                    # 优雅关闭
                    subprocess.run(
                        ["taskkill", "/IM", "Code.exe", "/T"],
                        capture_output=True,
                        timeout=10,
                    )
                else:
                    # 类 Unix 平台
                    if _HAS_PSUTIL:
                        for proc in psutil.process_iter(["name"]):
                            try:
                                name = proc.info.get("name", "")
                                if name and name.lower() in [
                                    n.lower() for n in self._PROCESS_NAMES
                                ]:
                                    proc.terminate()
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                    else:
                        subprocess.run(
                            ["pkill", "code"],
                            capture_output=True,
                            timeout=10,
                        )

                # 等待最多 5 秒确认关闭
                for _ in range(10):
                    time.sleep(0.5)
                    if not self.is_running():
                        return True

                return not self.is_running()

            except Exception:
                return False


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_vscode_launcher: VSCodeLauncher | None = None


def get_vscode_launcher() -> VSCodeLauncher:
    """获取 VS Code 启动器单例."""
    global _vscode_launcher
    if _vscode_launcher is None:
        _vscode_launcher = VSCodeLauncher()
    return _vscode_launcher


# ---------------------------------------------------------------------------
# 兼容相对导入和直接运行
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 直接运行时的简单测试
    launcher = VSCodeLauncher()
    print("检测结果:", launcher.detect_vscode())
    print("运行状态:", launcher.is_running())
