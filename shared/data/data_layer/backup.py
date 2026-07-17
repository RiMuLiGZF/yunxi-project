#!/usr/bin/env python3
"""
云汐统一备份 CLI 工具（第二阶段统一治理）

提供命令行方式管理全系统备份，支持：
- backup: 执行备份（指定模块或全部）
- restore: 恢复备份
- list: 列出备份
- verify: 校验备份完整性
- clean: 清理旧备份
- status: 查看备份状态

使用方式：
    python shared/data/data_layer/backup.py backup --all
    python shared/data/data_layer/backup.py backup --module m5
    python shared/data/data_layer/backup.py backup --module m5 --type incremental
    python shared/data/data_layer/backup.py restore --module m5 --backup-dir /path/to/backup
    python shared/data/data_layer/backup.py list --module m4
    python shared/data/data_layer/backup.py verify --backup-path /path/to/backup.db
    python shared/data/data_layer/backup.py clean --module m5 --max-age 30
    python shared/data/data_layer/backup.py status
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# 将 data_layer 目录加入 path（直接导入同级模块，绕过 shared 包的 __init__.py）
_data_layer_dir = Path(__file__).parent
sys.path.insert(0, str(_data_layer_dir))

from backup_manager import (
    BackupManager,
    BackupOrchestrator,
    ModuleBackupConfig,
    BackupType,
    CompressionType,
    EncryptionType,
    RetentionPolicy,
    calculate_sha256,
)
from module_backup_registry import (
    get_module_config,
    get_all_module_configs,
    get_modules_with_db,
    get_module_backup_summary,
)


# ============================================================
# 输出辅助函数
# ============================================================

def _print_header(title: str):
    """打印标题"""
    line = "=" * 60
    print(f"\n{line}")
    print(f"  {title}")
    print(line)


def _print_success(msg: str):
    """打印成功消息"""
    print(f"[OK] {msg}")


def _print_error(msg: str):
    """打印错误消息"""
    print(f"[ERROR] {msg}")


def _print_warning(msg: str):
    """打印警告消息"""
    print(f"[WARN] {msg}")


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


def _format_time(timestamp: float) -> str:
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 命令处理函数
# ============================================================

def cmd_backup(args):
    """执行备份命令"""
    backup_type = args.type or BackupType.FULL

    if args.all:
        # 备份所有模块
        _print_header(f"全系统备份（{backup_type}）")

        configs = get_all_module_configs()
        if not configs:
            _print_error("未找到任何有数据库的模块")
            return 1

        print(f"找到 {len(configs)} 个模块需要备份: {', '.join(sorted(configs.keys()))}")
        print()

        success_count = 0
        fail_count = 0
        total_size = 0

        for module_id in sorted(configs.keys()):
            config = configs[module_id]
            print(f"[{module_id}] 正在备份...")

            bm = BackupManager()
            report = bm.backup_module(config, backup_type=backup_type)

            if report.success:
                _print_success(
                    f"{module_id} 备份成功: {report.success_dbs}/{report.total_dbs} 个数据库, "
                    f"{_format_size(report.total_size_bytes)}, "
                    f"耗时 {report.duration_seconds:.1f}s"
                )
                success_count += 1
                total_size += report.total_size_bytes
            else:
                _print_error(
                    f"{module_id} 备份失败: {report.failed_dbs}/{report.total_dbs} 个数据库失败"
                )
                for err in report.errors:
                    print(f"       - {err}")
                fail_count += 1

        print()
        _print_header("备份结果汇总")
        print(f"  总模块数: {len(configs)}")
        print(f"  成功: {success_count}")
        print(f"  失败: {fail_count}")
        print(f"  总大小: {_format_size(total_size)}")

        return 0 if fail_count == 0 else 1

    elif args.module:
        # 备份指定模块
        module_id = args.module.lower()
        _print_header(f"模块备份: {module_id}（{backup_type}）")

        config = get_module_config(module_id)
        if not config:
            _print_error(f"未找到模块 {module_id} 的配置，或模块没有数据库")
            return 1

        print(f"数据库文件 ({len(config.db_paths)} 个):")
        for db in config.db_paths:
            print(f"  - {db}")
        print(f"备份目录: {config.backup_dir}")
        print()

        bm = BackupManager()
        report = bm.backup_module(config, backup_type=backup_type)

        if report.success:
            _print_success(f"备份成功!")
            print(f"  数据库: {report.success_dbs}/{report.total_dbs}")
            print(f"  原始大小: {_format_size(report.total_size_bytes)}")
            if report.compressed:
                print(f"  压缩后: {_format_size(report.compressed_size_bytes)}")
            print(f"  备份目录: {report.backup_dir}")
            print(f"  耗时: {report.duration_seconds:.2f} 秒")
            if report.checksum:
                print(f"  校验和: {report.checksum}")
            print(f"  压缩: {'是' if report.compressed else '否'}")
            print(f"  加密: {'是' if report.encrypted else '否'}")
            return 0
        else:
            _print_error("备份失败!")
            for err in report.errors:
                print(f"  - {err}")
            return 1

    else:
        _print_error("请指定 --all 或 --module <模块ID>")
        return 1


def cmd_restore(args):
    """执行恢复命令"""
    module_id = args.module.lower()
    backup_dir = args.backup_dir

    _print_header(f"恢复备份: {module_id}")

    if not backup_dir:
        _print_error("请使用 --backup-dir 指定备份目录")
        return 1

    config = get_module_config(module_id)
    if not config:
        _print_error(f"未找到模块 {module_id} 的配置")
        return 1

    backup_path = Path(backup_dir)
    if not backup_path.exists():
        _print_error(f"备份目录不存在: {backup_dir}")
        return 1

    print(f"备份目录: {backup_dir}")
    print(f"使用安全网: {'是' if args.safety_net else '否'}")
    print()

    # 确认操作
    if not args.yes:
        answer = input("确认要执行恢复操作吗？此操作可能覆盖现有数据 (y/N): ")
        if answer.lower() != "y":
            print("操作已取消")
            return 0

    bm = BackupManager()

    success_count = 0
    fail_count = 0

    for db_path_str in config.db_paths:
        db_path = Path(db_path_str)
        db_name = db_path.name

        # 查找对应的备份文件
        backup_file = None
        for ext in [".db", ".db.gz", ".db.enc", ".db.gz.enc"]:
            candidate = backup_path / (db_path.stem + ext)
            if candidate.exists():
                backup_file = candidate
                break

        if not backup_file:
            # 尝试模糊匹配
            for f in backup_path.iterdir():
                if f.is_file() and f.name.startswith(db_path.stem) and not f.name.endswith(".meta.json"):
                    backup_file = f
                    break

        if not backup_file:
            _print_error(f"{db_name}: 未找到备份文件")
            fail_count += 1
            continue

        print(f"[{db_name}] 正在恢复...")

        if args.safety_net:
            result = bm.restore_with_safety_net(
                str(backup_file), str(db_path), auto_rollback=True
            )
        else:
            result = bm.restore_backup(
                str(backup_file), str(db_path), overwrite=True
            )

        if result.get("success"):
            _print_success(f"{db_name}: 恢复成功")
            if args.safety_net and result.get("safety_net_path"):
                print(f"       安全网备份: {result['safety_net_path']}")
            success_count += 1
        else:
            _print_error(f"{db_name}: 恢复失败 - {result.get('error', '未知错误')}")
            fail_count += 1

    print()
    print(f"恢复完成: {success_count} 成功, {fail_count} 失败")
    return 0 if fail_count == 0 else 1


def cmd_list(args):
    """列出备份"""
    _print_header("备份列表")

    bm = BackupManager()

    module_id = args.module.lower() if args.module else None

    if module_id:
        config = get_module_config(module_id)
        if config:
            backups = bm.list_backups(module_id=module_id)
        else:
            backups = bm.list_backups()
    else:
        backups = bm.list_backups()

    if not backups:
        print("暂无备份")
        return 0

    print(f"共 {len(backups)} 个备份:\n")
    print(f"{'序号':<5} {'名称':<30} {'模块':<8} {'大小':>12} {'创建时间':<20}")
    print("-" * 80)

    for i, b in enumerate(backups, 1):
        module_name = b.get("module", "-") or "-"
        print(
            f"{i:<5} {b['name']:<30} {module_name:<8} "
            f"{_format_size(b['size_bytes']):>12} "
            f"{_format_time(b['created']):<20}"
        )

    return 0


def cmd_verify(args):
    """校验备份"""
    _print_header("备份校验")

    backup_path = args.backup_path

    if not backup_path:
        _print_error("请使用 --backup-path 指定备份文件路径")
        return 1

    bm = BackupManager()
    report = bm.verify_backup(
        backup_path,
        check_tables=args.check_tables,
        expected_checksum=args.expected_checksum or "",
    )

    print(f"备份路径: {report.backup_path}")
    print()

    # 文件检查
    print(f"  文件有效: {'是' if report.file_valid else '否'}")
    if report.file_valid:
        print(f"  文件大小: {_format_size(report.file_size_bytes)}")

    # 校验和
    if report.sha256_checksum:
        print(f"  SHA-256: {report.sha256_checksum}")
        if args.expected_checksum:
            print(f"  校验和匹配: {'是' if report.checksum_valid else '否'}")

    # SQLite 检查
    if report.integrity_check and "skipped" not in report.integrity_check:
        print(f"  完整性检查: {report.integrity_check}")
        print(f"  快速检查: {report.quick_check}")
        print(f"  表数量: {report.table_count}")

    # 错误
    if report.errors:
        print(f"\n错误 ({len(report.errors)}):")
        for err in report.errors:
            print(f"  - {err}")

    print()
    if report.overall_valid:
        _print_success("备份校验通过!")
        return 0
    else:
        _print_error("备份校验未通过!")
        return 1


def cmd_clean(args):
    """清理旧备份"""
    _print_header("清理旧备份")

    bm = BackupManager()
    module_id = args.module.lower() if args.module else None

    if args.max_age:
        # 按时间清理
        print(f"清理 {args.max_age} 天前的备份...")
        result = bm.cleanup_by_age(args.max_age)
        print(f"已删除 {result.get('deleted_count', 0)} 个备份")
        if result.get("failed_count", 0) > 0:
            _print_warning(f"{result['failed_count']} 个备份删除失败")

    elif args.max_count:
        # 按数量清理
        print(f"保留最近 {args.max_count} 个备份...")
        result = bm.apply_retention_policy("count", max_count=args.max_count)
        print(f"剩余 {result.get('remaining', 0)} 个备份")

    elif args.max_size_gb:
        # 按大小清理
        print(f"限制最大空间 {args.max_size_gb} GB...")
        result = bm.cleanup_by_size(args.max_size_gb)
        print(f"已删除 {result.get('deleted_count', 0)} 个备份")
        print(f"剩余大小: {_format_size(result.get('remaining_size_bytes', 0))}")

    else:
        # 使用默认策略
        print("使用默认保留策略清理...")
        result = bm.apply_retention_policy("count", max_count=bm.max_backups)
        print(f"剩余 {result.get('remaining', 0)} 个备份")

    _print_success("清理完成")
    return 0


def cmd_status(args):
    """查看备份状态"""
    _print_header("备份系统状态")

    # 存储使用情况
    bm = BackupManager()
    storage = bm.get_storage_usage()

    print("--- 存储使用 ---")
    if "error" in storage:
        _print_error(f"获取存储信息失败: {storage['error']}")
    else:
        print(f"  备份根目录: {storage.get('backup_root', 'N/A')}")
        print(f"  已用空间: {_format_size(storage.get('used_bytes', 0))}")
        print(f"  磁盘总量: {_format_size(storage.get('disk_total_bytes', 0))}")
        print(f"  磁盘剩余: {_format_size(storage.get('disk_free_bytes', 0))} "
              f"({storage.get('disk_free_percent', 0)}%)")

    # 模块列表
    print("\n--- 已注册模块 ---")
    modules = get_modules_with_db()
    if not modules:
        print("  （无）")
    else:
        summary = get_module_backup_summary()
        for mid in modules:
            info = summary.get(mid, {})
            db_count = info.get("db_count", 0)
            schedule = info.get("schedule", {})
            sched_str = "未配置"
            if schedule:
                if schedule.get("type") == "daily":
                    sched_str = f"每日 {schedule.get('time', '??:??')}"
                elif schedule.get("type") == "interval":
                    sched_str = f"每 {schedule.get('hours', schedule.get('minutes', '?'))} 小时/分钟"
                elif schedule.get("type") == "cron":
                    sched_str = f"cron: {schedule.get('expression', '?')}"

            print(f"  {mid:<6} {db_count} 个数据库  调度: {sched_str}")

    # 备份统计
    print("\n--- 备份统计 ---")
    stats = bm.get_backup_stats()
    print(f"  总备份数: {stats.get('total_backups', 0)}")
    print(f"  总大小: {_format_size(stats.get('total_size_bytes', 0))}")
    print(f"  最大保留: {stats.get('max_backups', 'N/A')} 个")

    if stats.get("latest_backup"):
        latest = stats["latest_backup"]
        print(f"  最新备份: {latest.get('name', 'N/A')} "
              f"({_format_time(latest.get('created', 0))})")

    print()
    return 0


# ============================================================
# 参数解析
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="backup.py",
        description="云汐统一备份 CLI 工具（第二阶段统一治理）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s backup --all                    # 备份所有模块
  %(prog)s backup --module m5              # 备份 M5 模块
  %(prog)s backup --module m5 --type incremental  # 增量备份 M5
  %(prog)s restore --module m5 --backup-dir /path  # 恢复 M5 备份
  %(prog)s list --module m4                # 列出 M4 的备份
  %(prog)s verify --backup-path /path/db.db  # 校验备份文件
  %(prog)s clean --max-age 30              # 清理30天前的备份
  %(prog)s status                          # 查看备份状态
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ---- backup 命令 ----
    backup_parser = subparsers.add_parser("backup", help="执行备份")
    backup_group = backup_parser.add_mutually_exclusive_group(required=True)
    backup_group.add_argument("--all", action="store_true", help="备份所有模块")
    backup_group.add_argument("--module", type=str, help="指定模块ID，如 m5")
    backup_parser.add_argument(
        "--type", type=str, default=None,
        choices=["full", "incremental", "differential"],
        help="备份类型：full（全量，默认）/ incremental（增量）/ differential（差异）",
    )

    # ---- restore 命令 ----
    restore_parser = subparsers.add_parser("restore", help="恢复备份")
    restore_parser.add_argument("--module", type=str, required=True, help="模块ID")
    restore_parser.add_argument("--backup-dir", type=str, required=True, help="备份目录路径")
    restore_parser.add_argument(
        "--no-safety-net", action="store_true", dest="no_safety_net",
        help="不使用安全网机制（不推荐）",
    )
    restore_parser.add_argument(
        "-y", "--yes", action="store_true", help="跳过确认提示",
    )

    # ---- list 命令 ----
    list_parser = subparsers.add_parser("list", help="列出备份")
    list_parser.add_argument("--module", type=str, help="按模块筛选")
    list_parser.add_argument("--type", type=str, help="按备份类型筛选")

    # ---- verify 命令 ----
    verify_parser = subparsers.add_parser("verify", help="校验备份完整性")
    verify_parser.add_argument("--backup-path", type=str, required=True, help="备份文件路径")
    verify_parser.add_argument(
        "--expected-checksum", type=str, default="",
        help="期望的 SHA-256 校验和",
    )
    verify_parser.add_argument(
        "--no-table-check", action="store_true", dest="no_table_check",
        help="跳过表数量检查",
    )

    # ---- clean 命令 ----
    clean_parser = subparsers.add_parser("clean", help="清理旧备份")
    clean_parser.add_argument("--module", type=str, help="指定模块")
    clean_group = clean_parser.add_mutually_exclusive_group()
    clean_group.add_argument("--max-age", type=int, help="最大保留天数")
    clean_group.add_argument("--max-count", type=int, help="最大保留数量")
    clean_group.add_argument("--max-size-gb", type=float, help="最大空间（GB）")

    # ---- status 命令 ----
    subparsers.add_parser("status", help="查看备份状态")

    return parser


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    """主入口函数"""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # 处理 restore 的 safety_net 参数
    if args.command == "restore":
        args.safety_net = not args.no_safety_net

    # 处理 verify 的 check_tables 参数
    if args.command == "verify":
        args.check_tables = not args.no_table_check

    # 分发命令
    commands = {
        "backup": cmd_backup,
        "restore": cmd_restore,
        "list": cmd_list,
        "verify": cmd_verify,
        "clean": cmd_clean,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
