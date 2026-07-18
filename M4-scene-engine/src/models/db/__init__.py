"""数据库模型包.

按模块拆分的 ORM 模型定义，所有模型均继承自 .base.Base。
"""

from .base import Base, get_db_path, init_db, get_session, get_engine
from .migration import DatabaseMigrator, Migration
from .migrations import MIGRATIONS


def get_migrator(db_path: str | None = None) -> DatabaseMigrator:
    """获取已注册所有迁移的数据库迁移器.

    Args:
        db_path: 数据库路径，为空则使用默认路径.

    Returns:
        已注册所有迁移的 DatabaseMigrator 实例.
    """
    if db_path is None:
        db_path = get_db_path()
    return DatabaseMigrator(db_path, MIGRATIONS)

# 场景引擎核心表
from .scene import (
    SceneContextDB,
    SceneSwitchHistoryDB,
    SceneConfigDB,
    CurrentSceneDB,
    GlobalConfigDB,
)

# 形象工坊表
from .appearance import (
    AppearanceConfigDB,
    MoodHistoryDB,
    AppearanceSnapshotDB,
    PersonalityTagDB,
    VoiceOptionDB,
)

# 情绪陪伴表
from .emotion import (
    EmotionRecordDB,
    RelaxContentDB,
    RelaxSessionDB,
    SleepContentDB,
    SleepRecordDB,
    PsychAssessmentDB,
    AssessmentResultDB,
    MoodDiaryDB,
)

# 人际关系表
from .social import (
    SocialContactDB,
    SocialInteractionDB,
    SocialReminderDB,
    SocialEqLessonDB,
)

# 复盘总结表
from .review import (
    ReviewReviewDB,
    ReviewDiaryDB,
    ReviewDecisionDB,
    ReviewEmotionDB,
    ReviewBiasDB,
)

# 生活管理表
from .life import (
    LifeScheduleDB,
    LifeTodoDB,
    LifeHabitDB,
    LifeHabitRecordDB,
    LifeSceneDB,
    LifeRuleDB,
    LifeFinanceCategoryDB,
    LifeFinanceRecordDB,
    LifeMetaDB,
)

# 学业规划表
from .study import (
    StudyGoalDB,
    StudyPlanDB,
    StudyNoteDB,
    StudyKnowledgeCategoryDB,
    StudyExamDB,
    StudyProgressDB,
    StudyMetaDB,
)

# 工作开发表
from .work import (
    WorkProjectDB,
    WorkTaskDB,
    WorkCommitDB,
    WorkCodeSnippetDB,
    WorkDevSessionDB,
    WorkCodeUsageDB,
)

# 聊天服务表
from .chat import (
    ChatConversationDB,
    ChatMessageDB,
)

# 语音服务表
from .voice import (
    VoiceConfigDB,
    VoiceHistoryDB,
)

# 手表交互表
from .watch import (
    WatchDeviceDB,
    WatchHealthDataDB,
    WatchNotificationDB,
)

__all__ = [
    # base
    "Base",
    "get_db_path",
    "init_db",
    "get_session",
    "get_engine",
    # migration
    "DatabaseMigrator",
    "Migration",
    # scene
    "SceneContextDB",
    "SceneSwitchHistoryDB",
    "SceneConfigDB",
    "CurrentSceneDB",
    "GlobalConfigDB",
    # appearance
    "AppearanceConfigDB",
    "MoodHistoryDB",
    "AppearanceSnapshotDB",
    "PersonalityTagDB",
    "VoiceOptionDB",
    # emotion
    "EmotionRecordDB",
    "RelaxContentDB",
    "RelaxSessionDB",
    "SleepContentDB",
    "SleepRecordDB",
    "PsychAssessmentDB",
    "AssessmentResultDB",
    "MoodDiaryDB",
    # social
    "SocialContactDB",
    "SocialInteractionDB",
    "SocialReminderDB",
    "SocialEqLessonDB",
    # review
    "ReviewReviewDB",
    "ReviewDiaryDB",
    "ReviewDecisionDB",
    "ReviewEmotionDB",
    "ReviewBiasDB",
    # life
    "LifeScheduleDB",
    "LifeTodoDB",
    "LifeHabitDB",
    "LifeHabitRecordDB",
    "LifeSceneDB",
    "LifeRuleDB",
    "LifeFinanceCategoryDB",
    "LifeFinanceRecordDB",
    "LifeMetaDB",
    # study
    "StudyGoalDB",
    "StudyPlanDB",
    "StudyNoteDB",
    "StudyKnowledgeCategoryDB",
    "StudyExamDB",
    "StudyProgressDB",
    "StudyMetaDB",
    # work
    "WorkProjectDB",
    "WorkTaskDB",
    "WorkCommitDB",
    "WorkCodeSnippetDB",
    "WorkDevSessionDB",
    "WorkCodeUsageDB",
    # chat
    "ChatConversationDB",
    "ChatMessageDB",
    # voice
    "VoiceConfigDB",
    "VoiceHistoryDB",
    # watch
    "WatchDeviceDB",
    "WatchHealthDataDB",
    "WatchNotificationDB",
]
