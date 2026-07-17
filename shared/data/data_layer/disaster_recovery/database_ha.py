"""
云汐数据库高可用模块 (Database High Availability)

提供 SQLite 数据库高可用优化：
- WAL 模式优化配置
- 连接池管理
- 读写分离设计（概念设计，SQLite 限制下的方案）
- 数据库故障检测和自动恢复

使用方式：
    from data_layer.disaster_recovery.database_ha import DatabaseHA, WALConfig

    dha = DatabaseHA(db_path="./data/mydb.db")
    dha.optimize_wal()
    dha.start_health_monitor()
"""

from __future__ import annotations

import time
import sqlite3
import threading
import logging
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from queue import Queue
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class DBHealthStatus(str, Enum):
    """数据库健康状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class WALConfig:
    """WAL 模式配置"""
    enabled: bool = True
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"      # NORMAL/FULL/OFF
    wal_autocheckpoint: int = 1000    # 自动检查点页数
    busy_timeout: int = 5000          # 锁等待超时（毫秒）
    mmap_size: int = 30000000000      # 内存映射大小（30GB）
    cache_size: int = -20000          # 缓存大小（负=KB，正=页数）
    temp_store: str = "MEMORY"        # 临时表存储

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "journal_mode": self.journal_mode,
            "synchronous": self.synchronous,
            "wal_autocheckpoint": self.wal_autocheckpoint,
            "busy_timeout": self.busy_timeout,
            "mmap_size": self.mmap_size,
            "cache_size": self.cache_size,
            "temp_store": self.temp_store,
        }


@dataclass
class ConnectionPoolConfig:
    """连接池配置"""
    max_connections: int = 10
    min_connections: int = 2
    max_idle_time: float = 300.0      # 最大空闲时间（秒）
    acquire_timeout: float = 10.0     # 获取连接超时（秒）
    connection_timeout: float = 5.0   # 连接超时（秒）
    auto_reconnect: bool = True       # 自动重连
    test_on_borrow: bool = True       # 借出时测试连接
    test_on_return: bool = False      # 归还时测试

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_connections": self.max_connections,
            "min_connections": self.min_connections,
            "max_idle_time": self.max_idle_time,
            "acquire_timeout": self.acquire_timeout,
            "connection_timeout": self.connection_timeout,
            "auto_reconnect": self.auto_reconnect,
            "test_on_borrow": self.test_on_borrow,
            "test_on_return": self.test_on_return,
        }


# ============================================================
# SQLite 连接池
# ============================================================

class SQLiteConnectionPool:
    """
    SQLite 连接池

    由于 SQLite 是文件型数据库，连接池的主要作用是：
    1. 复用连接，减少打开/关闭开销
    2. 限制并发连接数，避免锁竞争
    3. 连接健康检查和自动恢复
    """

    def __init__(
        self,
        db_path: str,
        config: Optional[ConnectionPoolConfig] = None,
    ):
        self.db_path = str(db_path)
        self.config = config or ConnectionPoolConfig()

        self._pool: Queue = Queue(maxsize=self.config.max_connections)
        self._active_connections: Dict[int, float] = {}  # id -> 借出时间
        self._lock = threading.Lock()
        self._total_created = 0
        self._total_borrowed = 0
        self._total_returned = 0
        self._closed = False

        # 初始化最小连接数
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """初始化连接池"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self.config.min_connections):
            conn = self._create_connection()
            if conn:
                self._pool.put((conn, time.time()))

    def _create_connection(self) -> Optional[sqlite3.Connection]:
        """创建新连接"""
        try:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.config.connection_timeout,
                check_same_thread=False,
                isolation_level=None,  # 自动提交模式
            )
            # 配置连接
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {self.config.connection_timeout * 1000}")
            self._total_created += 1
            return conn
        except Exception as e:
            logger.error("Failed to create SQLite connection: %s", e)
            return None

    def _is_connection_alive(self, conn: sqlite3.Connection) -> bool:
        """检查连接是否可用"""
        try:
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def borrow(self) -> Optional[sqlite3.Connection]:
        """借出连接"""
        if self._closed:
            return None

        start_time = time.time()

        while time.time() - start_time < self.config.acquire_timeout:
            try:
                # 尝试从池获取
                conn, create_time = self._pool.get_nowait()

                # 检查连接是否健康
                if self.config.test_on_borrow and not self._is_connection_alive(conn):
                    try:
                        conn.close()
                    except Exception:
                        pass
                    # 尝试创建新连接
                    new_conn = self._create_connection()
                    if new_conn:
                        with self._lock:
                            self._active_connections[id(new_conn)] = time.time()
                            self._total_borrowed += 1
                        return new_conn
                    continue

                # 检查是否超时
                if time.time() - create_time > self.config.max_idle_time:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    new_conn = self._create_connection()
                    if new_conn:
                        with self._lock:
                            self._active_connections[id(new_conn)] = time.time()
                            self._total_borrowed += 1
                        return new_conn
                    continue

                with self._lock:
                    self._active_connections[id(conn)] = time.time()
                    self._total_borrowed += 1
                return conn

            except Exception:
                # 池空了，创建新连接
                with self._lock:
                    active_count = len(self._active_connections)

                if active_count < self.config.max_connections:
                    new_conn = self._create_connection()
                    if new_conn:
                        with self._lock:
                            self._active_connections[id(new_conn)] = time.time()
                            self._total_borrowed += 1
                        return new_conn

                # 等待一下再试
                time.sleep(0.1)

        logger.warning("Connection pool exhausted for %s", self.db_path)
        return None

    def return_conn(self, conn: sqlite3.Connection) -> None:
        """归还连接"""
        if self._closed or conn is None:
            return

        with self._lock:
            self._active_connections.pop(id(conn), None)
            self._total_returned += 1

        # 测试连接
        if self.config.test_on_return and not self._is_connection_alive(conn):
            try:
                conn.close()
            except Exception:
                pass
            return

        try:
            self._pool.put_nowait((conn, time.time()))
        except Exception:
            # 池满了，关闭连接
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        """关闭连接池"""
        self._closed = True

        # 关闭池中的连接
        while not self._pool.empty():
            try:
                conn, _ = self._pool.get_nowait()
                conn.close()
            except Exception:
                pass

        # 关闭活跃连接（尽量）
        with self._lock:
            pass  # 活跃连接由调用方负责

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        with self._lock:
            active_count = len(self._active_connections)

        return {
            "db_path": self.db_path,
            "pool_size": self._pool.qsize(),
            "active_connections": active_count,
            "total_created": self._total_created,
            "total_borrowed": self._total_borrowed,
            "total_returned": self._total_returned,
            "max_connections": self.config.max_connections,
            "min_connections": self.config.min_connections,
            "closed": self._closed,
        }


