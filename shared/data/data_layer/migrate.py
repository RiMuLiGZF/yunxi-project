"""
统一数据迁移 CLI 工具
====================

提供全模块统一的数据库迁移命令行接口。
支持对单个模块或所有模块执行迁移、回滚、状态查询等操作。

支持的命令：
- init:     初始化迁移记录表
- migrate:  执行迁移（升级到最新版本或指定版本）
- rollback: 回滚迁移（降级到指定版本）
- status:   查看当前迁移状态
- history:  查看迁移历史
- check:    检查数据库完整性

使用示例::

    # 查看所有模块迁移状态
    python migrate.py status --all

    # 迁移指定模块到最新版本
    python migrate.py migrate --module m5

    # 迁移所有模块（dry-run 模式）
    python migrate.py migrate --all --dry-run

    # 回滚指定模块到版本 0
    python migrate.py rollback --module m10 --target 0

    # 检查所有模块数据库完整性
    python migrate.py check --all
"""

from __future__ import annotations

import argparse
import importlib
import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# 模块注册表
# ============================================================

# 模块迁移管理器注册表
# key: 模块标识（小写，如 "m0", "m5"）
# value: 模块配置字典
_MODULE_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _get_project_root() -> Path:
    """获取项目根目录路径"""
    # shared/data/data_layer/migrate.py
    return Path(__file__).resolve().parent.parent.parent.parent


def _register_module(
    module_id: str,
    module_path: str,
    manager_module: str,
    manager_class: str = None,
    get_manager_func: str = "get_migration_manager",
    db_type: str = "sqlite",
):
    """注册一个模块的迁移管理器

    Args:
        module_id: 模块标识（如 "m0", "m5"）
        module_path: 模块 Python 包路径（相对于项目根）
        manager_module: 迁移管理器模块路径（相对于模块包）
        manager_class: 迁移管理器类名（可选，与 get_manager_func 二选一）
        get_manager_func: 获取管理器单例的函数名
        db_type: 数据库类型（sqlite / postgresql）
    """
    _MODULE_REGISTRY[module_id.lower()] = {
        "module_id": module_id,
        "module_path": module_path,
        "manager_module": manager_module,
        "manager_class": manager_class,
        "get_manager_func": get_manager_func,
        "db_type": db_type,
    }


def _auto_discover_modules() -> None:
    """自动发现项目中的所有迁移模块"""
    project_root = _get_project_root()

    # 预定义的已知模块（带迁移能力的）
    known_modules = [
        # (模块ID, 模块目录, 管理器路径, 数据库类型)
        ("m0", "M0-principal-console/src", "migration_manager", "sqlite"),
        ("m4", "M4-scene-engine/src/models/db", "migrations.migration_manager", "sqlite"),
        ("m5", "M5-growth-core", "database.migration_manager", "sqlite"),
        ("m6", "M6-hardware-peripheral/m6_hardware/database", "migrations.migration_manager", "sqlite"),
        ("m7", "M7-workflow-builder/src", "migrations.migration_manager", "sqlite"),
        ("m9", "M9-dev-workshop/backend", "migration_manager", "sqlite"),
        ("m10", "M10-system-guard/m10_system_guard", "migration_manager", "sqlite"),
        ("m12", "M12-security-shield/backend", "migration_manager", "sqlite"),
    ]

    for mod_id, mod_dir, mgr_path, db_type in known_modules:
        full_path = project_root / mod_dir
        if full_path.exists():
            _register_module(
                module_id=mod_id,
                module_path=mod_dir.replace("/", "."),
                manager_module=mgr_path,
                db_type=db_type,
            )


