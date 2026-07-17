"""M10 系统卫士 - 迁移管理器

封装统一迁移引擎，提供 M10 模块专用的迁移管理接口。
使用 SQLAlchemyMigrationAdapter 适配 M10 的 SQLAlchemy 引擎。

主要功能：
- 自动扫描 migrations/ 目录下的迁移脚本
- 执行迁移/回滚
- 查询迁移状态
- 迁移前自动备份
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
#  路径设置：确保可以导入 shared 模块
# ============================================================

def _get_project_root() -> str:
    """获取项目根目录路径.

    M10 目录结构:
    yunxi-project/
      M10-system-guard/
        m10_system_guard/
          migration_manager.py  (本文件)
      shared/
        data/
          data_layer/
            migration.py
    """
    # m10_system_guard 目录
    pkg_dir = Path(__file__).resolve().parent
    # M10 模块根目录
    m10_dir = pkg_dir.parent
    # 项目根目录
    project_root = m10_dir.parent
    return str(project_root)


def _ensure_shared_on_path() -> None:
    """确保 shared 模块在 sys.path 中."""
    project_root = _get_project_root()
    shared_path = str(Path(project_root) / "shared")
    if shared_path not in sys.path:
        sys.path.insert(0, shared_path)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


_ensure_shared_on_path()

from data.data_layer import (
    MigrationEngine,
    EnhancedMigrationEngine,
    SQLAlchemyMigrationAdapter,
)


# ============================================================
#  M10 迁移管理器
# ============================================================

class M10MigrationManager:
    """M10 系统卫士迁移管理器.

    封装统一迁移引擎，提供 M10 专用的迁移管理接口。

    使用示例::

        from migration_manager import get_migration_manager
        mgr = get_migration_manager()

        # 执行迁移
        result = mgr.migrate()

        # 获取当前版本
        version = mgr.get_current_version()

        # 获取迁移历史
        history = mgr.get_migration_history()

        # 回滚到指定版本
        result = mgr.rollback(target_version=0)
    """

    def __init__(self, engine=None, db_path: Optional[str] = None):
        """
        初始化迁移管理器.

        Args:
            engine: SQLAlchemy Engine 对象，None 时从 database 模块获取
            db_path: 数据库文件路径
        """
        # 延迟导入避免循环引用
        from .database import engine as sa_engine, get_db_path

        self._sa_engine = engine or sa_engine
        self._db_path = db_path or str(get_db_path())
        self._db_name = "m10_system_guard"

        # 创建适配器
        self._adapter = SQLAlchemyMigrationAdapter(
            self._sa_engine,
            db_path=self._db_path,
        )

        # 创建迁移引擎（基础版）
        self._engine = MigrationEngine(db_manager=self._adapter)

        # 创建增强版迁移引擎
        self._enhanced_engine = EnhancedMigrationEngine(engine=self._engine)

        # 迁移脚本目录
        self._migrations_dir = str(Path(__file__).resolve().parent / "migrations")

        # 缓存扫描结果
        self._migrations_cache: Optional[List[Dict[str, Any]]] = None

    # --------------------------------------------------------
    #  迁移扫描
    # --------------------------------------------------------

    def scan_migrations(self, force_reload: bool = False) -> List[Dict[str, Any]]:
        """扫描迁移脚本目录.

        Args:
            force_reload: 是否强制重新扫描

        Returns:
            迁移列表，按版本号升序排列
        """
        if self._migrations_cache is not None and not force_reload:
            return self._migrations_cache

        self._migrations_cache = self._engine.scan_migrations(self._migrations_dir)
        return self._migrations_cache

    # --------------------------------------------------------
    #  版本查询
    # --------------------------------------------------------

    def get_current_version(self) -> int:
        """获取当前数据库版本.

        Returns:
            当前版本号（整数，0 表示未执行过任何迁移）
        """
        return self._engine.get_current_version(self._db_name)

    def get_latest_version(self) -> int:
        """获取最新的迁移脚本版本.

        Returns:
            最新版本号
        """
        migrations = self.scan_migrations()
        if not migrations:
            return 0
        return max(m["version"] for m in migrations)

    def get_migration_history(self) -> List[Dict[str, Any]]:
        """获取已应用的迁移历史记录.

        Returns:
            迁移历史列表，按版本号升序排列
        """
        return self._engine.get_migrations(self._db_name)

    def get_migration_stats(self) -> Dict[str, Any]:
        """获取迁移审计统计信息.

        Returns:
            统计信息字典
        """
        return self._engine.get_migration_stats(self._db_name)

    # --------------------------------------------------------
    #  迁移执行
    # --------------------------------------------------------

    def migrate(
        self,
        target_version: Optional[int] = None,
        pre_backup: bool = True,
        backup_dir: Optional[str] = None,
        skip_integrity_check: bool = False,
        dry_run: bool = False,
        enable_retry: bool = True,
    ) -> Dict[str, Any]:
        """执行数据库迁移.

        Args:
            target_version: 目标版本，None 表示迁移到最新版本
            pre_backup: 是否在迁移前自动备份数据库（默认 True）
            backup_dir: 备份目录，None 时使用 data/backups/
            skip_integrity_check: 是否跳过迁移前完整性检查
            dry_run: 是否为 dry-run 模式（仅模拟执行）
            enable_retry: 是否启用错误重试

        Returns:
            迁移结果字典，包含 success、from_version、to_version 等字段
        """
        migrations = self.scan_migrations()

        if backup_dir is None:
            backup_dir = str(Path(self._db_path).parent / "backups")

        return self._enhanced_engine.migrate_enhanced(
            db_name=self._db_name,
            migrations=migrations,
            target_version=target_version,
            dry_run=dry_run,
            pre_migration_backup=pre_backup,
            backup_dir=backup_dir,
            enable_integrity_check=not skip_integrity_check,
            enable_retry=enable_retry,
        )

    def rollback(
        self,
        target_version: int = 0,
        pre_backup: bool = True,
    ) -> Dict[str, Any]:
        """回滚迁移到指定版本.

        Args:
            target_version: 回滚到的版本号，0 表示回滚所有迁移
            pre_backup: 回滚前是否备份

        Returns:
            回滚结果字典
        """
        migrations = self.scan_migrations()
        return self._engine.rollback(
            db_name=self._db_name,
            migrations=migrations,
            target_version=target_version,
            pre_migration_backup=pre_backup,
            backup_dir=str(Path(self._db_path).parent / "backups"),
        )

    # --------------------------------------------------------
    #  完整性检查
    # --------------------------------------------------------

    def check_integrity(self) -> Dict[str, Any]:
        """检查数据库完整性.

        Returns:
            完整性检查结果
        """
        return self._engine.check_integrity(self._db_name)

    def verify_checksums(self) -> Dict[str, Any]:
        """验证已应用迁移的校验和.

        检测迁移脚本是否被篡改。

        Returns:
            验证结果字典
        """
        migrations = self.scan_migrations()
        return self._engine.verify_checksums(
            db_name=self._db_name,
            migrations=migrations,
        )

    # --------------------------------------------------------
    #  属性访问
    # --------------------------------------------------------

    @property
    def engine(self) -> MigrationEngine:
        """底层迁移引擎实例."""
        return self._engine

    @property
    def enhanced_engine(self) -> EnhancedMigrationEngine:
        """增强型迁移引擎实例."""
        return self._enhanced_engine

    @property
    def adapter(self) -> SQLAlchemyMigrationAdapter:
        """SQLAlchemy 适配器实例."""
        return self._adapter

    @property
    def migrations_dir(self) -> str:
        """迁移脚本目录路径."""
        return self._migrations_dir

    @property
    def db_name(self) -> str:
        """数据库名称."""
        return self._db_name


# ============================================================
#  全局单例
# ============================================================

_migration_manager: Optional[M10MigrationManager] = None


def get_migration_manager() -> M10MigrationManager:
    """获取 M10 迁移管理器全局单例.

    Returns:
        M10MigrationManager 实例
    """
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = M10MigrationManager()
    return _migration_manager


def init_migration_manager(engine=None, db_path: Optional[str] = None) -> M10MigrationManager:
    """初始化迁移管理器（可用于自定义配置）.

    Args:
        engine: SQLAlchemy Engine 对象
        db_path: 数据库路径

    Returns:
        M10MigrationManager 实例
    """
    global _migration_manager
    _migration_manager = M10MigrationManager(engine=engine, db_path=db_path)
    return _migration_manager


# ============================================================
#  CLI 入口
# ============================================================

def main():
    """命令行入口：执行迁移."""
    import argparse

    parser = argparse.ArgumentParser(description="M10 系统卫士 - 数据库迁移管理")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # migrate 命令
    migrate_parser = subparsers.add_parser("migrate", help="执行迁移")
    migrate_parser.add_argument("--target", type=int, help="目标版本号")
    migrate_parser.add_argument("--no-backup", action="store_true", help="跳过迁移前备份")
    migrate_parser.add_argument("--backup-dir", type=str, help="备份目录")
    migrate_parser.add_argument("--dry-run", action="store_true", help="试运行模式")
    migrate_parser.add_argument("--no-retry", action="store_true", help="禁用错误重试")

    # rollback 命令
    rollback_parser = subparsers.add_parser("rollback", help="回滚迁移")
    rollback_parser.add_argument("--target", type=int, default=0, help="回滚到的版本号")

    # status 命令
    subparsers.add_parser("status", help="查看迁移状态")

    # history 命令
    subparsers.add_parser("history", help="查看迁移历史")

    # check 命令
    subparsers.add_parser("check", help="检查数据库完整性")

    args = parser.parse_args()

    mgr = get_migration_manager()

    if args.command == "migrate":
        print(f"[M10-Migration] 开始迁移...")
        print(f"[M10-Migration] 当前版本: {mgr.get_current_version()}")
        print(f"[M10-Migration] 最新版本: {mgr.get_latest_version()}")

        if args.dry_run:
            print("[M10-Migration] DRY-RUN 模式（模拟执行）")

        result = mgr.migrate(
            target_version=args.target,
            pre_backup=not args.no_backup,
            backup_dir=args.backup_dir,
            dry_run=args.dry_run,
            enable_retry=not args.no_retry,
        )

        if result["success"]:
            print(f"[M10-Migration] 迁移成功！")
            print(f"  从版本: {result['from_version']}")
            print(f"  到版本: {result['to_version']}")
            print(f"  应用迁移数: {result['applied_count']}")
            print(f"  耗时: {result['duration_ms']}ms")
            if result.get("backup_path"):
                print(f"  备份路径: {result['backup_path']}")
            if args.dry_run:
                print("  [DRY-RUN] 未实际修改数据库")
        else:
            print(f"[M10-Migration] 迁移失败！")
            print(f"  错误: {result.get('error', 'unknown')}")
            print(f"  失败版本: {result.get('failed_at', 'unknown')}")
            sys.exit(1)

    elif args.command == "rollback":
        print(f"[M10-Migration] 开始回滚到版本 {args.target}...")
        result = mgr.rollback(target_version=args.target)

        if result["success"]:
            print(f"[M10-Migration] 回滚成功！")
            print(f"  从版本: {result['from_version']}")
            print(f"  到版本: {result['to_version']}")
            print(f"  回滚迁移数: {result['rolled_back_count']}")
        else:
            print(f"[M10-Migration] 回滚失败: {result.get('error', 'unknown')}")
            sys.exit(1)

    elif args.command == "status":
        current = mgr.get_current_version()
        latest = mgr.get_latest_version()
        print(f"[M10-Migration] 迁移状态:")
        print(f"  当前版本: {current}")
        print(f"  最新版本: {latest}")
        print(f"  状态: {'最新' if current >= latest else f'需要升级 (落后 {latest - current} 个版本)'}")

    elif args.command == "history":
        history = mgr.get_migration_history()
        print(f"[M10-Migration] 迁移历史（共 {len(history)} 条）:")
        for m in history:
            status = m.get("status", "success")
            status_icon = "✓" if status == "success" else "✗"
            print(f"  {status_icon} v{m['version']} - {m['name']} "
                  f"({m.get('applied_at', 'N/A')}, {m.get('duration_ms', 0)}ms)")

    elif args.command == "check":
        result = mgr.check_integrity()
        print(f"[M10-Migration] 完整性检查:")
        print(f"  状态: {result['status']}")
        print(f"  integrity_check: {result.get('integrity_check', 'N/A')}")
        print(f"  quick_check: {result.get('quick_check', 'N/A')}")
        print(f"  表数量: {result.get('table_count', 0)}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
