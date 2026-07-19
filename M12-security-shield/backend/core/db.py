"""
云汐 M12 安全盾 - 数据库连接管理模块

统一管理数据库连接、连接池配置、会话管理和重试机制，
确保数据库资源的正确释放和连接的可靠性。

设计原则：
1. 所有数据库操作使用上下文管理器（with 语句）
2. SQLAlchemy session 正确关闭
3. 连接池配置优化
4. 长连接添加超时和重试机制
5. 统一的数据库操作异常处理
"""

import logging
import time
import threading
from contextlib import contextmanager
from typing import Generator, Optional, Any, Callable
from functools import wraps

logger = logging.getLogger(__name__)

# 兼容相对导入和直接运行
try:
    from ..database import SessionLocal, engine, Base, init_db, get_db
    from ..config import get_settings
except ImportError:
    from database import SessionLocal, engine, Base, init_db, get_db
    from config import get_settings

from sqlalchemy.orm import Session
from sqlalchemy.exc import (
    SQLAlchemyError,
    OperationalError,
    IntegrityError,
    TimeoutError as SA_TimeoutError,
)


# ===========================================================================
# 数据库操作异常类
# ===========================================================================

class DatabaseError(Exception):
    """数据库操作基础异常"""
    pass


class DatabaseConnectionError(DatabaseError):
    """数据库连接异常"""
    pass


class DatabaseTimeoutError(DatabaseError):
    """数据库操作超时异常"""
    pass


class DatabaseIntegrityError(DatabaseError):
    """数据库完整性约束异常"""
    pass


# ===========================================================================
# 重试装饰器
# ===========================================================================

def db_retry(
    max_retries: int = 3,
    retry_delay: float = 0.5,
    backoff: float = 2.0,
    retry_on_exceptions: tuple = (OperationalError, SA_TimeoutError),
):
    """数据库操作重试装饰器

    对临时的数据库连接错误进行自动重试，提高系统稳定性。

    Args:
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        backoff: 退避因子（每次重试延迟乘以此因子）
        retry_on_exceptions: 需要重试的异常类型

    Usage:
        @db_retry(max_retries=3)
        def my_db_operation():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = retry_delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            "数据库操作失败，正在重试 (%d/%d): %s, 延迟 %.2f 秒",
                            attempt + 1, max_retries, e, delay,
                        )
                        time.sleep(delay)
                        delay *= backoff
                    else:
                        logger.error(
                            "数据库操作失败，已达最大重试次数 (%d): %s",
                            max_retries, e, exc_info=True,
                        )
                except IntegrityError as e:
                    # 完整性错误不重试
                    logger.error("数据库完整性错误: %s", e, exc_info=True)
                    raise DatabaseIntegrityError(str(e)) from e
                except SQLAlchemyError as e:
                    # 其他 SQLAlchemy 错误不重试
                    logger.error("数据库操作错误: %s", e, exc_info=True)
                    raise DatabaseError(str(e)) from e

            raise DatabaseConnectionError(
                f"数据库操作失败，重试 {max_retries} 次后仍失败: {last_exception}"
            ) from last_exception

        return wrapper
    return decorator


# ===========================================================================
# 数据库会话管理
# ===========================================================================

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """获取数据库会话（上下文管理器，自动关闭）

    确保会话在使用后正确关闭，防止连接泄漏。
    提供统一的异常处理和日志记录。

    Yields:
        Session: 数据库会话对象

    Raises:
        DatabaseError: 数据库操作异常
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except IntegrityError as e:
        session.rollback()
        logger.error("数据库完整性错误: %s", e, exc_info=True)
        raise DatabaseIntegrityError(str(e)) from e
    except OperationalError as e:
        session.rollback()
        logger.error("数据库连接错误: %s", e, exc_info=True)
        raise DatabaseConnectionError(str(e)) from e
    except SQLAlchemyError as e:
        session.rollback()
        logger.error("数据库操作错误: %s", e, exc_info=True)
        raise DatabaseError(str(e)) from e
    except Exception as e:
        session.rollback()
        logger.error("数据库操作未知错误: %s", e, exc_info=True)
        raise
    finally:
        session.close()


@contextmanager
def get_db_session_readonly() -> Generator[Session, None, None]:
    """获取只读数据库会话（上下文管理器）

    用于只读操作，自动回滚（不提交），确保数据一致性。

    Yields:
        Session: 数据库会话对象
    """
    session = SessionLocal()
    try:
        yield session
        # 只读操作不提交，直接回滚
        session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_with_retry(
    operation: Callable[[Session], Any],
    max_retries: int = 3,
    retry_delay: float = 0.5,
    readonly: bool = False,
) -> Any:
    """执行数据库操作并自动重试

    Args:
        operation: 数据库操作函数，接收 session 参数
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟
        readonly: 是否为只读操作

    Returns:
        操作结果
    """
    last_exception = None
    delay = retry_delay

    for attempt in range(max_retries + 1):
        try:
            if readonly:
                with get_db_session_readonly() as session:
                    return operation(session)
            else:
                with get_db_session() as session:
                    return operation(session)
        except (OperationalError, SA_TimeoutError, DatabaseConnectionError) as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    "数据库操作失败，重试 (%d/%d): %s",
                    attempt + 1, max_retries, e,
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    "数据库操作失败，重试 %d 次后仍失败: %s",
                    max_retries, e, exc_info=True,
                )
                raise

    raise last_exception  # type: ignore


# ===========================================================================
# 连接池配置与优化
# ===========================================================================

