"""
云汐系统进程管理器
统一管理各模块的启动、停止、状态监控

CQ-001 改造：模块配置从 ModuleRegistry 读取，不再硬编码。
向后兼容：如果配置文件不存在，使用内置默认配置。
"""

import os
import sys
import subprocess
import signal
from pathlib import Path
from typing import Dict, List, Optional

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.core.module_registry import (
    ModuleRegistry,
    ModuleInfo,
    ModuleStatus,
    get_module_registry,
)


# =============================================================================
#  向后兼容：旧的 MODULE_CONFIGS 列表（从注册表动态生成）
# =============================================================================

def _build_module_configs_from_registry() -> List[dict]:
    """
    从模块注册表构建旧格式的 MODULE_CONFIGS 列表。

    用于向后兼容，旧代码依赖 MODULE_CONFIGS 列表格式。
    """
    registry = get_module_registry()
    configs = []
    for module in registry.list_modules(enabled_only=False):
        configs.append({
            "key": module.id,
            "name": module.name,
            "work_dir": module.directory,
            "start_cmd": module.start_command,
            "port": module.port,
            "python_executable": module.python_executable or "python",
            "health_check": module.health_check_path,
        })
    return configs


# MODULE_CONFIGS 现在是属性访问器，每次访问都从注册表获取最新配置
# 这样动态注册的模块也能被旧代码看到
class _ModuleConfigsProxy:
    """MODULE_CONFIGS 的代理类，模拟列表行为，实际从注册表读取"""

    def __iter__(self):
        return iter(_build_module_configs_from_registry())

    def __len__(self):
        return len(_build_module_configs_from_registry())

    def __getitem__(self, index):
        return _build_module_configs_from_registry()[index]

    def __contains__(self, item):
        return item in _build_module_configs_from_registry()

    def copy(self):
        return _build_module_configs_from_registry()

    def __bool__(self):
        return bool(_build_module_configs_from_registry())


# 向后兼容的模块配置列表
MODULE_CONFIGS: List[dict] = _ModuleConfigsProxy()  # type: ignore[assignment]


# =============================================================================
#  ProcessInfo - 进程信息
# =============================================================================

class ProcessInfo:
    """进程信息类"""

    def __init__(self, module_key: str, process: Optional[subprocess.Popen] = None):
        self.module_key = module_key
        self.process = process
        self.pid = process.pid if process else None
        self.status = "stopped"  # running / stopped / error

    def is_running(self) -> bool:
        """检查进程是否在运行"""
        if self.process is None:
            return False
        return self.process.poll() is None


# =============================================================================
#  ProcessManager - 进程管理器
# =============================================================================

