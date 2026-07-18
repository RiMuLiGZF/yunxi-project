"""
云汐统一数据访问层（Unified Data Access Layer）
=============================================

打通各模块数据孤岛，提供统一的数据访问接口。

核心能力：
- BaseRepository: 统一 CRUD 接口
- UnitOfWork: 工作单元模式
- 多存储后端: SQLite / JSON / Memory
- 数据迁移框架: 版本化迁移、升级/回滚
- 模型注册中心: 跨模块模型管理
- 数据同步引擎: 增量/全量同步、冲突解决
- 数据聚合服务: 跨模块查询、联表、聚合
- 数据质量框架: 完整性/一致性/准确性检查

设计原则：
- 纯增量：各模块原有数据访问方式不变，可逐步迁移
- 后端无关：业务代码不依赖具体存储实现
- 向后兼容：所有新增能力不破坏现有代码
"""

from .base import (
    BaseModel,
    BaseRepository,
    UnitOfWork,
    QueryBuilder,
    QueryFilter,
    PaginationResult,
)
from .registry import ModelRegistry, get_model_registry, ModelInfo, RelationInfo
from .migration import (
    MigrationManager,
    Migration,
    MigrationContext,
    get_migration_manager,
)

__all__ = [
    # 基础抽象
    "BaseModel",
    "BaseRepository",
    "UnitOfWork",
    "QueryBuilder",
    "QueryFilter",
    "PaginationResult",
    # 模型注册
    "ModelRegistry",
    "get_model_registry",
    "ModelInfo",
    "RelationInfo",
    # 迁移
    "MigrationManager",
    "Migration",
    "MigrationContext",
    "get_migration_manager",
]
