"""
数据库连接管理
==============

提供统一的数据库连接配置、健康检查和重试机制。

核心组件：
- DatabaseConfig: 数据库连接配置
- DatabaseManager: 数据库连接管理器
- retry_on_db_error: 数据库操作重试装饰器
- health_check: 数据库健康检查

支持的数据库：
- SQLite（主要支持）
- PostgreSQL（预留接口）
"""

from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Type

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError

logger = logging.getLogger(__name__)


# ============================================================
# 数据库类型枚举
# ============================================================

class DatabaseType(str, Enum):
    """数据库类型"""
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """
    数据库连接配置。

    Attributes:
        db_type: 数据库类型
        db_path: SQLite 数据库文件路径（SQLite 专用）
        host: 数据库主机（PostgreSQL/MySQL 专用）
        port: 数据库端口
        database: 数据库名
        username: 用户名
        password: 密码
        pool_size: 连接池大小
        max_overflow: 连接池最大溢出数
        pool_timeout: 连接池超时时间（秒）
        pool_recycle: 连接回收时间（秒）
        pool_pre_ping: 是否在取出连接前 ping 检查
        echo: 是否输出 SQL 日志
        connect_timeout: 连接超时（秒）
        busy_timeout: SQLite 忙超时（毫秒）
        wal_mode: SQLite 是否启用 WAL 模式
        foreign_keys: 是否启用外键约束
    """

    db_type: DatabaseType = DatabaseType.SQLITE
    db_path: str = ":memory:"

    # TCP 数据库配置
    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""

    # 连接池配置
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    pool_pre_ping: bool = False

    # 其他配置
    echo: bool = False
    connect_timeout: int = 30
    busy_timeout: int = 30000  # SQLite 专用（毫秒）
    wal_mode: bool = True  # SQLite 专用
    foreign_keys: bool = True

    def get_database_url(self) -> str:
        """
        获取数据库连接 URL。

        Returns:
            SQLAlchemy 数据库 URL
        """
        if self.db_type == DatabaseType.SQLITE:
            return f"sqlite:///{self.db_path}"
        elif self.db_type == DatabaseType.POSTGRESQL:
            return (
                f"postgresql+psycopg2://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        elif self.db_type == DatabaseType.MYSQL:
            return (
                f"mysql+pymysql://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.database}"
            )
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

    def get_connect_args(self) -> Dict[str, Any]:
        """
        获取 SQLAlchemy connect_args。

        Returns:
            连接参数字典
        """
        if self.db_type == DatabaseType.SQLITE:
            return {
                "check_same_thread": False,
                "timeout": self.connect_timeout,
            }
        else:
            return {
                "connect_timeout": self.connect_timeout,
            }


# ============================================================
# 数据库管理器
# ============================================================

class DatabaseManager:
    """
    统一的数据库连接管理器。

    负责创建 engine、session factory、管理连接生命周期、
    提供健康检查和重试机制。

    使用方式::

        from shared.data_access.connection import DatabaseManager, DatabaseConfig

        config = DatabaseConfig(db_type=DatabaseType.SQLITE, db_path="data/app.db")
        db = DatabaseManager(config)
        db.init_db()  # 初始化，创建所有表

        with db.get_session() as session:
            # 使用 session
            pass

        # 健康检查
        health = db.health_check()
    """

    def __init__(self, config: DatabaseConfig):
        """
        初始化数据库管理器。

        Args:
            config: 数据库配置
        """
        self._config = config
        self._engine = None
        self._SessionLocal = None
        self._Base = declarative_base()

    # ============================================================
    #  初始化
    # ============================================================

    def init_engine(self) -> None:
        """初始化数据库引擎"""
        if self._engine is not None:
            return

        url = self._config.get_database_url()
        connect_args = self._config.get_connect_args()

        engine_kwargs: Dict[str, Any] = {
            "echo": self._config.echo,
            "connect_args": connect_args,
        }

        if self._config.db_type == DatabaseType.SQLITE:
            # SQLite 使用 StaticPool 或 QueuePool 取决于需求
            # 对于内存数据库，必须用 StaticPool
            if self._config.db_path == ":memory:":
                from sqlalchemy.pool import StaticPool
                engine_kwargs["poolclass"] = StaticPool
                engine_kwargs["pool_pre_ping"] = False
            else:
                engine_kwargs["pool_pre_ping"] = self._config.pool_pre_ping
        else:
            engine_kwargs.update({
                "pool_size": self._config.pool_size,
                "max_overflow": self._config.max_overflow,
                "pool_timeout": self._config.pool_timeout,
                "pool_recycle": self._config.pool_recycle,
                "pool_pre_ping": self._config.pool_pre_ping,
            })

        self._engine = create_engine(url, **engine_kwargs)
        self._SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine,
            expire_on_commit=False,
        )

        # SQLite 特定配置
        if self._config.db_type == DatabaseType.SQLITE:
            self._apply_sqlite_settings()

    def _apply_sqlite_settings(self) -> None:
        """应用 SQLite 特定设置"""
        assert self._engine is not None
        with self._engine.connect() as conn:
            if self._config.wal_mode:
                conn.execute(text("PRAGMA journal_mode = WAL"))
            conn.execute(text(f"PRAGMA busy_timeout = {self._config.busy_timeout}"))
            if self._config.foreign_keys:
                conn.execute(text("PRAGMA foreign_keys = ON"))
            conn.commit()

    def init_db(self, base_class: Any = None) -> None:
        """
        初始化数据库，创建所有表。

        Args:
            base_class: SQLAlchemy declarative_base 实例，
                       None 时使用内部的 Base
        """
        self.init_engine()
        base = base_class or self._Base
        base.metadata.create_all(bind=self._engine)
        logger.info("Database initialized: %s", self._config.db_path)

    # ============================================================
    #  Session 管理
    # ============================================================

    @property
    def engine(self):
        """获取 SQLAlchemy engine"""
        if self._engine is None:
            self.init_engine()
        return self._engine

    @property
    def SessionLocal(self):
        """获取 session factory"""
        if self._SessionLocal is None:
            self.init_engine()
        return self._SessionLocal

    @property
    def Base(self):
        """获取 declarative base"""
        return self._Base

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话（上下文管理器）。

        自动管理事务：成功提交，异常回滚，最后关闭。

        Yields:
            SQLAlchemy Session
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session_dependency(self) -> Generator[Session, None, None]:
        """
        FastAPI 依赖注入版本的 session 获取器。

        Yields:
            SQLAlchemy Session
        """
        session = self.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    # ============================================================
    #  健康检查
    # ============================================================

    def health_check(self) -> Dict[str, Any]:
        """
        检查数据库健康状态。

        Returns:
            健康状态字典，包含：
            - status: healthy/unhealthy
            - response_time_ms: 响应时间（毫秒）
            - error: 错误信息（如有）
            - db_type: 数据库类型
            - db_path: 数据库路径（SQLite）
        """
        result: Dict[str, Any] = {
            "status": "unknown",
            "response_time_ms": 0,
            "error": None,
            "db_type": self._config.db_type.value,
        }

        if self._config.db_type == DatabaseType.SQLITE:
            result["db_path"] = self._config.db_path

        start_time = time.time()
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
                result["status"] = "healthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
            logger.error("Database health check failed: %s", e)
        finally:
            result["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

        return result

    def check_connection(self, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        """
        检查数据库连接（带重试）。

        Args:
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            是否连接成功
        """
        delay = retry_delay
        last_error = None

        for attempt in range(max_retries):
            try:
                health = self.health_check()
                if health["status"] == "healthy":
                    return True
                last_error = health.get("error")
            except Exception as e:
                last_error = str(e)

            if attempt < max_retries - 1:
                logger.warning(
                    "Database connection failed (attempt %d/%d), retrying in %.1fs...",
                    attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
                delay *= 2  # 指数退避

        logger.error("Database connection failed after %d attempts: %s", max_retries, last_error)
        return False

    # ============================================================
    #  表管理
    # ============================================================

    def list_tables(self) -> List[str]:
        """列出所有表名"""
        if self._engine is None:
            self.init_engine()
        assert self._engine is not None
        from sqlalchemy import inspect
        inspector = inspect(self._engine)
        return inspector.get_table_names()

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        return table_name in self.list_tables()

    # ============================================================
    #  清理
    # ============================================================

    def dispose(self) -> None:
        """释放数据库连接池资源"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._SessionLocal = None
            logger.info("Database connections disposed")


# ============================================================
# 重试装饰器
# ============================================================

def retry_on_db_error(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    backoff: float = 2.0,
    retry_exceptions: tuple = (OperationalError,),
) -> Callable:
    """
    数据库操作重试装饰器。

    在遇到数据库操作错误时自动重试，使用指数退避。

    Args:
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟（秒）
        backoff: 退避倍数
        retry_exceptions: 需要重试的异常类型

    Returns:
        装饰器函数

    使用方式::

        @retry_on_db_error(max_retries=3)
        def create_user(session, data):
            user = User(**data)
            session.add(user)
            session.commit()
            return user
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = retry_delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            "Database operation failed (attempt %d/%d): %s. "
                            "Retrying in %.1fs...",
                            attempt + 1, max_retries + 1, e, delay,
                        )
                        time.sleep(delay)
                        delay *= backoff
                    else:
                        logger.error(
                            "Database operation failed after %d attempts: %s",
                            max_retries + 1, e,
                        )
                except IntegrityError:
                    # 完整性错误不重试
                    raise

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


# ============================================================
# 便捷函数
# ============================================================

def create_sqlite_manager(
    db_path: str = ":memory:",
    wal_mode: bool = True,
    foreign_keys: bool = True,
    echo: bool = False,
) -> DatabaseManager:
    """
    快速创建 SQLite 数据库管理器。

    Args:
        db_path: 数据库文件路径
        wal_mode: 是否启用 WAL 模式
        foreign_keys: 是否启用外键
        echo: 是否输出 SQL 日志

    Returns:
        DatabaseManager 实例
    """
    config = DatabaseConfig(
        db_type=DatabaseType.SQLITE,
        db_path=db_path,
        wal_mode=wal_mode,
        foreign_keys=foreign_keys,
        echo=echo,
    )
    return DatabaseManager(config)


def create_memory_manager(echo: bool = False) -> DatabaseManager:
    """
    创建内存 SQLite 数据库管理器（用于测试）。

    Args:
        echo: 是否输出 SQL 日志

    Returns:
        DatabaseManager 实例
    """
    return create_sqlite_manager(db_path=":memory:", echo=echo)


# ============================================================
# 导出
# ============================================================

__all__ = [
    "DatabaseType",
    "DatabaseConfig",
    "DatabaseManager",
    "retry_on_db_error",
    "create_sqlite_manager",
    "create_memory_manager",
]
