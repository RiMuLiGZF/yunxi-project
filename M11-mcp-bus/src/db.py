"""M11 MCP Bus - 数据库基础设施.

使用 SQLAlchemy + SQLite，支持线程安全访问。
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import get_settings


# 全局 engine 和 session（延迟初始化）
_engine = None
_SessionLocal = None
Base = declarative_base()


def _ensure_db_dir(db_path: Path) -> None:
    """确保数据库目录存在."""
    db_path.parent.mkdir(parents=True, exist_ok=True)


def init_db(db_path: Optional[str] = None) -> None:
    """初始化数据库引擎和表结构.

    幂等操作：已初始化则跳过。

    Args:
        db_path: 数据库文件路径，为 None 则从配置读取
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return

    if db_path:
        path = Path(db_path).expanduser().resolve()
        db_url = f"sqlite:///{path}"
    else:
        settings = get_settings()
        path = settings.db_file_path
        db_url = settings.db_url

    _ensure_db_dir(path)

    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # 导入模型并创建表
    from . import models_db  # noqa: F401
    Base.metadata.create_all(bind=_engine)


def get_engine():
    """获取数据库 engine."""
    if _engine is None:
        init_db()
    return _engine


def get_session() -> Session:
    """获取一个新的数据库 session.

    使用完后需要手动 close()。
    """
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：获取数据库 session."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()
