"""
云汐统一数据访问层
"""
from .database_manager import DatabaseManager, get_db_manager
from .backup_manager import (
    BackupManager,
    get_backup_manager,
    BackupOrchestrator,
    get_backup_orchestrator,
    ModuleBackupConfig,
    BackupReport,
    VerifyReport,
    BackupType,
    CompressionType,
    EncryptionType,
    RetentionPolicy,
)
from .module_backup_registry import (
    get_module_config,
    get_all_module_configs,
    register_modules_with_orchestrator,
    get_modules_with_db,
    get_module_backup_summary,
)
from .migration import MigrationEngine, get_migration_engine
from .migration_enhanced import (
    EnhancedMigrationEngine,
    TableIntegrityInfo,
    MigrationIntegrityReport,
    OperationalError,
    MigrationValidationError,
)
from .postgres_adapter import PostgreSQLMigrationAdapter
from .migration_tools import (
    # 数据类
    MigrationStats,
    TableMigrationStats,
    MigrationCheckpoint,
    # 进度追踪
    ProgressTracker,
    format_duration,
    # 重试机制
    retry_with_backoff,
    RetryableError,
    # 断点续传
    CheckpointManager,
    # 数据转换工具
    row_to_dict,
    safe_str,
    parse_datetime,
    safe_json_loads,
    # 幂等性检查
    IdempotencyChecker,
    # 迁移执行器基类
    BaseDataMigrator,
)

__all__ = [
    # 数据库管理器
    "DatabaseManager",
    "get_db_manager",
    # 备份管理器
    "BackupManager",
    "get_backup_manager",
    "BackupOrchestrator",
    "get_backup_orchestrator",
    "ModuleBackupConfig",
    "BackupReport",
    "VerifyReport",
    "BackupType",
    "CompressionType",
    "EncryptionType",
    "RetentionPolicy",
    # 模块备份注册表
    "get_module_config",
    "get_all_module_configs",
    "register_modules_with_orchestrator",
    "get_modules_with_db",
    "get_module_backup_summary",
    # 迁移引擎
    "MigrationEngine",
    "get_migration_engine",
    "EnhancedMigrationEngine",
    "TableIntegrityInfo",
    "MigrationIntegrityReport",
    "OperationalError",
    "MigrationValidationError",
    "PostgreSQLMigrationAdapter",
    # 迁移工具 - 数据类
    "MigrationStats",
    "TableMigrationStats",
    "MigrationCheckpoint",
    # 迁移工具 - 进度追踪
    "ProgressTracker",
    "format_duration",
    # 迁移工具 - 重试机制
    "retry_with_backoff",
    "RetryableError",
    # 迁移工具 - 断点续传
    "CheckpointManager",
    # 迁移工具 - 数据转换
    "row_to_dict",
    "safe_str",
    "parse_datetime",
    "safe_json_loads",
    # 迁移工具 - 幂等性检查
    "IdempotencyChecker",
    # 迁移工具 - 执行器基类
    "BaseDataMigrator",
    # 统一迁移 CLI
    "migrate_cli",
]
