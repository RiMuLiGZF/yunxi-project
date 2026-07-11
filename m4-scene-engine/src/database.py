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
    Column,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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
