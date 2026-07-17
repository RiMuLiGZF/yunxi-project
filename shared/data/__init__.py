"""
云汐共享数据层 (shared.data)
==============================

数据基础设施层，提供数据访问、缓存、数据治理等能力。

子模块：
- cache: 内存缓存（TTL + LRU）
- data_layer: 数据访问层（数据库管理 / 备份 / 迁移）
- data_governance: 数据治理（数据主权 / 去重规划）
"""

from .cache import (
    SimpleCache,
    CacheStats,
    get_cache_from_env,
    get_path_ttl,
    DEFAULT_PATH_TTL_MAP,
)

from .data_layer import (
    DatabaseManager,
    get_db_manager,
    BackupManager,
    get_backup_manager,
    MigrationEngine,
    get_migration_engine,
    # 增强型迁移引擎
    EnhancedMigrationEngine,
    TableIntegrityInfo,
    MigrationIntegrityReport,
    OperationalError,
    MigrationValidationError,
    # PostgreSQL 适配器
    PostgreSQLMigrationAdapter,
    # 迁移工具
    MigrationStats,
    TableMigrationStats,
    MigrationCheckpoint,
    ProgressTracker,
    format_duration,
    retry_with_backoff,
    RetryableError,
    CheckpointManager,
    row_to_dict,
    safe_str,
    parse_datetime,
    safe_json_loads,
    IdempotencyChecker,
    BaseDataMigrator,
)

from .data_governance import (
    load_sovereignty,
    get_module_sovereignty,
    check_data_owner,
    list_overlapping_domains,
    get_deduplication_progress,
    # 数据分类分级
    get_classification_rules,
    get_table_metadata,
    list_tables_by_category,
    list_tables_by_sensitivity,
    get_retention_policy,
    get_classification_summary,
    get_highest_risk_tables,
    get_encrypted_tables,
)

__version__ = "1.0.0"
"""shared.data 版本号"""

__all__ = [
    "__version__",
    # Cache
    "SimpleCache", "CacheStats", "get_cache_from_env", "get_path_ttl",
    "DEFAULT_PATH_TTL_MAP",
    # Data Layer - Database
    "DatabaseManager", "get_db_manager",
    # Data Layer - Backup
    "BackupManager", "get_backup_manager",
    # Data Layer - Migration
    "MigrationEngine", "get_migration_engine",
    # Data Layer - Enhanced Migration
    "EnhancedMigrationEngine", "TableIntegrityInfo", "MigrationIntegrityReport",
    "OperationalError", "MigrationValidationError",
    # Data Layer - PostgreSQL Adapter
    "PostgreSQLMigrationAdapter",
    # Data Layer - Tools
    "MigrationStats", "TableMigrationStats", "MigrationCheckpoint",
    "ProgressTracker", "format_duration", "retry_with_backoff",
    "RetryableError", "CheckpointManager", "row_to_dict", "safe_str",
    "parse_datetime", "safe_json_loads", "IdempotencyChecker", "BaseDataMigrator",
    # Data Governance
    "load_sovereignty", "get_module_sovereignty", "check_data_owner",
    "list_overlapping_domains", "get_deduplication_progress",
    # Data Governance - Classification
    "get_classification_rules", "get_table_metadata", "list_tables_by_category",
    "list_tables_by_sensitivity", "get_retention_policy",
    "get_classification_summary", "get_highest_risk_tables", "get_encrypted_tables",
]
