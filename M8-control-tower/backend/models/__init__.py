"""
M8 管理工作台 - 数据库模型统一导出

本模块从各子模块 re-export 所有模型和数据库工具，
确保 ``from backend.models import XXX`` 和 ``from backend.models.models import XXX``
两种导入路径均继续可用（向后兼容）。
"""

# 基类与数据库工具
from .base import Base, engine, SessionLocal, SQLALCHEMY_DATABASE_URL, init_db, get_db  # noqa: F401

# 用户与模块
from .user import User, ModuleRecord, TaskRecord, AlertRecord  # noqa: F401

# 审计日志
from .audit import AuditLog  # noqa: F401

# 算力调度
from .compute import (  # noqa: F401
    ComputeSource,
    ComputeKeyGroup,
    ComputeModelBinding,
    ComputeRoutingPolicy,
    ComputeCallLog,
    ComputeAlert,
    ComputeQuota,
    ComputeSkillBinding,
    ComputeConfigBackup,
)

# 工作流与系统设置
from .workflow import WorkflowDefinition, WorkflowRun, SystemSetting  # noqa: F401

# 成长中心
from .growth import (  # noqa: F401
    GrowthAchievement,
    GrowthTalent,
    GrowthTalentMeta,
    GrowthSeason,
    GrowthSeasonTask,
    GrowthMemory,
    GrowthChronicle,
    GrowthCalendar,
)

# 工作开发
from .work_dev import WorkProject, WorkTask, WorkCommit, WorkCodeUsage  # noqa: F401

# 复盘总结
from .review import ReviewReview, ReviewDiary, ReviewDecision, ReviewEmotion, ReviewBias  # noqa: F401

# 学业规划
from .study import (  # noqa: F401
    StudyGoal,
    StudyPlan,
    StudyNote,
    StudyKnowledgeCategory,
    StudyExam,
    StudyProgress,
    StudyMeta,
)

# 生活管理
from .life import (  # noqa: F401
    LifeSchedule,
    LifeRule,
    LifeTodo,
    LifeHabit,
    LifeScene,
    LifeFinanceCategory,
    LifeMeta,
    LifeHabitRecord,
    LifeFinanceRecord,
)

# 形象工坊
from .appearance import (  # noqa: F401
    AppearanceConfig,
    MoodHistory,
    AppearanceSnapshot,
    PersonalityTag,
    VoiceOption,
)

# 情绪陪伴
from .emotion import (  # noqa: F401
    EmotionRecord,
    RelaxContent,
    RelaxSession,
    SleepContent,
    SleepRecord,
    PsychAssessment,
    AssessmentResult,
    MoodDiary,
)

# 手表交互
from .watch import WatchDevice, WatchHealthData, WatchNotification, WatchSetting  # noqa: F401

# 自进化引擎
from .evolution import (  # noqa: F401
    EvoHealthScan,
    EvoPlan,
    EvoCandidate,
    EvoApproval,
    EvoVersion,
    EvoRollbackRecord,
    EvoDeployment,
    EvoAuditReport,
)

# 人际关系
from .social import SocialContact, SocialInteraction, SocialReminder, SocialEQLesson  # noqa: F401

# 巡检Agent
from .inspection import StartupCheckRecord, PrincipalChatSession, PrincipalChatMessage  # noqa: F401

# 备份调度中心
from .backup_scheduler import BackupModule, BackupHistory  # noqa: F401

# 配置中心（M8 Config Center）
from .config_center import (  # noqa: F401
    ConfigItem,
    ConfigVersion,
    ConfigAuditLog,
    ConfigSchema,
)

__all__ = [
    # 基类与工具
    "Base", "engine", "SessionLocal", "SQLALCHEMY_DATABASE_URL", "init_db", "get_db",
    # 用户与模块
    "User", "ModuleRecord", "TaskRecord", "AlertRecord",
    # 审计
    "AuditLog",
    # 算力调度
    "ComputeSource", "ComputeKeyGroup", "ComputeModelBinding", "ComputeRoutingPolicy",
    "ComputeCallLog", "ComputeAlert", "ComputeQuota", "ComputeSkillBinding", "ComputeConfigBackup",
    # 工作流与系统设置
    "SystemSetting", "WorkflowDefinition", "WorkflowRun",
    # 成长中心
    "GrowthAchievement", "GrowthTalent", "GrowthTalentMeta",
    "GrowthSeason", "GrowthSeasonTask", "GrowthMemory", "GrowthChronicle", "GrowthCalendar",
    # 工作开发
    "WorkProject", "WorkTask", "WorkCommit", "WorkCodeUsage",
    # 复盘总结
    "ReviewReview", "ReviewDiary", "ReviewDecision", "ReviewEmotion", "ReviewBias",
    # 学业规划
    "StudyGoal", "StudyPlan", "StudyNote", "StudyKnowledgeCategory",
    "StudyExam", "StudyProgress", "StudyMeta",
    # 生活管理
    "LifeSchedule", "LifeRule", "LifeTodo", "LifeHabit", "LifeScene",
    "LifeFinanceCategory", "LifeMeta", "LifeHabitRecord", "LifeFinanceRecord",
    # 形象工坊
    "AppearanceConfig", "MoodHistory", "AppearanceSnapshot", "PersonalityTag", "VoiceOption",
    # 情绪陪伴
    "EmotionRecord", "RelaxContent", "RelaxSession", "SleepContent", "SleepRecord",
    "PsychAssessment", "AssessmentResult", "MoodDiary",
    # 手表交互
    "WatchDevice", "WatchHealthData", "WatchNotification", "WatchSetting",
    # 自进化引擎
    "EvoHealthScan", "EvoPlan", "EvoCandidate", "EvoApproval", "EvoVersion",
    "EvoRollbackRecord", "EvoDeployment", "EvoAuditReport",
    # 人际关系
    "SocialContact", "SocialInteraction", "SocialReminder", "SocialEQLesson",
    # 巡检Agent
    "StartupCheckRecord", "PrincipalChatSession", "PrincipalChatMessage",
    # 备份调度中心
    "BackupModule", "BackupHistory",
    # 配置中心
    "ConfigItem", "ConfigVersion", "ConfigAuditLog", "ConfigSchema",
]
