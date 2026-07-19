"""
云汐 M12 安全盾 - 数据库连接模块
负责数据库引擎创建、会话管理和基础连接配置
使用 SQLAlchemy 2.0 + SQLite

安全加固（P2 架构解债）：
1. 连接池配置优化，防止连接泄漏
2. 统一的会话管理（上下文管理器 + 依赖注入）
3. 连接超时和重试机制
4. 数据库操作异常标准化
"""

import logging
import time
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 兼容相对导入和直接运行
try:
    from .config import get_settings
except ImportError:
    from config import get_settings

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError


# ===== 数据库初始化 =====
settings = get_settings()

# 数据库连接配置
DB_CONNECT_ARGS = {
    "check_same_thread": False,  # SQLite 多线程支持
    "timeout": 30,               # 写操作超时（秒）
    "isolation_level": None,     # 使用默认隔离级别
}

# 创建数据库引擎（带连接池配置）
# 对于 SQLite，使用 StaticPool 确保线程安全和连接复用
# 对于生产数据库，使用 QueuePool 并配置合理的池大小
engine = create_engine(
    settings.database_url,
    connect_args=DB_CONNECT_ARGS,
    echo=False,  # 生产环境不输出 SQL（debug 默认 True 会泄露查询参数）
    # SQLite 默认使用 StaticPool（单连接），这里显式配置以确保可预期的行为
    pool_pre_ping=False,  # SQLite 不支持 pool_pre_ping
    future=True,         # 使用 SQLAlchemy 2.0 风格
)

# 会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # 提交后不过期对象，方便后续使用
)

# 声明基类
Base = declarative_base()


# ===========================================================================
# 连接事件监听器（用于监控和故障恢复）
# ===========================================================================

@event.listens_for(engine, "connect")
def _on_db_connect(dbapi_connection, connection_record):
    """数据库连接建立时触发"""
    logger.debug("数据库连接已建立")


@event.listens_for(engine, "checkout")
def _on_db_checkout(dbapi_connection, connection_record, connection_proxy):
    """数据库连接检出时触发（连接池）"""
    logger.debug("数据库连接已检出")


@event.listens_for(engine, "checkin")
def _on_db_checkin(dbapi_connection, connection_record):
    """数据库连接归还时触发（连接池）"""
    logger.debug("数据库连接已归还")


# ===========================================================================
# 会话管理
# ===========================================================================

def get_db():
    """获取数据库会话（依赖注入用）

    用于 FastAPI 的 Depends 依赖注入，自动管理会话生命周期。
    确保在请求结束时关闭会话，防止连接泄漏。

    Yields:
        Session: 数据库会话对象
    """
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        logger.error("数据库操作错误: %s", e, exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_session():
    """获取数据库会话（上下文管理器，自动关闭）

    用于非依赖注入场景的数据库操作，确保会话正确关闭。
    自动提交成功的事务，异常时回滚。

    Yields:
        Session: 数据库会话对象

    Raises:
        SQLAlchemyError: 数据库操作异常
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_session_readonly():
    """获取只读数据库会话（上下文管理器）

    用于只读操作，自动回滚（不提交），确保数据一致性。

    Yields:
        Session: 数据库会话对象
    """
    session = SessionLocal()
    try:
        yield session
        session.rollback()  # 只读操作不提交
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# ===========================================================================
# 数据库健康检查
# ===========================================================================

def check_database_health() -> dict:
    """检查数据库健康状态

    Returns:
        健康状态字典 {status, response_time_ms, error}
    """
    result = {
        "status": "unknown",
        "response_time_ms": 0,
        "error": None,
    }

    start_time = time.time()
    try:
        with get_session_readonly() as session:
            session.execute("SELECT 1")
            result["status"] = "healthy"
    except Exception as e:
        result["status"] = "unhealthy"
        result["error"] = str(e)
        logger.error("数据库健康检查失败: %s", e)
    finally:
        result["response_time_ms"] = (time.time() - start_time) * 1000

    return result


# ===========================================================================
# 数据库初始化
# ===========================================================================

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


def safe_init_db(max_retries: int = 3, retry_delay: float = 1.0) -> bool:
    """安全初始化数据库（带重试机制）

    Args:
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）

    Returns:
        True 表示初始化成功，False 表示失败
    """
    delay = retry_delay
    for attempt in range(max_retries):
        try:
            init_db()
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    "数据库初始化失败，重试 (%d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.critical("数据库初始化失败，已达最大重试次数: %s", e, exc_info=True)
                return False
    return False


# 兼容直接运行：测试数据库连接
if __name__ == "__main__":
    init_db()
    logger.info("数据库已初始化: %s", settings.db_path)
    logger.info("数据库连接测试通过")

    # 健康检查
    health = check_database_health()
    logger.info("数据库健康状态: %s (%.2f ms)", health["status"], health["response_time_ms"])

    logger.info("已创建表:")
    for table in Base.metadata.tables:
        logger.info("  - %s", table)
