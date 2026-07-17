"""
云汐备份调度器 (Backup Scheduler)

提供定时备份调度能力：
- 按计划自动备份（全量/增量）
- 多种调度类型（间隔式、定时式）
- 备份保留策略
- 自动验证
- 异地同步

使用方式：
    from data_layer.disaster_recovery.backup_scheduler import BackupScheduler, ScheduleType

    scheduler = BackupScheduler(backup_root="./backups", data_root="./data")
    scheduler.add_schedule("daily_full", "mydb.db", mode="full", interval_hours=24)
    scheduler.start()
"""

from __future__ import annotations

import time
import json
import threading
import logging
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class ScheduleType(str, Enum):
    """调度类型"""
    INTERVAL = "interval"          # 间隔式（每N小时）
    DAILY = "daily"                # 每日定时
    WEEKLY = "weekly"              # 每周定时
    CRON_LIKE = "cron_like"        # Cron风格（简化版）


class ScheduleStatus(str, Enum):
    """调度状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


# ============================================================
# 数据类
# ============================================================

@dataclass
class ScheduledBackupTask:
    """定时备份任务"""
    schedule_id: str
    name: str
    database: str
    backup_mode: str = "full"           # full / incremental
    schedule_type: ScheduleType = ScheduleType.INTERVAL
    interval_hours: float = 24.0
    hour: int = 2                       # 每日定时：小时
    minute: int = 0                     # 每日定时：分钟
    weekday: int = 0                    # 每周定时：星期几（0=周一）
    max_keep: int = 7                   # 保留份数
    validate_after: bool = True         # 备份后验证
    validation_level: str = "integrity"  # quick / checksum / integrity / full
    remote_sync: bool = False           # 是否同步到异地
    status: ScheduleStatus = ScheduleStatus.ACTIVE
    last_run: float = 0.0
    next_run: float = 0.0
    total_runs: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_result: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "database": self.database,
            "backup_mode": self.backup_mode,
            "schedule_type": self.schedule_type.value,
            "interval_hours": self.interval_hours,
            "hour": self.hour,
            "minute": self.minute,
            "weekday": self.weekday,
            "max_keep": self.max_keep,
            "validate_after": self.validate_after,
            "validation_level": self.validation_level,
            "remote_sync": self.remote_sync,
            "status": self.status.value,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "total_runs": self.total_runs,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_result": self.last_result,
            "metadata": self.metadata,
        }


# ============================================================
# 备份调度器
# ============================================================

class BackupScheduler:
    """
    备份调度器

    支持多种调度方式的定时备份管理。
    """

    def __init__(
        self,
        backup_root: str,
        data_root: str,
        enhanced_backup_manager: Optional[Any] = None,
    ):
        self.backup_root = Path(backup_root).resolve()
        self.data_root = Path(data_root).resolve()

        # 延迟导入，避免循环依赖
        self._ebm = enhanced_backup_manager
        self._schedules: Dict[str, ScheduledBackupTask] = {}
        self._lock = threading.RLock()

        # 调度线程
        self._scheduler_thread: Optional[threading.Thread] = None
        self._scheduler_stop = threading.Event()
        self._check_interval: float = 60.0  # 调度检查间隔（秒）

        # 回调
        self._on_backup_start_callbacks: List[Callable[[ScheduledBackupTask], None]] = []
        self._on_backup_complete_callbacks: List[Callable[[ScheduledBackupTask, Dict[str, Any]], None]] = []
        self._on_backup_failure_callbacks: List[Callable[[ScheduledBackupTask, str], None]] = []

    # ------------------------------------------------------------------
    #  延迟获取 EnhancedBackupManager
    # ------------------------------------------------------------------

    def _get_ebm(self):
        if self._ebm is None:
            from .enhanced_backup import EnhancedBackupManager
            self._ebm = EnhancedBackupManager(
                backup_root=str(self.backup_root),
                data_root=str(self.data_root),
            )
        return self._ebm

    # ------------------------------------------------------------------
    #  调度任务管理
    # ------------------------------------------------------------------

    def add_schedule(
        self,
        schedule_id: str,
        name: str,
        database: str,
        backup_mode: str = "full",
        schedule_type: ScheduleType = ScheduleType.INTERVAL,
        interval_hours: float = 24.0,
        hour: int = 2,
        minute: int = 0,
        weekday: int = 0,
        max_keep: int = 7,
        validate_after: bool = True,
        remote_sync: bool = False,
    ) -> bool:
        """
        添加备份调度任务

        Args:
            schedule_id: 调度ID
            name: 调度名称
            database: 数据库文件名
            backup_mode: 备份模式（full/incremental）
            schedule_type: 调度类型
            interval_hours: 间隔小时数（INTERVAL类型使用）
            hour: 每日定时的小时
            minute: 每日定时的分钟
            weekday: 每周定时的星期几
            max_keep: 保留份数
            validate_after: 备份后是否验证
            remote_sync: 是否同步到异地

        Returns:
            是否添加成功
        """
        with self._lock:
            if schedule_id in self._schedules:
                logger.warning("Schedule already exists: %s", schedule_id)
                return False

            task = ScheduledBackupTask(
                schedule_id=schedule_id,
                name=name,
                database=database,
                backup_mode=backup_mode,
                schedule_type=schedule_type,
                interval_hours=interval_hours,
                hour=hour,
                minute=minute,
                weekday=weekday,
                max_keep=max_keep,
                validate_after=validate_after,
                remote_sync=remote_sync,
            )

            # 计算下次运行时间
            task.next_run = self._calculate_next_run(task)
            self._schedules[schedule_id] = task
            logger.info("Schedule added: %s (%s), next run: %s",
                        schedule_id, name,
                        datetime.fromtimestamp(task.next_run, tz=timezone.utc).isoformat())
            return True

    def remove_schedule(self, schedule_id: str) -> bool:
        """移除调度任务"""
        with self._lock:
            if schedule_id not in self._schedules:
                return False
            del self._schedules[schedule_id]
            logger.info("Schedule removed: %s", schedule_id)
            return True

    def pause_schedule(self, schedule_id: str) -> bool:
        """暂停调度"""
        with self._lock:
            task = self._schedules.get(schedule_id)
            if not task:
                return False
            task.status = ScheduleStatus.PAUSED
            logger.info("Schedule paused: %s", schedule_id)
            return True

    def resume_schedule(self, schedule_id: str) -> bool:
        """恢复调度"""
        with self._lock:
            task = self._schedules.get(schedule_id)
            if not task:
                return False
            task.status = ScheduleStatus.ACTIVE
            task.next_run = self._calculate_next_run(task)
            logger.info("Schedule resumed: %s", schedule_id)
            return True

    def get_schedule(self, schedule_id: str) -> Optional[ScheduledBackupTask]:
        """获取调度任务"""
        with self._lock:
            return self._schedules.get(schedule_id)

    def list_schedules(self) -> List[ScheduledBackupTask]:
        """列出所有调度任务"""
        with self._lock:
            return list(self._schedules.values())

    def trigger_now(self, schedule_id: str) -> Optional[Dict[str, Any]]:
        """立即触发一次备份"""
        with self._lock:
            task = self._schedules.get(schedule_id)
            if not task:
                return None

        return self._execute_backup(task)

    # ------------------------------------------------------------------
    #  调度线程
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """启动调度器"""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return True

        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="BackupScheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        logger.info("Backup scheduler started")
        return True

    def stop(self) -> None:
        """停止调度器"""
        self._scheduler_stop.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10)
            self._scheduler_thread = None
        logger.info("Backup scheduler stopped")

    def _scheduler_loop(self) -> None:
        """调度主循环"""
        while not self._scheduler_stop.is_set():
            try:
                self._check_and_run()
            except Exception as e:
                logger.error("Scheduler loop error: %s", e)

            self._scheduler_stop.wait(self._check_interval)

    def _check_and_run(self) -> None:
        """检查并运行到期的调度"""
        now = time.time()

        with self._lock:
            tasks = list(self._schedules.values())

        for task in tasks:
            if task.status != ScheduleStatus.ACTIVE:
                continue

            if task.next_run <= 0:
                task.next_run = self._calculate_next_run(task)
                continue

            if now >= task.next_run:
                # 执行备份
                result = self._execute_backup(task)
                # 计算下次运行时间
                with self._lock:
                    task.last_run = now
                    task.next_run = self._calculate_next_run(task)
                    task.total_runs += 1
                    if result.get("success"):
                        task.success_count += 1
                    else:
                        task.failure_count += 1
                    task.last_result = result

    # ------------------------------------------------------------------
    #  执行备份
    # ------------------------------------------------------------------

    def _execute_backup(self, task: ScheduledBackupTask) -> Dict[str, Any]:
        """执行备份"""
        logger.info("Executing scheduled backup: %s (%s)", task.schedule_id, task.name)

        # 触发开始回调
        for cb in self._on_backup_start_callbacks:
            try:
                cb(task)
            except Exception as e:
                logger.error("Backup start callback error: %s", e)

        try:
            ebm = self._get_ebm()

            if task.backup_mode == "full":
                result = ebm.full_backup(task.database)
            elif task.backup_mode == "incremental":
                result = ebm.incremental_backup(task.database)
            else:
                result = {"success": False, "error": f"Unknown backup mode: {task.backup_mode}"}

            # 验证
            if result.get("success") and task.validate_after:
                from .enhanced_backup import ValidationLevel
                level = ValidationLevel(task.validation_level)
                backup_id = result.get("backup_id", "")
                if backup_id:
                    validation = ebm.validate_backup(backup_id, level)
                    result["validation"] = validation.to_dict()
                    if not validation.passed:
                        result["success"] = False
                        result["error"] = f"Validation failed: {validation.error}"

            # 异地同步
            if result.get("success") and task.remote_sync:
                backup_id = result.get("backup_id", "")
                if backup_id:
                    synced = ebm.sync_to_remote(backup_id)
                    result["remote_synced"] = synced

            # 清理旧备份
            if result.get("success"):
                self._cleanup_old_backups(task)

            # 成功回调
            if result.get("success"):
                for cb in self._on_backup_complete_callbacks:
                    try:
                        cb(task, result)
                    except Exception as e:
                        logger.error("Backup complete callback error: %s", e)
            else:
                for cb in self._on_backup_failure_callbacks:
                    try:
                        cb(task, result.get("error", "unknown"))
                    except Exception as e:
                        logger.error("Backup failure callback error: %s", e)

            return result

        except Exception as e:
            logger.error("Scheduled backup failed: %s", e)
            error_result = {"success": False, "error": str(e)}
            for cb in self._on_backup_failure_callbacks:
                try:
                    cb(task, str(e))
                except Exception:
                    pass
            return error_result

    # ------------------------------------------------------------------
    #  下次运行时间计算
    # ------------------------------------------------------------------

    def _calculate_next_run(self, task: ScheduledBackupTask) -> float:
        """计算下次运行时间"""
        now = datetime.now()

        if task.schedule_type == ScheduleType.INTERVAL:
            if task.last_run == 0:
                # 首次运行：从现在开始加间隔
                return time.time() + task.interval_hours * 3600
            else:
                return task.last_run + task.interval_hours * 3600

        elif task.schedule_type == ScheduleType.DAILY:
            # 计算今天的目标时间
            target = now.replace(hour=task.hour, minute=task.minute, second=0, microsecond=0)
            if target <= now:
                # 今天的时间已过，明天
                target = target + timedelta(days=1)
            return target.timestamp()

        elif task.schedule_type == ScheduleType.WEEKLY:
            # 找到下一个指定的星期几
            days_ahead = task.weekday - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = now + timedelta(days=days_ahead)
            target = target.replace(hour=task.hour, minute=task.minute, second=0, microsecond=0)
            return target.timestamp()

        else:
            # 默认：每24小时
            return time.time() + 24 * 3600

    # ------------------------------------------------------------------
    #  旧备份清理
    # ------------------------------------------------------------------

    def _cleanup_old_backups(self, task: ScheduledBackupTask) -> int:
        """清理超出保留数量的旧备份"""
        try:
            ebm = self._get_ebm()
            from .enhanced_backup import BackupMode

            mode = BackupMode(task.backup_mode)
            backups = ebm.list_backups(database=task.database, backup_type=mode)

            if len(backups) <= task.max_keep:
                return 0

            # 删除最旧的
            to_remove = backups[task.max_keep:]
            removed = 0
            for backup in to_remove:
                if ebm.delete_backup(backup.backup_id):
                    removed += 1

            if removed > 0:
                logger.info("Cleaned up %d old backups for %s", removed, task.schedule_id)
            return removed

        except Exception as e:
            logger.error("Old backup cleanup failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    #  回调注册
    # ------------------------------------------------------------------

    def on_backup_start(self, callback: Callable[[ScheduledBackupTask], None]) -> None:
        self._on_backup_start_callbacks.append(callback)

    def on_backup_complete(self, callback: Callable[[ScheduledBackupTask, Dict[str, Any]], None]) -> None:
        self._on_backup_complete_callbacks.append(callback)

    def on_backup_failure(self, callback: Callable[[ScheduledBackupTask, str], None]) -> None:
        self._on_backup_failure_callbacks.append(callback)

    # ------------------------------------------------------------------
    #  状态
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """调度器是否在运行"""
        return self._scheduler_thread is not None and self._scheduler_thread.is_alive()

    def get_stats(self) -> Dict[str, Any]:
        """获取调度器统计"""
        with self._lock:
            schedules = [t.to_dict() for t in self._schedules.values()]

        total_runs = sum(t.total_runs for t in self._schedules.values())
        total_success = sum(t.success_count for t in self._schedules.values())
        total_failure = sum(t.failure_count for t in self._schedules.values())

        return {
            "running": self.is_running,
            "schedule_count": len(schedules),
            "active_count": sum(1 for s in schedules if s["status"] == "active"),
            "paused_count": sum(1 for s in schedules if s["status"] == "paused"),
            "total_runs": total_runs,
            "total_success": total_success,
            "total_failure": total_failure,
            "success_rate": round(total_success / total_runs * 100, 2) if total_runs > 0 else 0,
            "schedules": schedules,
        }
