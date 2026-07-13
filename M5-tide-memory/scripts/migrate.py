"""
数据库迁移脚本（版本化迁移）

使用版本化迁移系统管理 M5 潮汐记忆的所有数据库：
- L1 浅水层 (l1_shallow.db)
- L2 深水层 (l2_deep.db)
- L3 深海层索引 (l3_abyss/index.db)
- 成长系统 (growth.db)

运行示例：

    # 迁移所有数据库到最新版本
    python scripts/migrate.py

    # 迁移指定数据库
    python scripts/migrate.py --db l1
    python scripts/migrate.py --db l1,l2,growth

    # 迁移到指定版本
    python scripts/migrate.py --db l1 --version 1

    # 检查迁移状态
    python scripts/migrate.py --status

    # 查看迁移历史
    python scripts/migrate.py --history --db l1
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# 数据库配置
# ============================================================

DB_CONFIGS = {
    "l1": {
        "name": "L1 浅水层",
        "db_path": "./data/memory/l1_shallow.db",
        "migrator_factory": "l1",
    },
    "l2": {
        "name": "L2 深水层",
        "db_path": "./data/memory/l2_deep.db",
        "migrator_factory": "l2",
    },
    "l3": {
        "name": "L3 深海层索引",
        "db_path": "./data/memory/l3_abyss/index.db",
        "migrator_factory": "l3",
    },
    "growth": {
        "name": "成长系统",
        "db_path": "./data/growth/growth.db",
        "migrator_factory": "growth",
    },
}


# ============================================================
# 迁移器工厂
# ============================================================

def get_layer_migrator(layer_type: str, db_path: str):
    """
    获取指定层的迁移器（带注册的迁移）

    Args:
        layer_type: 层类型 ("l1", "l2", "l3")
        db_path: 数据库路径

    Returns:
        DatabaseMigrator 实例
    """
    from tide_memory.db import DatabaseMigrator

    migrator = DatabaseMigrator(db_path)

    if layer_type in ("l1", "l2"):
        # L1/L2 共享相同的基础 schema
        from tide_memory.layers.base import BaseSQLLayer

        # 构建索引列表
        base_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)",
            "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_last_accessed ON memories(last_accessed_at)",
            "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
        ]

        extra_indexes = []
        if layer_type == "l2":
            # L2 有额外的 quality_score 索引（实际与 base 重复，但保留以保持一致）
            extra_indexes = [
                "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
            ]

        # v1: 初始 schema（不含 original_encrypted，v2 添加
        migrator.register(
            version=1,
            name="initial_schema",
            up_sql=[
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    layer TEXT,
                    domain TEXT,
                    owner_agent TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_accessed_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    quality_score REAL DEFAULT 50,
                    quality_level TEXT DEFAULT 'normal',
                    retention_days INTEGER DEFAULT -1,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    sync_version INTEGER DEFAULT 0,
                    emotion_valence REAL DEFAULT 0,
                    emotion_arousal REAL DEFAULT 0,
                    emotion_ei REAL DEFAULT 0,
                    emotion_label TEXT DEFAULT 'neutral',
                    classification TEXT DEFAULT 'TOP_SECRET'
                )
                """,
            ] + base_indexes + extra_indexes,
        )

        # v2: 添加 original_encrypted 列
        migrator.register(
            version=2,
            name="add_original_encrypted_column",
            up_sql=[
                "ALTER TABLE memories ADD COLUMN original_encrypted TEXT",
            ],
        )

    elif layer_type == "l3":
        # L3 索引库
        migrator.register(
            version=1,
            name="initial_schema",
            up_sql=[
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    file_name TEXT,
                    layer TEXT,
                    domain TEXT,
                    owner_agent TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_accessed_at TEXT,
                    access_count INTEGER DEFAULT 0,
                    quality_score REAL DEFAULT 50,
                    quality_level TEXT DEFAULT 'normal',
                    retention_days INTEGER DEFAULT -1,
                    tags TEXT DEFAULT '[]',
                    metadata TEXT DEFAULT '{}',
                    sync_version INTEGER DEFAULT 0,
                    emotion_valence REAL DEFAULT 0,
                    emotion_arousal REAL DEFAULT 0,
                    emotion_ei REAL DEFAULT 0,
                    emotion_label TEXT DEFAULT 'neutral',
                    classification TEXT DEFAULT 'TOP_SECRET',
                    encryption_salt TEXT
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_domain ON memories(domain)",
                "CREATE INDEX IF NOT EXISTS idx_created ON memories(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_score)",
                "CREATE INDEX IF NOT EXISTS idx_content_hash ON memories(content_hash)",
            ],
        )

    return migrator


