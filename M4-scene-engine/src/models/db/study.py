"""学业规划表模块.

包含学习目标、学习计划、学习笔记、知识分类、考试计划、科目进度、元数据等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
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

logger = structlog.get_logger(__name__)


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
        except Exception as e:
            logger.debug("study.exam_days_left_failed", exam_date=self.exam_date,
                         error_type=type(e).__name__, error=str(e))
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
