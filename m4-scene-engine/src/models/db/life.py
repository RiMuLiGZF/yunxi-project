"""生活管理表模块.

包含日程、待办、习惯打卡、习惯打卡记录、场景模式、自动化规则、财务分类、财务记录、元数据等 ORM 模型。
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