def get_growth_migrator(db_path: str):
    """
    获取成长系统的迁移器（带注册的迁移）

    Args:
        db_path: 数据库路径

    Returns:
        DatabaseMigrator 实例
    """
    from tide_memory.db import DatabaseMigrator
    from tide_memory.growth.database import GrowthDatabase

    migrator = DatabaseMigrator(db_path)

    # 使用 GrowthDatabase 的 SQL 定义
    growth_db = GrowthDatabase.__new__(GrowthDatabase)
    growth_db._db_path = db_path

    def _init_seed_data(conn):
        """初始化预置数据"""
        growth_db._init_achievements(conn)
        growth_db._init_talents(conn)
        growth_db._init_points(conn)
        growth_db._init_seasons(conn)

    migrator.register(
        version=1,
        name="initial_schema",
        up_sql=growth_db._get_all_create_table_sql(),
        up_func=_init_seed_data,
    )

    return migrator


def get_migrator_for_db(db_key: str, db_path: str):
    """
    根据数据库 key 获取对应的迁移器

    Args:
        db_key: 数据库 key (l1, l2, l3, growth)
        db_path: 数据库路径

    Returns:
        DatabaseMigrator 实例
    """
    if db_key in ("l1", "l2", "l3"):
        return get_layer_migrator(db_key, db_path)
    elif db_key == "growth":
        return get_growth_migrator(db_path)
    else:
        raise ValueError(f"Unknown database: {db_key}")


# ============================================================
# 迁移操作
# ============================================================

def migrate_database(
    db_key: str,
    db_path: str,
    target_version: Optional[int] = None,
) -> Dict:
    """
    迁移单个数据库

    Args:
        db_key: 数据库 key
        db_path: 数据库路径
        target_version: 目标版本，None 表示最新

    Returns:
        迁移结果
    """
    config = DB_CONFIGS[db_key]
    migrator = get_migrator_for_db(db_key, db_path)

    result = migrator.migrate(target_version)
    result["db_key"] = db_key
    result["db_name"] = config["name"]
    result["db_path"] = db_path

    return result


def migrate_all(
    db_keys: List[str],
    data_dir: str = "./data",
    target_version: Optional[int] = None,
) -> List[Dict]:
    """
    迁移指定的所有数据库

    Args:
        db_keys: 数据库 key 列表
        data_dir: 数据根目录
        target_version: 目标版本

    Returns:
        迁移结果列表
    """
    results = []
    for db_key in db_keys:
        config = DB_CONFIGS[db_key]
        db_path = os.path.join(data_dir, os.path.relpath(config["db_path"], "./data"))
        # 修正路径计算
        db_path = config["db_path"]

        print(f"\n迁移: {config['name']} ({db_key})")
        print(f"  路径: {db_path}")

        try:
            result = migrate_database(db_key, db_path, target_version)
            results.append(result)

            if result["status"] == "already_at_target":
                print(f"  状态: 已是最新版本 (v{result['to_version']})")
            elif result["status"] == "success":
                print(f"  状态: 迁移成功")
                print(f"  版本: v{result['from_version']} → v{result['to_version']}")
                for m in result["applied"]:
                    print(f"    - v{m['version']}: {m['name']} ({m['duration_ms']:.2f}ms)")
        except Exception as e:
            print(f"  状态: 失败 - {e}")
            results.append({
                "db_key": db_key,
                "db_name": config["name"],
                "status": "failed",
                "error": str(e),
            })

    return results


