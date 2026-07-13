from __future__ import annotations

"""统一数据库 Repository 层.

为 M2 技能集群提供统一的 SQLite 数据库访问封装，包括：
- 连接管理与 WAL 模式
- 自动重试（database is locked 指数退避）
- 事务上下文管理器
- SQL 注入防护（全部参数化查询）
- 健康检查与损坏恢复
- 优雅关闭（PRAGMA optimize）
- 技能级 Repository 基类（用于 12 个独立 DB 的技能）
"""

from skill_cluster.db.base import (
    BaseRepository,
    DatabaseCorruptedError,
    SQLiteDatabase,
    transaction,
)
from skill_cluster.db.pipeline_repository import PipelineRepository
from skill_cluster.db.cache_repository import CacheRepository
from skill_cluster.db.skill_repository_base import (
    SkillBaseRepository,
    create_skill_repo,
)

__all__ = [
    "BaseRepository",
    "CacheRepository",
    "DatabaseCorruptedError",
    "PipelineRepository",
    "SQLiteDatabase",
    "SkillBaseRepository",
    "create_skill_repo",
    "transaction",
]
