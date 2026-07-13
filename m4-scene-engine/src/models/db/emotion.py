"""情绪陪伴表模块.

包含情绪记录、放松内容、放松训练、助眠内容、睡眠记录、心理测评、测评结果、心情日记等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)

from .base import Base


class EmotionRecordDB(Base):
    """情绪陪伴 - 情绪记录表."""

    __tablename__ = "emotion_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    emotion_type = Column(String(50), default="neutral")
    intensity = Column(Integer, default=5)
    trigger = Column(String(500), default="")
    note = Column(Text, default="")
    date = Column(String(20), index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "emotion": self.emotion_type,
            "level": self.intensity,
            "trigger": self.trigger,
            "note": self.note,
            "date": self.date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RelaxContentDB(Base):
    """情绪陪伴 - 放松内容库表."""

    __tablename__ = "relax_contents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200))
    category = Column(String(50), index=True)
    content_type = Column(String(20), default="guide")
    content_url = Column(String(500), default="")
    content_text = Column(Text, default="")
    duration_seconds = Column(Integer, default=300)
    difficulty = Column(String(20), default="easy")
    description = Column(String(500), default="")
    steps = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        minutes = self.duration_seconds // 60
        return {
            "id": self.id,
            "title": self.title,
            "duration": f"{minutes}分钟",
            "type": self.category,
            "description": self.description,
            "steps": self.steps or [],
        }


class RelaxSessionDB(Base):
    """情绪陪伴 - 放松训练记录表."""

    __tablename__ = "relax_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, index=True)
    duration_seconds = Column(Integer, default=0)
    completed = Column(Boolean, default=False)
    rating = Column(Integer, default=0)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class SleepContentDB(Base):
    """情绪陪伴 - 助眠内容库表."""

    __tablename__ = "sleep_contents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200))
    category = Column(String(50), index=True)
    content_type = Column(String(20), default="audio")
    content_url = Column(String(500), default="")
    duration_seconds = Column(Integer, default=1800)
    description = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        minutes = self.duration_seconds // 60
        return {
            "id": self.id,
            "title": self.title,
            "duration": f"{minutes}分钟",
            "type": self.category,
            "description": self.description,
        }


class SleepRecordDB(Base):
    """情绪陪伴 - 睡眠记录表."""

    __tablename__ = "sleep_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(20), index=True)
    sleep_duration = Column(Float, default=0)
    sleep_quality = Column(Integer, default=5)
    sleep_score = Column(Integer, default=70)
    bed_time = Column(String(20), default="")
    wake_time = Column(String(20), default="")
    note = Column(Text, default="")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PsychAssessmentDB(Base):
    """情绪陪伴 - 心理测评表."""

    __tablename__ = "psych_assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assessment_type = Column(String(50), index=True)
    title = Column(String(200))
    description = Column(String(500), default="")
    questions_json = Column(JSON, default=list)
    questions_count = Column(Integer, default=0)
    duration_minutes = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_simple_dict(self) -> dict[str, Any]:
        """转换为简版字典（不含题目）."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.assessment_type,
            "questions_count": self.questions_count,
            "duration": f"{self.duration_minutes}分钟",
        }

    def to_full_dict(self) -> dict[str, Any]:
        """转换为完整字典（含题目）."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.assessment_type,
            "questions_count": self.questions_count,
            "duration": f"{self.duration_minutes}分钟",
            "questions": self.questions_json or [],
        }


class AssessmentResultDB(Base):
    """情绪陪伴 - 测评结果表."""

    __tablename__ = "assessment_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assessment_id = Column(Integer, index=True)
    title = Column(String(200), default="")
    score = Column(Integer, default=0)
    result_text = Column(String(200), default="")
    level = Column(String(20), default="normal")
    answers_json = Column(JSON, default=dict)
    suggestion = Column(Text, default="")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    date = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
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


class MoodDiaryDB(Base):
    """情绪陪伴 - 心情日记表."""

    __tablename__ = "mood_diary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mood = Column(String(50), default="neutral")
    content = Column(Text, default="")
    tags = Column(JSON, default=list)
    date = Column(String(20), index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "emotion": self.mood,
            "content": self.content,
            "date": self.date,
            "tags": self.tags or [],
        }
