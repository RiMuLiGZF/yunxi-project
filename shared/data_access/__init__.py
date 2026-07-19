"""
云汐统一数据访问层（Unified Data Access Layer）
=============================================

打通各模块数据孤岛，提供统一的数据访问接口。

核心能力：
- BaseRepository: 统一 CRUD 接口
- UnitOfWork: 工作单元模式
- SQLAlchemy Repository: SQLAlchemy 2.0 标准实现（推荐使用）
- 多存储后端: SQLite / JSON / Memory
- 数据迁移框架: 版本化迁移、升级/回滚
- 模型注册中心: 跨模块模型管理
- 数据同步引擎: 增量/全量同步、冲突解决
- 数据聚合服务: 跨模块查询、联表、聚合
- 数据质量框架: 完整性/一致性/准确性检查
- Mixins: 软删除、时间戳、版本号、审计字段
- 连接管理: 统一配置、健康检查、重试机制

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
from .mixins import (
    SoftDeleteMixin,
    TimestampMixin,
    SoftDeleteModelMixin,
    VersionMixin,
    AuditMixin,
)
from .connection import (
    DatabaseConfig,
    DatabaseManager,
    DatabaseType,
    retry_on_db_error,
    create_sqlite_manager,
    create_memory_manager,
)
from .sqlalchemy_repo import (
    SQLAlchemyRepository,
    SQLAlchemyUnitOfWork,
)
from .sqlalchemy_migration import (
    SQLAlchemyMigrationHistoryStore,
    ModuleMigrationManager,
)

__all__ = [
    # 基础抽象
    "BaseModel",
    "BaseRepository",
    "UnitOfWork",
    "QueryBuilder",
    "QueryFilter",
    "PaginationResult",
    # SQLAlchemy 实现（推荐）
    "SQLAlchemyRepository",
    "SQLAlchemyUnitOfWork",
    # SQLAlchemy 迁移
    "SQLAlchemyMigrationHistoryStore",
    "ModuleMigrationManager",
    # Mixins
    "SoftDeleteMixin",
    "TimestampMixin",
    "SoftDeleteModelMixin",
    "VersionMixin",
    "AuditMixin",
    # 连接管理
    "DatabaseConfig",
    "DatabaseManager",
    "DatabaseType",
    "retry_on_db_error",
    "create_sqlite_manager",
    "create_memory_manager",
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
