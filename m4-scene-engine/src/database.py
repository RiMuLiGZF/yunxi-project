"""M4 场景引擎 - 数据库层.

使用 SQLAlchemy ORM 进行 SQLite 持久化存储。
数据库文件：data/m4.db
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

Base = declarative_base()


def get_db_path(base_dir: Path | None = None) -> str:
    """获取数据库文件路径.

    Args:
        base_dir: 项目根目录，为空则使用默认位置

    Returns:
        数据库文件绝对路径
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "m4.db")


# ---------------------------------------------------------------------------
# ORM 模型
# ---------------------------------------------------------------------------


class SceneContextDB(Base):
    """场景上下文表."""

    __tablename__ = "scene_contexts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default")
    scene_id = Column(String(64), nullable=False)
    context_data = Column(Text, nullable=False, default="{}")  # JSON 字符串
    last_updated = Column(Float, nullable=False, default=time.time)
    update_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "scene_id", name="uq_user_scene"),
        Index("idx_user_id", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "scene_id": self.scene_id,
            "context_data": json.loads(self.context_data) if self.context_data else {},
            "last_updated": self.last_updated,
            "update_count": self.update_count,
        }


class SceneSwitchHistoryDB(Base):
    """场景切换历史表."""

    __tablename__ = "scene_switch_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(String(32), nullable=False, unique=True)
    user_id = Column(String(128), nullable=False, default="default")
    from_scene = Column(String(64), nullable=False, default="")
    to_scene = Column(String(64), nullable=False)
    trigger_type = Column(String(32), nullable=False, default="manual")
    reason = Column(Text, nullable=False, default="")
    timestamp = Column(Float, nullable=False, default=time.time)

    __table_args__ = (
        Index("idx_user_timestamp", "user_id", "timestamp"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.record_id,
            "user_id": self.user_id,
            "from_scene": self.from_scene,
            "to_scene": self.to_scene,
            "trigger_type": self.trigger_type,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class SceneConfigDB(Base):
    """场景配置表."""

    __tablename__ = "scene_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scene_id = Column(String(64), nullable=False, unique=True)
    config = Column(Text, nullable=False, default="{}")  # JSON 字符串
    updated_at = Column(Float, nullable=False, default=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "scene_id": self.scene_id,
            "config": json.loads(self.config) if self.config else {},
            "updated_at": self.updated_at,
        }


class CurrentSceneDB(Base):
    """当前场景状态表."""

    __tablename__ = "current_scenes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, unique=True, default="default")
    current_scene = Column(String(64), nullable=False)
    last_switch_time = Column(Float, nullable=False, default=time.time)
    switch_count = Column(Integer, nullable=False, default=0)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "current_scene": self.current_scene,
            "last_switch_time": self.last_switch_time,
            "switch_count": self.switch_count,
        }


class GlobalConfigDB(Base):
    """全局配置表."""

    __tablename__ = "global_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(64), nullable=False, unique=True)
    config_value = Column(Text, nullable=False, default="{}")  # JSON 字符串
    updated_at = Column(Float, nullable=False, default=time.time)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "config_key": self.config_key,
            "config_value": json.loads(self.config_value) if self.config_value else None,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# 形象工坊 - ORM 模型
# ---------------------------------------------------------------------------


class AppearanceConfigDB(Base):
    """形象工坊 - 用户形象配置表."""

    __tablename__ = "appearance_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    theme = Column(String(50), default="default")
    primary_color = Column(String(20), default="#6366f1")
    secondary_color = Column(String(20), default="#a78bfa")
    accent_color = Column(String(20), default="#f472b6")
    bg_color = Column(String(20), default="#0f0f23")
    particle_count = Column(Integer, default=120)
    particle_speed = Column(Float, default=1.5)
    glow_intensity = Column(Float, default=0.8)
    avatar_style = Column(String(50), default="particle")
    mood = Column(String(50), default="calm")
    personality_tags = Column(JSON, default=list)
    voice_type = Column(String(50), default="warm_female")
    voice_speed = Column(Float, default=1.0)
    voice_pitch = Column(Float, default=1.0)
    quality = Column(String(20), default="high")
    model = Column(String(50), default="Yunxi-Core")
    sync_enabled = Column(Boolean, default=True)
    relationship_level = Column(Integer, default=1)
    intimacy = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_appearance_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "theme": self.theme,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "bg_color": self.bg_color,
            "particle_count": self.particle_count,
            "particle_speed": self.particle_speed,
            "glow_intensity": self.glow_intensity,
            "avatar_style": self.avatar_style,
            "mood": self.mood,
            "personality_tags": self.personality_tags or [],
            "voice_type": self.voice_type,
            "voice_speed": self.voice_speed,
            "voice_pitch": self.voice_pitch,
            "quality": self.quality,
            "model": self.model,
            "sync_enabled": self.sync_enabled,
            "relationship_level": self.relationship_level,
            "intimacy": self.intimacy,
        }


class MoodHistoryDB(Base):
    """形象工坊 - 心情切换历史表."""

    __tablename__ = "mood_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    mood_type = Column(String(50), index=True)
    reason = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "mood_type": self.mood_type,
            "reason": self.reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class AppearanceSnapshotDB(Base):
    """形象工坊 - 形象快照表."""

    __tablename__ = "appearance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String(100), default="")
    theme = Column(String(50), default="default")
    mood = Column(String(50), default="calm")
    snapshot_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None,
            "theme": self.theme,
            "mood": self.mood,
            "snapshot_data": self.snapshot_data or {},
        }


