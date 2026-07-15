"""M11 MCP Bus - 外部系统适配器包.

提供将外部系统（M2 技能集群、M4 场景引擎、M5 潮汐记忆、M7 积木平台、
M8 控制塔、M10 硬件策略、M12 安全网关等）封装为标准 MCP 服务的适配器基类和具体实现。
"""

from .base import BaseMcpAdapter
from .m2_adapter import M2SkillAdapter
from .m2_adapter_full import M2FullSkillAdapter
from .m4_adapter import M4SceneAdapter
from .m5_adapter import M5MemoryAdapter
from .m7_adapter import M7BlockAdapter
from .m8_adapter import M8ControlAdapter
from .m10_adapter import M10MetricsAdapter
from .m12_adapter import M12SecurityAdapter

__all__ = [
    "BaseMcpAdapter",
    "M2SkillAdapter",
    "M2FullSkillAdapter",
    "M4SceneAdapter",
    "M5MemoryAdapter",
    "M7BlockAdapter",
    "M8ControlAdapter",
    "M10MetricsAdapter",
    "M12SecurityAdapter",
]