def get_module_manager(module_id: str) -> Any:
    """获取指定模块的迁移管理器

    Args:
        module_id: 模块标识（如 "m0", "m5"）

    Returns:
        迁移管理器实例

    Raises:
        ValueError: 模块未注册或不存在
    """
    module_id = module_id.lower()

    if not _MODULE_REGISTRY:
        _auto_discover_modules()

    if module_id not in _MODULE_REGISTRY:
        raise ValueError(
            f"未知模块: {module_id}\n"
            f"可用模块: {', '.join(sorted(_MODULE_REGISTRY.keys()))}"
        )

    config = _MODULE_REGISTRY[module_id]
    project_root = _get_project_root()

    # 将项目根和模块路径加入 sys.path
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    # shared 目录
    shared_path = str(project_root / "shared")
    if shared_path not in sys.path:
        sys.path.insert(0, shared_path)

    # 动态导入迁移管理器模块
    module_path = config["module_path"]
    manager_module_name = config["manager_module"]
    full_module_name = f"{module_path}.{manager_module_name}".replace("..", ".")

    try:
        mod = importlib.import_module(full_module_name)
    except ImportError as e:
        raise ValueError(
            f"无法导入模块 {module_id} 的迁移管理器: {full_module_name}\n"
            f"错误: {e}"
        )

    # 获取管理器实例
    get_func_name = config["get_manager_func"]
    if hasattr(mod, get_func_name):
        return getattr(mod, get_func_name)()
    elif config["manager_class"] and hasattr(mod, config["manager_class"]):
        cls = getattr(mod, config["manager_class"])
        return cls()
    else:
        raise ValueError(
            f"模块 {module_id} 的迁移管理器中找不到 "
            f"{get_func_name}() 或 {config['manager_class']}"
        )


def list_registered_modules() -> List[str]:
    """列出所有已注册的模块"""
    if not _MODULE_REGISTRY:
        _auto_discover_modules()
    return sorted(_MODULE_REGISTRY.keys())


# ============================================================
# CLI 命令实现
# ============================================================

def _print_header(title: str):
    """打印标题"""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _print_module_header(module_id: str):
    """打印模块标题"""
    print()
    print("-" * 50)
    print(f"  [{module_id.upper()}]")
    print("-" * 50)


def cmd_init(args) -> int:
    """init 命令：初始化迁移记录表"""
    modules = _resolve_modules(args)
    _print_header("初始化迁移记录表")

    success_count = 0
    failed_modules = []

    for mod_id in modules:
        _print_module_header(mod_id)
        try:
            mgr = get_module_manager(mod_id)
            # 初始化：执行到版本 0（创建迁移记录表）
            current = mgr.get_current_version()
            print(f"  迁移记录表已就绪 (当前版本: v{current})")
            success_count += 1
        except Exception as e:
            print(f"  失败: {e}")
            failed_modules.append(mod_id)

    _print_summary(len(modules), success_count, len(failed_modules), "init")
    return 0 if not failed_modules else 1


def cmd_migrate(args) -> int:
    """migrate 命令：执行迁移"""
    modules = _resolve_modules(args)
    _print_header("执行数据库迁移")

    if args.dry_run:
        print("  [DRY-RUN 模式] 仅模拟执行，不实际修改数据库")
        print()

    success_count = 0
    failed_modules = []

    for mod_id in modules:
        _print_module_header(mod_id)
        try:
            mgr = get_module_manager(mod_id)
            current = mgr.get_current_version()
            latest = mgr.get_latest_version()

            print(f"  当前版本: v{current}")
            print(f"  最新版本: v{latest}")

            if current >= latest and args.target is None:
                print(f"  已是最新版本，无需迁移")
                success_count += 1
                continue

            result = mgr.migrate(
                target_version=args.target,
                pre_backup=not args.no_backup,
                dry_run=args.dry_run,
                enable_retry=not args.no_retry,
            )

            if result.get("success"):
                print(f"  ✓ 迁移成功")
                print(f"    从版本: v{result['from_version']}")
                print(f"    到版本: v{result['to_version']}")
                print(f"    应用迁移数: {result['applied_count']}")
                print(f"    耗时: {result['duration_ms']}ms")
                if result.get("backup_path"):
                    print(f"    备份路径: {result['backup_path']}")
                if args.dry_run:
                    print(f"    [DRY-RUN] 未实际修改数据库")
                success_count += 1
            else:
                print(f"  ✗ 迁移失败")
                print(f"    错误: {result.get('error', 'unknown')}")
                print(f"    失败版本: {result.get('failed_at', 'unknown')}")
                failed_modules.append(mod_id)

        except Exception as e:
            print(f"  ✗ 异常: {e}")
            failed_modules.append(mod_id)

    _print_summary(len(modules), success_count, len(failed_modules), "migrate")
    return 0 if not failed_modules else 1


