"""
M8 管理工作台 - 情绪陪伴模型

包含 EmotionRecord, RelaxContent, RelaxSession, SleepContent, SleepRecord,
PsychAssessment, AssessmentResult, MoodDiary。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class EmotionRecord(Base):
    """情绪陪伴 - 情绪记录表"""
    __tablename__ = "emotion_records"

    id = Column(Integer, primary_key=True, index=True)
    emotion_type = Column(String(50), default="neutral", comment="情绪类型")
    intensity = Column(Integer, default=5, comment="情绪强度 1-10")
    trigger = Column(String(500), default="", comment="触发因素")
    note = Column(Text, default="", comment="备注")
    date = Column(String(20), index=True, comment="日期 YYYY-MM-DD")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="记录时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "emotion": self.emotion_type,
            "level": self.intensity,
            "trigger": self.trigger,
            "note": self.note,
            "date": self.date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RelaxContent(Base):
    """情绪陪伴 - 放松内容库"""
    __tablename__ = "relax_contents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), comment="标题")
    category = Column(String(50), index=True, comment="分类")
    content_type = Column(String(20), default="guide", comment="内容类型")
    content_url = Column(String(500), default="", comment="内容URL")
    content_text = Column(Text, default="", comment="文本内容")
    duration_seconds = Column(Integer, default=300, comment="时长秒")
    difficulty = Column(String(20), default="easy", comment="难度")
    description = Column(String(500), default="", comment="描述")
    steps = Column(JSON, default=list, comment="步骤列表")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        minutes = self.duration_seconds // 60
        return {
            "id": self.id,
            "title": self.title,
            "duration": f"{minutes}分钟",
            "type": self.category,
            "description": self.description,
            "steps": self.steps or [],
        }


class RelaxSession(Base):
    """情绪陪伴 - 放松训练记录"""
    __tablename__ = "relax_sessions"

    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, index=True, comment="放松内容ID")
    duration_seconds = Column(Integer, default=0, comment="实际训练时长秒")
    completed = Column(Boolean, default=False, comment="是否完成")
    rating = Column(Integer, default=0, comment="评分 1-5")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class SleepContent(Base):
    """情绪陪伴 - 助眠内容库"""
    __tablename__ = "sleep_contents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), comment="标题")
    category = Column(String(50), index=True, comment="分类")
    content_type = Column(String(20), default="audio", comment="内容类型")
    content_url = Column(String(500), default="", comment="内容URL")
    duration_seconds = Column(Integer, default=1800, comment="时长秒")
    description = Column(String(500), default="", comment="描述")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        minutes = self.duration_seconds // 60
        return {
            "id": self.id,
            "title": self.title,
            "duration": f"{minutes}分钟",
            "type": self.category,
            "description": self.description,
        }


class SleepRecord(Base):
    """情绪陪伴 - 睡眠记录"""
    __tablename__ = "sleep_records"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(20), index=True, comment="日期 YYYY-MM-DD")
    sleep_duration = Column(Float, default=0, comment="睡眠时长小时")
    sleep_quality = Column(Integer, default=5, comment="睡眠质量 1-10")
    sleep_score = Column(Integer, default=70, comment="睡眠评分 0-100")
    bed_time = Column(String(20), default="", comment="入睡时间")
    wake_time = Column(String(20), default="", comment="起床时间")
    note = Column(Text, default="", comment="备注")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


class PsychAssessment(Base):
    """情绪陪伴 - 心理测评"""
    __tablename__ = "psych_assessments"

    id = Column(Integer, primary_key=True, index=True)
    assessment_type = Column(String(50), index=True, comment="测评类型")
    title = Column(String(200), comment="标题")
    description = Column(String(500), default="", comment="描述")
    questions_json = Column(JSON, default=list, comment="题目列表JSON")
    questions_count = Column(Integer, default=0, comment="题目数量")
    duration_minutes = Column(Integer, default=5, comment="预计时长分钟")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_simple_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.assessment_type,
            "questions_count": self.questions_count,
            "duration": f"{self.duration_minutes}分钟",
        }

    def to_full_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.assessment_type,
            "questions_count": self.questions_count,
            "duration": f"{self.duration_minutes}分钟",
            "questions": self.questions_json or [],
        }


class AssessmentResult(Base):
    """情绪陪伴 - 测评结果"""
    __tablename__ = "assessment_results"

    id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, index=True, comment="测评ID")
    title = Column(String(200), default="", comment="测评标题")
    score = Column(Integer, default=0, comment="得分")
    result_text = Column(String(200), default="", comment="结果描述")
    level = Column(String(20), default="normal", comment="等级")
    answers_json = Column(JSON, default=dict, comment="答题记录JSON")
    suggestion = Column(Text, default="", comment="建议")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    date = Column(String(20), comment="测评日期")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "assessment_id": self.assessment_id,
            "title": self.title,
            "result": self.result_text,
            "score": self.score,
            "level": self.level,
            "date": self.date,
            "suggestion": self.suggestion,
        }


class MoodDiary(Base):
    """情绪陪伴 - 心情日记"""
    __tablename__ = "mood_diary"

    id = Column(Integer, primary_key=True, index=True)
    mood = Column(String(50), default="neutral", comment="心情")
    content = Column(Text, default="", comment="日记内容")
    tags = Column(JSON, default=list, comment="标签列表")
    date = Column(String(20), index=True, comment="日期 YYYY-MM-DD")
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "emotion": self.mood,
            "content": self.content,
            "date": self.date,
            "tags": self.tags or [],
        }