def configure_connection_pool() -> None:
    """配置数据库连接池参数

    优化连接池配置，防止连接泄漏和资源耗尽。
    对于 SQLite，使用 NullPool 或 StaticPool。
    对于生产数据库，使用 QueuePool 并配置合理的池大小。
    """
    from sqlalchemy import event

    settings = get_settings()
    db_url = settings.database_url

    if db_url.startswith('sqlite'):
        # SQLite 使用静态池或空池（取决于使用场景）
        # 已经在 database.py 中配置了 check_same_thread=False
        logger.info("SQLite 数据库连接池配置: check_same_thread=False, timeout=30")
    else:
        # 生产数据库连接池配置
        logger.info("数据库连接池配置: pool_size=10, max_overflow=20, pool_recycle=3600")

    # 注册连接事件监听器
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        logger.debug("数据库连接已建立")

    @event.listens_for(engine, "checkout")
    def _on_checkout(dbapi_connection, connection_record, connection_proxy):
        logger.debug("数据库连接已检出")

    @event.listens_for(engine, "checkin")
    def _on_checkin(dbapi_connection, connection_record):
        logger.debug("数据库连接已归还")


# ===========================================================================
# 数据库健康检查
# ===========================================================================

def check_db_health() -> dict:
    """检查数据库健康状态

    Returns:
        健康状态字典
    """
    result = {
        "status": "unknown",
        "response_time_ms": 0,
        "error": None,
    }

    start_time = time.time()
    try:
        with get_db_session_readonly() as session:
            # 执行简单的查询来验证连接
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
# 数据库连接统计
# ===========================================================================

class DBConnectionStats:
    """数据库连接统计信息

    跟踪数据库操作的性能和错误统计，用于监控和调优。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._total_operations = 0
        self._total_errors = 0
        self._total_retries = 0
        self._total_time_ms = 0.0
        self._slow_queries = 0
        self._slow_threshold_ms = 1000.0  # 慢查询阈值

    def record_operation(self, duration_ms: float, has_error: bool = False, retries: int = 0):
        """记录一次数据库操作

        Args:
            duration_ms: 操作耗时（毫秒）
            has_error: 是否发生错误
            retries: 重试次数
        """
        with self._lock:
            self._total_operations += 1
            self._total_time_ms += duration_ms
            self._total_retries += retries
            if has_error:
                self._total_errors += 1
            if duration_ms > self._slow_threshold_ms:
                self._slow_queries += 1

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            avg_time = (
                self._total_time_ms / self._total_operations
                if self._total_operations > 0 else 0
            )
            error_rate = (
                self._total_errors / self._total_operations
                if self._total_operations > 0 else 0
            )
            return {
                "total_operations": self._total_operations,
                "total_errors": self._total_errors,
                "total_retries": self._total_retries,
                "error_rate": error_rate,
                "avg_response_time_ms": avg_time,
                "slow_queries": self._slow_queries,
                "slow_threshold_ms": self._slow_threshold_ms,
            }

    def reset(self):
        """重置统计"""
        with self._lock:
            self._total_operations = 0
            self._total_errors = 0
            self._total_retries = 0
            self._total_time_ms = 0.0
            self._slow_queries = 0


# 全局统计实例
_db_stats = DBConnectionStats()


def get_db_stats() -> DBConnectionStats:
    """获取数据库统计实例"""
    return _db_stats


# ===========================================================================
# 带统计的会话装饰器
# ===========================================================================

@contextmanager
def tracked_db_session(readonly: bool = False) -> Generator[Session, None, None]:
    """带统计的数据库会话（上下文管理器）

    自动记录操作耗时和错误统计。

    Args:
        readonly: 是否为只读操作

    Yields:
        Session: 数据库会话对象
    """
    start_time = time.time()
    has_error = False
    retries = 0

    try:
        if readonly:
            with get_db_session_readonly() as session:
                yield session
        else:
            with get_db_session() as session:
                yield session
    except Exception:
        has_error = True
        raise
    finally:
        duration_ms = (time.time() - start_time) * 1000
        _db_stats.record_operation(duration_ms, has_error, retries)


# ===========================================================================
# 数据库初始化辅助函数
# ===========================================================================

def safe_init_db(retry_count: int = 3, retry_delay: float = 1.0) -> bool:
    """安全初始化数据库（带错误处理和重试）

    Args:
        retry_count: 最大重试次数
        retry_delay: 初始重试延迟（秒）

    Returns:
        True 表示初始化成功，False 表示失败
    """
    max_retries = retry_count
    delay = retry_delay

    for attempt in range(max_retries):
        try:
            init_db()
            logger.info("数据库初始化成功")
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
                logger.critical("数据库初始化失败: %s", e, exc_info=True)
                return False

    return False


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== 数据库连接管理测试 ===")

    # 测试健康检查
    print("\n1. 数据库健康检查:")
    health = check_db_health()
    print(f"   状态: {health['status']}")
    print(f"   响应时间: {health['response_time_ms']:.2f} ms")

    # 测试会话管理
    print("\n2. 数据库会话测试:")
    try:
        with get_db_session() as db:
            result = db.execute("SELECT 1 as test").fetchone()
            print(f"   查询结果: {result}")
    except Exception as e:
        print(f"   错误: {e}")

    # 测试统计
    print("\n3. 连接统计:")
    stats = _db_stats.get_stats()
    print(f"   总操作数: {stats['total_operations']}")
    print(f"   错误数: {stats['total_errors']}")
    print(f"   平均响应时间: {stats['avg_response_time_ms']:.2f} ms")

    print("\n所有测试完成!")
