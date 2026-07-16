"""
云汐数据备份恢复管理器

提供统一的数据备份和恢复能力：
- 全量备份
- 增量备份
- 定时备份
- 一键恢复
- 备份生命周期管理
"""
import os
import time
import shutil
import sqlite3
import zipfile
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta


class BackupManager:
    """数据备份恢复管理器"""
    
    def __init__(
        self,
        backup_root: Optional[str] = None,
        data_root: Optional[str] = None,
        max_backups: int = 30,
    ):
        """
        初始化备份管理器
        
        Args:
            backup_root: 备份存储根目录
            data_root: 数据根目录
            max_backups: 最大保留备份数
        """
        if data_root is None:
            project_root = Path(__file__).parent.parent.parent
            data_root = project_root / "data"
        
        if backup_root is None:
            project_root = Path(__file__).parent.parent.parent
            backup_root = project_root / "backups"
        
        self.data_root = Path(data_root)
        self.backup_root = Path(backup_root)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.max_backups = max_backups
    
    def _get_backup_dir(self, backup_type: str = "full") -> Path:
        """获取备份目录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.backup_root / f"{backup_type}_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    
    def backup_database(
        self,
        db_path: str,
        backup_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        备份单个数据库
        
        Args:
            db_path: 数据库文件路径
            backup_name: 备份名称
        
        Returns:
            备份结果字典
        """
        db_path = Path(db_path)
        if not db_path.exists():
            return {
                "success": False,
                "error": f"Database not found: {db_path}",
            }
        
        backup_dir = self._get_backup_dir("db")
        backup_file = backup_dir / (backup_name or db_path.name)
        
        try:
            # 使用 SQLite 的在线备份API
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(backup_file))
            
            try:
                src.backup(dst)
            finally:
                src.close()
                dst.close()
            
            size = backup_file.stat().st_size
            
            return {
                "success": True,
                "backup_path": str(backup_file),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "timestamp": time.time(),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def backup_directory(
        self,
        source_dir: str,
        backup_name: Optional[str] = None,
        include_subdirs: bool = True,
    ) -> Dict[str, Any]:
        """
        备份整个目录
        
        Args:
            source_dir: 源目录
            backup_name: 备份名称
            include_subdirs: 是否包含子目录
        
        Returns:
            备份结果字典
        """
        source_dir = Path(source_dir)
        if not source_dir.exists():
            return {
                "success": False,
                "error": f"Directory not found: {source_dir}",
            }
        
        backup_dir = self._get_backup_dir("dir")
        backup_file = backup_dir / f"{backup_name or source_dir.name}.zip"
        
        try:
            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
                if include_subdirs:
                    for f in source_dir.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(source_dir.parent))
                else:
                    for f in source_dir.iterdir():
                        if f.is_file():
                            zf.write(f, f.name)
            
            size = backup_file.stat().st_size
            
            return {
                "success": True,
                "backup_path": str(backup_file),
                "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2),
                "timestamp": time.time(),
                "file_count": len(zipfile.ZipFile(backup_file).namelist()),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def full_backup(self, modules: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        全量备份
        
        Args:
            modules: 要备份的模块列表，None表示所有模块
        
        Returns:
            备份结果字典
        """
        backup_dir = self._get_backup_dir("full")
        results = {}
        total_size = 0
        success_count = 0
        
        # 扫描所有模块的data目录
        project_root = Path(__file__).parent.parent.parent
        
        for module_dir in sorted(project_root.iterdir()):
            if not module_dir.is_dir():
                continue
            if not module_dir.name.startswith(("M", "m")):
                continue
            
            module_key = module_dir.name.lower()
            if modules and module_key not in [m.lower() for m in modules]:
                continue
            
            data_dir = module_dir / "data"
            if not data_dir.exists():
                continue
            
            db_files = list(data_dir.rglob("*.db"))
            if not db_files:
                continue
            
            module_backup_dir = backup_dir / module_dir.name
            module_backup_dir.mkdir(parents=True, exist_ok=True)
            
            module_success = 0
            for db_file in db_files:
                backup_file = module_backup_dir / db_file.relative_to(data_dir)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    src = sqlite3.connect(str(db_file))
                    dst = sqlite3.connect(str(backup_file))
                    src.backup(dst)
                    src.close()
                    dst.close()
                    
                    total_size += backup_file.stat().st_size
                    module_success += 1
                    success_count += 1
                except Exception as e:
                    results[f"{module_dir.name}/{db_file.name}"] = {
                        "success": False,
                        "error": str(e),
                    }
            
            results[module_dir.name] = {
                "success": module_success > 0,
                "db_count": len(db_files),
                "success_count": module_success,
            }
        
        # 清理旧备份
        self._cleanup_old_backups()
        
        return {
            "success": success_count > 0,
            "backup_path": str(backup_dir),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "modules": results,
            "timestamp": time.time(),
        }
    
    def restore_backup(
        self,
        backup_path: str,
        target_path: str,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        恢复备份
        
        Args:
            backup_path: 备份文件路径
            target_path: 恢复目标路径
            overwrite: 是否覆盖现有文件
        
        Returns:
            恢复结果字典
        """
        backup_path = Path(backup_path)
        target_path = Path(target_path)
        
        if not backup_path.exists():
            return {
                "success": False,
                "error": f"Backup not found: {backup_path}",
            }
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            if backup_path.suffix == ".zip":
                # ZIP 备份恢复
                with zipfile.ZipFile(backup_path, "r") as zf:
                    if not overwrite and target_path.exists():
                        existing = set(f.name for f in target_path.iterdir())
                        zip_names = set(Path(n).name for n in zf.namelist())
                        conflicts = existing & zip_names
                        if conflicts:
                            return {
                                "success": False,
                                "error": f"Files already exist: {', '.join(conflicts)}",
                            }
                    
                    zf.extractall(target_path.parent)
            elif backup_path.suffix == ".db":
                # 数据库备份恢复
                if target_path.exists() and not overwrite:
                    return {
                        "success": False,
                        "error": f"Target already exists: {target_path}",
                    }
                
                # 先恢复到临时文件，再替换
                temp_path = target_path.with_suffix(".tmp")
                shutil.copy2(backup_path, temp_path)
                
                # 验证备份完整性
                try:
                    conn = sqlite3.connect(str(temp_path))
                    conn.execute("SELECT 1")
                    conn.close()
                except Exception as e:
                    temp_path.unlink(missing_ok=True)
                    return {
                        "success": False,
                        "error": f"Backup verification failed: {e}",
                    }
                
                if target_path.exists():
                    target_path.unlink()
                temp_path.rename(target_path)
            else:
                # 普通文件复制
                shutil.copy2(backup_path, target_path)
            
            return {
                "success": True,
                "restored_to": str(target_path),
                "timestamp": time.time(),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def list_backups(self, backup_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出所有备份
        
        Args:
            backup_type: 备份类型过滤
        
        Returns:
            备份列表
        """
        backups = []
        
        if not self.backup_root.exists():
            return backups
        
        for backup_dir in sorted(self.backup_root.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue
            
            if backup_type and not backup_dir.name.startswith(backup_type):
                continue
            
            try:
                # 计算备份大小
                total_size = sum(f.stat().st_size for f in backup_dir.rglob("*") if f.is_file())
                
                backups.append({
                    "name": backup_dir.name,
                    "type": backup_dir.name.split("_")[0],
                    "created": backup_dir.stat().st_ctime,
                    "size_bytes": total_size,
                    "size_mb": round(total_size / 1024 / 1024, 2),
                    "path": str(backup_dir),
                })
            except Exception:
                continue
        
        return backups
    
    def _cleanup_old_backups(self):
        """清理过期备份"""
        backups = self.list_backups()
        
        if len(backups) <= self.max_backups:
            return
        
        # 删除最旧的备份
        to_delete = backups[self.max_backups:]
        for backup in to_delete:
            try:
                backup_path = Path(backup["path"])
                if backup_path.is_dir():
                    shutil.rmtree(backup_path)
                else:
                    backup_path.unlink()
            except Exception:
                pass
    
    def get_backup_stats(self) -> Dict[str, Any]:
        """获取备份统计信息"""
        backups = self.list_backups()
        
        total_size = sum(b["size_bytes"] for b in backups)
        
        by_type = {}
        for b in backups:
            t = b["type"]
            if t not in by_type:
                by_type[t] = {"count": 0, "size_bytes": 0}
            by_type[t]["count"] += 1
            by_type[t]["size_bytes"] += b["size_bytes"]
        
        return {
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "max_backups": self.max_backups,
            "by_type": by_type,
            "latest_backup": backups[0] if backups else None,
        }


# 全局单例
_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """获取全局备份管理器实例"""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
