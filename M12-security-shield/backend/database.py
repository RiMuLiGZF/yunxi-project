"""
云汐 M12 安全盾 - 数据库连接模块
负责数据库引擎创建、会话管理和基础连接配置
使用 SQLAlchemy 2.0 + SQLite
"""

import sys
from pathlib import Path

# 兼容相对导入和直接运行
try:
    from .config import get_settings
except ImportError:
    from config import get_settings

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ===== 数据库初始化 =====
settings = get_settings()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
    echo=settings.debug,
)

# 会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# 声明基类
Base = declarative_base()


def get_db():
    """获取数据库会话（依赖注入用）

    用于 FastAPI 的 Depends 依赖注入，自动管理会话生命周期

    Yields:
        Session: 数据库会话对象
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """获取数据库会话（同步调用用）

    Returns:
        Session: 新的数据库会话对象
    """
    return SessionLocal()


def init_db() -> None:
    """初始化数据库，创建所有表

    延迟导入模型以避免循环引用问题
    """
    # 延迟导入模型，避免循环引用
    try:
        from . import models  # noqa: F401
    except ImportError:
        import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


# 兼容直接运行：测试数据库连接
if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {settings.db_path}")
    print("数据库连接测试通过")
    print("已创建表:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
