"""数据库基础配置模块.

包含 SQLAlchemy Base 类、数据库路径配置、引擎与会话管理函数。
所有 ORM 模型均从本模块导入 Base。
"""

from __future__ import annotations

import json
import os
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

    优先级：M4_DATA_PATH 环境变量 > base_dir 参数 > 默认路径

    Args:
        base_dir: 项目根目录，为空则使用默认位置

    Returns:
        数据库文件绝对路径
    """
    # 环境变量优先
    env_path = os.environ.get("M4_DATA_PATH", "")
    if env_path:
        # 如果是目录，拼接 m4.db
        if env_path.endswith(".db"):
            return env_path
        env_dir = Path(env_path)
        if env_dir.is_dir() or not env_path.endswith(".db"):
            return str(env_dir / "m4.db")
        return env_path

    if base_dir is None:
        # 从 src/models/db/base.py 向上四级到项目根目录
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
    data_dir = base_dir / "data"
    # 向后兼容：如果项目根 data 不存在但 src/data 存在，使用 src/data
    legacy_data_dir = base_dir / "src" / "data"
    if not data_dir.exists() and legacy_data_dir.exists():
        data_dir = legacy_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "m4.db")


# ---------------------------------------------------------------------------
# 数据库引擎与会话
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_db(db_path: str | None = None, base_dir: Path | None = None) -> dict[str, Any]:
    """初始化数据库引擎和表结构.

    使用迁移管理器进行版本化建表，替代直接的 create_all。

    Args:
        db_path: 数据库文件路径，为空则使用默认路径
        base_dir: 项目根目录（用于推导路径）

    Returns:
        迁移结果字典
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

    # 使用迁移管理器进行版本化建表
    from .migration import DatabaseMigrator
    from .migrations import MIGRATIONS

    migrator = DatabaseMigrator(db_path, MIGRATIONS)
    result = migrator.migrate()

    return result


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