def show_status(db_keys: List[str], data_dir: str = "./data") -> None:
    """
    显示数据库迁移状态

    Args:
        db_keys: 数据库 key 列表
        data_dir: 数据根目录
    """
    print("\n=== 数据库迁移状态 ===")
    for db_key in db_keys:
        config = DB_CONFIGS[db_key]
        db_path = config["db_path"]

        migrator = get_migrator_for_db(db_key, db_path)
        status = migrator.validate()

        status_icon = "✓" if status["is_up_to_date"] else "✗"
        print(f"\n{status_icon} {config['name']} ({db_key})")
        print(f"  路径: {status['db_path']}")
        print(f"  当前版本: v{status['current_version']}")
        print(f"  最新版本: v{status['latest_registered_version']}")
        print(f"  状态: {'最新' if status['is_up_to_date'] else '需要迁移'}")
        print(f"  迁移历史: {status['migration_history_count']} 条")


def show_history(db_keys: List[str], data_dir: str = "./data") -> None:
    """
    显示迁移历史

    Args:
        db_keys: 数据库 key 列表
        data_dir: 数据根目录
    """
    from datetime import datetime

    print("\n=== 迁移历史 ===")
    for db_key in db_keys:
        config = DB_CONFIGS[db_key]
        db_path = config["db_path"]

        migrator = get_migrator_for_db(db_key, db_path)
        history = migrator.get_migration_history()

        print(f"\n{config['name']} ({db_key})")
        if not history:
            print("  无迁移记录")
            continue

        for record in history:
            applied_at = datetime.fromtimestamp(record["applied_at"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  v{record['version']}: {record['name']}")
            print(f"    执行时间: {applied_at}")
            print(f"    耗时: {record['duration_ms']:.2f}ms")


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="M5 潮汐记忆系统 - 数据库版本化迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 迁移所有数据库到最新版本
  python scripts/migrate.py

  # 迁移指定数据库
  python scripts/migrate.py --db l1
  python scripts/migrate.py --db l1,l2,growth

  # 迁移到指定版本
  python scripts/migrate.py --db l1 --version 1

  # 检查迁移状态
  python scripts/migrate.py --status

  # 查看迁移历史
  python scripts/migrate.py --history --db l1
        """,
    )
    parser.add_argument(
        "--db",
        default=None,
        help="指定数据库，逗号分隔（l1, l2, l3, growth）。默认全部",
    )
    parser.add_argument(
        "--version",
        type=int,
        default=None,
        dest="target_version",
        help="目标版本号（默认最新版本）",
    )
    parser.add_argument(
        "--data-dir",
        default="./data",
        help="数据根目录（默认 ./data）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看迁移状态",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="查看迁移历史",
    )

    args = parser.parse_args()

    # 确定要操作的数据库
    if args.db:
        db_keys = [k.strip() for k in args.db.split(",") if k.strip()]
        invalid = [k for k in db_keys if k not in DB_CONFIGS]
        if invalid:
            print(f"错误: 未知的数据库: {', '.join(invalid)}")
            print(f"可用数据库: {', '.join(DB_CONFIGS.keys())}")
            sys.exit(1)
    else:
        db_keys = list(DB_CONFIGS.keys())

    # 状态查询
    if args.status:
        show_status(db_keys, args.data_dir)
        return

    # 历史查询
    if args.history:
        show_history(db_keys, args.data_dir)
        return

    # 执行迁移
    print(f"目标数据库: {', '.join(db_keys)}")
    if args.target_version:
        print(f"目标版本: v{args.target_version}")
    else:
        print("目标版本: 最新")

    results = migrate_all(db_keys, args.data_dir, args.target_version)

    # 汇总
    success_count = sum(1 for r in results if r["status"] in ("success", "already_at_target"))
    failed_count = sum(1 for r in results if r["status"] == "failed")

    print(f"\n=== 迁移汇总 ===")
    print(f"总计: {len(results)} 个数据库")
    print(f"成功: {success_count}")
    print(f"失败: {failed_count}")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
