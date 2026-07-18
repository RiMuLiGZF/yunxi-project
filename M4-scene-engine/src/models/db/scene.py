"""场景引擎核心表模块.

包含场景上下文、切换历史、配置、当前场景状态、全局配置等 ORM 模型。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .base import Base


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
