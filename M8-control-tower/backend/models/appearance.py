"""
M8 管理工作台 - 形象工坊模型

包含 AppearanceConfig, MoodHistory, AppearanceSnapshot, PersonalityTag, VoiceOption。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from datetime import datetime

from .base import Base


class AppearanceConfig(Base):
    """形象工坊 - 用户形象配置表"""
    __tablename__ = "appearance_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    theme = Column(String(50), default="default", comment="主题ID")
    primary_color = Column(String(20), default="#6366f1", comment="主色")
    secondary_color = Column(String(20), default="#a78bfa", comment="辅色")
    accent_color = Column(String(20), default="#f472b6", comment="强调色")
    bg_color = Column(String(20), default="#0f0f23", comment="背景色")
    particle_count = Column(Integer, default=120, comment="粒子数量")
    particle_speed = Column(Float, default=1.5, comment="粒子速度")
    glow_intensity = Column(Float, default=0.8, comment="光晕强度")
    avatar_style = Column(String(50), default="particle", comment="头像样式")
    mood = Column(String(50), default="calm", comment="当前心情")
    personality_tags = Column(JSON, default=list, comment="性格标签列表")
    voice_type = Column(String(50), default="warm_female", comment="声音类型")
    voice_speed = Column(Float, default=1.0, comment="语速")
    voice_pitch = Column(Float, default=1.0, comment="音调")
    quality = Column(String(20), default="high", comment="画质")
    model = Column(String(50), default="Yunxi-Core", comment="模型")
    sync_enabled = Column(Boolean, default=True, comment="是否同步")
    relationship_level = Column(Integer, default=1, comment="关系等级")
    intimacy = Column(Integer, default=0, comment="亲密度")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self) -> dict:
        """转换为字典"""
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


class MoodHistory(Base):
    """形象工坊 - 心情切换历史表"""
    __tablename__ = "mood_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    mood_type = Column(String(50), index=True, comment="心情类型")
    reason = Column(String(255), default="", comment="切换原因")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="切换时间")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "mood_type": self.mood_type,
            "reason": self.reason,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else None,
        }


class AppearanceSnapshot(Base):
    """形象工坊 - 形象快照表"""
    __tablename__ = "appearance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, default=1, index=True, comment="用户ID")
    name = Column(String(100), default="", comment="快照名称")
    theme = Column(String(50), default="default", comment="主题ID")
    mood = Column(String(50), default="calm", comment="心情")
    snapshot_data = Column(JSON, default=dict, comment="快照数据（完整配置）")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None,
            "theme": self.theme,
            "mood": self.mood,
            "snapshot_data": self.snapshot_data or {},
        }


class PersonalityTag(Base):
    """形象工坊 - 性格标签库"""
    __tablename__ = "personality_tags"

    id = Column(Integer, primary_key=True, index=True)
    tag_id = Column(Integer, index=True, comment="标签业务ID")
    name = Column(String(50), unique=True, index=True, comment="标签名称")
    category = Column(String(50), default="", comment="分类")
    is_default = Column(Boolean, default=False, comment="是否默认选中")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.tag_id,
            "name": self.name,
            "category": self.category,
            "selected": self.is_default,
        }


class VoiceOption(Base):
    """形象工坊 - 声音选项库"""
    __tablename__ = "voice_options"

    id = Column(Integer, primary_key=True, index=True)
    voice_id = Column(String(50), unique=True, index=True, comment="声音ID")
    name = Column(String(100), comment="显示名称")
    description = Column(String(255), default="", comment="描述")

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.voice_id,
            "name": self.name,
            "description": self.description,
        }