def cmd_rollback(args) -> int:
    """rollback 命令：回滚迁移"""
    modules = _resolve_modules(args)
    _print_header(f"回滚迁移到版本 {args.target}")

    if not args.force:
        print("  警告：回滚操作可能导致数据丢失！")
        confirm = input("  确认回滚？(yes/no): ")
        if confirm.lower() != "yes":
            print("  已取消")
            return 0

    success_count = 0
    failed_modules = []

    for mod_id in modules:
        _print_module_header(mod_id)
        try:
            mgr = get_module_manager(mod_id)
            current = mgr.get_current_version()

            print(f"  当前版本: v{current}")
            print(f"  目标版本: v{args.target}")

            if current <= args.target:
                print(f"  当前版本已低于或等于目标版本，无需回滚")
                success_count += 1
                continue

            result = mgr.rollback(target_version=args.target)

            if result.get("success"):
                print(f"  ✓ 回滚成功")
                print(f"    从版本: v{result['from_version']}")
                print(f"    到版本: v{result['to_version']}")
                print(f"    回滚迁移数: {result['rolled_back_count']}")
                success_count += 1
            else:
                print(f"  ✗ 回滚失败")
                print(f"    错误: {result.get('error', 'unknown')}")
                failed_modules.append(mod_id)

        except Exception as e:
            print(f"  ✗ 异常: {e}")
            failed_modules.append(mod_id)

    _print_summary(len(modules), success_count, len(failed_modules), "rollback")
    return 0 if not failed_modules else 1


def cmd_status(args) -> int:
    """status 命令：查看迁移状态"""
    modules = _resolve_modules(args)
    _print_header("迁移状态")

    print(f"  {'模块':<8} {'当前版本':<10} {'最新版本':<10} {'状态':<20}")
    print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*20}")

    up_to_date = 0
    needs_update = 0
    failed = 0

    for mod_id in modules:
        try:
            mgr = get_module_manager(mod_id)
            current = mgr.get_current_version()
            latest = mgr.get_latest_version()

            if current >= latest:
                status = "✓ 最新"
                up_to_date += 1
            else:
                status = f"↓ 落后 {latest - current} 个版本"
                needs_update += 1

            print(f"  {mod_id.upper():<8} v{current:<9} v{latest:<9} {status}")
        except Exception as e:
            print(f"  {mod_id.upper():<8} {'N/A':<10} {'N/A':<10} ✗ 错误: {e}")
            failed += 1

    print()
    print(f"  总计: {len(modules)} 个模块")
    print(f"    最新: {up_to_date}")
    print(f"    需升级: {needs_update}")
    if failed:
        print(f"    失败: {failed}")

    return 0 if failed == 0 else 1


def cmd_history(args) -> int:
    """history 命令：查看迁移历史"""
    modules = _resolve_modules(args)
    _print_header("迁移历史")

    for mod_id in modules:
        _print_module_header(mod_id)
        try:
            mgr = get_module_manager(mod_id)
            history = mgr.get_migration_history()

            if not history:
                print(f"  暂无迁移记录")
                continue

            print(f"  共 {len(history)} 条迁移记录:")
            print()
            for m in history:
                status = m.get("status", "success")
                status_icon = "✓" if status == "success" else "✗"
                version = m.get("version", 0)
                name = m.get("name", "unknown")
                applied_at = m.get("applied_at", "N/A")
                duration = m.get("duration_ms", 0)

                print(f"    {status_icon} v{version:<3} - {name}")
                print(f"        时间: {applied_at}, 耗时: {duration}ms")
                if m.get("description"):
                    print(f"        描述: {m['description']}")

        except Exception as e:
            print(f"  ✗ 错误: {e}")

    return 0


def cmd_check(args) -> int:
    """check 命令：检查数据库完整性"""
    modules = _resolve_modules(args)
    _print_header("数据库完整性检查")

    print(f"  {'模块':<8} {'状态':<12} {'表数量':<8} {'完整性':<12}")
    print(f"  {'-'*8} {'-'*12} {'-'*8} {'-'*12}")

    passed = 0
    failed = 0

    for mod_id in modules:
        try:
            mgr = get_module_manager(mod_id)
            result = mgr.check_integrity()

            status = result.get("status", "unknown")
            table_count = result.get("table_count", 0)
            integrity = result.get("integrity_check", "N/A")
            quick = result.get("quick_check", "N/A")

            status_icon = "✓" if status == "ok" else "✗"
            print(f"  {mod_id.upper():<8} {status_icon} {status:<10} {table_count:<8} {integrity:<12}")

            if status == "ok":
                passed += 1
            else:
                failed += 1

        except Exception as e:
            print(f"  {mod_id.upper():<8} ✗ 错误       N/A      N/A")
            print(f"          {e}")
            failed += 1

    print()
    print(f"  总计: {len(modules)} 个模块")
    print(f"    通过: {passed}")
    print(f"    失败: {failed}")

    return 0 if failed == 0 else 1


