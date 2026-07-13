"""人际关系表模块.

包含联系人、交往记录、社交提醒、情商课程等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
)

from .base import Base


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
