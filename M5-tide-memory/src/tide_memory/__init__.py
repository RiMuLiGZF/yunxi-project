"""
M5 潮汐分层记忆系统 v2.4-REV2

⚠️ 高涉密模块 - 所有用户记忆数据本地加密存储，绝不上传云端

四层潮汐模型：
- L0 沙滩层 - 瞬时记忆（分钟~小时级）
- L1 浅水层 - 短期记忆（小时~天级）
- L2 深水层 - 中期记忆（天~月级）
- L3 深海层 - 长期记忆（永久，AES-256加密）

核心特性：
- 三级域权限隔离
- 四级密级标记
- EI情绪推断
- 睡眠记忆巩固
- 审计日志系统
- M8标准接口
"""

__version__ = "2.4.0-REV2"
__author__ = "M5 Tide Memory Team"
__classification__ = "TOP_SECRET"
__local_only__ = True

from .core.config import TideConfig
from .core.models import MemoryItem, MemoryLayer, MemoryDomain, ClassificationLevel

__all__ = [
    "TideConfig",
    "MemoryItem",
    "MemoryLayer",
    "MemoryDomain",
    "ClassificationLevel",
    "__version__",
]
