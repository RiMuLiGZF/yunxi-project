"""
模块进程管理器
负责各模块的真实启动、停止、状态跟踪
"""

import os
import sys
import time
import subprocess
import threading
from pathlib import Path
from typing import Dict, Optional, List
from enum import Enum

from ..core.config import get_config
from ..core.logger import get_logger

logger = get_logger("yunxi.process")


class ProcessStatus(str, Enum):
    """进程状态"""
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"


class ModuleProcessInfo:
    """模块进程信息"""
    
    def __init__(self, module_key: str):
        self.module_key = module_key
        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.status: ProcessStatus = ProcessStatus.STOPPED
        self.start_time: Optional[float] = None
        self.stop_time: Optional[float] = None
        self.error_message: Optional[str] = None
        self.restart_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            "module_key": self.module_key,
            "pid": self.pid,
            "status": self.status.value,
            "start_time": self.start_time,
            "stop_time": self.stop_time,
            "error_message": self.error_message,
            "restart_count": self.restart_count,
            "uptime": int(time.time() - self.start_time) if self.start_time and self.status == ProcessStatus.RUNNING else 0,
        }


class ModuleProcessManager:
    """模块进程管理器 - 单例"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._processes: Dict[str, ModuleProcessInfo] = {}
            cls._instance._config = get_config()
            cls._instance._project_root = Path(__file__).parent.parent.parent  # 项目根目录（shared 的上一级）
            cls._instance._lock = threading.Lock()
        return cls._instance
    
    def _get_module_start_cmd(self, module_key: str) -> Optional[List[str]]:
        """获取模块的启动命令"""
        module_key = module_key.lower()
        
        # 各模块的启动命令
        module_cmds = {
            "m1": {
                "dir": "M1-agent-hub",
                "cmd": [sys.executable, "server.py"],
            },
            "m2": {
                "dir": "M2-skills-cluster",
                "cmd": [sys.executable, "start_server.py"],
            },
            "m3": {
                "dir": "M3-edge-cloud",
                "cmd": [sys.executable, "server.py"],
            },
            "m4": {
                "dir": "M4-scene-engine",
                "cmd": [sys.executable, "server.py"],
            },
            "m5": {
                "dir": "M5-tide-memory",
                "cmd": [sys.executable, "server.py"],
            },
            "m6": {
                "dir": "M6-hardware-peripheral",
                "cmd": [sys.executable, "server.py"],
            },
            "m7": {
                "dir": "M7-workflow-builder",
                "cmd": [sys.executable, "server.py"],
            },
            "m8": {
                "dir": "M8-control-tower",
                "cmd": [sys.executable, "server.py"],
            },
            "m9": {
                "dir": "M9-programming-dev",
                "cmd": [sys.executable, "server.py"],
            },
            "m10": {
                "dir": "M10-system-guard",
                "cmd": [sys.executable, "server.py"],
            },
        }
        
        info = module_cmds.get(module_key)
        if not info:
            return None
        
        work_dir = self._project_root / info["dir"]
        if not work_dir.exists():
            logger.warning(f"模块目录不存在: {work_dir}")
            return None
        
        return info["cmd"], str(work_dir)
    
    def start_module(self, module_key: str) -> ModuleProcessInfo:
        """启动模块"""
        module_key = module_key.lower()
        
        with self._lock:
            if module_key not in self._processes:
                self._processes[module_key] = ModuleProcessInfo(module_key)
            
            info = self._processes[module_key]
            
            if info.status == ProcessStatus.RUNNING:
                logger.info(f"模块 {module_key} 已在运行")
                return info
            
            if info.status == ProcessStatus.STARTING:
                logger.info(f"模块 {module_key} 正在启动中")
                return info
            
            cmd_info = self._get_module_start_cmd(module_key)
            if not cmd_info:
                info.status = ProcessStatus.ERROR
                info.error_message = f"不支持启动的模块: {module_key}"
                logger.error(info.error_message)
                return info
            
            cmd, work_dir = cmd_info
            
            try:
                info.status = ProcessStatus.STARTING
                info.error_message = None
                
                # Windows 下使用 DETACHED_PROCESS 让进程独立运行
                if os.name == 'nt':
                    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
                    # 不显示控制台窗口
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                    process = subprocess.Popen(
                        cmd,
                        cwd=work_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=creationflags,
                        startupinfo=startupinfo,
                    )
                else:
                    process = subprocess.Popen(
                        cmd,
                        cwd=work_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                    )
                
                info.process = process
                info.pid = process.pid
                info.start_time = time.time()
                info.restart_count += 1
                
                logger.info(f"模块 {module_key} 启动中，PID: {process.pid}")
                
                # 异步等待启动完成
                threading.Thread(
                    target=self._wait_for_start,
                    args=(module_key,),
                    daemon=True,
                ).start()
                
                return info
                
            except Exception as e:
                info.status = ProcessStatus.ERROR
                info.error_message = str(e)
                logger.error(f"模块 {module_key} 启动失败: {e}")
                return info
    
    def _wait_for_start(self, module_key: str):
        """等待模块启动完成（通过健康检查）"""
        import httpx
        
        info = self._processes.get(module_key)
        if not info:
            return
        
        port = self._config.get_module_port(module_key)
        if not port:
            info.status = ProcessStatus.ERROR
            info.error_message = "未配置端口"
            return
        
        # 最多等待 30 秒
        max_wait = 30
        start = time.time()
        
        while time.time() - start < max_wait:
            # 检查进程是否还活着
            if info.process and info.process.poll() is not None:
                info.status = ProcessStatus.ERROR
                info.error_message = f"进程已退出，退出码: {info.process.returncode}"
                logger.error(f"模块 {module_key} 启动失败: {info.error_message}")
                return
            
            # 尝试健康检查
            try:
                resp = httpx.get(f"http://localhost:{port}/health", timeout=2)
                if resp.status_code == 200:
                    info.status = ProcessStatus.RUNNING
                    logger.info(f"模块 {module_key} 启动成功，PID: {info.pid}")
                    return
            except:
                pass
            
            time.sleep(1)
        
        # 超时
        if info.process and info.process.poll() is None:
            info.status = ProcessStatus.RUNNING  # 进程在跑就算成功
            logger.warning(f"模块 {module_key} 启动超时但进程仍在运行，PID: {info.pid}")
        else:
            info.status = ProcessStatus.ERROR
            info.error_message = "启动超时"
    
    def stop_module(self, module_key: str, force: bool = False) -> ModuleProcessInfo:
        """停止模块"""
        module_key = module_key.lower()
        
        with self._lock:
            info = self._processes.get(module_key)
            if not info or not info.process:
                # 没有进程信息，检查是否已注册
                if module_key not in self._processes:
                    self._processes[module_key] = ModuleProcessInfo(module_key)
                info = self._processes[module_key]
                info.status = ProcessStatus.STOPPED
                return info
            
            if info.status in [ProcessStatus.STOPPED, ProcessStatus.STOPPING]:
                return info
            
            info.status = ProcessStatus.STOPPING
            logger.info(f"正在停止模块 {module_key}，PID: {info.pid}")
            
            try:
                if force:
                    # 强制终止
                    info.process.kill()
                else:
                    # 优雅停止
                    if os.name == 'nt':
                        # Windows 下发送 Ctrl+C 事件
                        import signal
                        try:
                            info.process.send_signal(signal.CTRL_BREAK_EVENT)
                        except:
                            info.process.terminate()
                    else:
                        info.process.terminate()
                
                # 等待最多 10 秒
                try:
                    info.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if not force:
                        info.process.kill()
                        info.process.wait(timeout=5)
                
                info.status = ProcessStatus.STOPPED
                info.stop_time = time.time()
                logger.info(f"模块 {module_key} 已停止")
                
            except Exception as e:
                info.status = ProcessStatus.ERROR
                info.error_message = str(e)
                logger.error(f"模块 {module_key} 停止失败: {e}")
            
            return info
    
    def get_process_info(self, module_key: str) -> Optional[ModuleProcessInfo]:
        """获取模块进程信息"""
        module_key = module_key.lower()
        info = self._processes.get(module_key)
        
        # 刷新状态
        if info and info.process:
            if info.process.poll() is not None:
                if info.status == ProcessStatus.RUNNING:
                    info.status = ProcessStatus.ERROR
                    info.error_message = f"进程异常退出，退出码: {info.process.returncode}"
                    info.stop_time = time.time()
                    logger.warning(f"模块 {module_key} 异常退出")
        
        return info
    
    def get_all_processes(self) -> Dict[str, ModuleProcessInfo]:
        """获取所有模块进程信息"""
        # 刷新所有状态
        for key, info in self._processes.items():
            if info.process and info.process.poll() is not None:
                if info.status == ProcessStatus.RUNNING:
                    info.status = ProcessStatus.ERROR
                    info.error_message = f"进程异常退出，退出码: {info.process.returncode}"
                    info.stop_time = time.time()
        
        return self._processes
    
    def restart_module(self, module_key: str) -> ModuleProcessInfo:
        """重启模块"""
        self.stop_module(module_key)
        # 等一下再启动
        time.sleep(2)
        return self.start_module(module_key)
    
    def get_logs(self, module_key: str, lines: int = 50) -> List[str]:
        """获取模块日志（最后 N 行）"""
        module_key = module_key.lower()
        info = self._processes.get(module_key)
        
        if not info or not info.process:
            return []
        
        # 从标准输出读取（如果有的话）
        try:
            # 尝试从日志文件读取
            log_dir = self._project_root / "logs"
            log_file = log_dir / f"{module_key}.log"
            
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    all_lines = f.readlines()
                    return all_lines[-lines:]
        except:
            pass
        
        return []


def get_process_manager() -> ModuleProcessManager:
    """获取进程管理器单例"""
    return ModuleProcessManager()
