"""
云汐数据备份恢复管理器

提供统一的数据备份和恢复能力：
- 全量备份
- 增量备份
- 定时备份
- 一键恢复
- 备份生命周期管理
- 模块级备份适配
- 安全网恢复机制
- 备份完整性校验
- 统一备份调度中心
"""
import os
import time
import shutil
import sqlite3
import zipfile
import hashlib
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Tuple
from pathlib import Path
from datetime import datetime, timedelta


# ============================================================
# 数据类
# ============================================================

@dataclass
class ModuleBackupConfig:
    """模块备份配置
    
    Attributes:
        module_id: 模块唯一标识
        db_paths: 数据库文件路径列表
        backup_dir: 备份存储目录
        max_backups: 最大保留备份数
        schedule: 定时调度配置，支持以下格式：
            - {"type": "daily", "time": "03:00"} 每日指定时间
            - {"type": "interval", "hours": 6} 每N小时
            - {"type": "interval", "minutes": 30} 每N分钟
            - None 不启用定时备份
    """
    module_id: str
    db_paths: List[str]
    backup_dir: str
    max_backups: int = 30
    schedule: Optional[Dict[str, Any]] = None


@dataclass
class BackupReport:
    """备份报告
    
    Attributes:
        module_id: 模块ID
        success: 是否全部成功
        total_dbs: 总数据库数
        success_dbs: 成功备份数
        failed_dbs: 失败备份数
        total_size_bytes: 总备份大小（字节）
        total_size_mb: 总备份大小（MB）
        backup_dir: 备份目录路径
        timestamp: 备份时间戳
        details: 每个数据库的详细备份结果
        errors: 错误信息列表
    """
    module_id: str
    success: bool
    total_dbs: int
    success_dbs: int
    failed_dbs: int
    total_size_bytes: int
    total_size_mb: float
    backup_dir: str
    timestamp: float
    details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    """备份校验报告
    
    Attributes:
        backup_path: 备份文件路径
        file_valid: 文件是否存在且可读
        file_size_bytes: 文件大小（字节）
        md5_checksum: MD5校验和
        integrity_check: PRAGMA integrity_check 结果
        quick_check: PRAGMA quick_check 结果
        table_count: 表数量
        has_tables: 是否包含表（表数量>0）
        overall_valid: 整体是否通过校验
        errors: 错误信息列表
    """
    backup_path: str
    file_valid: bool = False
    file_size_bytes: int = 0
    md5_checksum: str = ""
    integrity_check: str = ""
    quick_check: str = ""
    table_count: int = 0
    has_tables: bool = False
    overall_valid: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class IncrementalBackupReport:
    """增量备份报告
    
    Attributes:
        success: 是否成功
        db_path: 源数据库路径
        base_backup_path: 基准备份路径
        incremental_path: 增量备份路径
        base_size_bytes: 基准备份大小
        incremental_size_bytes: 增量备份大小
        changed_tables: 发生变化的表列表
        new_tables: 新增的表列表
        deleted_tables: 删除的表列表
        total_changes: 总变化记录数
        timestamp: 备份时间戳
        errors: 错误信息列表
    """
    success: bool
    db_path: str
    base_backup_path: str
    incremental_path: str = ""
    base_size_bytes: int = 0
    incremental_size_bytes: int = 0
    changed_tables: List[str] = field(default_factory=list)
    new_tables: List[str] = field(default_factory=list)
    deleted_tables: List[str] = field(default_factory=list)
    total_changes: int = 0
    timestamp: float = 0.0
    errors: List[str] = field(default_factory=list)


# ============================================================
# 定时备份调度器
# ============================================================