# ============================================================
# 辅助函数
# ============================================================

def _resolve_modules(args) -> List[str]:
    """解析要操作的模块列表"""
    if args.all:
        modules = list_registered_modules()
    elif args.module:
        modules = [m.strip().lower() for m in args.module.split(",")]
    else:
        # 默认列出所有可用模块
        modules = list_registered_modules()

    return modules


def _print_summary(total: int, success: int, failed: int, action: str):
    """打印操作摘要"""
    print()
    print("=" * 60)
    print(f"  操作完成: {action}")
    print(f"  总计: {total} 个模块, 成功: {success}, 失败: {failed}")
    print("=" * 60)


# ============================================================
# CLI 主入口
# ============================================================

def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(
        prog="migrate",
        description="云汐项目统一数据迁移 CLI 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看所有模块迁移状态
  python migrate.py status --all

  # 迁移指定模块到最新版本
  python migrate.py migrate --module m5

  # 迁移所有模块（dry-run 模式）
  python migrate.py migrate --all --dry-run

  # 回滚指定模块到版本 0
  python migrate.py rollback --module m10 --target 0

  # 检查所有模块数据库完整性
  python migrate.py check --all

  # 列出所有可用模块
  python migrate.py status --list
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # --------------------------------------------------------
    # init 命令
    # --------------------------------------------------------
    init_parser = subparsers.add_parser("init", help="初始化迁移记录表")
    _add_module_args(init_parser)

    # --------------------------------------------------------
    # migrate 命令
    # --------------------------------------------------------
    migrate_parser = subparsers.add_parser("migrate", help="执行数据库迁移")
    _add_module_args(migrate_parser)
    migrate_parser.add_argument(
        "--target", type=int, help="目标版本号（默认最新版本）"
    )
    migrate_parser.add_argument(
        "--no-backup", action="store_true",
        help="跳过迁移前自动备份（不推荐）"
    )
    migrate_parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行模式，模拟执行但不实际修改数据库"
    )
    migrate_parser.add_argument(
        "--no-retry", action="store_true",
        help="禁用错误重试机制"
    )

    # --------------------------------------------------------
    # rollback 命令
    # --------------------------------------------------------
    rollback_parser = subparsers.add_parser("rollback", help="回滚迁移")
    _add_module_args(rollback_parser)
    rollback_parser.add_argument(
        "--target", type=int, default=0,
        help="回滚到的版本号（默认 0，即回滚所有迁移）"
    )
    rollback_parser.add_argument(
        "--force", action="store_true",
        help="强制回滚，跳过确认提示"
    )

    # --------------------------------------------------------
    # status 命令
    # --------------------------------------------------------
    status_parser = subparsers.add_parser("status", help="查看迁移状态")
    _add_module_args(status_parser)
    status_parser.add_argument(
        "--list", action="store_true",
        help="列出所有可用模块"
    )

    # --------------------------------------------------------
    # history 命令
    # --------------------------------------------------------
    history_parser = subparsers.add_parser("history", help="查看迁移历史")
    _add_module_args(history_parser)

    # --------------------------------------------------------
    # check 命令
    # --------------------------------------------------------
    check_parser = subparsers.add_parser("check", help="检查数据库完整性")
    _add_module_args(check_parser)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # 特殊处理：status --list
    if args.command == "status" and getattr(args, "list", False):
        modules = list_registered_modules()
        print(f"可用模块（共 {len(modules)} 个）:")
        for m in modules:
            config = _MODULE_REGISTRY[m]
            print(f"  {m.upper():<6} ({config['db_type']})")
        return 0

    # 执行命令
    commands = {
        "init": cmd_init,
        "migrate": cmd_migrate,
        "rollback": cmd_rollback,
        "status": cmd_status,
        "history": cmd_history,
        "check": cmd_check,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        return cmd_func(args)
    else:
        parser.print_help()
        return 1


def _add_module_args(parser):
    """添加模块选择参数"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--module", "-m", type=str,
        help="指定模块（多个用逗号分隔，如 m0,m5,m10）"
    )
    group.add_argument(
        "--all", "-a", action="store_true",
        help="操作所有已注册的模块"
    )


if __name__ == "__main__":
    sys.exit(main())
