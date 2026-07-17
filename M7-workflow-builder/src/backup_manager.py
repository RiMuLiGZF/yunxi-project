"""M7 工作流模块 - 备份管理器.

封装统一备份管理器，提供 M7 模块专用的备份恢复接口。
支持立即备份、定时备份、恢复、列出备份、校验备份等功能。

备份目录: data/backups/
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
#  路径设置：确保可以导入 shared 模块
# ============================================================

def _get_shared_path() -> str:
    """获取 shared 目录的路径."""
    src_dir = Path(__file__).resolve().parent
    m7_dir = src_dir.parent
    project_root = m7_dir.parent
    return str(project_root)


def _ensure_shared_on_path() -> None:
    """确保 shared 模块在 sys.path 中."""
    shared_root = _get_shared_path()
    if shared_root not in sys.path:
        sys.path.insert(0, shared_root)


_ensure_shared_on_path()

from shared.data_layer.backup_manager import (
    BackupManager,
    BackupScheduler,
    ModuleBackupConfig,
    BackupReport,
    VerifyReport,
)


# ============================================================
#  M7 备份管理器
# ============================================================

class M7BackupManager:
    """M7 工作流备份管理器.

    封装统一备份管理器，提供 M7 专用的备份恢复接口。

    功能：
    - 立即备份
    - 定时备份（每日/间隔）
    - 恢复备份
    - 列出备份
    - 校验备份
    - 备份统计

    使用示例::

        from src.backup_manager import get_backup_manager
        bm = get_backup_manager()

        # 立即备份
        report = bm.backup_now()

        # 列出备份
        backups = bm.list_backups()

        # 恢复备份
        result = bm.restore(backup_path)

        # 启动定时备份
        bm.start_schedule({"type": "daily", "time": "03:00"})
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化备份管理器.

        Args:
            data_dir: 数据目录，默认从 db 模块获取
        """
        # 延迟导入避免循环引用
        from .db import get_db_path

        # 确定数据目录
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            db_path = get_db_path()
            self._data_dir = db_path.parent

        self._data_dir.mkdir(parents=True, exist_ok=True)

        # 备份目录
        self._backup_dir = self._data_dir / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

        # 数据库文件路径
        self._db_path = str(get_db_path(str(self._data_dir)))

        # 模块ID
        self._module_id = "m7_workflow"

        # 创建模块备份配置
        self._module_config = ModuleBackupConfig(
            module_id=self._module_id,
            db_paths=[self._db_path],
            backup_dir=str(self._backup_dir),
            max_backups=30,
            schedule=None,
        )

        # 底层备份管理器
        self._backup_manager = BackupManager(
            backup_root=str(self._backup_dir),
            data_root=str(self._data_dir),
            max_backups=30,
        )

        # 定时备份调度器
        self._scheduler: Optional[BackupScheduler] = None

    # --------------------------------------------------------
    #  立即备份
    # --------------------------------------------------------

    def backup_now(self, backup_name: Optional[str] = None) -> BackupReport:
        """立即执行备份.

        Args:
            backup_name: 备份名称（可选，默认自动生成）

        Returns:
            BackupReport 备份报告
        """
        report = self._backup_manager.backup_module(self._module_config)
        return report

    # --------------------------------------------------------
    #  备份列表
    # --------------------------------------------------------

    def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份.

        Returns:
            备份列表，按时间倒序排列
        """
        backups = []
        if not self._backup_dir.exists():
            return backups

        for backup_dir in sorted(self._backup_dir.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue
            if not backup_dir.name.startswith(f"{self._module_id}_"):
                continue

            try:
                # 计算备份大小
                total_size = sum(
                    f.stat().st_size
                    for f in backup_dir.rglob("*")
                    if f.is_file()
                )

                # 获取备份中的数据库文件
                db_files = list(backup_dir.glob("*.db"))

                backups.append({
                    "name": backup_dir.name,
                    "path": str(backup_dir),
                    "created": backup_dir.stat().st_ctime,
                    "created_str": time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(backup_dir.stat().st_ctime),
                    ),
                    "size_bytes": total_size,
                    "size_mb": round(total_size / 1024 / 1024, 2),
                    "db_count": len(db_files),
                    "module_id": self._module_id,
                })
            except Exception:
                continue

        return backups

    def get_latest_backup(self) -> Optional[Dict[str, Any]]:
        """获取最新的备份.

        Returns:
            最新备份信息，无备份时返回 None
        """
        backups = self.list_backups()
        return backups[0] if backups else None

    # --------------------------------------------------------
    #  恢复备份
    # --------------------------------------------------------

    def restore(
        self,
        backup_path: str,
        use_safety_net: bool = True,
    ) -> Dict[str, Any]:
        """恢复备份.

        Args:
            backup_path: 备份文件或目录路径
            use_safety_net: 是否使用安全网（恢复前自动备份当前数据）

        Returns:
            恢复结果字典
        """
        backup_path_obj = Path(backup_path)

        if not backup_path_obj.exists():
            return {
                "success": False,
                "error": f"Backup not found: {backup_path}",
            }

        # 确定备份文件
        backup_file = None
        if backup_path_obj.is_dir():
            # 目录中找数据库文件
            db_files = list(backup_path_obj.glob("*.db"))
            if db_files:
                backup_file = db_files[0]
            else:
                return {
                    "success": False,
                    "error": f"No database file found in backup directory: {backup_path}",
                }
        elif backup_path_obj.suffix == ".db":
            backup_file = backup_path_obj
        else:
            return {
                "success": False,
                "error": f"Unsupported backup format: {backup_path_obj.suffix}",
            }

        # 执行恢复
        if use_safety_net:
            result = self._backup_manager.restore_with_safety_net(
                str(backup_file),
                self._db_path,
                auto_rollback=True,
            )
        else:
            result = self._backup_manager.restore_backup(
                str(backup_file),
                self._db_path,
                overwrite=True,
            )

        return result

    # --------------------------------------------------------
    #  备份校验
    # --------------------------------------------------------

    def verify_backup(self, backup_path: str) -> VerifyReport:
        """校验备份文件完整性.

        Args:
            backup_path: 备份文件或目录路径

        Returns:
            VerifyReport 校验报告
        """
        backup_path_obj = Path(backup_path)

        # 确定要校验的数据库文件
        db_file = None
        if backup_path_obj.is_dir():
            db_files = list(backup_path_obj.glob("*.db"))
            if db_files:
                db_file = db_files[0]
            else:
                report = VerifyReport(backup_path=str(backup_path_obj))
                report.errors.append(f"No database file found in: {backup_path}")
                return report
        else:
            db_file = backup_path_obj

        return self._backup_manager.verify_backup(str(db_file))

    def verify_all_backups(self) -> List[Dict[str, Any]]:
        """校验所有备份文件.

        Returns:
            所有备份的校验结果列表
        """
        results = []
        backups = self.list_backups()

        for backup in backups:
            try:
                report = self.verify_backup(backup["path"])
                results.append({
                    "backup_name": backup["name"],
                    "backup_path": backup["path"],
                    "overall_valid": report.overall_valid,
                    "file_size_bytes": report.file_size_bytes,
                    "integrity_check": report.integrity_check,
                    "table_count": report.table_count,
                    "errors": report.errors,
                })
            except Exception as e:
                results.append({
                    "backup_name": backup["name"],
                    "backup_path": backup["path"],
                    "overall_valid": False,
                    "error": str(e),
                })

        return results

    # --------------------------------------------------------
    #  备份统计
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取备份统计信息.

        Returns:
            统计信息字典
        """
        backups = self.list_backups()
        total_size = sum(b["size_bytes"] for b in backups)

        return {
            "module_id": self._module_id,
            "backup_dir": str(self._backup_dir),
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "max_backups": self._module_config.max_backups,
            "latest_backup": backups[0] if backups else None,
            "oldest_backup": backups[-1] if backups else None,
            "scheduler_running": self._scheduler is not None and self._scheduler.running,
        }

    # --------------------------------------------------------
    #  定时备份
    # --------------------------------------------------------

    def start_schedule(self, schedule_config: Dict[str, Any]) -> bool:
        """启动定时备份.

        Args:
            schedule_config: 调度配置，支持：
                - {"type": "daily", "time": "03:00"} 每日指定时间
                - {"type": "interval", "hours": 6} 每N小时
                - {"type": "interval", "minutes": 30} 每N分钟

        Returns:
            是否成功启动
        """
        if self._scheduler is not None and self._scheduler.running:
            # 先停止当前调度
            self._scheduler.stop()

        def _backup_task():
            try:
                self.backup_now()
            except Exception:
                pass

        self._scheduler = BackupScheduler(_backup_task)
        success = self._scheduler.start(schedule_config)

        if success:
            self._module_config.schedule = schedule_config

        return success

    def stop_schedule(self) -> bool:
        """停止定时备份.

        Returns:
            是否成功停止
        """
        if self._scheduler is None:
            return False

        success = self._scheduler.stop()
        self._module_config.schedule = None
        return success

    def get_schedule_status(self) -> Dict[str, Any]:
        """获取定时备份调度器状态.

        Returns:
            调度器状态信息
        """
        if self._scheduler is None:
            return {
                "running": False,
                "schedule_config": None,
                "last_run": None,
                "next_run": None,
            }

        return self._scheduler.status()

    # --------------------------------------------------------
    #  备份清理
    # --------------------------------------------------------

    def cleanup_old_backups(self, max_count: Optional[int] = None) -> Dict[str, Any]:
        """清理旧备份.

        Args:
            max_count: 最大保留数，默认使用配置中的值

        Returns:
            清理结果
        """
        if max_count is None:
            max_count = self._module_config.max_backups

        backups = self.list_backups()
        if len(backups) <= max_count:
            return {
                "success": True,
                "deleted_count": 0,
                "remaining_count": len(backups),
            }

        to_delete = backups[max_count:]
        deleted = 0
        failed = []

        for backup in to_delete:
            try:
                import shutil
                shutil.rmtree(backup["path"])
                deleted += 1
            except Exception as e:
                failed.append({
                    "name": backup["name"],
                    "error": str(e),
                })

        return {
            "success": len(failed) == 0,
            "deleted_count": deleted,
            "failed_count": len(failed),
            "remaining_count": len(backups) - deleted,
            "failed": failed,
        }

    # --------------------------------------------------------
    #  属性访问
    # --------------------------------------------------------

    @property
    def backup_dir(self) -> str:
        """备份目录路径."""
        return str(self._backup_dir)

    @property
    def db_path(self) -> str:
        """数据库文件路径."""
        return self._db_path

    @property
    def module_id(self) -> str:
        """模块ID."""
        return self._module_id


# ============================================================
#  全局单例
# ============================================================

_backup_manager: Optional[M7BackupManager] = None


def get_backup_manager() -> M7BackupManager:
    """获取 M7 备份管理器全局单例.

    Returns:
        M7BackupManager 实例
    """
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = M7BackupManager()
    return _backup_manager


def init_backup_manager(data_dir: Optional[str] = None) -> M7BackupManager:
    """初始化备份管理器（可用于自定义配置）.

    Args:
        data_dir: 数据目录

    Returns:
        M7BackupManager 实例
    """
    global _backup_manager
    _backup_manager = M7BackupManager(data_dir=data_dir)
    return _backup_manager


# ============================================================
#  CLI 入口
# ============================================================

def main():
    """命令行入口."""
    import argparse

    parser = argparse.ArgumentParser(description="M7 工作流 - 备份管理")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # backup 命令
    subparsers.add_parser("backup", help="立即备份")

    # list 命令
    subparsers.add_parser("list", help="列出备份")

    # restore 命令
    restore_parser = subparsers.add_parser("restore", help="恢复备份")
    restore_parser.add_argument("path", help="备份路径")
    restore_parser.add_argument("--no-safety-net", action="store_true",
                                help="不使用安全网")

    # verify 命令
    verify_parser = subparsers.add_parser("verify", help="校验备份")
    verify_parser.add_argument("path", nargs="?", help="备份路径，不指定则校验所有")

    # stats 命令
    subparsers.add_parser("stats", help="备份统计")

    args = parser.parse_args()
    bm = get_backup_manager()

    if args.command == "backup":
        print("[M7-Backup] 开始备份...")
        report = bm.backup_now()
        print(f"[M7-Backup] 备份完成:")
        print(f"  成功: {report.success}")
        print(f"  数据库数: {report.total_dbs}")
        print(f"  成功数: {report.success_dbs}")
        print(f"  失败数: {report.failed_dbs}")
        print(f"  总大小: {report.total_size_mb} MB")
        print(f"  备份目录: {report.backup_dir}")
        if report.errors:
            print(f"  错误: {report.errors}")

    elif args.command == "list":
        backups = bm.list_backups()
        print(f"[M7-Backup] 备份列表（共 {len(backups)} 个）:")
        for i, b in enumerate(backups):
            print(f"  {i+1}. {b['name']}")
            print(f"     时间: {b['created_str']}")
            print(f"     大小: {b['size_mb']} MB")
            print(f"     路径: {b['path']}")

    elif args.command == "restore":
        print(f"[M7-Backup] 恢复备份: {args.path}")
        result = bm.restore(args.path, use_safety_net=not args.no_safety_net)
        if result["success"]:
            print(f"[M7-Backup] 恢复成功！")
            if result.get("safety_net_path"):
                print(f"  安全网备份: {result['safety_net_path']}")
        else:
            print(f"[M7-Backup] 恢复失败: {result.get('error', 'unknown')}")
            sys.exit(1)

    elif args.command == "verify":
        if args.path:
            print(f"[M7-Backup] 校验备份: {args.path}")
            report = bm.verify_backup(args.path)
            print(f"  有效: {report.overall_valid}")
            print(f"  文件大小: {report.file_size_bytes} bytes")
            print(f"  MD5: {report.md5_checksum}")
            print(f"  完整性检查: {report.integrity_check}")
            print(f"  表数量: {report.table_count}")
            if report.errors:
                print(f"  错误: {report.errors}")
        else:
            print("[M7-Backup] 校验所有备份...")
            results = bm.verify_all_backups()
            for r in results:
                status = "✓" if r["overall_valid"] else "✗"
                print(f"  {status} {r['backup_name']}: {r.get('integrity_check', 'error')}")

    elif args.command == "stats":
        stats = bm.get_stats()
        print("[M7-Backup] 备份统计:")
        print(f"  备份总数: {stats['total_backups']}")
        print(f"  总大小: {stats['total_size_mb']} MB")
        print(f"  最大保留数: {stats['max_backups']}")
        print(f"  备份目录: {stats['backup_dir']}")
        if stats.get("latest_backup"):
            latest = stats["latest_backup"]
            print(f"  最新备份: {latest['name']} ({latest['created_str']})")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