class BackupScheduler:
    """定时备份调度器
    
    使用 threading.Timer 实现的线程安全定时备份调度器，
    支持每日指定时间和间隔两种调度模式。
    
    Attributes:
        callback: 备份任务回调函数
        running: 调度器是否运行中
    """
    
    def __init__(self, callback: Callable[[], Any]):
        """
        初始化备份调度器
        
        Args:
            callback: 备份任务回调，备份完成时调用（可选）
        """
        self._callback = callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._schedule_config: Optional[Dict[str, Any]] = None
        self._last_run: Optional[float] = None
    
    @property
    def running(self) -> bool:
        """调度器是否运行中"""
        return self._running
    
    @property
    def last_run(self) -> Optional[float]:
        """上次执行时间戳"""
        return self._last_run
    
    def start(self, schedule_config: Dict[str, Any]) -> bool:
        """
        启动调度器
        
        Args:
            schedule_config: 调度配置，支持：
                - {"type": "daily", "time": "03:00"} 每日指定时间（24小时制）
                - {"type": "interval", "hours": 6} 每N小时
                - {"type": "interval", "minutes": 30} 每N分钟
        
        Returns:
            是否成功启动
        """
        with self._lock:
            if self._running:
                return False
            
            self._schedule_config = schedule_config
            self._running = True
            self._schedule_next()
            return True
    
    def stop(self) -> bool:
        """
        停止调度器
        
        Returns:
            是否成功停止
        """
        with self._lock:
            if not self._running:
                return False
            
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            return True
    
    def status(self) -> Dict[str, Any]:
        """
        查询调度器状态
        
        Returns:
            状态信息字典
        """
        with self._lock:
            return {
                "running": self._running,
                "schedule_config": self._schedule_config,
                "last_run": self._last_run,
                "next_run": self._get_next_run_time(),
            }
    
    def _get_next_run_time(self) -> Optional[float]:
        """计算下次运行时间（仅供状态查询参考）"""
        if not self._schedule_config or not self._running:
            return None
        
        config = self._schedule_config
        now = datetime.now()
        
        if config.get("type") == "daily":
            time_str = config.get("time", "03:00")
            try:
                hour, minute = map(int, time_str.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target.timestamp()
            except (ValueError, AttributeError):
                return None
        
        elif config.get("type") == "interval":
            seconds = 0
            if "hours" in config:
                seconds = config["hours"] * 3600
            elif "minutes" in config:
                seconds = config["minutes"] * 60
            else:
                return None
            
            if self._last_run:
                return self._last_run + seconds
            else:
                return now.timestamp() + seconds
        
        return None
    
    def _schedule_next(self) -> None:
        """调度下一次执行（内部方法，调用时必须持有 _lock）"""
        if not self._running or not self._schedule_config:
            return
        
        delay = self._calculate_delay()
        if delay is None:
            return
        
        self._timer = threading.Timer(delay, self._run_task)
        self._timer.daemon = True
        self._timer.start()
    
    def _calculate_delay(self) -> Optional[float]:
        """计算距离下次执行的延迟秒数"""
        if not self._schedule_config:
            return None
        
        config = self._schedule_config
        now = datetime.now()
        
        if config.get("type") == "daily":
            time_str = config.get("time", "03:00")
            try:
                hour, minute = map(int, time_str.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return (target - now).total_seconds()
            except (ValueError, AttributeError):
                return None
        
        elif config.get("type") == "interval":
            if "hours" in config:
                return float(config["hours"] * 3600)
            elif "minutes" in config:
                return float(config["minutes"] * 60)
            else:
                return None
        
        return None
    
    def _run_task(self) -> None:
        """执行备份任务（Timer回调）"""
        try:
            self._callback()
        except Exception:
            # 回调异常不应导致调度器停止
            pass
        finally:
            self._last_run = time.time()
            # 调度下一次
            with self._lock:
                if self._running:
                    self._schedule_next()


# ============================================================
# 主备份管理器
# ============================================================

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
    
    # --------------------------------------------------------
    # 内部工具方法
    # --------------------------------------------------------
    
    def _get_backup_dir(self, backup_type: str = "full") -> Path:
        """获取备份目录"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.backup_root / f"{backup_type}_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir
    
    def _backup_single_db(self, db_path: Path, backup_file: Path) -> Dict[str, Any]:
        """
        备份单个数据库（内部方法）
        
        Args:
            db_path: 源数据库路径
            backup_file: 目标备份文件路径
        
        Returns:
            备份结果字典
        """
        try:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
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
    
    # --------------------------------------------------------
    # 基础备份方法（保持向后兼容）
    # --------------------------------------------------------
    
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
        
        return self._backup_single_db(db_path, backup_file)
    
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
                
                result = self._backup_single_db(db_file, backup_file)
                if result["success"]:
                    total_size += result["size_bytes"]
                    module_success += 1
                    success_count += 1
                else:
                    results[f"{module_dir.name}/{db_file.name}"] = {
                        "success": False,
                        "error": result.get("error", "unknown"),
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
    
    # --------------------------------------------------------
    # 恢复方法（增强版）
    # --------------------------------------------------------
    
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
                
                # 使用 SQLite 备份 API 进行恢复
                # 这种方式可以在目标数据库有活跃连接时也能正常工作（处理文件锁问题）
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 先验证备份文件完整性
                try:
                    verify_conn = sqlite3.connect(str(backup_path))
                    verify_conn.execute("SELECT 1")
                    verify_conn.close()
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Backup verification failed: {e}",
                    }
                
                # 使用 SQLite 备份 API 恢复：从备份文件拷贝到目标数据库
                # 注意：SQLite 备份 API 会自动处理目标数据库的锁定和并发访问
                src = sqlite3.connect(str(backup_path))
                dst = sqlite3.connect(str(target_path))
                try:
                    src.backup(dst)
                finally:
                    src.close()
                    dst.close()
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
    
    def restore_with_safety_net(
        self,
        backup_path: str,
        target_path: str,
        auto_rollback: bool = True,
    ) -> Dict[str, Any]:
        """
        带安全网的恢复操作
        
        恢复前自动创建当前数据库的安全网备份，
        如果恢复失败则自动回滚到安全网备份。
        
        Args:
            backup_path: 要恢复的备份文件路径
            target_path: 恢复目标路径
            auto_rollback: 恢复失败时是否自动回滚
        
        Returns:
            恢复结果字典，包含 safety_net_path 字段
        """
        backup_path = Path(backup_path)
        target_path = Path(target_path)
        safety_net_path: Optional[Path] = None
        
        try:
            # 1. 创建安全网备份（如果目标已存在）
            if target_path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safety_net_name = f".safety_net_{timestamp}.db"
                safety_net_path = target_path.parent / safety_net_name
                
                safety_result = self._backup_single_db(target_path, safety_net_path)
                if not safety_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to create safety net backup: {safety_result.get('error')}",
                        "safety_net_created": False,
                    }
            else:
                # 目标不存在，无需安全网
                safety_net_path = None
            
            # 2. 执行恢复
            restore_result = self.restore_backup(
                str(backup_path),
                str(target_path),
                overwrite=True,
            )
            
            # 3. 恢复成功
            if restore_result["success"]:
                return {
                    "success": True,
                    "restored_to": str(target_path),
                    "safety_net_path": str(safety_net_path) if safety_net_path else None,
                    "safety_net_created": safety_net_path is not None,
                    "rolled_back": False,
                    "timestamp": time.time(),
                }
            
            # 4. 恢复失败，尝试回滚
            if auto_rollback and safety_net_path is not None:
                rollback_result = self.restore_backup(
                    str(safety_net_path),
                    str(target_path),
                    overwrite=True,
                )
                return {
                    "success": False,
                    "error": restore_result.get("error", "Restore failed"),
                    "safety_net_path": str(safety_net_path),
                    "safety_net_created": True,
                    "rolled_back": rollback_result["success"],
                    "rollback_error": None if rollback_result["success"] else rollback_result.get("error"),
                    "timestamp": time.time(),
                }
            
            # 恢复失败且不自动回滚
            return {
                "success": False,
                "error": restore_result.get("error", "Restore failed"),
                "safety_net_path": str(safety_net_path) if safety_net_path else None,
                "safety_net_created": safety_net_path is not None,
                "rolled_back": False,
                "timestamp": time.time(),
            }
            
        except Exception as e:
            # 异常时尝试回滚
            if auto_rollback and safety_net_path is not None and safety_net_path.exists():
                try:
                    self.restore_backup(str(safety_net_path), str(target_path), overwrite=True)
                    rolled_back = True
                    rollback_error = None
                except Exception as re:
                    rolled_back = False
                    rollback_error = str(re)
            else:
                rolled_back = False
                rollback_error = None
            
            return {
                "success": False,
                "error": str(e),
                "safety_net_path": str(safety_net_path) if safety_net_path else None,
                "safety_net_created": safety_net_path is not None and safety_net_path.exists(),
                "rolled_back": rolled_back,
                "rollback_error": rollback_error,
                "timestamp": time.time(),
            }
    
    # --------------------------------------------------------
    # 模块级备份
    # --------------------------------------------------------
    
    def backup_module(self, module_config: ModuleBackupConfig) -> BackupReport:
        """
        备份指定模块的所有数据库
        
        Args:
            module_config: 模块备份配置
        
        Returns:
            详细的备份报告
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(module_config.backup_dir) / f"{module_config.module_id}_{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        total_size = 0
        success_count = 0
        fail_count = 0
        details: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        
        for db_path_str in module_config.db_paths:
            db_path = Path(db_path_str)
            
            if not db_path.exists():
                fail_count += 1
                errors.append(f"Database not found: {db_path}")
                details[db_path.name] = {
                    "success": False,
                    "error": f"Database not found: {db_path}",
                }
                continue
            
            backup_file = backup_dir / db_path.name
            result = self._backup_single_db(db_path, backup_file)
            
            if result["success"]:
                success_count += 1
                total_size += result["size_bytes"]
                details[db_path.name] = result
            else:
                fail_count += 1
                errors.append(f"{db_path.name}: {result.get('error', 'unknown')}")
                details[db_path.name] = result
        
        # 清理该模块的旧备份
        self._cleanup_module_backups(
            module_config.backup_dir,
            module_config.module_id,
            module_config.max_backups,
        )
        
        return BackupReport(
            module_id=module_config.module_id,
            success=fail_count == 0 and success_count > 0,
            total_dbs=len(module_config.db_paths),
            success_dbs=success_count,
            failed_dbs=fail_count,
            total_size_bytes=total_size,
            total_size_mb=round(total_size / 1024 / 1024, 2),
            backup_dir=str(backup_dir),
            timestamp=time.time(),
            details=details,
            errors=errors,
        )
    
    def _cleanup_module_backups(
        self,
        backup_base_dir: str,
        module_id: str,
        max_backups: int,
    ) -> None:
        """
        清理指定模块的旧备份
        
        Args:
            backup_base_dir: 备份根目录
            module_id: 模块ID
            max_backups: 最大保留数
        """
        try:
            base_dir = Path(backup_base_dir)
            if not base_dir.exists():
                return
            
            # 查找该模块的所有备份目录
            module_backups = sorted(
                [d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith(f"{module_id}_")],
                key=lambda d: d.stat().st_ctime,
                reverse=True,
            )
            
            if len(module_backups) <= max_backups:
                return
            
            # 删除超出数量的旧备份
            for old_backup in module_backups[max_backups:]:
                try:
                    shutil.rmtree(old_backup)
                except Exception:
                    pass
        except Exception:
            pass
    
    # --------------------------------------------------------
    # 备份完整性校验
    # --------------------------------------------------------
    
    def verify_backup(
        self,
        backup_path: str,
        check_tables: bool = True,
    ) -> VerifyReport:
        """
        校验备份文件的完整性
        
        执行以下检查：
        1. 文件存在性与大小检查
        2. MD5 校验和计算
        3. PRAGMA integrity_check 完整性检查
        4. PRAGMA quick_check 快速检查
        5. 表数量验证（可选）
        
        Args:
            backup_path: 备份文件路径
            check_tables: 是否检查表数量>0
        
        Returns:
            详细的校验报告
        """
        backup_path_obj = Path(backup_path)
        report = VerifyReport(backup_path=str(backup_path_obj))
        
        # 1. 文件存在性检查
        if not backup_path_obj.exists():
            report.errors.append(f"Backup file not found: {backup_path}")
            return report
        
        if not backup_path_obj.is_file():
            report.errors.append(f"Path is not a file: {backup_path}")
            return report
        
        report.file_valid = True
        
        # 2. 文件大小
        try:
            report.file_size_bytes = backup_path_obj.stat().st_size
        except Exception as e:
            report.errors.append(f"Failed to get file size: {e}")
        
        # 3. MD5 校验和
        try:
            md5_hash = hashlib.md5()
            with open(backup_path_obj, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5_hash.update(chunk)
            report.md5_checksum = md5_hash.hexdigest()
        except Exception as e:
            report.errors.append(f"Failed to calculate MD5: {e}")
        
        # 4. SQLite 完整性检查
        if backup_path_obj.suffix == ".db" or backup_path_obj.suffix == ".sqlite":
            conn = None
            try:
                conn = sqlite3.connect(str(backup_path_obj))
                
                # PRAGMA integrity_check
                cursor = conn.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                report.integrity_check = result[0] if result else "unknown"
                
                # PRAGMA quick_check
                cursor = conn.execute("PRAGMA quick_check")
                result = cursor.fetchone()
                report.quick_check = result[0] if result else "unknown"
                
                # 表数量
                cursor = conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                )
                result = cursor.fetchone()
                report.table_count = result[0] if result else 0
                report.has_tables = report.table_count > 0
                
                conn.close()
                conn = None
                
            except Exception as e:
                report.errors.append(f"SQLite check failed: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        else:
            # 非SQLite文件，跳过数据库检查
            report.integrity_check = "skipped (not a database file)"
            report.quick_check = "skipped (not a database file)"
            report.has_tables = True  # 非DB文件不检查表
        
        # 5. 综合判断
        integrity_ok = report.integrity_check == "ok" or "skipped" in report.integrity_check
        quick_ok = report.quick_check == "ok" or "skipped" in report.quick_check
        tables_ok = (not check_tables) or report.has_tables
        
        report.overall_valid = (
            report.file_valid
            and report.file_size_bytes > 0
            and integrity_ok
            and quick_ok
            and tables_ok
            and len(report.errors) == 0
        )
        
        return report
    
    # --------------------------------------------------------
    # 增量备份
    # --------------------------------------------------------
    
    def incremental_backup(
        self,
        db_path: str,
        base_backup_path: str,
    ) -> IncrementalBackupReport:
        """
        基于基准备份的增量备份
        
        使用简化版 page-level 比较：记录表级别的记录数变化。
        生成一个包含差异信息的增量备份文件。
        
        Args:
            db_path: 当前数据库路径
            base_backup_path: 基准备份路径
        
        Returns:
            增量备份报告
        """
        db_path_obj = Path(db_path)
        base_backup_obj = Path(base_backup_path)
        
        report = IncrementalBackupReport(
            success=False,
            db_path=str(db_path_obj),
            base_backup_path=str(base_backup_obj),
        )
        
        try:
            # 检查输入
            if not db_path_obj.exists():
                report.errors.append(f"Source database not found: {db_path}")
                return report
            
            if not base_backup_obj.exists():
                report.errors.append(f"Base backup not found: {base_backup_path}")
                return report
            
            report.base_size_bytes = base_backup_obj.stat().st_size
            report.timestamp = time.time()
            
            # 1. 获取基准备份的表信息和记录数
            base_tables = self._get_table_row_counts(str(base_backup_obj))
            if base_tables is None:
                report.errors.append("Failed to read base backup table info")
                return report
            
            # 2. 获取当前数据库的表信息和记录数
            current_tables = self._get_table_row_counts(str(db_path_obj))
            if current_tables is None:
                report.errors.append("Failed to read current database table info")
                return report
            
            # 3. 计算差异
            base_table_set = set(base_tables.keys())
            current_table_set = set(current_tables.keys())
            
            report.new_tables = sorted(list(current_table_set - base_table_set))
            report.deleted_tables = sorted(list(base_table_set - current_table_set))
            
            # 查找记录数变化的表
            common_tables = base_table_set & current_table_set
            for table in sorted(common_tables):
                if base_tables[table] != current_tables[table]:
                    report.changed_tables.append(table)
                    diff = abs(current_tables[table] - base_tables[table])
                    report.total_changes += diff
            
            # 4. 创建增量备份（完整复制当前数据库 + 元数据）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            incremental_dir = db_path_obj.parent / "incremental_backups"
            incremental_dir.mkdir(parents=True, exist_ok=True)
            incremental_name = f"incr_{timestamp}_{db_path_obj.stem}.db"
            incremental_path = incremental_dir / incremental_name
            
            # 使用 SQLite backup API 复制当前数据库作为增量
            incr_result = self._backup_single_db(db_path_obj, incremental_path)
            if not incr_result["success"]:
                report.errors.append(f"Failed to create incremental backup: {incr_result.get('error')}")
                return report
            
            report.incremental_path = str(incremental_path)
            report.incremental_size_bytes = incr_result["size_bytes"]
            
            # 5. 写入增量元数据（通过 PRAGMA user_version 不适合，改用附加元数据表）
            try:
                conn = sqlite3.connect(str(incremental_path))
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS _backup_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
                metadata = {
                    "backup_type": "incremental",
                    "base_backup": str(base_backup_obj),
                    "source_db": str(db_path_obj),
                    "timestamp": str(report.timestamp),
                    "changed_tables": ",".join(report.changed_tables),
                    "new_tables": ",".join(report.new_tables),
                    "deleted_tables": ",".join(report.deleted_tables),
                    "total_changes": str(report.total_changes),
                }
                for key, value in metadata.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO _backup_metadata (key, value) VALUES (?, ?)",
                        (key, value),
                    )
                conn.commit()
                conn.close()
            except Exception as e:
                report.errors.append(f"Failed to write metadata: {e}")
                # 元数据写入失败不影响整体成功
            
            report.success = True
            
        except Exception as e:
            report.errors.append(f"Incremental backup failed: {e}")
        
        return report
    
    def _get_table_row_counts(self, db_path: str) -> Optional[Dict[str, int]]:
        """
        获取数据库中所有用户表的记录数
        
        Args:
            db_path: 数据库路径
        
        Returns:
            表名->记录数的字典，失败返回None
        """
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_backup_%'"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
            row_counts: Dict[str, int] = {}
            for table in tables:
                try:
                    cursor = conn.execute(f'SELECT count(*) FROM "{table}"')
                    row_counts[table] = cursor.fetchone()[0]
                except Exception:
                    row_counts[table] = -1
            
            conn.close()
            return row_counts
        except Exception:
            return None
    
    # --------------------------------------------------------
    # 备份生命周期管理
    # --------------------------------------------------------
    
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
        """清理过期备份（按数量）"""
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
    
    def cleanup_by_age(self, max_age_days: int) -> Dict[str, Any]:
        """
        按时间保留策略清理旧备份
        
        Args:
            max_age_days: 最大保留天数
        
        Returns:
            清理结果字典
        """
        if max_age_days <= 0:
            return {
                "success": False,
                "error": "max_age_days must be positive",
            }
        
        cutoff_time = time.time() - (max_age_days * 86400)
        backups = self.list_backups()
        
        deleted = []
        failed = []
        
        for backup in backups:
            if backup["created"] < cutoff_time:
                try:
                    backup_path = Path(backup["path"])
                    if backup_path.is_dir():
                        shutil.rmtree(backup_path)
                    else:
                        backup_path.unlink()
                    deleted.append(backup["name"])
                except Exception as e:
                    failed.append({
                        "name": backup["name"],
                        "error": str(e),
                    })
        
        return {
            "success": True,
            "max_age_days": max_age_days,
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted": deleted,
            "failed": failed,
            "timestamp": time.time(),
        }
    
    def apply_retention_policy(
        self,
        strategy: str = "count",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        应用备份保留策略
        
        支持的策略：
        - "count": 按数量保留（默认）
        - "age": 按时间保留
        - "hybrid": 混合策略（同时满足数量和时间条件才删除）
        
        Args:
            strategy: 保留策略名称
            **kwargs: 策略参数
                - count 策略: max_count (int)
                - age 策略: max_age_days (int)
                - hybrid 策略: max_count (int), max_age_days (int)
        
        Returns:
            策略执行结果
        """
        if strategy == "count":
            max_count = kwargs.get("max_count", self.max_backups)
            self.max_backups = max_count
            self._cleanup_old_backups()
            backups = self.list_backups()
            return {
                "success": True,
                "strategy": "count",
                "max_count": max_count,
                "remaining": len(backups),
                "timestamp": time.time(),
            }
        
        elif strategy == "age":
            max_age_days = kwargs.get("max_age_days", 30)
            result = self.cleanup_by_age(max_age_days)
            result["strategy"] = "age"
            return result
        
        elif strategy == "hybrid":
            max_count = kwargs.get("max_count", self.max_backups)
            max_age_days = kwargs.get("max_age_days", 30)
            
            # 先按时间清理
            age_result = self.cleanup_by_age(max_age_days)
            
            # 再按数量清理
            original_max = self.max_backups
            self.max_backups = max_count
            self._cleanup_old_backups()
            self.max_backups = original_max
            
            backups = self.list_backups()
            
            return {
                "success": True,
                "strategy": "hybrid",
                "max_count": max_count,
                "max_age_days": max_age_days,
                "age_deleted_count": age_result.get("deleted_count", 0),
                "remaining": len(backups),
                "timestamp": time.time(),
            }
        
        else:
            return {
                "success": False,
                "error": f"Unknown retention strategy: {strategy}. "
                         f"Supported: count, age, hybrid",
            }
    
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


# ============================================================
# 统一备份调度中心
# ============================================================

class BackupOrchestrator:
    """统一备份调度中心
    
    管理多个模块的备份配置，统一调度所有模块的备份，
    生成全系统备份报告，支持按模块查询备份历史。
    
    Attributes:
        backup_manager: 备份管理器实例
    """
    
    def __init__(self, backup_manager: Optional[BackupManager] = None):
        """
        初始化备份调度中心
        
        Args:
            backup_manager: 备份管理器实例，None则使用默认
        """
        self.backup_manager = backup_manager or BackupManager()
        self._module_configs: Dict[str, ModuleBackupConfig] = {}
        self._schedulers: Dict[str, BackupScheduler] = {}
        self._backup_history: Dict[str, List[BackupReport]] = {}
        self._lock = threading.Lock()
    
    def register_module(self, config: ModuleBackupConfig) -> bool:
        """
        注册模块备份配置
        
        Args:
            config: 模块备份配置
        
        Returns:
            是否注册成功
        """
        with self._lock:
            if config.module_id in self._module_configs:
                return False
            
            self._module_configs[config.module_id] = config
            self._backup_history[config.module_id] = []
            
            # 如果配置了调度，自动创建调度器
            if config.schedule:
                self._setup_scheduler(config)
            
            return True
    
    def unregister_module(self, module_id: str) -> bool:
        """
        注销模块备份配置
        
        Args:
            module_id: 模块ID
        
        Returns:
            是否注销成功
        """
        with self._lock:
            if module_id not in self._module_configs:
                return False
            
            # 停止调度器
            if module_id in self._schedulers:
                self._schedulers[module_id].stop()
                del self._schedulers[module_id]
            
            del self._module_configs[module_id]
            if module_id in self._backup_history:
                del self._backup_history[module_id]
            
            return True
    
    def _setup_scheduler(self, config: ModuleBackupConfig) -> None:
        """
        为模块设置定时调度器（内部方法，必须持有 _lock）
        
        Args:
            config: 模块备份配置
        """
        if not config.schedule:
            return
        
        module_id = config.module_id
        
        def _backup_task():
            try:
                self.backup_module(module_id)
            except Exception:
                pass
        
        scheduler = BackupScheduler(_backup_task)
        scheduler.start(config.schedule)
        self._schedulers[module_id] = scheduler
    
    def backup_module(self, module_id: str) -> Optional[BackupReport]:
        """
        立即备份指定模块
        
        Args:
            module_id: 模块ID
        
        Returns:
            备份报告，模块不存在返回None
        """
        with self._lock:
            config = self._module_configs.get(module_id)
            if config is None:
                return None
        
        report = self.backup_manager.backup_module(config)
        
        # 记录历史
        with self._lock:
            if module_id in self._backup_history:
                self._backup_history[module_id].append(report)
                # 最多保留100条历史
                if len(self._backup_history[module_id]) > 100:
                    self._backup_history[module_id] = \
                        self._backup_history[module_id][-100:]
        
        return report
    
    def backup_all_modules(self) -> Dict[str, Any]:
        """
        备份所有已注册的模块
        
        Returns:
            全系统备份报告
        """
        results: Dict[str, Any] = {}
        total_size = 0
        success_count = 0
        fail_count = 0
        
        with self._lock:
            module_ids = list(self._module_configs.keys())
        
        for module_id in module_ids:
            report = self.backup_module(module_id)
            if report is None:
                continue
            
            results[module_id] = {
                "success": report.success,
                "total_dbs": report.total_dbs,
                "success_dbs": report.success_dbs,
                "failed_dbs": report.failed_dbs,
                "total_size_bytes": report.total_size_bytes,
                "backup_dir": report.backup_dir,
            }
            
            if report.success:
                success_count += 1
            else:
                fail_count += 1
            total_size += report.total_size_bytes
        
        return {
            "success": fail_count == 0 and success_count > 0,
            "total_modules": len(module_ids),
            "success_modules": success_count,
            "failed_modules": fail_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "modules": results,
            "timestamp": time.time(),
        }
    
    def get_module_history(
        self,
        module_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        查询指定模块的备份历史
        
        Args:
            module_id: 模块ID
            limit: 返回条数限制
        
        Returns:
            备份历史列表（按时间倒序）
        """
        with self._lock:
            history = self._backup_history.get(module_id, [])
            # 复制并倒序
            recent = list(reversed(history))[:limit]
        
        return [
            {
                "module_id": r.module_id,
                "success": r.success,
                "total_dbs": r.total_dbs,
                "success_dbs": r.success_dbs,
                "failed_dbs": r.failed_dbs,
                "total_size_bytes": r.total_size_bytes,
                "backup_dir": r.backup_dir,
                "timestamp": r.timestamp,
                "errors": r.errors,
            }
            for r in recent
        ]
    
    def get_system_report(self) -> Dict[str, Any]:
        """
        获取全系统备份报告
        
        Returns:
            系统备份状态报告
        """
        with self._lock:
            module_ids = list(self._module_configs.keys())
            scheduler_status = {
                mid: sched.status()
                for mid, sched in self._schedulers.items()
            }
        
        module_stats = {}
        total_backups = 0
        
        for module_id in module_ids:
            history = self.get_module_history(module_id, limit=100)
            success_count = sum(1 for h in history if h["success"])
            module_stats[module_id] = {
                "total_backups": len(history),
                "success_count": success_count,
                "fail_count": len(history) - success_count,
                "last_backup": history[0] if history else None,
                "scheduler": scheduler_status.get(module_id, {"running": False}),
            }
            total_backups += len(history)
        
        base_stats = self.backup_manager.get_backup_stats()
        
        return {
            "total_modules": len(module_ids),
            "total_backups": total_backups,
            "modules": module_stats,
            "backup_root": str(self.backup_manager.backup_root),
            "base_stats": base_stats,
            "timestamp": time.time(),
        }
    
    def restore_system(
        self,
        backup_dir: str,
        modules: Optional[List[str]] = None,
        use_safety_net: bool = True,
    ) -> Dict[str, Any]:
        """
        全系统一键恢复（谨慎操作）
        
        从指定备份目录恢复所有模块的数据库。
        注意：此操作具有破坏性，请确保已验证备份完整性。
        
        Args:
            backup_dir: 备份目录路径
            modules: 要恢复的模块列表，None表示全部
            use_safety_net: 是否使用安全网恢复
        
        Returns:
            恢复结果
        """
        backup_dir_obj = Path(backup_dir)
        if not backup_dir_obj.exists():
            return {
                "success": False,
                "error": f"Backup directory not found: {backup_dir}",
            }
        
        results: Dict[str, Any] = {}
        success_count = 0
        fail_count = 0
        
        with self._lock:
            config_items = list(self._module_configs.items())
        
        for module_id, config in config_items:
            if modules and module_id not in modules:
                continue
            
            module_backup_dir = backup_dir_obj / config.module_id
            if not module_backup_dir.exists():
                # 尝试直接用 backup_dir 作为模块备份目录
                if backup_dir_obj.name.startswith(f"{config.module_id}_"):
                    module_backup_dir = backup_dir_obj
                else:
                    results[module_id] = {
                        "success": False,
                        "error": f"Module backup dir not found: {module_backup_dir}",
                    }
                    fail_count += 1
                    continue
            
            module_success = 0
            module_fail = 0
            db_results: Dict[str, Any] = {}
            
            for db_path_str in config.db_paths:
                db_path = Path(db_path_str)
                backup_file = module_backup_dir / db_path.name
                
                if not backup_file.exists():
                    module_fail += 1
                    db_results[db_path.name] = {
                        "success": False,
                        "error": f"Backup file not found: {backup_file}",
                    }
                    continue
                
                if use_safety_net:
                    restore_result = self.backup_manager.restore_with_safety_net(
                        str(backup_file),
                        str(db_path),
                        auto_rollback=True,
                    )
                else:
                    restore_result = self.backup_manager.restore_backup(
                        str(backup_file),
                        str(db_path),
                        overwrite=True,
                    )
                
                if restore_result["success"]:
                    module_success += 1
                else:
                    module_fail += 1
                db_results[db_path.name] = restore_result
            
            results[module_id] = {
                "success": module_fail == 0 and module_success > 0,
                "total_dbs": len(config.db_paths),
                "success_dbs": module_success,
                "failed_dbs": module_fail,
                "databases": db_results,
            }
            
            if results[module_id]["success"]:
                success_count += 1
            else:
                fail_count += 1
        
        return {
            "success": fail_count == 0 and success_count > 0,
            "backup_dir": str(backup_dir_obj),
            "total_modules": success_count + fail_count,
            "success_modules": success_count,
            "failed_modules": fail_count,
            "modules": results,
            "use_safety_net": use_safety_net,
            "timestamp": time.time(),
        }
    
    def get_module_config(self, module_id: str) -> Optional[ModuleBackupConfig]:
        """
        获取模块备份配置
        
        Args:
            module_id: 模块ID
        
        Returns:
            模块配置，不存在返回None
        """
        with self._lock:
            return self._module_configs.get(module_id)
    
    def list_modules(self) -> List[str]:
        """
        列出所有已注册的模块ID
        
        Returns:
            模块ID列表
        """
        with self._lock:
            return list(self._module_configs.keys())


# ============================================================
# 全局单例
# ============================================================

_backup_manager: Optional[BackupManager] = None
_backup_orchestrator: Optional[BackupOrchestrator] = None


def get_backup_manager() -> BackupManager:
    """获取全局备份管理器实例"""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager


def get_backup_orchestrator() -> BackupOrchestrator:
    """获取全局备份调度中心实例"""
    global _backup_orchestrator
    if _backup_orchestrator is None:
        _backup_orchestrator = BackupOrchestrator()
    return _backup_orchestrator
