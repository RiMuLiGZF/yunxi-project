"""
M6 硬件外设 - 数据库备份管理

P2-6 改造：接入统一备份管理器
- 使用 shared.data_layer.backup_manager.BackupManager 统一管理备份
- 使用 BackupScheduler 实现定时备份调度
- 支持安全网恢复机制
- 备份存储位置：M6 模块 data/backups/ 目录

提供以下能力：
- backup_database() - 立即备份
- schedule_daily_backup(hour=3) - 每日定时备份
- restore_from_backup(backup_path) - 从备份恢复（带安全网）
- list_backups() - 列出备份
- verify_backup(backup_path) - 校验备份
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# 共享模块导入辅助
# ============================================================================

def _ensure_shared_path() -> None:
    """确保 shared 模块在 sys.path 中"""
    current = Path(__file__).resolve().parent
    # 向上查找 shared 目录
    for _ in range(5):
        shared_dir = current / "shared"
        if shared_dir.exists():
            project_root = str(current)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            return
        current = current.parent


def _import_backup_manager():
    """延迟导入备份管理器，避免循环依赖"""
    _ensure_shared_path()
    from shared.data_layer.backup_manager import (
        BackupManager,
        BackupScheduler,
        ModuleBackupConfig,
        BackupReport,
        VerifyReport,
    )
    return BackupManager, BackupScheduler, ModuleBackupConfig, BackupReport, VerifyReport


# ============================================================================
# 常量
# ============================================================================

MODULE_ID = "m6_hardware"
MAX_BACKUPS = 30  # 最大保留备份数


# ============================================================================
# 路径辅助
# ============================================================================

def _get_data_dir() -> Path:
    """获取 M6 模块 data 目录的绝对路径"""
    # 从 database/__init__.py 向上两级到 m6_hardware/，再找 data/
    m6_dir = Path(__file__).resolve().parent.parent
    data_dir = m6_dir.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_backup_dir() -> str:
    """获取 M6 备份存储目录的绝对路径

    Returns:
        备份目录路径字符串
    """
    backup_dir = _get_data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return str(backup_dir)


def get_db_path() -> str:
    """获取 M6 数据库文件路径

    优先从配置读取，否则使用默认路径。

    Returns:
        数据库文件路径字符串
    """
    try:
        from ..config import get_config
        config = get_config()
        return config.database_path
    except Exception:
        # 配置不可用时使用默认路径
        return str(_get_data_dir() / "m6_sensors.db")


# ============================================================================
# 备份管理器实例（懒加载）
# ============================================================================

_backup_manager_instance: Optional[Any] = None
_backup_scheduler_instance: Optional[Any] = None


def _get_backup_manager() -> Any:
    """获取 M6 专用的 BackupManager 实例

    Returns:
        BackupManager 实例
    """
    global _backup_manager_instance
    if _backup_manager_instance is None:
        BackupManager, _, _, _, _ = _import_backup_manager()
        _backup_manager_instance = BackupManager(
            backup_root=get_backup_dir(),
            data_root=str(_get_data_dir()),
            max_backups=MAX_BACKUPS,
        )
    return _backup_manager_instance


def _get_module_config() -> Any:
    """构建 M6 模块备份配置

    Returns:
        ModuleBackupConfig 实例
    """
    _, _, ModuleBackupConfig, _, _ = _import_backup_manager()
    return ModuleBackupConfig(
        module_id=MODULE_ID,
        db_paths=[get_db_path()],
        backup_dir=get_backup_dir(),
        max_backups=MAX_BACKUPS,
    )


# ============================================================================
# 公共 API - 备份操作
# ============================================================================

def backup_database() -> Dict[str, Any]:
    """立即创建数据库备份

    使用统一 BackupManager 的模块级备份功能，
    自动清理超出保留数量的旧备份。

    Returns:
        备份结果字典，包含：
        - success: 是否成功
        - backup_id: 备份标识（目录名）
        - backup_dir: 备份目录路径
        - total_size_bytes: 总大小（字节）
        - total_size_mb: 总大小（MB）
        - details: 各数据库详细结果
        - timestamp: 备份时间戳
    """
    try:
        bm = _get_backup_manager()
        config = _get_module_config()
        report = bm.backup_module(config)

        result = {
            "success": report.success,
            "module_id": report.module_id,
            "backup_id": Path(report.backup_dir).name,
            "backup_dir": report.backup_dir,
            "total_dbs": report.total_dbs,
            "success_dbs": report.success_dbs,
            "failed_dbs": report.failed_dbs,
            "total_size_bytes": report.total_size_bytes,
            "total_size_mb": report.total_size_mb,
            "details": report.details,
            "timestamp": report.timestamp,
            "errors": report.errors,
        }

        if report.success:
            logger.info(
                f"M6 数据库备份成功: {result['backup_id']} "
                f"({result['total_size_mb']} MB)"
            )
        else:
            logger.error(f"M6 数据库备份失败: {report.errors}")

        return result

    except Exception as e:
        logger.exception(f"创建备份时发生异常: {e}")
        return {
            "success": False,
            "module_id": MODULE_ID,
            "error": str(e),
            "errors": [str(e)],
            "timestamp": __import__("time").time(),
        }


def list_backups(limit: int = 20) -> List[Dict[str, Any]]:
    """列出 M6 模块的所有备份

    Args:
        limit: 最多返回的备份数量，默认 20

    Returns:
        备份列表，按时间倒序排列，每个元素包含：
        - backup_id: 备份标识
        - backup_dir: 备份目录路径
        - created: 创建时间戳
        - size_bytes: 大小（字节）
        - size_mb: 大小（MB）
        - file_count: 文件数量
    """
    backup_dir = Path(get_backup_dir())
    if not backup_dir.exists():
        return []

    backups = []
    for dir_path in sorted(
        backup_dir.iterdir(),
        key=lambda d: d.stat().st_ctime,
        reverse=True,
    ):
        if not dir_path.is_dir():
            continue
        if not dir_path.name.startswith(f"{MODULE_ID}_"):
            continue

        try:
            total_size = sum(
                f.stat().st_size for f in dir_path.rglob("*") if f.is_file()
            )
            file_count = sum(1 for f in dir_path.rglob("*") if f.is_file())

            backups.append({
                "backup_id": dir_path.name,
                "backup_dir": str(dir_path),
                "created": dir_path.stat().st_ctime,
                "size_bytes": total_size,
                "size_mb": round(total_size / 1024 / 1024, 2),
                "file_count": file_count,
            })
        except Exception:
            continue

        if len(backups) >= limit:
            break

    return backups


def verify_backup(backup_id: str) -> Dict[str, Any]:
    """校验指定备份的完整性

    Args:
        backup_id: 备份标识（目录名）

    Returns:
        校验结果字典，包含：
        - valid: 整体是否有效
        - backup_id: 备份标识
        - files: 各文件的校验结果
        - errors: 错误列表
    """
    backup_dir = Path(get_backup_dir()) / backup_id
    if not backup_dir.exists() or not backup_dir.is_dir():
        return {
            "valid": False,
            "backup_id": backup_id,
            "error": f"备份不存在: {backup_id}",
            "files": {},
            "errors": [f"Backup not found: {backup_id}"],
        }

    try:
        bm = _get_backup_manager()
        db_path = get_db_path()
        db_filename = Path(db_path).name
        backup_file = backup_dir / db_filename

        if not backup_file.exists():
            return {
                "valid": False,
                "backup_id": backup_id,
                "error": f"备份中找不到数据库文件: {db_filename}",
                "files": {},
                "errors": [f"Database file not found in backup: {db_filename}"],
            }

        report = bm.verify_backup(str(backup_file))

        return {
            "valid": report.overall_valid,
            "backup_id": backup_id,
            "backup_file": str(backup_file),
            "file_valid": report.file_valid,
            "file_size_bytes": report.file_size_bytes,
            "md5_checksum": report.md5_checksum,
            "integrity_check": report.integrity_check,
            "quick_check": report.quick_check,
            "table_count": report.table_count,
            "has_tables": report.has_tables,
            "errors": report.errors,
        }

    except Exception as e:
        logger.exception(f"校验备份时发生异常: {e}")
        return {
            "valid": False,
            "backup_id": backup_id,
            "error": str(e),
            "errors": [str(e)],
        }


def restore_from_backup(
    backup_id: str,
    *,
    auto_rollback: bool = True,
) -> Dict[str, Any]:
    """从备份恢复数据库（带安全网）

    恢复前自动创建当前数据库的安全网备份，
    如果恢复失败则自动回滚到安全网备份。

    Args:
        backup_id: 备份标识（目录名）
        auto_rollback: 恢复失败时是否自动回滚，默认 True

    Returns:
        恢复结果字典，包含：
        - success: 是否成功
        - backup_id: 使用的备份标识
        - target_path: 恢复目标路径
        - safety_net_path: 安全网备份路径（如果创建了）
        - safety_net_created: 是否创建了安全网
        - rolled_back: 是否发生了回滚
        - errors: 错误列表
    """
    backup_dir = Path(get_backup_dir()) / backup_id
    if not backup_dir.exists() or not backup_dir.is_dir():
        return {
            "success": False,
            "backup_id": backup_id,
            "error": f"备份不存在: {backup_id}",
            "errors": [f"Backup not found: {backup_id}"],
            "safety_net_created": False,
            "rolled_back": False,
        }

    try:
        bm = _get_backup_manager()
        db_path = get_db_path()
        db_filename = Path(db_path).name
        backup_file = backup_dir / db_filename

        if not backup_file.exists():
            return {
                "success": False,
                "backup_id": backup_id,
                "error": f"备份中找不到数据库文件: {db_filename}",
                "errors": [f"Database file not found in backup: {db_filename}"],
                "safety_net_created": False,
                "rolled_back": False,
            }

        # 先校验备份完整性
        verify_report = bm.verify_backup(str(backup_file))
        if not verify_report.overall_valid:
            return {
                "success": False,
                "backup_id": backup_id,
                "error": "备份完整性校验失败，拒绝恢复",
                "errors": ["Backup integrity check failed"] + verify_report.errors,
                "safety_net_created": False,
                "rolled_back": False,
                "verify_result": {
                    "integrity_check": verify_report.integrity_check,
                    "quick_check": verify_report.quick_check,
                },
            }

        # 带安全网恢复
        result = bm.restore_with_safety_net(
            str(backup_file),
            db_path,
            auto_rollback=auto_rollback,
        )

        result["backup_id"] = backup_id

        if result.get("success"):
            logger.info(
                f"M6 数据库恢复成功 (from {backup_id})"
            )
        else:
            logger.error(
                f"M6 数据库恢复失败: {result.get('error')}"
            )

        return result

    except Exception as e:
        logger.exception(f"恢复备份时发生异常: {e}")
        return {
            "success": False,
            "backup_id": backup_id,
            "error": str(e),
            "errors": [str(e)],
            "safety_net_created": False,
            "rolled_back": False,
        }


def get_backup_stats() -> Dict[str, Any]:
    """获取 M6 备份统计信息

    Returns:
        统计信息字典，包含：
        - total_backups: 备份总数
        - total_size_bytes: 总大小（字节）
        - total_size_mb: 总大小（MB）
        - max_backups: 最大保留数
        - latest_backup: 最新备份信息
        - scheduler: 调度器状态
    """
    backups = list_backups(limit=100)
    total_size = sum(b["size_bytes"] for b in backups)

    scheduler_status = None
    if _backup_scheduler_instance is not None:
        try:
            scheduler_status = _backup_scheduler_instance.status()
        except Exception:
            pass

    return {
        "module_id": MODULE_ID,
        "total_backups": len(backups),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "max_backups": MAX_BACKUPS,
        "backup_dir": get_backup_dir(),
        "latest_backup": backups[0] if backups else None,
        "scheduler": scheduler_status,
    }


# ============================================================================
# 公共 API - 定时备份调度
# ============================================================================

def schedule_daily_backup(hour: int = 3, minute: int = 0) -> bool:
    """启动每日定时备份

    Args:
        hour: 每日备份小时（0-23），默认 3
        minute: 每日备份分钟（0-59），默认 0

    Returns:
        是否成功启动调度
    """
    global _backup_scheduler_instance

    try:
        _, BackupScheduler, _, _, _ = _import_backup_manager()

        if _backup_scheduler_instance is not None:
            # 已存在调度器，先停止
            _backup_scheduler_instance.stop()

        def _backup_task():
            try:
                backup_database()
            except Exception:
                logger.exception("定时备份任务执行失败")

        scheduler = BackupScheduler(_backup_task)
        time_str = f"{hour:02d}:{minute:02d}"
        success = scheduler.start({
            "type": "daily",
            "time": time_str,
        })

        if success:
            _backup_scheduler_instance = scheduler
            logger.info(f"M6 每日定时备份已启动 (每天 {time_str})")
        else:
            logger.warning("M6 每日定时备份启动失败")

        return success

    except Exception as e:
        logger.exception(f"启动定时备份时发生异常: {e}")
        return False


def stop_scheduled_backup() -> bool:
    """停止定时备份调度

    Returns:
        是否成功停止
    """
    global _backup_scheduler_instance

    if _backup_scheduler_instance is None:
        return True  # 已经停止

    try:
        result = _backup_scheduler_instance.stop()
        if result:
            logger.info("M6 定时备份已停止")
        _backup_scheduler_instance = None
        return result
    except Exception as e:
        logger.exception(f"停止定时备份时发生异常: {e}")
        return False


def get_scheduler_status() -> Dict[str, Any]:
    """获取定时备份调度器状态

    Returns:
        调度器状态字典
    """
    if _backup_scheduler_instance is None:
        return {
            "running": False,
            "schedule_config": None,
            "last_run": None,
            "next_run": None,
        }

    try:
        return _backup_scheduler_instance.status()
    except Exception as e:
        return {
            "running": False,
            "error": str(e),
        }
