"""
云汐系统模块客户端
统一管理所有模块的注册、发现和通信
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.config import get_config


class ModuleInfo:
    """模块信息类"""

    def __init__(
        self,
        key: str,
        name: str,
        version: str,
        port: int,
        base_url: str,
        description: str = "",
    ):
        self.key = key
        self.name = name
        self.version = version
        self.port = port
        self.base_url = base_url
        self.description = description
        self.status = "unknown"  # unknown / running / stopped / error

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "port": self.port,
            "base_url": self.base_url,
            "description": self.description,
            "status": self.status,
        }


class ModuleRegistry:
    """模块注册表 - 单例模式"""

    _instance: Optional["ModuleRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config=None):
        if self._initialized:
            return
        self._initialized = True
        self._config = config or get_config()
        self._modules: Dict[str, ModuleInfo] = {}
        self._register_default_modules()

    def _register_default_modules(self):
        """注册默认模块（共9个）"""
        default_modules = [
            {
                "key": "m1",
                "name": "代理集群",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m1"),
                "base_url": self._config.get_module_base_url("m1"),
                "description": "多智能体协作、联邦调度、任务编排",
            },
            {
                "key": "m2",
                "name": "技能集群",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m2"),
                "base_url": self._config.get_module_base_url("m2"),
                "description": "技能库管理、技能发现、技能执行引擎",
            },
            {
                "key": "m3",
                "name": "边缘云端",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m3"),
                "base_url": self._config.get_module_base_url("m3"),
                "description": "边缘计算、云边协同、混合算力调度",
            },
            {
                "key": "m4",
                "name": "场景引擎",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m4"),
                "base_url": self._config.get_module_base_url("m4"),
                "description": "场景模板、场景编排、交互引擎",
            },
            {
                "key": "m5",
                "name": "潮汐记忆",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m5"),
                "base_url": self._config.get_module_base_url("m5"),
                "description": "长期记忆、向量检索、知识图谱",
            },
            {
                "key": "m6",
                "name": "硬件外设",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m6"),
                "base_url": self._config.get_module_base_url("m6"),
                "description": "硬件驱动、外设管理、设备联动",
            },
            {
                "key": "m7",
                "name": "工作流构建器",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m7"),
                "base_url": self._config.get_module_base_url("m7"),
                "description": "可视化流程编排、自动化任务、触发器",
            },
            {
                "key": "m8",
                "name": "控制塔",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m8"),
                "base_url": self._config.get_module_base_url("m8"),
                "description": "算力调度、API网关、统一管控台",
            },
            {
                "key": "m10",
                "name": "系统卫士",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m10"),
                "base_url": self._config.get_module_base_url("m10"),
                "description": "系统资源监控、进程管理、阈值防护、审计日志",
            },
        ]

        for module_data in default_modules:
            module = ModuleInfo(**module_data)
            self._modules[module.key] = module

    def register_module(self, module: ModuleInfo):
        """注册一个模块"""
        self._modules[module.key] = module

    def unregister_module(self, key: str):
        """注销一个模块"""
        if key in self._modules:
            del self._modules[key]

    def get_module(self, key: str) -> Optional[ModuleInfo]:
        """获取指定模块的信息"""
        return self._modules.get(key)

    def get_all_modules(self) -> List[ModuleInfo]:
        """获取所有已注册的模块"""
        return list(self._modules.values())

    def get_module_count(self) -> int:
        """获取已注册模块的数量"""
        return len(self._modules)

    def update_module_status(self, key: str, status: str):
        """更新模块状态"""
        if key in self._modules:
            self._modules[key].status = status


# 全局注册表单例
_registry: Optional[ModuleRegistry] = None


def get_registry() -> ModuleRegistry:
    """获取全局模块注册表实例"""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry


# ==================== 向后兼容别名 ====================

# 函数别名
get_module_registry = get_registry

# ModuleStatus 兼容（使用字符串状态）
class ModuleStatus:
    """模块状态常量（向后兼容）"""
    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"

# ModuleClient 兼容（指向 ModuleRegistry）
ModuleClient = ModuleRegistry
