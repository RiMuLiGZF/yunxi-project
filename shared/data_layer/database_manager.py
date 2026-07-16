"""
云汐统一数据库管理器

提供统一的数据库连接管理，支持：
- 连接池管理
- 统一查询接口
- 事务管理
- 健康检查
"""
import os
import sqlite3
import threading
from typing import Optional, Dict, Any, List, Tuple, ContextManager
from contextlib import contextmanager
from pathlib import Path


class DatabaseManager:
    """统一数据库管理器"""
    
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
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()
    
    def _get_db_path(self, db_name: str) -> Path:
        """获取数据库文件路径"""
        if not db_name.endswith(".db"):
            db_name = f"{db_name}.db"
        return self.data_root / db_name
    
    def _get_connection(self, db_name: str) -> sqlite3.Connection:
        """
        获取或创建数据库连接
        
        Args:
            db_name: 数据库名称
        
        Returns:
            SQLite 连接对象
        """
        if db_name not in self._connections:
            with self._global_lock:
                if db_name not in self._connections:
                    db_path = self._get_db_path(db_name)
                    db_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    conn = sqlite3.connect(
                        str(db_path),
                        check_same_thread=False,
                        isolation_level=None,  # 自动提交模式
                    )
                    
                    # 配置SQLite
                    conn.execute("PRAGMA journal_mode = WAL")
                    conn.execute("PRAGMA synchronous = NORMAL")
                    conn.execute("PRAGMA foreign_keys = ON")
                    conn.execute("PRAGMA cache_size = -20000")  # 20MB缓存
                    conn.row_factory = sqlite3.Row
                    
                    self._connections[db_name] = conn
                    self._locks[db_name] = threading.Lock()
        
        return self._connections[db_name]
    
    @contextmanager
    def get_connection(self, db_name: str) -> ContextManager[sqlite3.Connection]:
        """
        获取数据库连接（上下文管理器形式）
        
        Args:
            db_name: 数据库名称
        
        Yields:
            SQLite 连接对象
        """
        conn = self._get_connection(db_name)
        lock = self._locks.get(db_name, self._global_lock)
        
        with lock:
            yield conn
    
    def execute(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple] = None,
    ) -> int:
        """
        执行SQL语句（INSERT/UPDATE/DELETE）
        
        Args:
            db_name: 数据库名称
            sql: SQL语句
            params: 参数元组
        
        Returns:
            受影响的行数
        """
        with self.get_connection(db_name) as conn:
            cursor = conn.execute(sql, params or ())
            return cursor.rowcount
    
    def query_one(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        查询单行数据
        
        Args:
            db_name: 数据库名称
            sql: SQL语句
            params: 参数元组
        
        Returns:
            行字典，无数据返回None
        """
        with self.get_connection(db_name) as conn:
            cursor = conn.execute(sql, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def query_all(
        self,
        db_name: str,
        sql: str,
        params: Optional[Tuple] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询多行数据
        
        Args:
            db_name: 数据库名称
            sql: SQL语句
            params: 参数元组
        
        Returns:
            行字典列表
        """
        with self.get_connection(db_name) as conn:
            cursor = conn.execute(sql, params or ())
            return [dict(row) for row in cursor.fetchall()]
    
    @contextmanager
    def transaction(self, db_name: str) -> ContextManager[sqlite3.Connection]:
        """
        事务上下文管理器
        
        Args:
            db_name: 数据库名称
        
        Yields:
            SQLite 连接对象
        
        示例:
            with db_manager.transaction("users") as conn:
                conn.execute("INSERT INTO ...")
                conn.execute("UPDATE ...")
            # 自动提交，异常时自动回滚
        """
        conn = self._get_connection(db_name)
        lock = self._locks.get(db_name, self._global_lock)
        
        with lock:
            conn.execute("BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    
    def table_exists(self, db_name: str, table_name: str) -> bool:
        """检查表是否存在"""
        result = self.query_one(
            db_name,
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return result is not None
    
    def get_tables(self, db_name: str) -> List[str]:
        """获取数据库中所有表名"""
        rows = self.query_all(
            db_name,
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        )
        return [r["name"] for r in rows]
    
    def get_table_size(self, db_name: str, table_name: str) -> int:
        """获取表的行数"""
        result = self.query_one(db_name, f"SELECT COUNT(*) as cnt FROM {table_name}")
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
            with self.get_connection(db_name) as conn:
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
                self._connections[db_name].close()
                del self._connections[db_name]
                del self._locks[db_name]
        else:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
            self._locks.clear()


# 全局单例
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """获取全局数据库管理器实例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager
