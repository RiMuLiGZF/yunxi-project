"""
云汐系统进程管理器
统一管理各模块的启动、停止、状态监控
"""

import os
import sys
import subprocess
import signal
from pathlib import Path
from typing import Dict, List, Optional


# 模块配置（硬编码）
MODULE_CONFIGS: List[dict] = [
    {
        "key": "m1",
        "name": "代理集群",
        "work_dir": "M1-agent-cluster",
        "start_cmd": "python server.py",
        "port": 8001,
    },
    {
        "key": "m2",
        "name": "技能集群",
        "work_dir": "M2-skills-cluster",
        "start_cmd": "python server.py",
        "port": 8002,
    },
    {
        "key": "m3",
        "name": "边缘云端",
        "work_dir": "M3-edge-cloud",
        "start_cmd": "python server.py",
        "port": 8003,
    },
    {
        "key": "m4",
        "name": "场景引擎",
        "work_dir": "m4-scene-engine",
        "start_cmd": "python server.py",
        "port": 8004,
    },
    {
        "key": "m5",
        "name": "潮汐记忆",
        "work_dir": "M5-tide-memory",
        "start_cmd": "python server.py",
        "port": 8005,
    },
    {
        "key": "m6",
        "name": "硬件外设",
        "work_dir": "M6-hardware-peripheral",
        "start_cmd": "python server.py",
        "port": 8006,
    },
    {
        "key": "m7",
        "name": "工作流构建器",
        "work_dir": "M7-workflow-builder",
        "start_cmd": "python server.py",
        "port": 8007,
    },
    {
        "key": "m8",
        "name": "控制塔",
        "work_dir": "M8-control-tower",
        "start_cmd": "python server.py",
        "port": 8008,
    },
    {
        "key": "m10",
        "name": "系统卫士",
        "work_dir": "M10-system-guard",
        "start_cmd": "python server.py",
        "port": 8010,
    },
]


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


class ProcessManager:
    """进程管理器 - 单例模式"""

    _instance: Optional["ProcessManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, project_root: Optional[Path] = None):
        if self._initialized:
            return
        self._initialized = True
        self._project_root = project_root or Path(__file__).resolve().parent.parent
        self._processes: Dict[str, ProcessInfo] = {}

    def get_module_config(self, module_key: str) -> Optional[dict]:
        """获取指定模块的配置"""
        for config in MODULE_CONFIGS:
            if config["key"] == module_key:
                return config
        return None

    def get_all_module_configs(self) -> List[dict]:
        """获取所有模块的配置"""
        return MODULE_CONFIGS.copy()

    def get_module_count(self) -> int:
        """获取模块总数"""
        return len(MODULE_CONFIGS)

    def start_module(self, module_key: str) -> bool:
        """启动指定模块"""
        config = self.get_module_config(module_key)
        if not config:
            print(f"[ProcessManager] 模块 {module_key} 不存在")
            return False

        # 检查是否已经在运行
        if self.is_module_running(module_key):
            print(f"[ProcessManager] 模块 {module_key} 已在运行")
            return True

        work_dir = self._project_root / config["work_dir"]
        if not work_dir.exists():
            print(f"[ProcessManager] 模块工作目录不存在: {work_dir}")
            return False

        try:
            # 启动进程
            cmd = config["start_cmd"].split()
            process = subprocess.Popen(
                cmd,
                cwd=str(work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            self._processes[module_key] = ProcessInfo(module_key, process)
            print(f"[ProcessManager] 模块 {module_key} 启动成功，PID: {process.pid}")
            return True
        except Exception as e:
            print(f"[ProcessManager] 模块 {module_key} 启动失败: {e}")
            return False

    def stop_module(self, module_key: str) -> bool:
        """停止指定模块"""
        if module_key not in self._processes:
            print(f"[ProcessManager] 模块 {module_key} 未启动")
            return False

        proc_info = self._processes[module_key]
        if not proc_info.is_running():
            del self._processes[module_key]
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
            print(f"[ProcessManager] 模块 {module_key} 已停止")
            return True
        except Exception as e:
            print(f"[ProcessManager] 停止模块 {module_key} 失败: {e}")
            return False

    def is_module_running(self, module_key: str) -> bool:
        """检查模块是否在运行"""
        if module_key not in self._processes:
            return False
        return self._processes[module_key].is_running()

    def get_module_status(self, module_key: str) -> str:
        """获取模块状态"""
        if self.is_module_running(module_key):
            return "running"
        return "stopped"

    def get_all_status(self) -> List[dict]:
        """获取所有模块的状态"""
        status_list = []
        for config in MODULE_CONFIGS:
            status_list.append({
                "key": config["key"],
                "name": config["name"],
                "port": config["port"],
                "status": self.get_module_status(config["key"]),
            })
        return status_list

    def start_all(self) -> dict:
        """启动所有模块"""
        results = {"success": [], "failed": []}
        for config in MODULE_CONFIGS:
            if self.start_module(config["key"]):
                results["success"].append(config["key"])
            else:
                results["failed"].append(config["key"])
        return results

    def stop_all(self) -> dict:
        """停止所有模块"""
        results = {"success": [], "failed": []}
        for config in MODULE_CONFIGS:
            if self.stop_module(config["key"]):
                results["success"].append(config["key"])
            else:
                results["failed"].append(config["key"])
        return results


# 全局进程管理器单例
_process_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    """获取全局进程管理器实例"""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
