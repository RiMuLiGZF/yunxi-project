"""
云汐 M10 系统卫士 - 数据库连接模块
负责数据库引擎创建、会话管理和基础连接配置
"""

import sys
import os

# 兼容相对导入和直接运行
try:
    from .config import get_settings
except ImportError:
    from config import get_settings

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# ===== 数据库初始化 =====
settings = get_settings()
engine = create_engine(
    settings.get_db_url(),
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
    echo=settings.debug,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话（依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """获取数据库会话（同步调用用）"""
    return SessionLocal()


def init_db():
    """初始化数据库，创建所有表"""
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
