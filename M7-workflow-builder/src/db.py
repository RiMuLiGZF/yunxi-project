"""M7 积木平台 - 数据库基础设施.

P2-25: JSON→数据库迁移的数据库引擎和 Session 管理。
使用 SQLAlchemy + SQLite，支持线程安全访问。
"""

from __future__ import annotations

from pathlib import Path
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session


# 数据库文件路径（与 JSON 文件同目录）
def get_db_path(data_dir: Optional[str] = None) -> Path:
    """获取数据库文件路径.

    Args:
        data_dir: 数据目录，默认 ~/.yunxi

    Returns:
        数据库文件 Path
    """
    if data_dir:
        base = Path(data_dir)
    else:
        base = Path.home() / ".yunxi"
    base.mkdir(parents=True, exist_ok=True)
    return base / "m7_workflow.db"


def get_db_url(data_dir: Optional[str] = None) -> str:
    """获取 SQLAlchemy 数据库 URL."""
    return f"sqlite:///{get_db_path(data_dir)}"


# 全局 engine 和 session（延迟初始化）
_engine = None
_SessionLocal = None
Base = declarative_base()


def init_db(data_dir: Optional[str] = None) -> None:
    """初始化数据库引擎和表结构.

    幂等操作：已初始化则跳过。

    Args:
        data_dir: 数据目录
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return

    db_url = get_db_url(data_dir)
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    # P1-08: WAL 模式 + 性能优化 PRAGMA
    from sqlalchemy import event, text
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-20000")  # 20MB 缓存
        cursor.execute("PRAGMA busy_timeout=5000")  # 5秒忙等待
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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


def get_db_dependency() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：获取数据库 session."""
    db = get_session()
    try:
        yield db
    finally:
        db.close()
