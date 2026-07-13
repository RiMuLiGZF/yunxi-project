"""M4 场景引擎 - 数据库兼容层.

为保持向后兼容，本文件从 models.db 重新导出所有 ORM 模型和数据库函数。
新代码请直接从 models.db 导入：
    from src.models.db import SceneContextDB, get_session
"""

from __future__ import annotations

from src.models.db import (  # noqa: F401
    # 基础
    Base,
    get_db_path,
    init_db,
    get_session,
    get_engine,
    # 场景引擎核心
    SceneContextDB,
    SceneSwitchHistoryDB,
    SceneConfigDB,
    CurrentSceneDB,
    GlobalConfigDB,
    # 形象工坊
    AppearanceConfigDB,
    MoodHistoryDB,
    AppearanceSnapshotDB,
    PersonalityTagDB,
    VoiceOptionDB,
    # 情绪陪伴
    EmotionRecordDB,
    RelaxContentDB,
    RelaxSessionDB,
    SleepContentDB,
    SleepRecordDB,
    PsychAssessmentDB,
    AssessmentResultDB,
    MoodDiaryDB,
    # 人际关系
    SocialContactDB,
    SocialInteractionDB,
    SocialReminderDB,
    SocialEqLessonDB,
    # 复盘总结
    ReviewReviewDB,
    ReviewDiaryDB,
    ReviewDecisionDB,
    ReviewEmotionDB,
    ReviewBiasDB,
    # 生活管理
    LifeScheduleDB,
    LifeTodoDB,
    LifeHabitDB,
    LifeHabitRecordDB,
    LifeSceneDB,
    LifeRuleDB,
    LifeFinanceCategoryDB,
    LifeFinanceRecordDB,
    LifeMetaDB,
    # 学业规划
    StudyGoalDB,
    StudyPlanDB,
    StudyNoteDB,
    StudyKnowledgeCategoryDB,
    StudyExamDB,
    StudyProgressDB,
    StudyMetaDB,
    # 工作开发
    WorkProjectDB,
    WorkTaskDB,
    WorkCommitDB,
    WorkCodeSnippetDB,
    WorkDevSessionDB,
    WorkCodeUsageDB,
    # 聊天服务
    ChatConversationDB,
    ChatMessageDB,
    # 语音服务
    VoiceConfigDB,
    VoiceHistoryDB,
    # 手表交互
    WatchDeviceDB,
    WatchHealthDataDB,
    WatchNotificationDB,
)
