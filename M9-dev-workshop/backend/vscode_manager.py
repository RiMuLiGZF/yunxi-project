"""
云汐 M9 开发者工坊 - VS Code 管理器
负责 VS Code 的启动、关闭、状态监控、扩展管理等核心功能
"""

import os
import sys
import subprocess
import time
from datetime import datetime
from typing import Optional, List, Dict
from pathlib import Path

# 路径安全工具（防止路径遍历攻击）
try:
    from .core.path_safety import is_path_safe, assert_path_safe, sanitize_filename
except ImportError:
    from core.path_safety import is_path_safe, assert_path_safe, sanitize_filename

# 兼容相对导入和直接运行
try:
    from .config import get_settings
    from .models import SessionLocal, VSCodeSession
except ImportError:
    from config import get_settings
    from models import SessionLocal, VSCodeSession


class VSCodeManager:
    """VS Code 管理器类"""

    def __init__(self):
        """初始化 VS Code 管理器"""
        self.settings = get_settings()
        self.vscode_path = self.settings.vscode_path
        self._db = SessionLocal()

    # ===== 基础检测功能 =====

    def is_installed(self) -> bool:
        """检查 VS Code 是否已安装"""
        if not self.vscode_path:
            return False
        return os.path.isfile(os.path.expandvars(self.vscode_path))

    def get_version(self) -> Optional[str]:
        """获取 VS Code 版本号"""
        if not self.is_installed():
            return None
        try:
            result = subprocess.run(
                [self.vscode_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                # 第一行是版本号
                lines = result.stdout.strip().split("\n")
                return lines[0] if lines else None
        except Exception:
            pass
        return None

    # ===== 进程管理 =====

    def get_running_processes(self) -> List[Dict]:
        """
        获取所有正在运行的 VS Code 进程
        返回进程列表：[{"pid": int, "name": str, "cmdline": str}]
        """
        processes = []
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    name = proc.info["name"] or ""
                    # VS Code 主进程名通常是 Code.exe
                    if name.lower().startswith("code") and name.lower().endswith(".exe"):
                        cmdline = " ".join(proc.info["cmdline"] or [])
                        # 过滤掉子进程（只保留有窗口的主进程）
                        if "--type=" not in cmdline:
                            processes.append({
                                "pid": proc.info["pid"],
                                "name": name,
                                "cmdline": cmdline,
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            # 如果没有 psutil，使用 tasklist 命令作为备选
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq Code.exe", "/FO", "CSV"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                lines = result.stdout.strip().split("\n")
                for line in lines[1:]:  # 跳过标题行
                    if line.strip():
                        parts = line.strip('"').split('","')
                        if len(parts) >= 2:
                            processes.append({
                                "pid": int(parts[1]),
                                "name": parts[0],
                                "cmdline": "",
                            })
            except Exception:
                pass
        return processes

    def is_running(self) -> bool:
        """检查 VS Code 是否正在运行"""
        return len(self.get_running_processes()) > 0

    # ===== 启动/关闭 =====

    def start(self, project_path: Optional[str] = None, new_window: bool = False) -> Dict:
        """
        启动 VS Code
        :param project_path: 要打开的项目路径（可选）
        :param new_window: 是否在新窗口打开
        :return: 启动结果 {"success": bool, "pid": int, "message": str}
        """
        if not self.is_installed():
            return {
                "success": False,
                "pid": None,
                "message": "VS Code 未安装或路径未配置"
            }

        # 路径安全校验：确保项目路径在 workspace_root 内，防止路径遍历攻击
        if project_path:
            try:
                assert_path_safe(self.settings.workspace_root, project_path, "vscode_start")
            except PathSecurityError as e:
                return {
                    "success": False,
                    "pid": None,
                    "message": f"路径安全校验失败: {str(e)}"
                }

        try:
            # 构建命令参数
            args = [self.vscode_path]
            if new_window:
                args.append("-n")
            if project_path and os.path.exists(project_path):
                args.append(project_path)

            # 启动进程（不等待，使用 DETACHED_PROCESS 让进程独立）
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200

            proc = subprocess.Popen(
                args,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                cwd=os.path.dirname(self.vscode_path),
            )

            # 等待一下让进程完全启动
            time.sleep(1.5)

            # 记录会话
            session = VSCodeSession(
                pid=proc.pid,
                project_path=project_path,
                start_time=datetime.now(),
                status="running",
                window_title=os.path.basename(project_path) if project_path else "VS Code",
            )
            self._db.add(session)
            self._db.commit()
            self._db.refresh(session)

            return {
                "success": True,
                "pid": proc.pid,
                "session_id": session.id,
                "message": f"VS Code 已启动，PID: {proc.pid}"
            }

        except Exception as e:
            return {
                "success": False,
                "pid": None,
                "message": f"启动失败: {str(e)}"
            }

    def close(self, pid: Optional[int] = None, force: bool = False) -> Dict:
        """
        关闭 VS Code
        :param pid: 指定进程 ID，为 None 则关闭所有
        :param force: 是否强制关闭
        :return: 关闭结果 {"success": bool, "closed_count": int}
        """
        closed_count = 0
        processes = self.get_running_processes()

        if not processes:
            return {"success": True, "closed_count": 0, "message": "没有运行中的 VS Code 进程"}

        try:
            import psutil
            for proc_info in processes:
                if pid is not None and proc_info["pid"] != pid:
                    continue
                try:
                    proc = psutil.Process(proc_info["pid"])
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                    closed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except ImportError:
            # 使用 taskkill 命令
            for proc_info in processes:
                if pid is not None and proc_info["pid"] != pid:
                    continue
                try:
                    cmd = ["taskkill", "/PID", str(proc_info["pid"])]
                    if force:
                        cmd.append("/F")
                    subprocess.run(cmd, capture_output=True, timeout=5)
                    closed_count += 1
                except Exception:
                    continue

        # 更新会话状态
        if closed_count > 0:
            self._db.query(VSCodeSession).filter(
                VSCodeSession.status == "running"
            ).update({
                VSCodeSession.status: "closed",
                VSCodeSession.end_time: datetime.now(),
            })
            self._db.commit()

        return {
            "success": True,
            "closed_count": closed_count,
            "message": f"已关闭 {closed_count} 个 VS Code 进程"
        }

    # ===== 打开文件/项目 =====

    def open_path(self, path: str, new_window: bool = False) -> Dict:
        """
        在 VS Code 中打开指定路径（项目或文件）
        :param path: 文件或文件夹路径
        :param new_window: 是否在新窗口打开
        :return: 操作结果
        """
        if not os.path.exists(path):
            return {"success": False, "message": f"路径不存在: {path}"}

        # 路径安全校验：确保路径在 workspace_root 内，防止路径遍历攻击
        try:
            assert_path_safe(self.settings.workspace_root, path, "vscode_open_path")
        except PathSecurityError as e:
            return {"success": False, "message": f"路径安全校验失败: {str(e)}"}

        if not self.is_installed():
            return {"success": False, "message": "VS Code 未安装"}

        try:
            args = [self.vscode_path]
            if new_window:
                args.append("-n")
            args.append(path)

            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                args,
                creationflags=DETACHED_PROCESS,
            )
            return {"success": True, "message": f"已打开: {path}"}
        except Exception as e:
            return {"success": False, "message": f"打开失败: {str(e)}"}

    def open_file(self, file_path: str, line: Optional[int] = None) -> Dict:
        """
        打开指定文件，可选跳转到行号
        :param file_path: 文件路径
        :param line: 行号（可选）
        :return: 操作结果
        """
        if not os.path.isfile(file_path):
            return {"success": False, "message": f"文件不存在: {file_path}"}

        # 路径安全校验：确保文件路径在 workspace_root 内，防止路径遍历攻击
        try:
            assert_path_safe(self.settings.workspace_root, file_path, "vscode_open_file")
        except PathSecurityError as e:
            return {"success": False, "message": f"路径安全校验失败: {str(e)}"}

        if not self.is_installed():
            return {"success": False, "message": "VS Code 未安装"}

        try:
            target = file_path
            if line is not None:
                target = f"{file_path}:{line}"

            args = [self.vscode_path, "-g", target]
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(args, creationflags=DETACHED_PROCESS)
            return {"success": True, "message": f"已打开文件: {file_path}" + (f" (第{line}行)" if line else "")}
        except Exception as e:
            return {"success": False, "message": f"打开失败: {str(e)}"}

    # ===== 扩展管理 =====

    def list_extensions(self) -> List[Dict]:
        """
        列出已安装的 VS Code 扩展
        返回扩展列表：[{"id": str, "name": str, "version": str, "publisher": str}]
        """
        if not self.is_installed():
            return []

        extensions = []
        try:
            # 使用 CLI 列出扩展
            result = subprocess.run(
                [self.vscode_path, "--list-extensions", "--show-versions"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip():
                        # 格式: publisher.extension@version
                        if "@" in line:
                            full_name, version = line.rsplit("@", 1)
                        else:
                            full_name = line
                            version = ""
                        parts = full_name.split(".", 1)
                        publisher = parts[0] if len(parts) > 0 else ""
                        name = parts[1] if len(parts) > 1 else full_name
                        extensions.append({
                            "id": full_name,
                            "name": name,
                            "publisher": publisher,
                            "version": version,
                        })
        except Exception:
            pass
        return extensions

    def install_extension(self, extension_id: str) -> Dict:
        """
        安装 VS Code 扩展
        :param extension_id: 扩展 ID（如 ms-python.python）
        :return: 安装结果
        """
        if not self.is_installed():
            return {"success": False, "message": "VS Code 未安装"}

        try:
            result = subprocess.run(
                [self.vscode_path, "--install-extension", extension_id],
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0
            return {
                "success": success,
                "message": result.stdout.strip() if success else result.stderr.strip()
            }
        except Exception as e:
            return {"success": False, "message": f"安装失败: {str(e)}"}

    def uninstall_extension(self, extension_id: str) -> Dict:
        """卸载 VS Code 扩展"""
        if not self.is_installed():
            return {"success": False, "message": "VS Code 未安装"}

        try:
            result = subprocess.run(
                [self.vscode_path, "--uninstall-extension", extension_id],
                capture_output=True,
                text=True,
                timeout=60
            )
            success = result.returncode == 0
            return {
                "success": success,
                "message": result.stdout.strip() if success else result.stderr.strip()
            }
        except Exception as e:
            return {"success": False, "message": f"卸载失败: {str(e)}"}

    # ===== 会话管理 =====

    def get_sessions(self, limit: int = 20, status: Optional[str] = None) -> List[Dict]:
        """获取会话记录"""
        query = self._db.query(VSCodeSession)
        if status:
            query = query.filter(VSCodeSession.status == status)
        sessions = query.order_by(VSCodeSession.start_time.desc()).limit(limit).all()
        return [s.to_dict() for s in sessions]

    def get_status(self) -> Dict:
        """获取 VS Code 综合状态"""
        processes = self.get_running_processes()
        return {
            "installed": self.is_installed(),
            "path": self.vscode_path,
            "version": self.get_version(),
            "running": len(processes) > 0,
            "process_count": len(processes),
            "processes": processes[:10],  # 最多返回 10 个
            "extension_count": len(self.list_extensions()),
        }

    def close_db(self):
        """关闭数据库连接"""
        self._db.close()


# 全局单例
_vscode_manager: Optional[VSCodeManager] = None


def get_vscode_manager() -> VSCodeManager:
    """获取 VS Code 管理器单例"""
    global _vscode_manager
    if _vscode_manager is None:
        _vscode_manager = VSCodeManager()
    return _vscode_manager


# 兼容直接运行测试
if __name__ == "__main__":
    mgr = get_vscode_manager()
    status = mgr.get_status()
    print("VS Code 状态:")
    for k, v in status.items():
        if k != "processes":
            print(f"  {k}: {v}")
    print(f"  进程数: {status['process_count']}")
    mgr.close_db()
