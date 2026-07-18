"""形象工坊表模块.

包含用户形象配置、心情历史、形象快照、性格标签、声音选项等 ORM 模型。
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
)

from .base import Base


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
