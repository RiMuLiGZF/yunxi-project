"""
M8 管理工作台 - 备份调度中心核心服务（第二阶段统一治理增强版）

BackupOrchestratorService 是全系统备份的统一管理入口，
负责：
- 管理所有模块的备份配置（注册/注销/更新）
- 定时调度各模块执行备份（支持 cron 表达式）
- 调用各模块备份 API 端点执行备份
- 本地回退备份（直接使用 shared backup_manager）
- 收集备份结果，记录历史
- 提供统计分析
- 备份失败告警
- 备份存储空间监控
- 支持按模块配置不同的备份策略

设计要点：
- 使用 threading.Timer 实现轻量级定时调度
- 线程安全，支持并发访问
- 配置持久化到数据库（backup_modules 表）
- 历史记录持久化到数据库（backup_history 表）
- 支持一键触发全系统备份和单模块备份
- 与 shared.data_layer.backup_manager 深度集成
"""

import sys
import time
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session

from shared.logger import get_logger
from ..models import BackupModule, BackupHistory, SessionLocal, get_db

# 导入增强版备份管理器
try:
    from shared.data.data_layer.backup_manager import (
        BackupManager,
        ModuleBackupConfig as SharedModuleConfig,
        BackupType,
        CompressionType,
        EncryptionType,
        RetentionPolicy,
        CronExpression,
    )
    _HAS_ENHANCED_BACKUP = True
except ImportError:
    _HAS_ENHANCED_BACKUP = False
    # 回退导入
    try:
        from shared.data_layer.backup_manager import BackupManager, ModuleBackupConfig
        _HAS_OLD_BACKUP = True
    except ImportError:
        _HAS_OLD_BACKUP = False

logger = get_logger("m8.backup_scheduler")


# ============================================================
# 模块调度器（增强版，支持 cron）
# ============================================================

