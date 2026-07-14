"""
云汐 M12 安全盾 - 数据库连接模块
负责数据库引擎创建、会话管理和基础连接配置
使用 SQLAlchemy 2.0 + SQLite
"""

import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

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
    connect_args={"check_same_thread": False, "timeout": 30},  # SQLite 多线程支持 + 写超时
    echo=False,  # 生产环境不输出 SQL（debug 默认 True 会泄露查询参数）
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


@contextmanager
def get_session():
    """获取数据库会话（上下文管理器，自动关闭）
    
    用于非依赖注入场景的数据库操作，确保会话正确关闭。
    
    Yields:
        Session: 数据库会话对象
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """初始化数据库，创建所有表

    延迟导入模型以避免循环引用问题
    """
    try:
        from . import models
    except ImportError:
        import models
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully at: %s", settings.db_path)
    except Exception as e:
        logger.error("Failed to initialize database: %s", e, exc_info=True)
        raise


# 兼容直接运行：测试数据库连接
if __name__ == "__main__":
    init_db()
    logger.info("数据库已初始化: %s", settings.db_path)
    logger.info("数据库连接测试通过")
    logger.info("已创建表:")
    for table in Base.metadata.tables:
        logger.info("  - %s", table)
