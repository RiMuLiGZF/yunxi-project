"""
M5 潮汐分层记忆系统

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

__author__ = "M5 Tide Memory Team"
__classification__ = "TOP_SECRET"
__local_only__ = True


def _load_version() -> str:
    """
    加载版本号

    优先级：
    1. shared.version.SYSTEM_VERSION（从项目共享模块导入）
    2. version.txt 文件（项目根目录）
    3. 内置默认值
    """
    # 1. 尝试从 shared.version 导入
    try:
        from pathlib import Path
        current = Path(__file__).resolve()
        for _ in range(10):
            current = current.parent
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                from shared.version import SYSTEM_VERSION
                return SYSTEM_VERSION
    except Exception:
        pass

    # 2. 尝试从 version.txt 读取
    try:
        from pathlib import Path
        version_file = Path(__file__).resolve().parent.parent.parent / "version.txt"
        if version_file.exists():
            return version_file.read_text().strip()
    except Exception:
        pass

    # 3. 内置默认值
    return "2.4.0-REV2"


__version__ = _load_version()

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
# vim: set et ts=4 sw=4:
