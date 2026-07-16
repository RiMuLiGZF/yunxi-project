"""
云汐统一数据库管理器

提供统一的数据库连接管理，支持：
- 连接池管理
- 读写锁优化（多读单写，提升并发性能）
- 统一查询接口（参数化查询，防SQL注入）
- 事务管理
- 健康检查
"""
import os
import re
import sqlite3
import threading
from typing import Optional, Dict, Any, List, Tuple, ContextManager
from contextlib import contextmanager
from pathlib import Path


class _ReadWriteLock:
    """读写锁（Read-Write Lock）.
    
    允许多个读者同时持有读锁，但写者独占。
    写者优先，防止写饥饿。
    
    比 threading.Lock 更适合读多写少的场景（如数据库查询）。
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._read_ready = threading.Condition(self._lock)
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False
    
    @contextmanager
    def read_lock(self):
        """获取读锁（上下文管理器）"""
        with self._read_ready:
            # 写者优先：如果有写者等待或正在写，等待
            while self._writers_waiting > 0 or self._writer_active:
                self._read_ready.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._read_ready:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()
    
    @contextmanager
    def write_lock(self):
        """获取写锁（上下文管理器）"""
        with self._read_ready:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._read_ready.wait()
            self._writers_waiting -= 1
            self._writer_active = True
        try:
            yield
        finally:
            with self._read_ready:
                self._writer_active = False
                self._read_ready.notify_all()


# 安全表名校验正则（只允许字母、数字、下划线）
_SAFE_TABLE_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_SAFE_COLUMN_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(name: str, kind: str = "identifier") -> str:
    """校验SQL标识符（表名、列名）是否安全.
    
    SQLite 参数化查询不能绑定表名和列名，
    因此需要白名单校验确保安全。
    
    Args:
        name: 标识符名称
        kind: 标识符类型（用于错误消息）
    
    Returns:
        原始名称（如果安全）
    
    Raises:
        ValueError: 标识符包含不安全字符
    """
    if not _SAFE_TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid {kind}: {repr(name)} - only alphanumeric and underscore allowed")
    return name


class DatabaseManager:
    """统一数据库管理器
    
    线程安全，使用读写锁优化读多写少场景。
    所有查询接口默认使用参数化查询防SQL注入。
    """
    
    def __init__(self, data_root: Optional[str] = None):
        """
        初始化数据库管理器
        
        Args:
            data_root: 数据根目录，默认为项目根目录下的 data/
        """
        if data_root is None:
            # 默认数据目录
            project_root = Path(__file__).parent.parent.parent
            data_root = project_root / "data"
        
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        
        # 连接缓存
        self._connections: Dict[str, sqlite3.Connection] = {}
        # 读写锁（每个数据库独立的读写锁）
        self._rw_locks: Dict[str, _ReadWriteLock] = {}
        # 全局锁（用于连接创建等元操作）
        self._global_lock = threading.Lock()
    
    def _get_db_path(self, db_name: str) -> Path:
        """获取数据库文件路径"""
        if not db_name.endswith(".db"):
            db_name = f"{db_name}.db"
        return self.data_root / db_name
    
    def _get_connection(self, db_name: str) -> sqlite3.Connection:
        """
        获取或创建数据库连接（线程安全）
        
        Args:
            db_name: 数据库名称
        
        Returns:
            SQLite 连接对象
        """
        # 快速路径：已存在的连接
        if db_name in self._connections:
            return self._connections[db_name]
        
        # 慢路径：创建新连接（双重检查锁定）
        with self._global_lock:
            if db_name not in self._connections:
                db_path = self._get_db_path(db_name)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                
                conn = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                    isolation_level=None,  # 自动提交模式
                    timeout=30.0,  # 锁等待超时
                )
                
                # 配置SQLite - WAL模式支持并发读写
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA cache_size = -20000")  # 20MB缓存
                conn.execute("PRAGMA busy_timeout = 30000")  # 30秒 busy 超时
                conn.row_factory = sqlite3.Row
                
                self._connections[db_name] = conn
                self._rw_locks[db_name] = _ReadWriteLock()
        
        return self._connections[db_name]
    
    def _get_rw_lock(self, db_name: str) -> _ReadWriteLock:
        """获取数据库的读写锁（确保已初始化）"""
        # 确保连接已创建（同时会创建锁）
        self._get_connection(db_name)
        return self._rw_locks[db_name]
    
    @contextmanager
    def get_connection(self, db_name: str, write: bool = False) -> ContextManager[sqlite3.Connection]:
        """
        获取数据库连接（上下文管理器形式）
        
        Args:
            db_name: 数据库名称
            write: 是否为写操作（True=写锁，False=读锁）
        
        Yields:
            SQLite 连接对象
        """
        conn = self._get_connection(db_name)
        rw_lock = self._get_rw_lock(db_name)
        
        if write:
            with rw_lock.write_lock():
                yield conn
        else:
            with rw_lock.read_lock():
                yield conn
    
    @contextmanager
    def transaction(self, db_name: str) -> ContextManager[sqlite3.Connection]:
        """
        事务上下文管理器（写锁 + 事务）
        
        使用方式：
            with db.transaction("mydb") as conn:
                conn.execute(...)
                conn.execute(...)
            # 自动提交，异常时自动回滚
        """
        conn = self._get_connection(db_name)
        rw_lock = self._get_rw_lock(db_name)
        
        with rw_lock.write_lock():
            try:
                conn.execute("BEGIN")
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    
    def execute(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> int:
        """
        执行写操作（INSERT / UPDATE / DELETE）
        
        Args:
            db_name: 数据库名称
            sql: SQL语句（使用 ? 占位符）
            params: 参数元组
        
        Returns:
            受影响的行数
        """
        with self.get_connection(db_name, write=True) as conn:
            cursor = conn.execute(sql, params or ())
            return cursor.rowcount
    
    def execute_many(
        self,
        db_name: str,
        sql: str,
        seq_of_params: List[Tuple[Any, ...]],
    ) -> int:
        """
        批量执行写操作
        
        Args:
            db_name: 数据库名称
            sql: SQL语句
            seq_of_params: 参数列表
        
        Returns:
            受影响的总行数
        """
        with self.get_connection(db_name, write=True) as conn:
            cursor = conn.executemany(sql, seq_of_params)
            return cursor.rowcount
    
    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查询单行数据
        
        Args:
            db_name: 数据库名称
            sql: SQL查询语句（使用 ? 占位符）
            params: 参数元组
        
        Returns:
            行字典，无结果返回 None
        """
        with self.get_connection(db_name, write=False) as conn:
            cursor = conn.execute(sql, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询多行数据
        
        Args:
            db_name: 数据库名称
            sql: SQL查询语句（使用 ? 占位符）
            params: 参数元组
            limit: 最大返回行数
            offset: 偏移量
        
        Returns:
            行字典列表
        """
        # 构建带 LIMIT/OFFSET 的 SQL
        final_sql = sql
        if limit is not None:
            final_sql += f" LIMIT {int(limit)}"
        if offset is not None:
            final_sql += f" OFFSET {int(offset)}"
        
        with self.get_connection(db_name, write=False) as conn:
            cursor = conn.execute(final_sql, params or ())
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def insert(
        self,
        db_name: str,
        table: str,
        data: Dict[str, Any],
    ) -> int:
        """
        插入一行数据（安全，自动参数化）
        
        Args:
            db_name: 数据库名称
            table: 表名（会做安全校验）
            data: 字段-值字典
        
        Returns:
            插入行的 rowid
        """
        _validate_identifier(table, "table name")
        
        columns = list(data.keys())
        placeholders = ", ".join("?" for _ in columns)
        columns_str = ", ".join(f'"{c}"' for c in columns)  # 引号包裹防关键字冲突
        values = tuple(data[col] for col in columns)
        
        sql = f'INSERT INTO "{table}" ({columns_str}) VALUES ({placeholders})'
        
        with self.get_connection(db_name, write=True) as conn:
            cursor = conn.execute(sql, values)
            return cursor.lastrowid
    
    def update(
        self,
        db_name: str,
        table: str,
        data: Dict[str, Any],
        where: str,
        where_params: Optional[Tuple[Any, ...]] = None,
    ) -> int:
        """
        更新数据（安全，自动参数化）
        
        Args:
            db_name: 数据库名称
            table: 表名（会做安全校验）
            data: 字段-值字典
            where: WHERE条件（使用 ? 占位符）
            where_params: WHERE参数
        
        Returns:
            受影响的行数
        """
        _validate_identifier(table, "table name")
        
        set_clause = ", ".join(f'"{col}" = ?' for col in data.keys())
        values = tuple(data.values())
        params = values + (where_params or ())
        
        sql = f'UPDATE "{table}" SET {set_clause} WHERE {where}'
        
        with self.get_connection(db_name, write=True) as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount
    
    def delete(
        self,
        db_name: str,
        table: str,
        where: str,
        where_params: Optional[Tuple[Any, ...]] = None,
    ) -> int:
        """
        删除数据（安全，自动参数化）
        
        Args:
            db_name: 数据库名称
            table: 表名（会做安全校验）
            where: WHERE条件（使用 ? 占位符）
            where_params: WHERE参数
        
        Returns:
            受影响的行数
        """
        _validate_identifier(table, "table name")
        
        sql = f'DELETE FROM "{table}" WHERE {where}'
        
        with self.get_connection(db_name, write=True) as conn:
            cursor = conn.execute(sql, where_params or ())
            return cursor.rowcount
    
    def get_tables(self, db_name: str) -> List[str]:
        """获取数据库中所有表名"""
        rows = self.query_all(
            db_name,
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        )
        return [r["name"] for r in rows]
    
    def table_exists(self, db_name: str, table_name: str) -> bool:
        """检查表是否存在（安全版本）"""
        _validate_identifier(table_name, "table name")
        result = self.query_one(
            db_name,
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        )
        return result is not None
    
    def get_table_size(self, db_name: str, table_name: str) -> int:
        """获取表的行数（安全版本，表名校验防注入）
        
        Args:
            db_name: 数据库名称
            table_name: 表名（会做安全校验）
        
        Returns:
            行数
        """
        # 安全校验：表名只能包含字母、数字、下划线
        _validate_identifier(table_name, "table name")
        
        # 检查表是否存在（额外安全层）
        if not self.table_exists(db_name, table_name):
            return 0
        
        # 使用引号包裹表名，防止关键字冲突
        result = self.query_one(db_name, f'SELECT COUNT(*) as cnt FROM "{table_name}"')
        return result["cnt"] if result else 0
    
    def get_db_size(self, db_name: str) -> int:
        """获取数据库文件大小（字节）"""
        db_path = self._get_db_path(db_name)
        if db_path.exists():
            return db_path.stat().st_size
        return 0
    
    def health_check(self, db_name: str) -> Dict[str, Any]:
        """
        数据库健康检查
        
        Returns:
            健康状态字典
        """
        try:
            with self.get_connection(db_name, write=False) as conn:
                # 测试连接
                conn.execute("SELECT 1")
                
                # 获取表数量
                tables = self.get_tables(db_name)
                
                # 获取数据库大小
                size = self.get_db_size(db_name)
                
                return {
                    "status": "healthy",
                    "tables": len(tables),
                    "table_names": tables,
                    "size_bytes": size,
                    "size_mb": round(size / 1024 / 1024, 2),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
    
    def close(self, db_name: Optional[str] = None):
        """
        关闭数据库连接
        
        Args:
            db_name: 指定数据库，None表示关闭所有
        """
        if db_name:
            if db_name in self._connections:
                with self._global_lock:
                    if db_name in self._connections:
                        try:
                            self._connections[db_name].close()
                        except Exception:
                            pass
                        del self._connections[db_name]
                        self._rw_locks.pop(db_name, None)
        else:
            with self._global_lock:
                for conn in self._connections.values():
                    try:
                        conn.close()
                    except Exception:
                        pass
                self._connections.clear()
                self._rw_locks.clear()
    
    def __del__(self):
        """析构时关闭所有连接"""
        try:
            self.close()
        except Exception:
            pass


# 全局单例
_db_manager: Optional[DatabaseManager] = None
_db_manager_lock = threading.Lock()


def get_db_manager(data_root: Optional[str] = None) -> DatabaseManager:
    """获取数据库管理器单例"""
    global _db_manager
    if _db_manager is None:
        with _db_manager_lock:
            if _db_manager is None:
                _db_manager = DatabaseManager(data_root)
    return _db_manager
