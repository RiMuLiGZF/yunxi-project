"""云汐内核 - Skills技能集群系统版本信息.

【第六轮优化】统一版本标识，6轮迭代变更追踪。
"""

# 版本号：Major.Minor.Patch (语义化版本)
# Major: 架构重大变更
# Minor: 新增功能/模块
# Patch: Bug修复/小优化
__version__ = "1.0.0"


def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        # 查找项目根目录并加入 sys.path
        from pathlib import Path
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()
__version_info__ = (3, 10, 2)

# 迭代轮次标识
ITERATION_ROUND = 12

# 构建元数据
BUILD_DATE = "2026-07-04"
BUILD_LABEL = "R12-m8-integration"
