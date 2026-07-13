'''
M10 系统卫士 - 数据库模块

提供 SQLAlchemy 数据库连接、会话管理和初始化功能。
所有持久化数据通过统一的数据库层访问。
'''

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import get_config


def _get_db_path() -> str:
    '''获取数据库文件路径.'''
    env_path = os.getenv('M10_DB_PATH')
    if env_path:
        return env_path

    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / 'yunxi_m10.db')


DB_PATH = _get_db_path()
DB_URL = f'sqlite:///{DB_PATH}'

engine = create_engine(
    DB_URL,
    echo=False,
    connect_args={
        'check_same_thread': False,
        'timeout': 30,
    },
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    '''获取数据库会话（FastAPI 依赖注入用）.'''
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    '''获取一个新的数据库会话.'''
    return SessionLocal()


def init_db() -> None:
    '''初始化数据库，创建所有表.'''
    from . import db_models  # noqa: F401

    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    print(f'  数据库: 已初始化 ({DB_PATH})')


def check_db_health() -> bool:
    '''检查数据库连接是否正常.'''
    try:
        db = SessionLocal()
        from sqlalchemy import text
        db.execute(text('SELECT 1'))
        db.close()
        return True
    except Exception:
        return False