"""
M5 记忆共享功能包

提供记忆的脱敏导出、共享池管理、导入与评分能力。

组件：
- MemoryExporter: 记忆导出器，将本地记忆元数据脱敏打包为共享包
- MemoryImporter: 记忆导入器，将共享包写入本地 shared 域
- SharePoolManager: 共享池管理器（SQLite 持久化，单例）
- share_router: FastAPI 路由，挂载在 /api/v1/memory/share 下
"""

from .exporter import MemoryExporter
from .importer import MemoryImporter
from .share_pool import SharePoolManager
from .router import share_router, configure_share_router

__all__ = [
    "MemoryExporter",
    "MemoryImporter",
    "SharePoolManager",
    "share_router",
    "configure_share_router",
]
# vim: set et ts=4 sw=4:
