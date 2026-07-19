"""
M8 管理工作台 - 数据库模型（兼容层）

本文件已拆分为 models/ 包（按领域分子模块）。
为保持向后兼容，本文件从 models 包中重新导出所有内容。

新代码建议直接从子模块导入，例如：
    from backend.models.user import User
    from backend.models.compute import ComputeSource
    from backend.models.base import Base, engine, SessionLocal
"""

# 从 models 包中重新导出所有公开符号
from backend.models.base import Base, engine, SessionLocal, SQLALCHEMY_DATABASE_URL, init_db, get_db  # noqa: F401
from backend.models.user import User, ModuleRecord, TaskRecord, AlertRecord  # noqa: F401
from backend.models.audit import AuditLog  # noqa: F401
from backend.models.compute import (  # noqa: F401
    ComputeSource, ComputeKeyGroup, ComputeModelBinding, ComputeRoutingPolicy,
    ComputeCallLog, ComputeAlert, ComputeQuota, ComputeSkillBinding, ComputeConfigBackup,
)
from backend.models.workflow import WorkflowDefinition, WorkflowRun, SystemSetting  # noqa: F401
from backend.models.growth import (  # noqa: F401
    GrowthAchievement, GrowthTalent, GrowthTalentMeta,
    GrowthSeason, GrowthSeasonTask, GrowthMemory, GrowthChronicle, GrowthCalendar,
)
from backend.models.work_dev import WorkProject, WorkTask, WorkCommit, WorkCodeUsage  # noqa: F401
from backend.models.review import ReviewReview, ReviewDiary, ReviewDecision, ReviewEmotion, ReviewBias  # noqa: F401
from backend.models.study import (  # noqa: F401
    StudyGoal, StudyPlan, StudyNote, StudyKnowledgeCategory,
    StudyExam, StudyProgress, StudyMeta,
)
from backend.models.life import (  # noqa: F401
    LifeSchedule, LifeRule, LifeTodo, LifeHabit, LifeScene,
    LifeFinanceCategory, LifeMeta, LifeHabitRecord, LifeFinanceRecord,
)
from backend.models.appearance import (  # noqa: F401
    AppearanceConfig, MoodHistory, AppearanceSnapshot, PersonalityTag, VoiceOption,
)
from backend.models.emotion import (  # noqa: F401
    EmotionRecord, RelaxContent, RelaxSession, SleepContent, SleepRecord,
    PsychAssessment, AssessmentResult, MoodDiary,
)
from backend.models.watch import WatchDevice, WatchHealthData, WatchNotification, WatchSetting  # noqa: F401
from backend.models.evolution import (  # noqa: F401
    EvoHealthScan, EvoPlan, EvoCandidate, EvoApproval, EvoVersion,
    EvoRollbackRecord, EvoDeployment, EvoAuditReport,
)
from backend.models.social import SocialContact, SocialInteraction, SocialReminder, SocialEQLesson  # noqa: F401
from backend.models.inspection import StartupCheckRecord, PrincipalChatSession, PrincipalChatMessage  # noqa: F401