class ModuleBackupScheduler:
    """单个模块的备份调度器（增强版）

    支持 daily/interval/cron 三种调度模式。
    """

    def __init__(self, module_id: str, callback):
        self.module_id = module_id
        self._callback = callback
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._schedule_type: str = "none"
        self._schedule_time: str = "03:00"
        self._schedule_interval_minutes: int = 0
        self._cron_expression: str = ""
        self._cron: Optional[Any] = None
        self._last_run: Optional[float] = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_run(self) -> Optional[float]:
        return self._last_run

    def start(self, schedule_type: str, schedule_time: str = "03:00",
              schedule_interval_minutes: int = 0,
              cron_expression: str = "") -> bool:
        """
        启动调度器

        Args:
            schedule_type: 调度类型：daily/interval/cron/none
            schedule_time: 每日备份时间（daily 模式使用）
            schedule_interval_minutes: 间隔分钟数（interval 模式使用）
            cron_expression: cron 表达式（cron 模式使用）

        Returns:
            是否成功启动
        """
        with self._lock:
            if self._running:
                self._stop_no_lock()

            self._schedule_type = schedule_type
            self._schedule_time = schedule_time
            self._schedule_interval_minutes = schedule_interval_minutes
            self._cron_expression = cron_expression
            self._cron = None

            if schedule_type == "none" or schedule_type is None:
                return False

            # cron 模式
            if schedule_type == "cron" and cron_expression:
                if _HAS_ENHANCED_BACKUP:
                    try:
                        self._cron = CronExpression(cron_expression)
                    except Exception as e:
                        logger.error(f"cron 表达式解析失败: module={self.module_id}, error={e}")
                        return False
                else:
                    # 没有增强版 backup_manager，cron 模式不支持
                    return False

            self._running = True
            self._schedule_next()
            logger.info(f"备份调度器已启动: module={self.module_id}, type={schedule_type}")
            return True

    def stop(self) -> bool:
        """停止调度器"""
        with self._lock:
            return self._stop_no_lock()

    def _stop_no_lock(self) -> bool:
        """停止调度器（不获取锁，内部方法）"""
        if not self._running:
            return False
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._cron = None
        logger.info(f"备份调度器已停止: module={self.module_id}")
        return True

    def status(self) -> Dict[str, Any]:
        """查询调度器状态"""
        with self._lock:
            return {
                "running": self._running,
                "schedule_type": self._schedule_type,
                "schedule_time": self._schedule_time,
                "schedule_interval_minutes": self._schedule_interval_minutes,
                "cron_expression": self._cron_expression,
                "last_run": self._last_run,
                "next_run": self._get_next_run_time(),
            }

    def _get_next_run_time(self) -> Optional[float]:
        """计算下次运行时间"""
        if not self._running or self._schedule_type == "none":
            return None

        now = datetime.now()

        if self._schedule_type == "cron" and self._cron:
            try:
                return self._cron.next_run_time(now).timestamp()
            except Exception:
                return None

        if self._schedule_type == "daily":
            try:
                hour, minute = map(int, self._schedule_time.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return target.timestamp()
            except (ValueError, AttributeError):
                return None

        elif self._schedule_type == "interval":
            seconds = self._schedule_interval_minutes * 60
            if seconds <= 0:
                return None
            if self._last_run:
                return self._last_run + seconds
            else:
                return now.timestamp() + seconds

        return None

    def _schedule_next(self) -> None:
        """调度下一次执行（内部方法，调用时必须持有 _lock）"""
        if not self._running or self._schedule_type == "none":
            return

        delay = self._calculate_delay()
        if delay is None or delay <= 0:
            return

        self._timer = threading.Timer(delay, self._run_task)
        self._timer.daemon = True
        self._timer.start()

    def _calculate_delay(self) -> Optional[float]:
        """计算距离下次执行的延迟秒数"""
        if self._schedule_type == "none":
            return None

        now = datetime.now()

        if self._schedule_type == "cron" and self._cron:
            try:
                next_time = self._cron.next_run_time(now)
                return (next_time - now).total_seconds()
            except Exception:
                return None

        if self._schedule_type == "daily":
            try:
                hour, minute = map(int, self._schedule_time.split(":"))
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                return (target - now).total_seconds()
            except (ValueError, AttributeError):
                return None

        elif self._schedule_type == "interval":
            seconds = self._schedule_interval_minutes * 60
            if seconds <= 0:
                return None
            return float(seconds)

        return None

    def _run_task(self) -> None:
        """执行备份任务（Timer回调）"""
        try:
            logger.info(f"定时备份触发: module={self.module_id}")
            self._callback(self.module_id, trigger_type="scheduled")
        except Exception as e:
            logger.error(f"定时备份执行异常: module={self.module_id}, error={e}")
        finally:
            self._last_run = time.time()
            with self._lock:
                if self._running:
                    self._schedule_next()


# ============================================================
# 备份调度中心主服务（增强版）
# ============================================================

class BackupOrchestratorService:
    """备份调度中心服务（增强版）

    第二阶段统一治理增强：
    - 支持 cron 表达式调度
    - 备份失败告警
    - 存储空间监控
    - 与增强版 backup_manager 深度集成
    - 支持按模块配置不同的备份策略
    """

    def __init__(self):
        """初始化备份调度中心"""
        self._lock = threading.RLock()
        self._schedulers: Dict[str, ModuleBackupScheduler] = {}
        self._running_modules: Dict[str, bool] = {}
        self._initialized = False
        self._backup_manager: Optional[Any] = None
        self._alerts: List[Dict[str, Any]] = []
        self._alerts_lock = threading.Lock()

        # 告警阈值配置
        self._alert_config = {
            "consecutive_failures": 3,       # 连续失败次数阈值
            "disk_free_percent_warn": 20,   # 磁盘空间警告阈值（%）
            "disk_free_percent_critical": 10,  # 磁盘空间严重阈值（%）
            "max_backup_age_hours": 48,     # 最大备份间隔（小时）
        }

    def initialize(self) -> None:
        """初始化调度中心

        从数据库加载所有已启用的模块配置，
        并启动对应的调度器。
        """
        with self._lock:
            if self._initialized:
                return

            # 初始化备份管理器
            if _HAS_ENHANCED_BACKUP:
                try:
                    backup_root = project_root / "backups" / "m8_backups"
                    self._backup_manager = BackupManager(
                        backup_root=str(backup_root),
                    )
                except Exception as e:
                    logger.error(f"备份管理器初始化失败: {e}")

            db = SessionLocal()
            try:
                modules = db.query(BackupModule).filter(
                    BackupModule.enabled == True  # noqa: E712
                ).all()

                for module in modules:
                    self._setup_scheduler_for_module(module)

                self._initialized = True
                logger.info(f"备份调度中心初始化完成，已加载 {len(modules)} 个模块")
            except Exception as e:
                logger.error(f"备份调度中心初始化失败: {e}")
            finally:
                db.close()

            # 启动存储监控线程
            self._start_storage_monitor()

    def _setup_scheduler_for_module(self, module: BackupModule) -> None:
        """为模块设置调度器（内部方法，必须持有 _lock）"""
        if module.module_id in self._schedulers:
            self._schedulers[module.module_id].stop()

        if not module.enabled or module.schedule_type == "none":
            return

        scheduler = ModuleBackupScheduler(
            module.module_id,
            self._execute_scheduled_backup,
        )

        # 从 extra_config 中获取 cron 表达式
        extra = module.extra_config or {}
        cron_expr = extra.get("cron_expression", "")

        scheduler.start(
            schedule_type=module.schedule_type,
            schedule_time=module.schedule_time,
            schedule_interval_minutes=module.schedule_interval_minutes,
            cron_expression=cron_expr,
        )
        self._schedulers[module.module_id] = scheduler

    def _execute_scheduled_backup(self, module_id: str, trigger_type: str = "scheduled") -> None:
        """执行定时备份（调度器回调）"""
        try:
            self.trigger_backup(module_id, trigger_type=trigger_type)
        except Exception as e:
            logger.error(f"定时备份执行失败: module={module_id}, error={e}")

    # --------------------------------------------------------
    # 模块管理
    # --------------------------------------------------------

    def register_module(self, module_data: Dict[str, Any]) -> Dict[str, Any]:
        """注册新的备份模块"""
        db = SessionLocal()
        try:
            module_id = module_data.get("module_id", "").strip().lower()
            if not module_id:
                return {"success": False, "error": "module_id 不能为空"}

            existing = db.query(BackupModule).filter(
                BackupModule.module_id == module_id
            ).first()
            if existing:
                return {"success": False, "error": f"模块 {module_id} 已存在"}

            # 处理 extra_config
            extra_config = module_data.get("extra_config", {})
            if not isinstance(extra_config, dict):
                extra_config = {}

            module = BackupModule(
                module_id=module_id,
                module_name=module_data.get("module_name", module_id),
                backup_endpoint=module_data.get("backup_endpoint", ""),
                auth_token=module_data.get("auth_token", ""),
                schedule_type=module_data.get("schedule_type", "daily"),
                schedule_time=module_data.get("schedule_time", "03:00"),
                schedule_interval_minutes=module_data.get("schedule_interval_minutes", 0),
                enabled=module_data.get("enabled", True),
                max_backups=module_data.get("max_backups", 30),
                description=module_data.get("description", ""),
                extra_config=extra_config,
            )

            db.add(module)
            db.commit()
            db.refresh(module)

            with self._lock:
                if module.enabled:
                    self._setup_scheduler_for_module(module)

            logger.info(f"模块已注册: {module_id}")
            return {"success": True, "module": module.to_dict()}
        except Exception as e:
            db.rollback()
            logger.error(f"注册模块失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def update_module(self, module_id: str, module_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新模块备份配置"""
        db = SessionLocal()
        try:
            module = db.query(BackupModule).filter(
                BackupModule.module_id == module_id
            ).first()
            if not module:
                return {"success": False, "error": f"模块 {module_id} 不存在"}

            updatable_fields = [
                "module_name", "backup_endpoint", "auth_token",
                "schedule_type", "schedule_time", "schedule_interval_minutes",
                "enabled", "max_backups", "description", "extra_config",
            ]
            for field in updatable_fields:
                if field in module_data:
                    setattr(module, field, module_data[field])

            db.commit()
            db.refresh(module)

            with self._lock:
                self._setup_scheduler_for_module(module)

            logger.info(f"模块配置已更新: {module_id}")
            return {"success": True, "module": module.to_dict()}
        except Exception as e:
            db.rollback()
            logger.error(f"更新模块失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def delete_module(self, module_id: str) -> Dict[str, Any]:
        """删除备份模块"""
        db = SessionLocal()
        try:
            module = db.query(BackupModule).filter(
                BackupModule.module_id == module_id
            ).first()
            if not module:
                return {"success": False, "error": f"模块 {module_id} 不存在"}

            db.delete(module)
            db.commit()

            with self._lock:
                if module_id in self._schedulers:
                    self._schedulers[module_id].stop()
                    del self._schedulers[module_id]

            logger.info(f"模块已删除: {module_id}")
            return {"success": True}
        except Exception as e:
            db.rollback()
            logger.error(f"删除模块失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def get_module(self, module_id: str) -> Optional[Dict[str, Any]]:
        """获取模块配置"""
        db = SessionLocal()
        try:
            module = db.query(BackupModule).filter(
                BackupModule.module_id == module_id
            ).first()
            return module.to_dict() if module else None
        finally:
            db.close()

    def list_modules(self) -> List[Dict[str, Any]]:
        """列出所有注册的模块"""
        db = SessionLocal()
        try:
            modules = db.query(BackupModule).order_by(BackupModule.module_id).all()
            return [m.to_dict() for m in modules]
        finally:
            db.close()

    # --------------------------------------------------------
    # 备份执行
    # --------------------------------------------------------

    def trigger_backup(self, module_id: str, trigger_type: str = "manual",
                       backup_type: str = "full") -> Dict[str, Any]:
        """触发指定模块的备份"""
        db = SessionLocal()
        try:
            module = db.query(BackupModule).filter(
                BackupModule.module_id == module_id
            ).first()
            if not module:
                return {"success": False, "error": f"模块 {module_id} 不存在"}

            # 检查是否正在执行备份
            with self._lock:
                if self._running_modules.get(module_id, False):
                    return {
                        "success": False,
                        "error": f"模块 {module_id} 正在执行备份，请稍后再试",
                    }
                self._running_modules[module_id] = True

            # 创建历史记录
            history = BackupHistory(
                module_id=module.module_id,
                module_name=module.module_name,
                status="running",
                backup_type=backup_type,
                trigger_type=trigger_type,
                started_at=datetime.utcnow(),
            )
            db.add(history)
            db.commit()
            db.refresh(history)

            start_time = time.time()

            try:
                # 调用模块备份 API
                result = self._call_module_backup_api(module, backup_type)

                # 更新历史记录
                history.status = "success" if result.get("success", False) else "failed"
                history.backup_size_bytes = result.get("total_size_bytes", 0)
                history.backup_size_mb = int(result.get("total_size_mb", 0))
                history.backup_path = result.get("backup_dir", "")
                history.total_dbs = result.get("total_dbs", 0)
                history.success_dbs = result.get("success_dbs", 0)
                history.failed_dbs = result.get("failed_dbs", 0)
                history.error_message = "" if result.get("success", False) else result.get("error", "备份失败")
                history.details = result.get("details", {})
                history.duration_seconds = int(time.time() - start_time)
                history.finished_at = datetime.utcnow()

                # 更新模块的最后备份时间
                if result.get("success", False):
                    module.last_backup_at = datetime.utcnow()

                db.commit()

                # 检查是否需要告警
                if not result.get("success", False):
                    self._check_and_add_alert(module_id, "backup_failed",
                                              f"模块 {module_id} 备份失败: {result.get('error', '未知错误')}")

                return {
                    "success": result.get("success", False),
                    "module_id": module_id,
                    "history_id": history.id,
                    "details": result,
                }

            except Exception as e:
                history.status = "failed"
                history.error_message = str(e)
                history.duration_seconds = int(time.time() - start_time)
                history.finished_at = datetime.utcnow()
                db.commit()

                self._check_and_add_alert(module_id, "backup_failed",
                                          f"模块 {module_id} 备份异常: {e}")

                logger.error(f"备份执行异常: module={module_id}, error={e}")
                return {
                    "success": False,
                    "module_id": module_id,
                    "history_id": history.id,
                    "error": str(e),
                }
            finally:
                with self._lock:
                    self._running_modules[module_id] = False
        finally:
            db.close()

    def _call_module_backup_api(self, module: BackupModule,
                                backup_type: str = "full") -> Dict[str, Any]:
        """调用模块的备份 API"""
        import httpx

        endpoint = module.backup_endpoint
        if not endpoint:
            return self._local_backup_fallback(module, backup_type)

        try:
            headers = {}
            if module.auth_token:
                headers["Authorization"] = f"Bearer {module.auth_token}"
                headers["X-Module-Token"] = module.auth_token

            timeout = httpx.Timeout(300.0, connect=10.0)

            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    endpoint,
                    json={"backup_type": backup_type},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

                if "data" in data and isinstance(data["data"], dict):
                    return data["data"]
                return data

        except Exception as e:
            logger.warning(f"调用模块备份API失败，尝试本地回退: module={module.module_id}, error={e}")
            return self._local_backup_fallback(module, backup_type)

    def _local_backup_fallback(self, module: BackupModule,
                               backup_type: str = "full") -> Dict[str, Any]:
        """本地备份回退方案（增强版）

        当模块备份 API 不可用时，直接使用 shared backup_manager
        在本地执行备份。
        """
        try:
            if not (_HAS_ENHANCED_BACKUP or _HAS_OLD_BACKUP):
                return {
                    "success": False,
                    "error": "备份管理器不可用",
                    "total_dbs": 0,
                    "success_dbs": 0,
                    "failed_dbs": 0,
                    "total_size_bytes": 0,
                    "total_size_mb": 0,
                    "details": {},
                }

            # 查找模块数据库文件
            db_paths = self._find_module_dbs(module)

            if not db_paths:
                # 尝试从 extra_config 读取数据库路径
                extra = module.extra_config or {}
                if "db_paths" in extra:
                    db_paths = extra["db_paths"]

            if not db_paths:
                return {
                    "success": False,
                    "error": f"未找到模块 {module.module_id} 的数据库文件",
                    "total_dbs": 0,
                    "success_dbs": 0,
                    "failed_dbs": 0,
                    "total_size_bytes": 0,
                    "total_size_mb": 0,
                    "details": {},
                }

            # 构造备份目录
            backup_root = project_root / "backups" / "module_backups" / module.module_id

            if _HAS_ENHANCED_BACKUP:
                # 使用增强版备份管理器
                extra = module.extra_config or {}
                compression = extra.get("compression", CompressionType.GZIP)
                encryption = extra.get("encryption", EncryptionType.NONE)
                encryption_key = extra.get("encryption_key", "")

                retention = RetentionPolicy(
                    strategy=extra.get("retention_strategy", "count"),
                    max_count=module.max_backups,
                    max_age_days=extra.get("retention_max_age_days", 30),
                    max_size_gb=extra.get("retention_max_size_gb", 10.0),
                )

                module_config = SharedModuleConfig(
                    module_id=module.module_id,
                    db_paths=db_paths,
                    backup_dir=str(backup_root),
                    max_backups=module.max_backups,
                    backup_type=backup_type,
                    compression=compression,
                    encryption=encryption,
                    encryption_key=encryption_key,
                    retention=retention,
                )

                bm = BackupManager(backup_root=str(backup_root))
                report = bm.backup_module(module_config, backup_type=backup_type)

                return {
                    "success": report.success,
                    "total_dbs": report.total_dbs,
                    "success_dbs": report.success_dbs,
                    "failed_dbs": report.failed_dbs,
                    "total_size_bytes": report.total_size_bytes,
                    "total_size_mb": report.total_size_mb,
                    "backup_dir": report.backup_dir,
                    "details": report.details,
                    "errors": report.errors,
                    "checksum": report.checksum,
                    "compressed": report.compressed,
                    "encrypted": report.encrypted,
                    "duration_seconds": report.duration_seconds,
                }
            else:
                # 使用旧版备份管理器
                from shared.data_layer.backup_manager import (
                    BackupManager, ModuleBackupConfig,
                )
                module_config = ModuleBackupConfig(
                    module_id=module.module_id,
                    db_paths=db_paths,
                    backup_dir=str(backup_root),
                    max_backups=module.max_backups,
                )

                backup_manager = BackupManager()
                report = backup_manager.backup_module(module_config)

                return {
                    "success": report.success,
                    "total_dbs": report.total_dbs,
                    "success_dbs": report.success_dbs,
                    "failed_dbs": report.failed_dbs,
                    "total_size_bytes": report.total_size_bytes,
                    "total_size_mb": report.total_size_mb,
                    "backup_dir": report.backup_dir,
                    "details": report.details,
                    "errors": report.errors,
                }

        except Exception as e:
            logger.error(f"本地备份回退失败: module={module.module_id}, error={e}")
            return {
                "success": False,
                "error": str(e),
                "total_dbs": 0,
                "success_dbs": 0,
                "failed_dbs": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0,
                "details": {},
            }

    def _find_module_dbs(self, module: BackupModule) -> List[str]:
        """查找模块的数据库文件
        
        在项目目录中搜索模块对应的 .db 文件。
        """
        import glob
        
        db_paths = []
        module_id = module.module_id
        module_id_upper = module_id.upper()  # m5 -> M5

        # 常见的模块目录命名模式
        patterns = [
            project_root / f"{module_id_upper}-*" / "data" / "*.db",
            project_root / f"{module_id_upper}-*" / "data" / "**" / "*.db",
            project_root / f"{module_id}-*" / "data" / "*.db",
            project_root / f"{module_id}-*" / "data" / "**" / "*.db",
        ]

        # 如果 extra_config 中有 data_dir，也加入搜索
        extra = module.extra_config or {}
        if "data_dir" in extra:
            data_dir = Path(extra["data_dir"])
            if data_dir.is_absolute():
                patterns.append(data_dir / "*.db")
                patterns.append(data_dir / "**" / "*.db")

        for pattern in patterns:
            for db_file in glob.glob(str(pattern), recursive=True):
                db_path = Path(db_file)
                # 排除备份目录中的数据库
                if "backup" in str(db_path).lower():
                    continue
                if str(db_path) not in db_paths:
                    db_paths.append(str(db_path))

        return db_paths

    def trigger_all_backup(self, trigger_type: str = "manual",
                           backup_type: str = "full") -> Dict[str, Any]:
        """触发全系统备份"""
        db = SessionLocal()
        try:
            modules = db.query(BackupModule).filter(
                BackupModule.enabled == True  # noqa: E712
            ).order_by(BackupModule.module_id).all()
        finally:
            db.close()

        results = {}
        total_size = 0
        success_count = 0
        fail_count = 0

        for module in modules:
            result = self.trigger_backup(
                module.module_id,
                trigger_type=trigger_type,
                backup_type=backup_type,
            )
            results[module.module_id] = result

            if result.get("success", False):
                success_count += 1
                details = result.get("details", {})
                total_size += details.get("total_size_bytes", 0)
            else:
                fail_count += 1

        return {
            "success": fail_count == 0 and success_count > 0,
            "total_modules": len(modules),
            "success_modules": success_count,
            "failed_modules": fail_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "modules": results,
            "timestamp": time.time(),
        }

    # --------------------------------------------------------
    # 历史记录查询
    # --------------------------------------------------------

    def get_history(self, module_id: Optional[str] = None,
                    status: Optional[str] = None,
                    limit: int = 50,
                    offset: int = 0) -> Dict[str, Any]:
        """查询备份历史记录"""
        db = SessionLocal()
        try:
            query = db.query(BackupHistory)

            if module_id:
                query = query.filter(BackupHistory.module_id == module_id)
            if status:
                query = query.filter(BackupHistory.status == status)

            total = query.count()
            records = query.order_by(
                BackupHistory.started_at.desc()
            ).offset(offset).limit(limit).all()

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "items": [r.to_dict() for r in records],
            }
        finally:
            db.close()

    # --------------------------------------------------------
    # 统计分析
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取备份统计信息"""
        db = SessionLocal()
        try:
            from sqlalchemy import func

            total_modules = db.query(BackupModule).count()
            enabled_modules = db.query(BackupModule).filter(
                BackupModule.enabled == True  # noqa: E712
            ).count()

            total_backups = db.query(BackupHistory).count()
            success_backups = db.query(BackupHistory).filter(
                BackupHistory.status == "success"
            ).count()
            failed_backups = db.query(BackupHistory).filter(
                BackupHistory.status == "failed"
            ).count()
            running_backups = db.query(BackupHistory).filter(
                BackupHistory.status == "running"
            ).count()

            success_rate = (success_backups / total_backups * 100) if total_backups > 0 else 0.0

            total_size_result = db.query(
                func.sum(BackupHistory.backup_size_bytes)
            ).filter(BackupHistory.status == "success").scalar()
            total_size_bytes = total_size_result or 0

            # 按模块统计
            module_stats = {}
            modules = db.query(BackupModule).all()
            for module in modules:
                module_history = db.query(BackupHistory).filter(
                    BackupHistory.module_id == module.module_id
                ).order_by(BackupHistory.started_at.desc()).limit(10).all()

                module_success = sum(1 for h in module_history if h.status == "success")
                module_total = len(module_history)
                module_rate = (module_success / module_total * 100) if module_total > 0 else 0.0

                latest = module_history[0] if module_history else None

                scheduler_status = None
                with self._lock:
                    if module.module_id in self._schedulers:
                        scheduler_status = self._schedulers[module.module_id].status()

                module_stats[module.module_id] = {
                    "module_name": module.module_name,
                    "enabled": module.enabled,
                    "schedule_type": module.schedule_type,
                    "total_backups_recent": module_total,
                    "success_rate": round(module_rate, 2),
                    "latest_backup": latest.to_dict() if latest else None,
                    "scheduler": scheduler_status or {"running": False},
                    "is_running": self._running_modules.get(module.module_id, False),
                }

            # 最近 7 天的备份趋势
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            recent_backups = db.query(BackupHistory).filter(
                BackupHistory.started_at >= seven_days_ago
            ).all()

            daily_stats = {}
            for backup in recent_backups:
                day_key = backup.started_at.strftime("%Y-%m-%d")
                if day_key not in daily_stats:
                    daily_stats[day_key] = {"total": 0, "success": 0, "failed": 0}
                daily_stats[day_key]["total"] += 1
                if backup.status == "success":
                    daily_stats[day_key]["success"] += 1
                elif backup.status == "failed":
                    daily_stats[day_key]["failed"] += 1

            # 存储使用情况
            storage_usage = self.get_storage_usage()

            return {
                "total_modules": total_modules,
                "enabled_modules": enabled_modules,
                "total_backups": total_backups,
                "success_backups": success_backups,
                "failed_backups": failed_backups,
                "running_backups": running_backups,
                "success_rate": round(success_rate, 2),
                "total_size_bytes": total_size_bytes,
                "total_size_mb": round(total_size_bytes / 1024 / 1024, 2),
                "module_stats": module_stats,
                "daily_stats": daily_stats,
                "storage_usage": storage_usage,
                "timestamp": time.time(),
            }
        finally:
            db.close()

    # --------------------------------------------------------
    # 存储监控
    # --------------------------------------------------------

    def get_storage_usage(self) -> Dict[str, Any]:
        """获取备份存储空间使用情况"""
        try:
            backup_root = project_root / "backups"
            backup_root.mkdir(parents=True, exist_ok=True)

            total_size = sum(
                f.stat().st_size
                for f in backup_root.rglob("*")
                if f.is_file()
            )

            import shutil
            disk_usage = shutil.disk_usage(str(backup_root))

            return {
                "backup_root": str(backup_root),
                "used_bytes": total_size,
                "used_mb": round(total_size / 1024 / 1024, 2),
                "used_gb": round(total_size / 1024 / 1024 / 1024, 3),
                "disk_total_bytes": disk_usage.total,
                "disk_used_bytes": disk_usage.used,
                "disk_free_bytes": disk_usage.free,
                "disk_free_percent": round(disk_usage.free / disk_usage.total * 100, 2),
            }
        except Exception as e:
            return {
                "error": str(e),
            }

    # --------------------------------------------------------
    # 告警管理
    # --------------------------------------------------------

    def _check_and_add_alert(self, module_id: str, alert_type: str, message: str) -> None:
        """检查并添加告警"""
        alert = {
            "level": "warning",
            "type": alert_type,
            "module_id": module_id,
            "message": message,
            "timestamp": time.time(),
            "acknowledged": False,
        }

        with self._alerts_lock:
            self._alerts.append(alert)
            # 最多保留 100 条告警
            if len(self._alerts) > 100:
                self._alerts = self._alerts[-100:]

        logger.warning(f"备份告警: module={module_id}, type={alert_type}, message={message}")

    def get_alerts(self, unacknowledged_only: bool = False,
                   limit: int = 50) -> Dict[str, Any]:
        """获取备份告警列表"""
        with self._alerts_lock:
            alerts = list(reversed(self._alerts))
            if unacknowledged_only:
                alerts = [a for a in alerts if not a.get("acknowledged", False)]
            alerts = alerts[:limit]

        return {
            "total": len(self._alerts),
            "unacknowledged": sum(1 for a in self._alerts if not a.get("acknowledged", False)),
            "items": alerts,
        }

    def acknowledge_alert(self, alert_index: int) -> Dict[str, Any]:
        """确认告警"""
        with self._alerts_lock:
            # 从尾部（最新）计算索引
            actual_index = len(self._alerts) - 1 - alert_index
            if 0 <= actual_index < len(self._alerts):
                self._alerts[actual_index]["acknowledged"] = True
                return {"success": True}
            return {"success": False, "error": "告警不存在"}

    def _start_storage_monitor(self) -> None:
        """启动存储监控线程"""
        def _monitor_loop():
            while True:
                try:
                    time.sleep(3600)  # 每小时检查一次
                    storage = self.get_storage_usage()
                    if "disk_free_percent" in storage:
                        free_pct = storage["disk_free_percent"]
                        if free_pct < self._alert_config["disk_free_percent_critical"]:
                            self._check_and_add_alert(
                                "system", "storage_critical",
                                f"备份磁盘空间严重不足，剩余 {free_pct}%"
                            )
                        elif free_pct < self._alert_config["disk_free_percent_warn"]:
                            self._check_and_add_alert(
                                "system", "storage_warning",
                                f"备份磁盘空间不足，剩余 {free_pct}%"
                            )
                except Exception:
                    pass

        thread = threading.Thread(target=_monitor_loop, daemon=True)
        thread.start()

    # --------------------------------------------------------
    # 调度器状态
    # --------------------------------------------------------

    def get_scheduler_status(self) -> Dict[str, Any]:
        """获取调度器整体状态"""
        with self._lock:
            scheduler_count = len(self._schedulers)
            running_count = sum(
                1 for s in self._schedulers.values() if s.running
            )
            scheduler_details = {
                mid: sched.status()
                for mid, sched in self._schedulers.items()
            }

        db = SessionLocal()
        try:
            total_modules = db.query(BackupModule).count()
            enabled_modules = db.query(BackupModule).filter(
                BackupModule.enabled == True  # noqa: E712
            ).count()
        finally:
            db.close()

        return {
            "initialized": self._initialized,
            "total_modules": total_modules,
            "enabled_modules": enabled_modules,
            "active_schedulers": scheduler_count,
            "running_schedulers": running_count,
            "running_backups": sum(1 for v in self._running_modules.values() if v),
            "schedulers": scheduler_details,
            "timestamp": time.time(),
        }

    def shutdown(self) -> None:
        """关闭调度中心，停止所有调度器"""
        with self._lock:
            for scheduler in self._schedulers.values():
                try:
                    scheduler.stop()
                except Exception:
                    pass
            self._schedulers.clear()
            self._initialized = False
            logger.info("备份调度中心已关闭")


# ============================================================
# 全局单例
# ============================================================

_backup_orchestrator_service: Optional[BackupOrchestratorService] = None
_init_lock = threading.Lock()


def get_backup_orchestrator_service() -> BackupOrchestratorService:
    """获取全局备份调度中心服务实例"""
    global _backup_orchestrator_service
    if _backup_orchestrator_service is None:
        with _init_lock:
            if _backup_orchestrator_service is None:
                _backup_orchestrator_service = BackupOrchestratorService()
    return _backup_orchestrator_service
