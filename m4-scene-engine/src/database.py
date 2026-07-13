"""M4 场景引擎 - 数据库兼容层（已弃用，保留向后兼容）.

.. deprecated:: 2.0.0
    本模块已迁移至 ``src.models.db``，所有新代码请直接从新位置导入：

    .. code-block:: python

        from src.models.db import SceneContextDB, get_session

为保持向后兼容，本文件从 ``src.models.db`` 重新导出所有 ORM 模型和数据库函数。
项目内全部业务代码导入已迁移至新路径，本文件仅作为兼容层保留。

.. warning::
    本兼容层将在未来版本中移除，请尽快迁移至 ``src.models.db``。
"""

from __future__ import annotations

import warnings

# 发出弃用警告，提醒开发者迁移至新路径
warnings.warn(
    "src.database 已弃用，请使用 src.models.db 替代。"
    "兼容层将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

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
