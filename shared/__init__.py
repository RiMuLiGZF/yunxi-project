"""
云汐系统共享模块
提供全局配置、模块注册、进程管理等共享功能
"""

from shared.config import YunxiConfig, get_config
from shared.module_client import ModuleRegistry, ModuleInfo, get_registry
from shared.process_manager import ProcessManager, ProcessInfo, get_process_manager

__all__ = [
    "YunxiConfig",
    "get_config",
    "ModuleRegistry",
    "ModuleInfo",
    "get_registry",
    "ProcessManager",
    "ProcessInfo",
    "get_process_manager",
]
