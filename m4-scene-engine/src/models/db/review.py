"""复盘总结表模块.

包含复盘记录、日记、决策记录、情绪记录、认知偏差等 ORM 模型。
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
