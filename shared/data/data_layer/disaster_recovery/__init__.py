"""
云汐数据容灾模块 (Disaster Recovery)

提供生产级数据容灾能力：
- 备份增强：全量/增量/定时/验证/异地
- 数据恢复：全量恢复/时间点恢复/恢复验证/进度跟踪
- 数据库高可用：WAL优化/连接池/故障检测与恢复

使用方式：
    from data_layer.disaster_recovery import (
        EnhancedBackupManager,
        RecoveryManager,
        DatabaseHA,
        BackupScheduler,
    )
"""

from .enhanced_backup import (
    EnhancedBackupManager,
    BackupMode,
    BackupSchedule,
    BackupValidationResult,
    RemoteBackupConfig,
    ValidationLevel,
)
from .recovery_manager import (
    RecoveryManager,
    RecoveryMode,
    RecoveryProgress,
    RecoveryResult,
    PointInTimeRecovery,
)
from .database_ha import (
    DatabaseHA,
    WALConfig,
    ConnectionPoolConfig,
    DBHealthStatus,
)
from .backup_scheduler import (
    BackupScheduler,
    ScheduledBackupTask,
    ScheduleType,
)

__all__ = [
    # 增强备份
    "EnhancedBackupManager",
    "BackupMode",
    "BackupSchedule",
    "BackupValidationResult",
    "RemoteBackupConfig",
    "ValidationLevel",
    # 数据恢复
    "RecoveryManager",
    "RecoveryMode",
    "RecoveryProgress",
    "RecoveryResult",
    "PointInTimeRecovery",
    # 数据库高可用
    "DatabaseHA",
    "WALConfig",
    "ConnectionPoolConfig",
    "DBHealthStatus",
    # 备份调度
    "BackupScheduler",
    "ScheduledBackupTask",
    "ScheduleType",
]