# ============================================================
# 数据库高可用管理器
# ============================================================

class DatabaseHA:
    """
    数据库高可用管理器

    提供：
    - WAL 模式优化
    - 连接池管理
    - 健康监控
    - 故障检测与自动恢复
    - 读写分离（概念设计层）
    """

    def __init__(
        self,
        db_path: str,
        wal_config: Optional[WALConfig] = None,
        pool_config: Optional[ConnectionPoolConfig] = None,
        auto_recovery: bool = True,
        health_check_interval: float = 30.0,
    ):
        self.db_path = str(db_path)
        self.wal_config = wal_config or WALConfig()
        self.pool_config = pool_config or ConnectionPoolConfig()
        self.auto_recovery = auto_recovery
        self.health_check_interval = health_check_interval

        self._pool: Optional[SQLiteConnectionPool] = None
        self._health_status = DBHealthStatus.UNKNOWN
        self._last_health_check: float = 0.0
        self._consecutive_failures: int = 0
        self._recovery_count: int = 0
        self._lock = threading.RLock()

        # 监控线程
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()

        # 回调
        self._on_failure_callbacks: List[Callable[[str], None]] = []
        self._on_recovery_callbacks: List[Callable[[str], None]] = []
        self._on_status_change_callbacks: List[Callable[[DBHealthStatus, DBHealthStatus], None]] = []

    # ------------------------------------------------------------------
    #  初始化
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """初始化数据库高可用配置"""
        try:
            # 确保目录存在
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            # 优化 WAL 配置
            self.optimize_wal()

            # 初始化连接池
            self._pool = SQLiteConnectionPool(self.db_path, self.pool_config)

            # 初始健康检查
            self._update_health_status(DBHealthStatus.HEALTHY)
            logger.info("Database HA initialized: %s", self.db_path)
            return True

        except Exception as e:
            logger.error("Database HA initialization failed: %s", e)
            self._update_health_status(DBHealthStatus.UNHEALTHY)
            return False

    def optimize_wal(self) -> Dict[str, Any]:
        """
        优化 WAL 模式配置

        返回应用的配置。
        """
        results: Dict[str, Any] = {}

        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            cursor = conn.cursor()

            # 启用 WAL 模式
            cursor.execute(f"PRAGMA journal_mode = {self.wal_config.journal_mode}")
            results["journal_mode"] = cursor.fetchone()[0]

            # 设置同步级别
            cursor.execute(f"PRAGMA synchronous = {self.wal_config.synchronous}")

            # WAL 自动检查点
            cursor.execute(f"PRAGMA wal_autocheckpoint = {self.wal_config.wal_autocheckpoint}")

            # 繁忙超时
            cursor.execute(f"PRAGMA busy_timeout = {self.wal_config.busy_timeout}")

            # 内存映射
            cursor.execute(f"PRAGMA mmap_size = {self.wal_config.mmap_size}")

            # 缓存大小
            cursor.execute(f"PRAGMA cache_size = {self.wal_config.cache_size}")

            # 临时存储
            cursor.execute(f"PRAGMA temp_store = {self.wal_config.temp_store}")

            conn.commit()
            conn.close()

            results["success"] = True
            results["config"] = self.wal_config.to_dict()
            logger.info("WAL optimization applied for %s", self.db_path)

        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            logger.error("WAL optimization failed: %s", e)

        return results

    # ------------------------------------------------------------------
    #  连接池接口
    # ------------------------------------------------------------------

    def get_connection(self) -> Optional[sqlite3.Connection]:
        """获取数据库连接（从连接池）"""
        if self._pool is None:
            # 懒初始化
            self.initialize()

        if self._pool is None:
            return None

        conn = self._pool.borrow()
        if conn is None and self.auto_recovery:
            # 连接获取失败，尝试恢复
            self._attempt_recovery()
            if self._pool:
                conn = self._pool.borrow()

        return conn

    def release_connection(self, conn: sqlite3.Connection) -> None:
        """归还数据库连接"""
        if self._pool and conn:
            self._pool.return_conn(conn)

    def execute_query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """执行查询（便捷方法）"""
        conn = self.get_connection()
        if not conn:
            raise RuntimeError("Failed to get database connection")

        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
            return rows
        finally:
            self.release_connection(conn)

    def execute_update(self, sql: str, params: tuple = ()) -> int:
        """执行更新（便捷方法）"""
        conn = self.get_connection()
        if not conn:
            raise RuntimeError("Failed to get database connection")

        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
        finally:
            self.release_connection(conn)

    # ------------------------------------------------------------------
    #  健康监控
    # ------------------------------------------------------------------

    def start_health_monitor(self) -> bool:
        """启动健康监控"""
        if self._pool is None:
            self.initialize()

        if self._monitor_thread and self._monitor_thread.is_alive():
            return True

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name=f"DBHealthMonitor-{Path(self.db_path).stem}",
            daemon=True,
        )
        self._monitor_thread.start()
        logger.info("Database health monitor started: %s", self.db_path)
        return True

    def stop_health_monitor(self) -> None:
        """停止健康监控"""
        self._monitor_stop.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

    def _monitor_loop(self) -> None:
        """监控循环"""
        while not self._monitor_stop.is_set():
            try:
                self._perform_health_check()
            except Exception as e:
                logger.error("DB health monitor error: %s", e)

            self._monitor_stop.wait(self.health_check_interval)

    def _perform_health_check(self) -> DBHealthStatus:
        """执行健康检查"""
        self._last_health_check = time.time()

        try:
            conn = sqlite3.connect(self.db_path, timeout=3)
            cursor = conn.cursor()

            # 基本连通性测试
            cursor.execute("SELECT 1")
            cursor.fetchone()

            # WAL 状态
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]

            # 检查数据库大小
            cursor.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            db_size = page_count * page_size

            # 快速完整性检查
            cursor.execute("PRAGMA quick_check")
            quick_result = cursor.fetchone()[0]

            conn.close()

            if quick_result == "ok":
                self._consecutive_failures = 0
                new_status = DBHealthStatus.HEALTHY
            else:
                self._consecutive_failures += 1
                new_status = DBHealthStatus.DEGRADED

            self._update_health_status(new_status)
            return new_status

        except Exception as e:
            self._consecutive_failures += 1
            logger.warning("DB health check failed (%d): %s", self._consecutive_failures, e)

            if self._consecutive_failures >= 3:
                self._update_health_status(DBHealthStatus.UNHEALTHY)
                if self.auto_recovery:
                    self._attempt_recovery()
                self._fire_failure(str(e))

            return DBHealthStatus.UNHEALTHY

    def _update_health_status(self, new_status: DBHealthStatus) -> None:
        """更新健康状态"""
        old_status = self._health_status
        if old_status != new_status:
            self._health_status = new_status
            logger.info("DB health status changed: %s -> %s (%s)",
                        old_status.value, new_status.value, self.db_path)
            self._fire_status_change(old_status, new_status)

            if new_status == DBHealthStatus.HEALTHY and old_status in (
                DBHealthStatus.UNHEALTHY, DBHealthStatus.RECOVERING
            ):
                self._fire_recovery()

    # ------------------------------------------------------------------
    #  故障恢复
    # ------------------------------------------------------------------

    def _attempt_recovery(self) -> bool:
        """尝试自动恢复数据库"""
        with self._lock:
            if self._health_status == DBHealthStatus.RECOVERING:
                return False

            self._update_health_status(DBHealthStatus.RECOVERING)
            self._recovery_count += 1

        try:
            # 恢复步骤1：尝试重新建立连接
            if self._pool:
                self._pool.close()

            # 恢复步骤2：重新初始化
            self._pool = SQLiteConnectionPool(self.db_path, self.pool_config)

            # 恢复步骤3：验证
            conn = self._pool.borrow()
            if conn:
                conn.execute("SELECT 1")
                self._pool.return_conn(conn)
                self._update_health_status(DBHealthStatus.HEALTHY)
                self._consecutive_failures = 0
                logger.info("Database recovered successfully: %s", self.db_path)
                return True
            else:
                self._update_health_status(DBHealthStatus.UNHEALTHY)
                return False

        except Exception as e:
            logger.error("Database recovery failed: %s", e)
            self._update_health_status(DBHealthStatus.UNHEALTHY)
            return False

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def on_failure(self, callback: Callable[[str], None]) -> None:
        self._on_failure_callbacks.append(callback)

    def on_recovery(self, callback: Callable[[str], None]) -> None:
        self._on_recovery_callbacks.append(callback)

    def on_status_change(self, callback: Callable[[DBHealthStatus, DBHealthStatus], None]) -> None:
        self._on_status_change_callbacks.append(callback)

    def _fire_failure(self, error: str) -> None:
        for cb in self._on_failure_callbacks:
            try:
                cb(error)
            except Exception as e:
                logger.error("Failure callback error: %s", e)

    def _fire_recovery(self) -> None:
        for cb in self._on_recovery_callbacks:
            try:
                cb(self.db_path)
            except Exception as e:
                logger.error("Recovery callback error: %s", e)

    def _fire_status_change(self, old: DBHealthStatus, new: DBHealthStatus) -> None:
        for cb in self._on_status_change_callbacks:
            try:
                cb(old, new)
            except Exception as e:
                logger.error("Status change callback error: %s", e)

    # ------------------------------------------------------------------
    #  读写分离（概念设计层）
    # ------------------------------------------------------------------

    def get_read_connection(self) -> Optional[sqlite3.Connection]:
        """
        获取读连接（读写分离概念设计）

        由于 SQLite 是单文件数据库，真正的读写分离需要复制机制。
        这里提供统一的接口，为未来扩展预留。
        当前实现：复用主连接池，但标记为只读事务优化。
        """
        conn = self.get_connection()
        if conn:
            try:
                # 设置为只读事务模式（优化查询）
                conn.execute("PRAGMA query_only = ON")
            except Exception:
                pass
        return conn

    def get_write_connection(self) -> Optional[sqlite3.Connection]:
        """获取写连接"""
        conn = self.get_connection()
        if conn:
            try:
                conn.execute("PRAGMA query_only = OFF")
            except Exception:
                pass
        return conn

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    @property
    def health_status(self) -> DBHealthStatus:
        """当前健康状态"""
        return self._health_status

    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self._health_status == DBHealthStatus.HEALTHY

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        db_size = 0
        wal_size = 0
        journal_mode = "unknown"

        try:
            if Path(self.db_path).exists():
                db_size = Path(self.db_path).stat().st_size

            wal_file = Path(self.db_path + "-wal")
            if wal_file.exists():
                wal_size = wal_file.stat().st_size

            conn = sqlite3.connect(self.db_path, timeout=2)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            conn.close()
        except Exception:
            pass

        pool_stats = self._pool.get_stats() if self._pool else {}

        return {
            "db_path": self.db_path,
            "health_status": self._health_status.value,
            "last_health_check": self._last_health_check,
            "consecutive_failures": self._consecutive_failures,
            "recovery_count": self._recovery_count,
            "db_size_bytes": db_size,
            "wal_size_bytes": wal_size,
            "journal_mode": journal_mode,
            "auto_recovery": self.auto_recovery,
            "pool_stats": pool_stats,
            "wal_config": self.wal_config.to_dict(),
        }

    def shutdown(self) -> None:
        """关闭数据库高可用管理器"""
        self.stop_health_monitor()
        if self._pool:
            self._pool.close()
            self._pool = None
