"""M11 MCP Bus - 外部系统适配器包.

提供将外部系统（M2 技能集群、M7 积木平台、语音模块等）封装为
标准 MCP 服务的适配器基类和具体实现。
"""

from .base import BaseMcpAdapter
from .m2_adapter import M2SkillAdapter
from .m7_adapter import M7BlockAdapter
from .m4_adapter import M4SceneAdapter
from .m5_adapter import M5MemoryAdapter

__all__ = [
    "BaseMcpAdapter",
    "M2SkillAdapter",
    "M7BlockAdapter",
    "M4SceneAdapter",
    "M5MemoryAdapter",
]