class ProcessManager:
    """进程管理器 - 单例模式

    CQ-001 改造：从 ModuleRegistry 读取模块配置，支持动态注册的模块。
    """

    _instance: Optional["ProcessManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, project_root: Optional[Path] = None, registry: Optional[ModuleRegistry] = None):
        if self._initialized:
            return
        self._initialized = True
        self._project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self._processes: Dict[str, ProcessInfo] = {}

        # 使用传入的注册表或获取全局注册表
        self._registry = registry or get_module_registry()

    @property
    def registry(self) -> ModuleRegistry:
        """获取关联的模块注册表"""
        return self._registry

    def get_module_config(self, module_key: str) -> Optional[dict]:
        """
        获取指定模块的配置（旧格式 dict，向后兼容）。

        Args:
            module_key: 模块标识

        Returns:
            模块配置字典，或 None
        """
        module = self._registry.get_module(module_key)
        if module is None:
            return None
        return {
            "key": module.id,
            "name": module.name,
            "work_dir": module.directory,
            "start_cmd": module.start_command,
            "port": module.port,
            "python_executable": module.python_executable or "python",
            "health_check": module.health_check_path,
        }

    def get_module_info(self, module_key: str) -> Optional[ModuleInfo]:
        """
        获取指定模块的 ModuleInfo 对象（新 API）。

        Args:
            module_key: 模块标识

        Returns:
            ModuleInfo 对象，或 None
        """
        return self._registry.get_module(module_key)

    def get_all_module_configs(self) -> List[dict]:
        """获取所有模块的配置（旧格式 list，向后兼容）"""
        return _build_module_configs_from_registry()

    def get_all_modules(self) -> List[ModuleInfo]:
        """获取所有模块的 ModuleInfo 列表（新 API）"""
        return self._registry.list_modules(enabled_only=False)

    def get_module_count(self) -> int:
        """获取模块总数"""
        return self._registry.get_module_count(enabled_only=False)

    def start_module(self, module_key: str) -> bool:
        """
        启动指定模块。

        Args:
            module_key: 模块标识

        Returns:
            True 表示启动成功
        """
        module = self._registry.get_module(module_key)
        if module is None:
            print(f"[ProcessManager] 模块 {module_key} 不存在")
            return False

        if not module.enabled:
            print(f"[ProcessManager] 模块 {module_key} 已禁用，跳过启动")
            return False

        # 检查是否已经在运行
        if self.is_module_running(module_key):
            print(f"[ProcessManager] 模块 {module_key} 已在运行")
            return True

        work_dir = module.get_work_dir(self._project_root)
        if not work_dir.exists():
            print(f"[ProcessManager] 模块工作目录不存在: {work_dir}")
            return False

        try:
            # 更新状态
            module.status = ModuleStatus.STARTING

            # 启动进程
            cmd = module.start_command.split()
            # 如果配置了指定的 python 可执行文件且命令以 python 开头，替换之
            python_exe = module.python_executable or self._registry.global_config.python_executable
            if cmd and cmd[0] in ("python", "python3") and python_exe != "python":
                cmd[0] = python_exe

            process = subprocess.Popen(
                cmd,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            self._processes[module_key] = ProcessInfo(module_key, process)
            module.pid = process.pid
            module.status = ModuleStatus.RUNNING
            print(f"[ProcessManager] 模块 {module_key} 启动成功，PID: {process.pid}")
            return True
        except Exception as e:
            module.status = ModuleStatus.ERROR
            print(f"[ProcessManager] 模块 {module_key} 启动失败: {e}")
            return False

    def stop_module(self, module_key: str) -> bool:
        """
        停止指定模块。

        Args:
            module_key: 模块标识

        Returns:
            True 表示停止成功
        """
        if module_key not in self._processes:
            print(f"[ProcessManager] 模块 {module_key} 未启动")
            return False

        proc_info = self._processes[module_key]
        if not proc_info.is_running():
            del self._processes[module_key]
            module = self._registry.get_module(module_key)
            if module:
                module.status = ModuleStatus.STOPPED
                module.pid = None
            return True

        try:
            if os.name == "nt":
                # Windows: 使用 taskkill 终止进程树
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc_info.pid)],
                    capture_output=True,
                )
            else:
                # Unix/Linux: 发送 SIGTERM
                proc_info.process.terminate()
                try:
                    proc_info.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc_info.process.kill()

            proc_info.status = "stopped"
            del self._processes[module_key]

            # 更新注册表中的状态
            module = self._registry.get_module(module_key)
            if module:
                module.status = ModuleStatus.STOPPED
                module.pid = None

            print(f"[ProcessManager] 模块 {module_key} 已停止")
            return True
        except Exception as e:
            module = self._registry.get_module(module_key)
            if module:
                module.status = ModuleStatus.ERROR
            print(f"[ProcessManager] 停止模块 {module_key} 失败: {e}")
            return False

    def is_module_running(self, module_key: str) -> bool:
        """检查模块是否在运行"""
        if module_key not in self._processes:
            return False
        return self._processes[module_key].is_running()

    def get_module_status(self, module_key: str) -> str:
        """
        获取模块状态。

        Returns:
            "running" / "stopped" / "error"
        """
        module = self._registry.get_module(module_key)
        if module:
            return module.status.value

        if self.is_module_running(module_key):
            return "running"
        return "stopped"

    def get_all_status(self) -> List[dict]:
        """获取所有模块的状态"""
        status_list = []
        for module in self._registry.list_modules(enabled_only=False):
            # 实时检查进程状态
            if module.id in self._processes:
                is_running = self._processes[module.id].is_running()
                if is_running:
                    status = "running"
                else:
                    status = "stopped"
            else:
                status = module.status.value

            status_list.append({
                "key": module.id,
                "name": module.name,
                "port": module.port,
                "status": status,
                "enabled": module.enabled,
                "category": module.category.value,
                "priority": module.priority,
            })
        return status_list

    def start_all(self, enabled_only: bool = True) -> dict:
        """
        启动所有模块（按优先级顺序）。

        Args:
            enabled_only: 是否只启动启用的模块

        Returns:
            {"success": [...], "failed": [...]}
        """
        results = {"success": [], "failed": []}
        modules = self._registry.get_startup_order(enabled_only=enabled_only)
        for module in modules:
            if self.start_module(module.id):
                results["success"].append(module.id)
            else:
                results["failed"].append(module.id)
        return results

    def stop_all(self) -> dict:
        """
        停止所有模块（按启动顺序的逆序）。

        Returns:
            {"success": [...], "failed": [...]}
        """
        results = {"success": [], "failed": []}
        # 逆序停止（优先级高的后停）
        modules = list(reversed(self._registry.get_startup_order(enabled_only=False)))
        for module in modules:
            if module.id in self._processes:
                if self.stop_module(module.id):
                    results["success"].append(module.id)
                else:
                    results["failed"].append(module.id)
        return results

    def restart_module(self, module_key: str) -> bool:
        """
        重启指定模块。

        Args:
            module_key: 模块标识

        Returns:
            True 表示重启成功
        """
        self.stop_module(module_key)
        return self.start_module(module_key)


# =============================================================================
#  全局进程管理器单例
# =============================================================================

_process_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    """获取全局进程管理器实例"""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager


# =============================================================================
#  向后兼容别名
# =============================================================================

class ProcessStatus:
    """进程状态常量（向后兼容）"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    RESTARTING = "restarting"
    UNKNOWN = "unknown"


# =============================================================================
#  模块导出
# =============================================================================

__all__ = [
    "ProcessInfo",
    "ProcessManager",
    "ProcessStatus",
    "MODULE_CONFIGS",
    "get_process_manager",
]
