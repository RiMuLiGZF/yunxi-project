"""
云汐数据库迁移引擎

提供数据库版本管理和迁移能力：
- 版本追踪
- 增量迁移
- 回滚支持
- 迁移状态查询
"""
import os
import sqlite3
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path


class MigrationEngine:
    """数据库迁移引擎"""
    
    def __init__(self, db_manager=None):
        """
        初始化迁移引擎
        
        Args:
            db_manager: DatabaseManager 实例，None则使用全局实例
        """
        if db_manager is None:
            from .database_manager import get_db_manager
            db_manager = get_db_manager()
        self.db_manager = db_manager
    
    def _ensure_migrations_table(self, db_name: str):
        """确保迁移记录表存在"""
        with self.db_manager.get_connection(db_name) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
    
    def get_current_version(self, db_name: str) -> int:
        """获取当前数据库版本"""
        self._ensure_migrations_table(db_name)
        result = self.db_manager.query_one(
            db_name,
            "SELECT MAX(version) as max_ver FROM _schema_migrations",
        )
        return result["max_ver"] if result and result["max_ver"] else 0
    
    def get_migrations(self, db_name: str) -> List[Dict[str, Any]]:
        """获取所有已应用的迁移"""
        self._ensure_migrations_table(db_name)
        return self.db_manager.query_all(
            db_name,
            "SELECT * FROM _schema_migrations ORDER BY version",
        )
    
    def migrate(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        执行数据库迁移
        
        Args:
            db_name: 数据库名称
            migrations: 迁移列表，每个迁移包含:
                - version: 版本号（整数，递增）
                - name: 迁移名称
                - up: 升级SQL或函数
                - down: 降级SQL或函数（可选）
                - description: 描述（可选）
            target_version: 目标版本，None表示最新
        
        Returns:
            迁移结果字典
        """
        self._ensure_migrations_table(db_name)
        
        current_version = self.get_current_version(db_name)
        
        if target_version is None:
            target_version = max(m["version"] for m in migrations) if migrations else 0
        
        applied = []
        failed = None
        
        # 按版本排序
        sorted_migrations = sorted(migrations, key=lambda m: m["version"])
        
        try:
            for migration in sorted_migrations:
                version = migration["version"]
                
                if version <= current_version:
                    continue
                
                if version > target_version:
                    break
                
                # 执行升级
                with self.db_manager.transaction(db_name) as conn:
                    up_script = migration.get("up", "")
                    
                    if callable(up_script):
                        up_script(conn)
                    elif isinstance(up_script, str):
                        conn.executescript(up_script)
                    
                    # 记录迁移
                    conn.execute(
                        "INSERT INTO _schema_migrations (version, name, description) VALUES (?, ?, ?)",
                        (
                            version,
                            migration.get("name", f"v{version}"),
                            migration.get("description", ""),
                        ),
                    )
                    
                    applied.append(version)
            
            return {
                "success": True,
                "from_version": current_version,
                "to_version": target_version,
                "applied_count": len(applied),
                "applied_versions": applied,
            }
        
        except Exception as e:
            failed = str(e)
            return {
                "success": False,
                "error": failed,
                "from_version": current_version,
                "failed_at": applied[-1] + 1 if applied else current_version + 1,
                "applied_versions": applied,
            }
    
    def rollback(
        self,
        db_name: str,
        migrations: List[Dict[str, Any]],
        target_version: int = 0,
    ) -> Dict[str, Any]:
        """
        回滚迁移
        
        Args:
            db_name: 数据库名称
            migrations: 迁移列表
            target_version: 回滚到的版本
        
        Returns:
            回滚结果字典
        """
        self._ensure_migrations_table(db_name)
        
        current_version = self.get_current_version(db_name)
        
        if current_version <= target_version:
            return {
                "success": True,
                "message": "Already at target version",
                "current_version": current_version,
            }
        
        # 按版本降序排序
        sorted_migrations = sorted(
            [m for m in migrations if m["version"] > target_version],
            key=lambda m: m["version"],
            reverse=True,
        )
        
        rolled_back = []
        
        try:
            for migration in sorted_migrations:
                version = migration["version"]
                
                if version <= target_version:
                    continue
                
                # 执行降级
                with self.db_manager.transaction(db_name) as conn:
                    down_script = migration.get("down", "")
                    
                    if callable(down_script):
                        down_script(conn)
                    elif isinstance(down_script, str):
                        conn.executescript(down_script)
                    
                    # 删除迁移记录
                    conn.execute(
                        "DELETE FROM _schema_migrations WHERE version = ?",
                        (version,),
                    )
                    
                    rolled_back.append(version)
            
            return {
                "success": True,
                "from_version": current_version,
                "to_version": target_version,
                "rolled_back_count": len(rolled_back),
                "rolled_back_versions": rolled_back,
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "from_version": current_version,
                "rolled_back_versions": rolled_back,
            }
    
    def check_integrity(self, db_name: str) -> Dict[str, Any]:
        """检查数据库完整性"""
        try:
            with self.db_manager.get_connection(db_name) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()
                
                quick_check = conn.execute("PRAGMA quick_check").fetchone()
                
                # 获取表数量
                tables = conn.execute(
                    "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table'"
                ).fetchone()
                
                return {
                    "status": "ok" if result[0] == "ok" else "corrupted",
                    "integrity_check": result[0],
                    "quick_check": quick_check[0],
                    "table_count": tables["cnt"],
                }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }


# 全局单例
_migration_engine: Optional[MigrationEngine] = None


def get_migration_engine() -> MigrationEngine:
    """获取全局迁移引擎实例"""
    global _migration_engine
    if _migration_engine is None:
        _migration_engine = MigrationEngine()
    return _migration_engine
