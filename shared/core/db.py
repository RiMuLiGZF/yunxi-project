"""
统一数据库工具

提供各模块共用的数据库基础设施：
- Base: SQLAlchemy 声明式基类
- create_module_engine: 创建模块级别的 engine
- create_session_factory: 创建 session 工厂
- get_db: FastAPI 依赖注入函数（生成器模式）
- init_db: 初始化数据库表结构

各模块按需调用，避免重复代码。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .db_config import get_db_url, get_db_path


# 全局基类（所有模块共享同一个 Base 类型，但各自有独立的 metadata）
Base = declarative_base()


def create_module_engine(
    module_name: str,
    db_name: Optional[str] = None,
    echo: bool = False,
    pool_pre_ping: bool = True,
):
    """创建模块级别的 SQLAlchemy engine.

    Args:
        module_name: 模块名称
        db_name: 数据库名（可选）
        echo: 是否打印 SQL 语句
        pool_pre_ping: 是否启用连接前检测

    Returns:
        SQLAlchemy Engine 实例
    """
    db_url = get_db_url(module_name, db_name)

    # 确保数据库目录存在
    db_path = get_db_path(module_name, db_name)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        db_url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        connect_args={"check_same_thread": False},  # SQLite 多线程支持
    )
    return engine


def create_session_factory(engine) -> sessionmaker:
    """创建 session 工厂.

    Args:
        engine: SQLAlchemy engine

    Returns:
        sessionmaker 实例
    """
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine, base=Base) -> None:
    """初始化数据库表结构.

    自动创建所有继承自 base 的模型对应的表。
    已存在的表不会被修改（安全的幂等操作）。

    Args:
        engine: SQLAlchemy engine
        base: 声明式基类（默认使用全局 Base）
    """
    base.metadata.create_all(bind=engine)


@contextmanager
def get_session(session_factory: sessionmaker) -> Generator[Session, None, None]:
    """上下文管理器方式获取数据库 session.

    自动提交和回滚，使用完自动关闭。

    示例:
        with get_session(SessionLocal) as db:
            db.query(User).all()
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_dependency(session_factory: sessionmaker):
    """生成 FastAPI 依赖注入用的数据库 session 生成器.

    Args:
        session_factory: session 工厂

    Returns:
        可用于 FastAPI Depends 的生成器函数

    示例:
        get_db = get_db_dependency(SessionLocal)

        @app.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """

    def _get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _get_db


def table_exists(engine, table_name: str) -> bool:
    """检查数据库中是否存在指定表.

    Args:
        engine: SQLAlchemy engine
        table_name: 表名

    Returns:
        True 表示表存在
    """
    from sqlalchemy import inspect
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def get_table_count(engine, table_name: str) -> int:
    """获取表的记录数.

    Args:
        engine: SQLAlchemy engine
        table_name: 表名

    Returns:
        记录数，表不存在返回 0
    """
    if not table_exists(engine, table_name):
        return 0
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        return result.scalar() or 0
