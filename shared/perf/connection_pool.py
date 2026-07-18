"""
连接池管理 (Connection Pool Manager)

功能:
- 数据库连接池
- 连接复用
- 连接健康检查
- 连接泄漏检测

使用方式::

    from shared.perf.connection_pool import ConnectionPoolManager

    pool = ConnectionPoolManager(
        db_path="/path/to/db.sqlite",
        pool_size=5,
        max_overflow=10,
    )

    conn = pool.acquire()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
    finally:
        pool.release(conn)

    # 或使用上下文管理器
    with pool.connection() as conn:
        conn.execute(...)
"""

from __future__ import annotations

import time
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from contextlib import contextmanager


logger = logging.getLogger(__name__)


# ============================================================
# 连接信息
# ============================================================

@dataclass
class PooledConnection:
    """池化连接"""
    conn: Any
    created_at: float
    last_used_at: float
    use_count: int = 0
    in_use: bool = False
    borrowed_at: float = 0.0
    borrower_thread: str = ""


# ============================================================
# 连接池统计
# ============================================================

@dataclass
class PoolStats:
    """连接池统计"""
    pool_size: int = 0
    max_overflow: int = 0
    total_connections: int = 0
    idle_connections: int = 0
    in_use_connections: int = 0
    total_acquires: int = 0
    total_releases: int = 0
    total_timeouts: int = 0
    total_health_check_failures: int = 0
    total_leaked_connections: int = 0
    avg_borrow_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "total_connections": self.total_connections,
            "idle_connections": self.idle_connections,
            "in_use_connections": self.in_use_connections,
            "total_acquires": self.total_acquires,
            "total_releases": self.total_releases,
            "total_timeouts": self.total_timeouts,
            "total_health_check_failures": self.total_health_check_failures,
            "total_leaked_connections": self.total_leaked_connections,
            "avg_borrow_time_ms": round(self.avg_borrow_time_ms, 3),
        }


# ============================================================
# 连接池管理器
# ============================================================