class PersonalityTagDB(Base):
    """形象工坊 - 性格标签库表."""

    __tablename__ = "personality_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag_id = Column(Integer, index=True)
    name = Column(String(50), unique=True, index=True)
    category = Column(String(50), default="性格")
    is_default = Column(Boolean, default=False)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.tag_id,
            "name": self.name,
            "category": self.category,
            "selected": self.is_default,
        }


class VoiceOptionDB(Base):
    """形象工坊 - 声音选项库表."""

    __tablename__ = "voice_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voice_id = Column(String(50), unique=True, index=True)
    name = Column(String(100))
    description = Column(String(255), default="")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.voice_id,
            "name": self.name,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# 情绪陪伴 - ORM 模型
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 人际关系模式 - ORM 模型（从 M8 迁移）
# ---------------------------------------------------------------------------


class SocialContactDB(Base):
    """人际关系 - 联系人表."""

    __tablename__ = "social_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String(100), nullable=False, index=True)
    avatar = Column(String(20), nullable=False, default="👤")
    relationship_type = Column(String(50), nullable=False, default="朋友", index=True)
    importance = Column(Integer, nullable=False, default=50)  # 亲密度/重要度 0-100
    tags = Column(JSON, default=list)  # 标签列表
    phone = Column(String(50), nullable=False, default="")
    email = Column(String(100), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    last_contact_at = Column(DateTime, nullable=True)
    contact_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_social_contact_user", "user_id"),
        Index("idx_social_contact_type", "user_id", "relationship_type"),
    )

    def _last_contact_text(self) -> str:
        """计算最后联系时间的显示文本."""
        if not self.last_contact_at:
            return "从未联系"
        now = datetime.utcnow()
        diff = now - self.last_contact_at
        days = diff.days
        if days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                return "刚刚"
            return f"{hours}小时前"
        if days == 1:
            return "昨天"
        if days < 7:
            return f"{days}天前"
        if days < 30:
            return f"{days // 7}周前"
        return f"{days // 30}个月前"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "name": self.name,
            "avatar": self.avatar,
            "relation": self.relationship_type,
            "closeness": self.importance,
            "last_contact": self._last_contact_text(),
            "contact_count": self.contact_count,
            "tags": self.tags or [],
            "phone": self.phone,
            "email": self.email,
            "note": self.note,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class SocialInteractionDB(Base):
    """人际关系 - 交往记录表."""

    __tablename__ = "social_interactions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    contact_id = Column(Integer, nullable=False, index=True)
    contact_name = Column(String(100), nullable=False, default="")
    type = Column(String(50), nullable=False, default="聊天", index=True)
    content = Column(Text, nullable=False, default="")
    duration_minutes = Column(Integer, nullable=False, default=0)
    mood = Column(String(20), nullable=False, default="neutral")  # positive/neutral/negative
    location = Column(String(100), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_social_inter_user", "user_id"),
        Index("idx_social_inter_contact", "user_id", "contact_id"),
    )

    def _date_text(self) -> str:
        """计算交往时间的显示文本."""
        if not self.created_at:
            return ""
        now = datetime.utcnow()
        diff = now - self.created_at
        days = diff.days
        if days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = diff.seconds // 60
                return f"{mins}分钟前" if mins > 0 else "刚刚"
            return f"今天 {self.created_at.strftime('%H:%M')}"
        if days == 1:
            return f"昨天 {self.created_at.strftime('%H:%M')}"
        if days < 7:
            return f"{days}天前"
        return self.created_at.strftime("%Y-%m-%d")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "type": self.type,
            "content": self.content,
            "date": self._date_text(),
            "emotion": self.mood,
            "duration_minutes": self.duration_minutes,
            "location": self.location,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SocialReminderDB(Base):
    """人际关系 - 社交提醒表."""

    __tablename__ = "social_reminders"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    contact_id = Column(Integer, nullable=False, default=0, index=True)  # 0 表示无关联联系人
    reminder_type = Column(String(50), nullable=False, default="contact", index=True)
    title = Column(String(200), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    reminder_date = Column(DateTime, nullable=True)
    repeat = Column(String(20), nullable=False, default="none")  # none/daily/weekly/monthly/yearly
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending/done/cancelled
    priority = Column(String(20), nullable=False, default="medium")  # high/medium/low
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_social_reminder_user", "user_id"),
        Index("idx_social_reminder_status", "user_id", "status"),
    )

    def _date_text(self) -> str:
        """计算提醒日期的显示文本."""
        if not self.reminder_date:
            return ""
        now = datetime.utcnow()
        diff = self.reminder_date - now
        days = diff.days
        if days < 0:
            return f"{abs(days)}天前"
        if days == 0:
            return "今天"
        if days == 1:
            return "明天"
        if days < 7:
            return f"{days}天后"
        return self.reminder_date.strftime("%Y-%m-%d")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "type": self.reminder_type,
            "title": self.title,
            "description": self.description,
            "date": self._date_text(),
            "priority": self.priority,
            "status": self.status,
            "repeat": self.repeat,
            "contact_id": self.contact_id,
            "reminder_date": self.reminder_date.strftime("%Y-%m-%d") if self.reminder_date else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class SocialEqLessonDB(Base):
    """人际关系 - 情商课程表."""

    __tablename__ = "social_eq_lessons"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    title = Column(String(200), nullable=False, default="")
    category = Column(String(50), nullable=False, default="情绪管理", index=True)
    content = Column(Text, nullable=False, default="")
    difficulty = Column(String(20), nullable=False, default="beginner")
    duration_minutes = Column(Integer, nullable=False, default=0)
    completed = Column(Boolean, nullable=False, default=False)
    progress = Column(Integer, nullable=False, default=0)  # 进度百分比 0-100
    total_lessons = Column(Integer, nullable=False, default=1)
    completed_lessons = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_social_eq_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "title": self.title,
            "progress": self.progress,
            "total_lessons": self.total_lessons,
            "completed_lessons": self.completed_lessons,
            "description": self.description,
            "category": self.category,
            "content": self.content,
            "difficulty": self.difficulty,
            "duration_minutes": self.duration_minutes,
            "completed": self.completed,
        }


