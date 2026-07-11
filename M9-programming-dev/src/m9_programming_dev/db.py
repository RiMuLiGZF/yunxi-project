"""M9 开发者工坊 - 数据库基础设施.

P2-27: 项目索引数据库，用于加速项目列表查询。
实际项目文件仍存储在文件系统中，数据库仅作为索引。
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


Base = declarative_base()

_engine = None
_SessionLocal = None


def get_db_path() -> Path:
    """获取数据库文件路径."""
    from .config import settings
    db_dir = Path(settings.projects_root_dir).parent / ".m9_db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "m9_projects.db"


def init_db() -> None:
    """初始化数据库引擎和表结构（幂等）."""
    global _engine, _SessionLocal
    if _engine is not None:
        return

    db_url = f"sqlite:///{get_db_path()}"
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    from . import models_db  # noqa: F401
    Base.metadata.create_all(bind=_engine)


def get_session() -> Session:
    """获取数据库 session."""
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()