class ConnectionPoolManager:
    """数据库连接池管理器

    特性:
    - 核心连接池 + 溢出连接
    - 连接复用
    - 健康检查 (获取时/空闲时)
    - 连接泄漏检测 (超时未归还)
    - 空闲连接超时回收
    - 线程安全
    - 统计信息
    """

    def __init__(
        self,
        db_path: str,
        pool_size: int = 5,
        max_overflow: int = 10,
        acquire_timeout: float = 30.0,
        idle_timeout: float = 300.0,
        connection_max_age: float = 3600.0,
        leak_detection_threshold: float = 60.0,
        health_check_on_acquire: bool = True,
        health_check_interval: float = 60.0,
        db_type: str = "sqlite",
    ):
        """
        Args:
            db_path: 数据库路径
            pool_size: 核心连接数
            max_overflow: 最大溢出连接数
            acquire_timeout: 获取连接超时 (秒)
            idle_timeout: 空闲连接超时 (秒)
            connection_max_age: 连接最大存活时间 (秒)
            leak_detection_threshold: 泄漏检测阈值 (秒)
            health_check_on_acquire: 获取时是否健康检查
            health_check_interval: 健康检查间隔 (秒)
            db_type: 数据库类型 (sqlite/postgres/...)
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.acquire_timeout = acquire_timeout
        self.idle_timeout = idle_timeout
        self.connection_max_age = connection_max_age
        self.leak_detection_threshold = leak_detection_threshold
        self.health_check_on_acquire = health_check_on_acquire
        self.health_check_interval = health_check_interval
        self.db_type = db_type

        # 连接池
        self._idle: List[PooledConnection] = []
        self._in_use: List[PooledConnection] = []
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(pool_size + max_overflow)

        # 统计
        self.stats = PoolStats(pool_size=pool_size, max_overflow=max_overflow)
        self._total_borrow_time = 0.0
        self._borrow_count = 0

        # 健康检查线程
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        if health_check_interval > 0:
            self._start_health_checker()

        # 预创建核心连接
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """预创建核心连接"""
        for _ in range(self.pool_size):
            try:
                conn = self._create_connection()
                self._idle.append(conn)
            except Exception:
                logger.warning("Failed to pre-create connection")

    def _create_connection(self) -> PooledConnection:
        """创建新连接"""
        if self.db_type == "sqlite":
            import sqlite3
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
                timeout=30.0,
            )
            # SQLite 优化
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA cache_size = -20000")
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA mmap_size = 268435456")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.row_factory = sqlite3.Row
        else:
            raise ValueError(f"Unsupported db_type: {self.db_type}")

        now = time.time()
        return PooledConnection(
            conn=conn,
            created_at=now,
            last_used_at=now,
        )

    # ---------- 获取/释放 ----------

    def acquire(self) -> Any:
        """获取连接

        Returns:
            数据库连接对象

        Raises:
            TimeoutError: 超时未获取到连接
        """
        if not self._semaphore.acquire(timeout=self.acquire_timeout):
            with self._lock:
                self.stats.total_timeouts += 1
            raise TimeoutError(
                f"Failed to acquire connection within {self.acquire_timeout}s"
            )

        try:
            with self._lock:
                self.stats.total_acquires += 1

                # 从空闲池获取
                while self._idle:
                    pooled = self._idle.pop(0)

                    # 健康检查
                    if self.health_check_on_acquire:
                        if not self._check_connection_health(pooled):
                            self.stats.total_health_check_failures += 1
                            self._close_connection(pooled)
                            continue

                    # 检查连接年龄
                    if time.time() - pooled.created_at > self.connection_max_age:
                        self._close_connection(pooled)
                        continue

                    # 借出
                    pooled.in_use = True
                    pooled.borrowed_at = time.time()
                    pooled.borrower_thread = threading.current_thread().name
                    pooled.use_count += 1
                    pooled.last_used_at = time.time()
                    self._in_use.append(pooled)

                    self._update_stats()
                    return pooled.conn

                # 空闲池为空，创建新连接
                try:
                    pooled = self._create_connection()
                    pooled.in_use = True
                    pooled.borrowed_at = time.time()
                    pooled.borrower_thread = threading.current_thread().name
                    pooled.use_count = 1
                    self._in_use.append(pooled)

                    self._update_stats()
                    return pooled.conn
                except Exception:
                    self._semaphore.release()
                    raise

        except Exception:
            self._semaphore.release()
            raise

    def release(self, conn: Any) -> None:
        """释放连接"""
        with self._lock:
            # 找到对应的 PooledConnection
            pooled = None
            for p in self._in_use:
                if p.conn is conn:
                    pooled = p
                    break

            if pooled is None:
                # 不在池中，直接关闭
                try:
                    conn.close()
                except Exception:
                    pass
                self._semaphore.release()
                return

            # 记录借用时间
            borrow_time = time.time() - pooled.borrowed_at
            self._total_borrow_time += borrow_time
            self._borrow_count += 1
            self.stats.avg_borrow_time_ms = (
                self._total_borrow_time / self._borrow_count * 1000
            )

            # 从使用中移除
            self._in_use.remove(pooled)
            pooled.in_use = False
            pooled.last_used_at = time.time()

            # 检查连接是否还能用
            if not self._check_connection_health(pooled):
                self.stats.total_health_check_failures += 1
                self._close_connection(pooled)
                self._update_stats()
                self._semaphore.release()
                return

            # 检查连接年龄
            if time.time() - pooled.created_at > self.connection_max_age:
                self._close_connection(pooled)
                self._update_stats()
                self._semaphore.release()
                return

            # 空闲池未满，归还
            if len(self._idle) < self.pool_size:
                self._idle.append(pooled)
            else:
                # 池满，关闭
                self._close_connection(pooled)

            self.stats.total_releases += 1
            self._update_stats()

        self._semaphore.release()

    @contextmanager
    def connection(self):
        """上下文管理器方式获取连接"""
        conn = self.acquire()
        try:
            yield conn
        finally:
            self.release(conn)

    # ---------- 健康检查 ----------

    def _check_connection_health(self, pooled: PooledConnection) -> bool:
        """检查连接是否健康"""
        try:
            if self.db_type == "sqlite":
                # SQLite: 执行一个简单查询
                cursor = pooled.conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
                return True
            return True
        except Exception:
            return False

    def _start_health_checker(self) -> None:
        """启动健康检查线程"""
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            name="ConnPool-HealthChecker",
            daemon=True,
        )
        self._health_thread.start()

    def _health_check_loop(self) -> None:
        """健康检查循环"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.health_check_interval)
            if self._stop_event.is_set():
                break
            try:
                self._perform_health_check()
            except Exception:
                logger.exception("Health check error")

    def _perform_health_check(self) -> None:
        """执行健康检查"""
        with self._lock:
            now = time.time()

            # 检查空闲连接
            healthy_idle = []
            for pooled in self._idle:
                # 空闲超时
                if now - pooled.last_used_at > self.idle_timeout:
                    self._close_connection(pooled)
                    continue
                # 连接年龄
                if now - pooled.created_at > self.connection_max_age:
                    self._close_connection(pooled)
                    continue
                # 健康检查
                if not self._check_connection_health(pooled):
                    self.stats.total_health_check_failures += 1
                    self._close_connection(pooled)
                    continue
                healthy_idle.append(pooled)
            self._idle = healthy_idle

            # 泄漏检测 (使用中的连接)
            still_in_use = []
            for pooled in self._in_use:
                if now - pooled.borrowed_at > self.leak_detection_threshold:
                    logger.warning(
                        f"Connection leak detected: borrowed by "
                        f"{pooled.borrower_thread} for "
                        f"{now - pooled.borrowed_at:.1f}s"
                    )
                    self.stats.total_leaked_connections += 1
                    # 不强制回收，只记录
                still_in_use.append(pooled)
            self._in_use = still_in_use

            self._update_stats()

    # ---------- 内部工具 ----------

    def _close_connection(self, pooled: PooledConnection) -> None:
        """关闭连接 (调用方需持有锁)"""
        try:
            pooled.conn.close()
        except Exception:
            pass

    def _update_stats(self) -> None:
        """更新统计 (调用方需持有锁)"""
        self.stats.total_connections = len(self._idle) + len(self._in_use)
        self.stats.idle_connections = len(self._idle)
        self.stats.in_use_connections = len(self._in_use)

    # ---------- 公共方法 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取连接池统计"""
        with self._lock:
            self._update_stats()
            return self.stats.to_dict()

    def close_all(self) -> None:
        """关闭所有连接"""
        self._stop_event.set()

        with self._lock:
            for pooled in self._idle:
                try:
                    pooled.conn.close()
                except Exception:
                    pass
            self._idle.clear()

            # 注意: 不关闭使用中的连接，让调用方自己释放

            self._update_stats()

        if self._health_thread and self._health_thread.is_alive():
            self._health_thread.join(timeout=5.0)

    def reset(self) -> None:
        """重置连接池 (关闭所有连接并重新初始化)"""
        self.close_all()
        self._idle.clear()
        self._in_use.clear()
        self.stats = PoolStats(pool_size=self.pool_size, max_overflow=self.max_overflow)
        self._total_borrow_time = 0.0
        self._borrow_count = 0
        self._initialize_pool()