# ---------------------------------------------------------------------------
# 复盘总结模式表
# ---------------------------------------------------------------------------


class ReviewReviewDB(Base):
    """复盘总结 - 复盘记录表."""

    __tablename__ = "review_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    review_id = Column(Integer, nullable=False, index=True, comment="复盘业务ID")
    title = Column(String(255), nullable=False, default="", comment="复盘标题")
    content = Column(Text, nullable=False, default="", comment="复盘内容")
    type = Column(String(20), nullable=False, default="daily", index=True,
                  comment="类型：daily/weekly/monthly")
    rating = Column(Integer, nullable=False, default=0, comment="评分")
    quality = Column(String(20), nullable=False, default="medium",
                     comment="质量：low/medium/high")
    insights = Column(JSON, default=list, comment="洞察列表")
    actions = Column(JSON, default=list, comment="行动项列表")
    date = Column(String(20), nullable=False, default="", index=True, comment="复盘日期")
    word_count = Column(Integer, nullable=False, default=0, comment="字数")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_review_user", "user_id"),
        Index("idx_review_type", "user_id", "type"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.review_id,
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "date": self.date,
            "quality": self.quality,
            "word_count": self.word_count,
            "insights": self.insights or [],
            "actions": self.actions or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReviewDiaryDB(Base):
    """复盘总结 - 日记表."""

    __tablename__ = "review_diaries"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    diary_id = Column(Integer, nullable=False, index=True, comment="日记业务ID")
    title = Column(String(255), nullable=False, default="", comment="日记标题")
    content = Column(Text, nullable=False, default="", comment="日记内容")
    mood = Column(String(50), nullable=False, default="neutral", comment="心情")
    weather = Column(String(50), nullable=False, default="", comment="天气")
    tags = Column(JSON, default=list, comment="标签列表")
    word_count = Column(Integer, nullable=False, default=0, comment="字数")
    encrypted = Column(Boolean, nullable=False, default=True, comment="是否加密")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_review_diary_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.diary_id,
            "title": self.title,
            "content": self.content,
            "mood": self.mood,
            "tags": self.tags or [],
            "word_count": self.word_count,
            "encrypted": self.encrypted,
            "weather": self.weather,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReviewDecisionDB(Base):
    """复盘总结 - 决策记录表."""

    __tablename__ = "review_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    decision_id = Column(Integer, nullable=False, index=True, comment="决策业务ID")
    title = Column(String(255), nullable=False, default="", comment="决策标题")
    description = Column(Text, nullable=False, default="", comment="决策描述")
    alternatives = Column(JSON, default=list, comment="备选方案列表")
    outcome = Column(Text, nullable=False, default="", comment="结果")
    lessons = Column(Text, nullable=False, default="", comment="经验教训")
    status = Column(String(20), nullable=False, default="pending", index=True,
                    comment="状态：pending/executing/completed")
    final_choice = Column(String(255), nullable=False, default="", comment="最终选择")
    result = Column(Text, nullable=False, default="", comment="结果描述")
    emotion_level = Column(Integer, nullable=False, default=5, comment="情绪强度 1-10")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_review_decision_user", "user_id"),
        Index("idx_review_decision_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.decision_id,
            "title": self.title,
            "description": self.description,
            "options": self.alternatives or [],
            "final_choice": self.final_choice,
            "result": self.result,
            "emotion_level": self.emotion_level,
            "status": self.status,
            "outcome": self.outcome,
            "lessons": self.lessons,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ReviewEmotionDB(Base):
    """复盘总结 - 情绪记录表."""

    __tablename__ = "review_emotions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    date = Column(String(20), nullable=False, default="", index=True,
                  comment="日期 YYYY-MM-DD")
    emotion = Column(String(50), nullable=False, default="neutral",
                     comment="情绪类型")
    intensity = Column(Integer, nullable=False, default=5, comment="情绪强度 1-10")
    trigger = Column(String(500), nullable=False, default="", comment="触发因素")
    note = Column(Text, nullable=False, default="", comment="备注")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_review_emotion_user", "user_id"),
        Index("idx_review_emotion_date", "user_id", "date"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "emotion": self.emotion,
            "level": self.intensity,
            "trigger": self.trigger,
            "note": self.note,
            "date": self.date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ReviewBiasDB(Base):
    """复盘总结 - 认知偏差表."""

    __tablename__ = "review_biases"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    bias_id = Column(Integer, nullable=False, index=True, comment="偏差业务ID")
    name = Column(String(100), nullable=False, default="", comment="偏差名称")
    description = Column(Text, nullable=False, default="", comment="偏差描述")
    category = Column(String(50), nullable=False, default="", comment="分类")
    level = Column(String(20), nullable=False, default="low",
                   comment="风险等级：low/medium/high")
    detected_count = Column(Integer, nullable=False, default=0, comment="检测次数")
    last_detected = Column(DateTime, nullable=True, comment="最近检测时间")
    suggestions = Column(JSON, default=list, comment="建议列表")
    user_id = Column(String(128), nullable=False, default="default", index=True)

    __table_args__ = (
        Index("idx_review_bias_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.bias_id,
            "name": self.name,
            "description": self.description,
            "level": self.level,
            "detection_count": self.detected_count,
            "last_detected": self.last_detected.isoformat() if self.last_detected else None,
            "suggestions": self.suggestions or [],
            "category": self.category,
        }


# ---------------------------------------------------------------------------
# 生活管理模式 - ORM 模型（从 M8 迁移）
# ---------------------------------------------------------------------------


class LifeScheduleDB(Base):
    """生活管理 - 日程表."""

    __tablename__ = "life_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    schedule_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    start_time = Column(String(10), nullable=False, default="09:00")
    end_time = Column(String(10), nullable=False, default="10:00")
    time_range = Column(String(30), nullable=False, default="")
    date = Column(String(20), nullable=True, index=True)
    repeat_type = Column(String(20), nullable=False, default="none")
    category = Column(String(20), nullable=False, default="固定")
    tag_color = Column(String(20), nullable=False, default="green")
    all_day = Column(Boolean, nullable=False, default=False)
    priority = Column(String(20), nullable=False, default="normal")
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_sched_user", "user_id"),
        Index("idx_life_sched_date", "user_id", "date"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.schedule_id,
            "schedule_id": self.schedule_id,
            "title": self.title,
            "time": self.time_range or f"{self.start_time} - {self.end_time}",
            "tag": self.category,
            "tag_color": self.tag_color,
            "date": self.date,
            "all_day": self.all_day,
            "priority": self.priority,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeTodoDB(Base):
    """生活管理 - 待办事项表."""

    __tablename__ = "life_todos"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    todo_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    priority = Column(String(20), nullable=False, default="normal")
    status = Column(String(20), nullable=False, default="todo", index=True)
    progress = Column(Integer, nullable=False, default=0)
    due_date = Column(String(20), nullable=True)
    category = Column(String(50), nullable=False, default="今日待办")
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_todo_user", "user_id"),
        Index("idx_life_todo_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.todo_id,
            "todo_id": self.todo_id,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "category": self.category,
            "priority": self.priority,
            "description": self.description,
            "due_date": self.due_date,
            "completed_at": self.completed_at.strftime("%Y-%m-%d %H:%M:%S") if self.completed_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeHabitDB(Base):
    """生活管理 - 习惯打卡表."""

    __tablename__ = "life_habits"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    habit_id = Column(Integer, nullable=False, default=0, index=True)
    name = Column(String(100), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    category = Column(String(50), nullable=False, default="")
    icon = Column(String(20), nullable=False, default="✅")
    streak = Column(Integer, nullable=False, default=0)
    longest_streak = Column(Integer, nullable=False, default=0)
    target_count = Column(Integer, nullable=False, default=1)
    current_count = Column(Integer, nullable=False, default=0)
    done = Column(Boolean, nullable=False, default=False)
    frequency = Column(String(20), nullable=False, default="daily")
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_habit_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.habit_id,
            "habit_id": self.habit_id,
            "name": self.name,
            "icon": self.icon,
            "streak": self.streak,
            "longest_streak": self.longest_streak,
            "done": self.done,
            "frequency": self.frequency,
            "category": self.category,
            "description": self.description,
            "target_count": self.target_count,
            "current_count": self.current_count,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeHabitRecordDB(Base):
    """生活管理 - 习惯打卡记录表."""

    __tablename__ = "life_habit_records"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    habit_id = Column(Integer, nullable=False, default=0, index=True)
    date = Column(String(20), nullable=False, default="", index=True)
    completed = Column(Boolean, nullable=False, default=True)
    note = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_habit_rec_user", "user_id"),
        Index("idx_life_habit_rec_date", "user_id", "date"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "habit_id": self.habit_id,
            "date": self.date,
            "completed": self.completed,
            "note": self.note,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeSceneDB(Base):
    """生活管理 - 场景模式表."""

    __tablename__ = "life_scenes"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    scene_id = Column(String(50), nullable=False, default="", index=True)
    name = Column(String(100), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    icon = Column(String(20), nullable=False, default="🏠")
    active = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=False)
    settings_json = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_scene_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "key": self.scene_id,
            "scene_id": self.scene_id,
            "label": self.name,
            "name": self.name,
            "icon": self.icon,
            "active": self.active,
            "description": self.description,
            "settings": self.settings_json or {},
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeRuleDB(Base):
    """生活管理 - 自动化规则表."""

    __tablename__ = "life_rules"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    rule_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    condition = Column(Text, nullable=False, default="")
    action = Column(Text, nullable=False, default="")
    category = Column(String(50), nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_rule_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.rule_id,
            "rule_id": self.rule_id,
            "condition": self.condition,
            "action": self.action,
            "enabled": self.enabled,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeFinanceCategoryDB(Base):
    """生活管理 - 财务分类表."""

    __tablename__ = "life_finance_categories"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    category_id = Column(Integer, nullable=False, default=0, index=True)
    name = Column(String(100), nullable=False, default="")
    type = Column(String(20), nullable=False, default="expense")
    budget = Column(Float, nullable=False, default=0.0)
    spent = Column(Float, nullable=False, default=0.0)
    percentage = Column(Float, nullable=False, default=0.0)
    color = Column(String(20), nullable=False, default="#1890FF")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_fin_cat_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.category_id,
            "category_id": self.category_id,
            "name": self.name,
            "amount": self.spent,
            "spent": self.spent,
            "percentage": self.percentage,
            "color": self.color,
            "budget": self.budget,
            "type": self.type,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeFinanceRecordDB(Base):
    """生活管理 - 财务记录表."""

    __tablename__ = "life_finance_records"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    type = Column(String(20), nullable=False, default="expense")
    amount = Column(Float, nullable=False, default=0.0)
    category = Column(String(50), nullable=False, default="其他")
    description = Column(Text, nullable=False, default="")
    transaction_date = Column(String(20), nullable=False, default="", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_fin_rec_user", "user_id"),
        Index("idx_life_fin_rec_date", "user_id", "transaction_date"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "type": self.type,
            "amount": self.amount,
            "category": self.category,
            "description": self.description,
            "transaction_date": self.transaction_date,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class LifeMetaDB(Base):
    """生活管理 - 元数据表（key-value JSON 存储）."""

    __tablename__ = "life_meta"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    meta_key = Column(String(50), nullable=False, default="", index=True)
    meta_value = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_life_meta_user_key", "user_id", "meta_key", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "key": self.meta_key,
            "value": self.meta_value,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# 学业规划模式 - ORM 模型（从 M8 迁移）
# ---------------------------------------------------------------------------


class StudyGoalDB(Base):
    """学业规划 - 学习目标表（树形结构）."""

    __tablename__ = "study_goals"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    goal_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    parent_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="not-started", index=True)
    progress = Column(Integer, nullable=False, default=0)
    priority = Column(String(20), nullable=False, default="normal")
    deadline = Column(String(20), nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    icon = Column(String(20), nullable=False, default="📚")
    expanded = Column(Boolean, nullable=False, default=True)
    level = Column(Integer, nullable=False, default=0)
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_goal_user", "user_id"),
        Index("idx_study_goal_parent", "user_id", "parent_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.goal_id,
            "goal_id": self.goal_id,
            "label": self.title,
            "title": self.title,
            "icon": self.icon,
            "progress": self.progress,
            "status": self.status,
            "expanded": self.expanded,
            "parent_id": self.parent_id,
            "level": self.level,
            "order_index": self.order_index,
            "priority": self.priority,
            "description": self.description,
            "deadline": self.deadline,
        }


class StudyPlanDB(Base):
    """学业规划 - 学习计划表."""

    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    plan_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    subject = Column(String(50), nullable=False, default="", index=True)
    status = Column(String(20), nullable=False, default="pending")
    start_time = Column(String(10), nullable=False, default="09:00")
    end_time = Column(String(10), nullable=False, default="10:00")
    date = Column(String(20), nullable=False, default="", index=True)
    duration = Column(Float, nullable=False, default=1.0)
    priority = Column(String(20), nullable=False, default="常规")
    completed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_plan_user", "user_id"),
        Index("idx_study_plan_date", "user_id", "date"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.plan_id,
            "plan_id": self.plan_id,
            "title": self.title,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "priority": self.priority,
            "completed": self.completed,
            "subject": self.subject,
            "date": self.date,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class StudyNoteDB(Base):
    """学业规划 - 学习笔记表."""

    __tablename__ = "study_notes"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    note_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(200), nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    category = Column(String(50), nullable=False, default="", index=True)
    tags = Column(JSON, default=list)
    important = Column(Boolean, nullable=False, default=False)
    date_label = Column(String(20), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_note_user", "user_id"),
        Index("idx_study_note_category", "user_id", "category"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.note_id,
            "note_id": self.note_id,
            "title": self.title,
            "subject": self.category,
            "category": self.category,
            "date": self.date_label,
            "date_label": self.date_label,
            "content": self.content,
            "tags": self.tags or [],
            "important": self.important,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "",
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M") if self.updated_at else "",
        }


class StudyKnowledgeCategoryDB(Base):
    """学业规划 - 知识分类表."""

    __tablename__ = "study_knowledge_categories"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    category_id = Column(Integer, nullable=False, default=0, index=True)
    name = Column(String(100), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    parent_id = Column(Integer, nullable=True)
    note_count = Column(Integer, nullable=False, default=0)
    icon = Column(String(20), nullable=False, default="📚")
    unit = Column(String(20), nullable=False, default="个知识点")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_kcat_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.category_id,
            "category_id": self.category_id,
            "name": self.name,
            "icon": self.icon,
            "item_count": self.note_count,
            "note_count": self.note_count,
            "unit": self.unit,
            "description": self.description,
            "parent_id": self.parent_id,
        }


class StudyExamDB(Base):
    """学业规划 - 考试计划表."""

    __tablename__ = "study_exams"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    exam_id = Column(Integer, nullable=False, default=0, index=True)
    name = Column(String(200), nullable=False, default="")
    subject = Column(String(50), nullable=False, default="")
    exam_date = Column(String(30), nullable=False, default="")
    location = Column(String(200), nullable=False, default="")
    score = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="upcoming")
    urgency = Column(String(20), nullable=False, default="备考中")
    color_theme = Column(String(20), nullable=False, default="blue")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_exam_user", "user_id"),
    )

    def _days_left(self) -> int:
        """计算距离考试的天数."""
        try:
            exam_dt = datetime.strptime(self.exam_date, "%Y-%m-%d %H:%M")
            return max(0, (exam_dt - datetime.now()).days)
        except Exception:
            return 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.exam_id,
            "exam_id": self.exam_id,
            "name": self.name,
            "exam_date": self.exam_date,
            "location": self.location,
            "days_left": self._days_left(),
            "urgency": self.urgency,
            "color_theme": self.color_theme,
            "subject": self.subject,
            "score": self.score,
            "status": self.status,
        }


class StudyProgressDB(Base):
    """学业规划 - 科目进度表."""

    __tablename__ = "study_progress"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    subject = Column(String(50), nullable=False, default="", index=True)
    progress = Column(Integer, nullable=False, default=0)
    total_hours = Column(Float, nullable=False, default=0.0)
    mastered_topics = Column(Integer, nullable=False, default=0)
    total_topics = Column(Integer, nullable=False, default=0)
    color = Column(String(20), nullable=False, default="blue")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_prog_user", "user_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.id,
            "subject": self.subject,
            "progress": self.progress,
            "color": self.color,
            "total_hours": self.total_hours,
            "mastered_topics": self.mastered_topics,
            "total_topics": self.total_topics,
        }


class StudyMetaDB(Base):
    """学业规划 - 元数据表（key-value JSON 存储）."""

    __tablename__ = "study_meta"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    meta_key = Column(String(50), nullable=False, default="", index=True)
    meta_value = Column(JSON, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_study_meta_user_key", "user_id", "meta_key", unique=True),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "key": self.meta_key,
            "value": self.meta_value,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


# ---------------------------------------------------------------------------
# 工作开发模式 - ORM 模型（从 M8 迁移）
# ---------------------------------------------------------------------------


class WorkProjectDB(Base):
    """工作开发 - 项目表."""

    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="项目ID（业务ID）")
    name = Column(String(200), nullable=False, default="", comment="项目名称")
    description = Column(Text, nullable=False, default="", comment="项目描述")
    status = Column(String(20), nullable=False, default="planning", index=True,
                    comment="状态：planning/active/completed/archived")
    progress = Column(Integer, nullable=False, default=0, comment="进度百分比 0-100")
    repo_url = Column(String(500), nullable=False, default="", comment="仓库地址")
    language = Column(String(50), nullable=False, default="python", comment="主要语言")
    category = Column(String(50), nullable=False, default="", index=True, comment="项目分类")
    file_count = Column(Integer, nullable=False, default=0, comment="文件数量")
    line_count = Column(Integer, nullable=False, default=0, comment="代码行数")
    commit_count = Column(Integer, nullable=False, default=0, comment="提交次数")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_proj_user", "user_id"),
        Index("idx_work_proj_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.project_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "language": self.language,
            "category": self.category,
            "repo_url": self.repo_url,
            "file_count": self.file_count,
            "line_count": self.line_count,
            "commit_count": self.commit_count,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkTaskDB(Base):
    """工作开发 - 任务表."""

    __tablename__ = "work_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    task_id = Column(Integer, nullable=False, default=0, index=True, comment="任务ID（业务ID）")
    title = Column(String(255), nullable=False, default="", comment="任务标题")
    description = Column(Text, nullable=False, default="", comment="任务描述")
    status = Column(String(20), nullable=False, default="todo", index=True,
                    comment="状态：todo/in_progress/review/done")
    priority = Column(String(20), nullable=False, default="medium", index=True,
                      comment="优先级：low/medium/high")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    assignee = Column(String(100), nullable=False, default="", comment="负责人")
    due_date = Column(String(20), nullable=True, comment="截止日期")
    tags = Column(JSON, default=list, comment="标签列表")
    estimate_hours = Column(Integer, nullable=False, default=0, comment="预估工时（小时）")
    spent_hours = Column(Integer, nullable=False, default=0, comment="已用工时（小时）")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_task_user", "user_id"),
        Index("idx_work_task_status", "user_id", "status"),
        Index("idx_work_task_project", "user_id", "project_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.task_id,
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "project_id": self.project_id,
            "assignee": self.assignee,
            "due_date": self.due_date,
            "tags": self.tags or [],
            "estimate_hours": self.estimate_hours,
            "spent_hours": self.spent_hours,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkCommitDB(Base):
    """工作开发 - 提交记录表."""

    __tablename__ = "work_commits"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    commit_id = Column(Integer, nullable=False, default=0, index=True, comment="提交ID（业务ID）")
    hash = Column(String(64), nullable=False, default="", comment="提交哈希")
    message = Column(Text, nullable=False, default="", comment="提交信息")
    author = Column(String(100), nullable=False, default="", comment="作者")
    branch = Column(String(100), nullable=False, default="main", comment="分支")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    additions = Column(Integer, nullable=False, default=0, comment="新增行数")
    deletions = Column(Integer, nullable=False, default=0, comment="删除行数")
    files_changed = Column(Integer, nullable=False, default=0, comment="变更文件数")
    committed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)

    __table_args__ = (
        Index("idx_work_commit_user", "user_id"),
        Index("idx_work_commit_project", "user_id", "project_id"),
        Index("idx_work_commit_time", "user_id", "committed_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（兼容前端字段名）."""
        return {
            "id": self.commit_id,
            "commit_id": self.commit_id,
            "hash": self.hash,
            "message": self.message,
            "author": self.author,
            "project_id": self.project_id,
            "branch": self.branch,
            "files_changed": self.files_changed,
            "insertions": self.additions,
            "deletions": self.deletions,
            "additions": self.additions,
            "created_at": self.committed_at.strftime("%Y-%m-%d %H:%M:%S") if self.committed_at else None,
            "committed_at": self.committed_at.strftime("%Y-%m-%d %H:%M:%S") if self.committed_at else None,
        }


class WorkCodeSnippetDB(Base):
    """工作开发 - 代码片段表."""

    __tablename__ = "work_code_snippets"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    snippet_id = Column(Integer, nullable=False, default=0, index=True, comment="片段ID（业务ID）")
    title = Column(String(200), nullable=False, default="", comment="片段标题")
    language = Column(String(50), nullable=False, default="python", index=True, comment="编程语言")
    code = Column(Text, nullable=False, default="", comment="代码内容")
    description = Column(Text, nullable=False, default="", comment="描述说明")
    tags = Column(JSON, default=list, comment="标签列表")
    is_favorite = Column(Boolean, nullable=False, default=False, comment="是否收藏")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID（0表示无）")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_snippet_user", "user_id"),
        Index("idx_work_snippet_lang", "user_id", "language"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.snippet_id,
            "snippet_id": self.snippet_id,
            "title": self.title,
            "language": self.language,
            "code": self.code,
            "description": self.description,
            "tags": self.tags or [],
            "is_favorite": self.is_favorite,
            "project_id": self.project_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkDevSessionDB(Base):
    """工作开发 - 开发会话表."""

    __tablename__ = "work_dev_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    session_id = Column(String(64), nullable=False, default="", unique=True, index=True, comment="会话ID")
    session_type = Column(String(30), nullable=False, default="code_chat", index=True,
                          comment="会话类型：code_chat/code_review/code_generate")
    title = Column(String(200), nullable=False, default="", comment="会话标题")
    language = Column(String(50), nullable=False, default="python", comment="编程语言")
    messages_json = Column(JSON, default=list, comment="消息列表（JSON）")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="关联项目ID")
    message_count = Column(Integer, nullable=False, default=0, comment="消息数量")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_work_session_user", "user_id"),
        Index("idx_work_session_type", "user_id", "session_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.session_id,
            "session_id": self.session_id,
            "session_type": self.session_type,
            "title": self.title,
            "language": self.language,
            "project_id": self.project_id,
            "message_count": self.message_count,
            "messages": self.messages_json or [],
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
            "updated_at": self.updated_at.strftime("%Y-%m-%d %H:%M:%S") if self.updated_at else None,
        }


class WorkCodeUsageDB(Base):
    """工作开发 - 代码使用统计表."""

    __tablename__ = "work_code_usage"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    usage_id = Column(Integer, nullable=False, default=0, index=True, comment="使用记录ID（业务ID）")
    action_type = Column(String(20), nullable=False, default="generate", index=True,
                         comment="操作类型：generate/chat/execute/complete")
    operation_type = Column(String(20), nullable=False, default="",
                            comment="操作子类型：generate/review/debug/optimize/refactor/explain/test")
    language = Column(String(50), nullable=False, default="python", comment="编程语言")
    tokens_used = Column(Integer, nullable=False, default=0, comment="消耗 Token 数（估算）")
    project_id = Column(Integer, nullable=False, default=0, index=True, comment="所属项目ID")
    is_fallback = Column(Boolean, nullable=False, default=False, comment="是否为 fallback 模板模式")
    user_id = Column(String(128), nullable=False, default="default", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_work_usage_user", "user_id"),
        Index("idx_work_usage_action", "user_id", "action_type"),
        Index("idx_work_usage_time", "user_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.usage_id,
            "usage_id": self.usage_id,
            "action_type": self.action_type,
            "operation_type": self.operation_type,
            "language": self.language,
            "tokens_used": self.tokens_used,
            "project_id": self.project_id,
            "is_fallback": self.is_fallback,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# 主聊天服务 - ORM 模型
# ---------------------------------------------------------------------------


class ChatConversationDB(Base):
    """聊天服务 - 会话表."""

    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    title = Column(String(255), default="新对话")
    mode = Column(String(50), default="main-chat", index=True)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_chat_conv_user", "user_id"),
        Index("idx_chat_conv_updated", "user_id", "updated_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.conversation_id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "mode": self.mode,
            "message_count": self.message_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessageDB(Base):
    """聊天服务 - 消息表."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(64), nullable=False, unique=True, index=True)
    conversation_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    role = Column(String(20), nullable=False, index=True)  # user/assistant/system
    content = Column(Text, nullable=False, default="")
    mode = Column(String(50), default="main-chat", index=True)
    model = Column(String(100), default="")
    tokens_used = Column(Integer, default=0)
    is_fallback = Column(Boolean, default=False)
    extra = Column(JSON, default=dict)  # 额外数据（如记忆引用、工具调用等）
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_chat_msg_conv", "conversation_id", "created_at"),
        Index("idx_chat_msg_user", "user_id", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.message_id,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "mode": self.mode,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "is_fallback": self.is_fallback,
            "extra": self.extra or {},
            "timestamp": self.created_at.timestamp() if self.created_at else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# 语音服务 - ORM 模型
# ---------------------------------------------------------------------------


class VoiceConfigDB(Base):
    """语音服务 - 配置表."""

    __tablename__ = "voice_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", unique=True, index=True)
    voice_type = Column(String(50), default="warm_female")
    voice_speed = Column(Float, default=1.0)
    voice_pitch = Column(Float, default=1.0)
    prefer_online = Column(Boolean, default=True)
    asr_model_size = Column(String(20), default="small")
    asr_language = Column(String(10), default="zh")
    wake_words = Column(JSON, default=list)  # ["云汐", "你好云汐"]
    vad_threshold = Column(Float, default=0.5)
    vad_min_speech = Column(Float, default=0.3)
    vad_max_silence = Column(Float, default=0.5)
    tts_output_format = Column(String(10), default="mp3")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "voice_type": self.voice_type,
            "voice_speed": self.voice_speed,
            "voice_pitch": self.voice_pitch,
            "prefer_online": self.prefer_online,
            "asr_model_size": self.asr_model_size,
            "asr_language": self.asr_language,
            "wake_words": self.wake_words or ["云汐", "你好云汐"],
            "vad_threshold": self.vad_threshold,
            "vad_min_speech_duration": self.vad_min_speech,
            "vad_max_silence_duration": self.vad_max_silence,
            "tts_output_format": self.tts_output_format,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class VoiceHistoryDB(Base):
    """语音服务 - 调用历史表."""

    __tablename__ = "voice_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    operation_type = Column(String(20), nullable=False, index=True)  # tts/asr/vad/wake_word
    text = Column(Text, default="")  # TTS 输入文本 或 ASR 识别结果
    audio_id = Column(String(64), default="")
    duration = Column(Float, default=0.0)  # 音频时长（秒）
    engine = Column(String(50), default="mock")
    success = Column(Boolean, default=True)
    error_msg = Column(String(255), default="")
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_voice_hist_user", "user_id", "created_at"),
        Index("idx_voice_hist_op", "operation_type", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "operation_type": self.operation_type,
            "text": self.text,
            "audio_id": self.audio_id,
            "duration": self.duration,
            "engine": self.engine,
            "success": self.success,
            "error_msg": self.error_msg,
            "extra": self.extra or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# 手表交互 - ORM 模型
# ---------------------------------------------------------------------------


class WatchDeviceDB(Base):
    """手表交互 - 设备表."""

    __tablename__ = "watch_devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    name = Column(String(100), default="智能手表")
    device_type = Column(String(20), default="watch", index=True)  # watch/ring/band
    brand = Column(String(50), default="Yunxi")
    model = Column(String(50), default="")
    firmware_version = Column(String(50), default="v1.0.0")
    status = Column(String(20), default="offline", index=True)  # online/offline
    battery = Column(Integer, default=100)
    paired = Column(Boolean, default=False)
    paired_at = Column(DateTime, nullable=True)
    last_sync = Column(DateTime, nullable=True)
    mac_address = Column(String(32), default="")
    features = Column(JSON, default=list)  # ["heart_rate", "steps", "sleep", ...]
    settings = Column(JSON, default=dict)  # 手表端配置
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_watch_dev_user", "user_id"),
        Index("idx_watch_dev_status", "user_id", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "device_id": self.device_id,
            "name": self.name,
            "device_type": self.device_type,
            "brand": self.brand,
            "model": self.model,
            "firmware_version": self.firmware_version,
            "status": self.status,
            "battery": self.battery,
            "paired": self.paired,
            "paired_at": self.paired_at.isoformat() if self.paired_at else None,
            "last_sync": self.last_sync.isoformat() if self.last_sync else None,
            "mac_address": self.mac_address,
            "features": self.features or [],
            "settings": self.settings or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WatchHealthDataDB(Base):
    """手表交互 - 健康数据表."""

    __tablename__ = "watch_health_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    data_type = Column(String(30), nullable=False, index=True)  # heart_rate/steps/spo2/sleep/calories
    value = Column(Float, default=0.0)
    unit = Column(String(20), default="")
    extra = Column(JSON, default=dict)  # 额外字段（如睡眠分期、步数目标等）
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_watch_health_dev", "device_id", "data_type", "recorded_at"),
        Index("idx_watch_health_user", "user_id", "data_type", "recorded_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "device_id": self.device_id,
            "data_type": self.data_type,
            "value": self.value,
            "unit": self.unit,
            "extra": self.extra or {},
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "timestamp": self.recorded_at.isoformat() if self.recorded_at else None,
        }


class WatchNotificationDB(Base):
    """手表交互 - 通知表."""

    __tablename__ = "watch_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(String(64), nullable=False, unique=True, index=True)
    device_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    title = Column(String(100), default="")
    content = Column(Text, default="")
    notification_type = Column(String(20), default="info", index=True)  # info/warning/reminder/error
    status = Column(String(20), default="pending", index=True)  # pending/delivered/read/failed
    action_type = Column(String(50), default="")
    action_data = Column(JSON, default=dict)
    source = Column(String(30), default="api")
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_watch_notif_dev", "device_id", "created_at"),
        Index("idx_watch_notif_user", "user_id", "created_at"),
        Index("idx_watch_notif_status", "status"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "notification_id": self.notification_id,
            "device_id": self.device_id,
            "title": self.title,
            "content": self.content,
            "notification_type": self.notification_type,
            "status": self.status,
            "action_type": self.action_type,
            "action_data": self.action_data or {},
            "source": self.source,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# 数据库引擎与会话
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_db(db_path: str | None = None, base_dir: Path | None = None) -> None:
    """初始化数据库引擎和表结构.

    Args:
        db_path: 数据库文件路径，为空则使用默认路径
        base_dir: 项目根目录（用于推导路径）
    """
    global _engine, _SessionLocal

    if db_path is None:
        db_path = get_db_path(base_dir)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    _SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine,
    )

    # 创建所有表
    Base.metadata.create_all(bind=_engine)


def get_session():
    """获取数据库会话.

    Returns:
        SQLAlchemy Session 对象
    """
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal()


def get_engine():
    """获取数据库引擎."""
    if _engine is None:
        init_db()
    return _engine
