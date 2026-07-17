"""
P1b 批次数据迁移脚本：M8 work_* 表 -> M9 work_* 表
工作开发模块（4张表）：work_projects, work_tasks, work_commits, work_dev_code_usage

功能特性：
- MigrationStats 数据类统计迁移结果
- 分批迁移（batch_size=1000）
- 幂等性检查（业务ID去重）
- 重试机制（指数退避，max_retries=3）
- 断点续传（checkpoint JSON文件）
- ProgressTracker 进度报告 + ETA
- 详细的日志输出
- 支持 --full, --dry-run, --resume, --batch-size 参数

用法：
  python migrate_work_m8_to_m9.py --dry-run
  python migrate_work_m8_to_m9.py --full
  python migrate_work_m8_to_m9.py --resume
  python migrate_work_m8_to_m9.py --batch-size 500
"""

import sys
import os
import time
import json
import logging
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

# 添加父目录到 path，以便导入 models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from sqlalchemy.orm import Session

from models import (
    engine,
    SessionLocal,
    WorkProject,
    WorkTask,
    WorkCommit,
    WorkDevCodeUsage,
    init_db,
)

# ===== 日志配置 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("migrate_work")

# ===== 路径配置 =====
M8_DB_PATH = r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend\data\m8.db"
CHECKPOINT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "checkpoint_work_migration.json"
)

# ===== 迁移表配置 =====
TABLE_CONFIGS = [
    {
        "m8_table": "work_projects",
        "m9_model": WorkProject,
        "m9_table": "work_projects",
        "biz_id_field": "project_id",
        "order_field": "id",
        "field_mapping": {
            "id": None,  # M9 自增，不直接使用
            "project_id": "project_id",
            "name": "name",
            "description": "description",
            "status": "status",
            "progress": "progress",
            "repo_url": "repo_url",
            "language": "language",
            "file_count": "file_count",
            "line_count": "line_count",
            "commit_count": "commit_count",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "user_id": "user_id",  # Integer -> String 转换
        },
    },
    {
        "m8_table": "work_tasks",
        "m9_model": WorkTask,
        "m9_table": "work_tasks",
        "biz_id_field": "task_id",
        "order_field": "id",
        "field_mapping": {
            "id": None,
            "task_id": "task_id",
            "title": "title",
            "description": "description",
            "status": "status",
            "priority": "priority",
            "project_id": "project_id",
            "assignee": "assignee",
            "due_date": "due_date",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "user_id": "user_id",
        },
    },
    {
        "m8_table": "work_commits",
        "m9_model": WorkCommit,
        "m9_table": "work_commits",
        "biz_id_field": "commit_id",
        "order_field": "id",
        "field_mapping": {
            "id": None,
            "commit_id": "commit_id",
            "hash": "hash",
            "message": "message",
            "author": "author",
            "branch": "branch",
            "project_id": "project_id",
            "additions": "additions",
            "deletions": "deletions",
            "files_changed": "files_changed",
            "committed_at": "committed_at",
            "user_id": "user_id",
        },
    },
    {
        "m8_table": "work_dev_code_usage",
        "m9_model": WorkDevCodeUsage,
        "m9_table": "work_dev_code_usage",
        "biz_id_field": "usage_id",
        "order_field": "id",
        "field_mapping": {
            "id": None,
            "usage_id": "usage_id",
            "action_type": "action_type",
            "operation_type": "operation_type",
            "language": "language",
            "tokens_used": "tokens_used",
            "project_id": "project_id",
            "is_fallback": "is_fallback",
            "created_at": "created_at",
            "user_id": "user_id",
        },
    },
]


# ===== 数据类 =====
@dataclass
class TableMigrationStats:
    """单表迁移统计"""
    table_name: str
    total_source: int = 0
    migrated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0


@dataclass
class MigrationStats:
    """整体迁移统计"""
    batch_size: int = 1000
    dry_run: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    table_stats: Dict[str, TableMigrationStats] = field(default_factory=dict)

    @property
    def total_source(self) -> int:
        return sum(s.total_source for s in self.table_stats.values())

    @property
    def total_migrated(self) -> int:
        return sum(s.migrated for s in self.table_stats.values())

    @property
    def total_skipped(self) -> int:
        return sum(s.skipped for s in self.table_stats.values())

    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.table_stats.values())

    @property
    def total_duration(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    def summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            "  迁移结果汇总",
            "=" * 60,
            f"  模式: {'DRY-RUN' if self.dry_run else 'FULL MIGRATION'}",
            f"  批次大小: {self.batch_size}",
            f"  总耗时: {self.total_duration:.2f}s",
            f"  源记录总数: {self.total_source}",
            f"  成功迁移: {self.total_migrated}",
            f"  跳过(已存在): {self.total_skipped}",
            f"  失败: {self.total_failed}",
            "-" * 60,
        ]
        for name, stats in self.table_stats.items():
            lines.append(
                f"  {name}: {stats.migrated}/{stats.total_source} "
                f"(成功:{stats.migrated}, 跳过:{stats.skipped}, 失败:{stats.failed}) "
                f"耗时:{stats.duration:.2f}s"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


class ProgressTracker:
    """进度跟踪器，带ETA估算"""

    def __init__(self, total: int, label: str = "迁移"):
        self.total = total
        self.label = label
        self.current = 0
        self.start_time = time.time()
        self.last_report = 0.0
        self.report_interval = 1.0  # 最少1秒输出一次

    def update(self, count: int):
        self.current += count

    def report(self) -> Optional[str]:
        now = time.time()
        if now - self.last_report < self.report_interval and self.current < self.total:
            return None
        self.last_report = now

        elapsed = now - self.start_time
        if self.current > 0 and self.total > 0:
            rate = self.current / elapsed if elapsed > 0 else 0
            eta_seconds = (self.total - self.current) / rate if rate > 0 else 0
            eta_str = str(timedelta(seconds=int(eta_seconds)))
            percent = (self.current / self.total) * 100
            return (
                f"[{self.label}] {self.current}/{self.total} ({percent:.1f}%) "
                f"速度: {rate:.1f}条/s ETA: {eta_str}"
            )
        return f"[{self.label}] {self.current}/{self.total}"

    def final_report(self) -> str:
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        return (
            f"[{self.label}] 完成: {self.current}/{self.total} "
            f"耗时: {elapsed:.2f}s 速度: {rate:.1f}条/s"
        )


# ===== 工具函数 =====
def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """解析M8中的datetime字符串"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def convert_user_id(value: Any) -> Optional[str]:
    """将 user_id 从 Integer 转换为 String"""
    if value is None:
        return None
    return str(value)


def load_checkpoint() -> Dict:
    """加载断点续传检查点"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                cp = json.load(f)
            logger.info(f"加载检查点: {CHECKPOINT_FILE}")
            return cp
        except Exception as e:
            logger.warning(f"加载检查点失败: {e}，将从头开始")
    return {}


def save_checkpoint(checkpoint: Dict):
    """保存断点续传检查点"""
    try:
        checkpoint["last_updated"] = datetime.now().isoformat()
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存检查点失败: {e}")


def retry_with_backup(func, max_retries: int = 3, base_delay: float = 0.5):
    """指数退避重试装饰器"""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"操作失败 (第 {attempt + 1}/{max_retries} 次): {e}，"
                        f"{delay:.1f}s 后重试..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"操作失败，已达最大重试次数 ({max_retries}): {e}")
        raise last_exception
    return wrapper


# ===== 核心迁移逻辑 =====
def get_m8_count(conn: sqlite3.Connection, table_name: str) -> int:
    """获取M8表记录数"""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def fetch_m8_batch(
    conn: sqlite3.Connection,
    table_name: str,
    order_field: str,
    last_id: int,
    batch_size: int,
) -> List[Dict]:
    """分批从M8读取数据"""
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM {table_name} WHERE {order_field} > ? "
        f"ORDER BY {order_field} ASC LIMIT ?",
        (last_id, batch_size),
    )
    col_names = [d[0] for d in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def check_duplicate(
    db: Session, model, biz_id_field: str, biz_id_value: Any) -> bool:
    """幂等性检查：业务ID是否已存在"""
    existing = db.query(model).filter(
        getattr(model, biz_id_field) == biz_id_value).first()
    return existing is not None


def map_row_to_model(row: Dict, field_mapping: Dict) -> Dict:
    """将M8行数据映射为M9模型字段"""
    result = {}
    for m8_field, m9_field in field_mapping.items():
        if m9_field is None:
            continue
        if m8_field not in row:
            continue

        value = row[m8_field]

        # user_id 类型转换 Integer -> String
        if m9_field == "user_id":
            value = convert_user_id(value)

        # 日期时间字段转换
        if m9_field in ("created_at", "updated_at", "committed_at"):
            value = parse_datetime(value)

        result[m9_field] = value

    return result


def migrate_table(
    conn_m8: sqlite3.Connection,
    db: Session,
    table_config: Dict,
    batch_size: int,
    dry_run: bool,
    checkpoint: Dict,
    stats: MigrationStats,
) -> TableMigrationStats:
    """迁移单张表"""
    m8_table = table_config["m8_table"]
    m9_model = table_config["m9_model"]
    biz_id_field = table_config["biz_id_field"]
    order_field = table_config["order_field"]
    field_mapping = table_config["field_mapping"]

    table_stats = TableMigrationStats(table_name=m8_table)
    table_stats.start_time = time.time()

    # 读取总数
    table_stats.total_source = get_m8_count(conn_m8, m8_table)
    logger.info(f"开始迁移 {m8_table}，共 {table_stats.total_source} 条记录")

    # 断点续传：获取上次最后处理的ID
    last_id = checkpoint.get(m8_table, {}).get("last_id", 0)
    if last_id > 0:
        logger.info(f"  从断点恢复，上次处理到 ID={last_id}")

    progress = ProgressTracker(table_stats.total_source, label=m8_table)

    while True:
        # 读取一批数据
        batch = fetch_m8_batch(conn_m8, m8_table, order_field, last_id, batch_size)
        if not batch:
            break

        migrated_in_batch = 0
        skipped_in_batch = 0
        failed_in_batch = 0

        for row in batch:
            last_id = row[order_field]

            try:
                # 幂等性检查
                biz_id_value = row.get(biz_id_field)
                if biz_id_value is not None and not dry_run:
                    if check_duplicate(db, m9_model, biz_id_field, biz_id_value):
                        table_stats.skipped += 1
                        skipped_in_batch += 1
                        continue

                # 字段映射
                mapped_data = map_row_to_model(row, field_mapping)

                if dry_run:
                    # dry-run 模式只统计不写入
                    table_stats.migrated += 1
                    migrated_in_batch += 1
                else:
                    # 实际写入M9
                    @retry_with_backup
                    def insert_record():
                        instance = m9_model(**mapped_data)
                        db.add(instance)
                        db.flush()
                        return instance

                    insert_record()
                    table_stats.migrated += 1
                    migrated_in_batch += 1

            except Exception as e:
                table_stats.failed += 1
                failed_in_batch += 1
                error_msg = f"ID={row.get(order_field)}: {str(e)}"
                table_stats.errors.append(error_msg)
                logger.error(f"  迁移失败 {m8_table} {error_msg}")
                db.rollback()  # 回滚单条失败，继续下一条
                continue

        # 批量提交
        if not dry_run:
            db.commit()

        # 保存检查点
        if not dry_run:
            if m8_table not in checkpoint:
                checkpoint[m8_table] = {}
            checkpoint[m8_table]["last_id"] = last_id
            checkpoint[m8_table]["migrated"] = table_stats.migrated
            save_checkpoint(checkpoint)

        progress.update(len(batch))
        report = progress.report()
        if report:
            logger.info(report)

    table_stats.end_time = time.time()
    stats.table_stats[m8_table] = table_stats

    logger.info(progress.final_report())
    logger.info(
        f"  {m8_table} 迁移完成: 成功={table_stats.migrated}, "
        f"跳过={table_stats.skipped}, 失败={table_stats.failed}"
    )

    return table_stats


def run_migration(
    full: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    batch_size: int = 1000,
):
    """执行迁移主流程"""
    stats = MigrationStats(batch_size=batch_size, dry_run=dry_run)
    stats.start_time = time.time()

    logger.info("=" * 60)
    logger.info("  P1b 批次迁移：M8 work_* -> M9 work_*")
    logger.info(f"  模式: {'DRY-RUN' if dry_run else 'FULL MIGRATION'}")
    logger.info(f"  批次大小: {batch_size}")
    logger.info(f"  断点续传: {'开启' if resume else '关闭'}")
    logger.info("=" * 60)

    # 初始化M9数据库
    init_db()
    logger.info("M9 数据库初始化完成")

    # 连接M8数据库
    if not os.path.exists(M8_DB_PATH):
        logger.error(f"M8 数据库不存在: {M8_DB_PATH}")
        sys.exit(1)

    conn_m8 = sqlite3.connect(M8_DB_PATH)
    logger.info(f"M8 数据库连接成功: {M8_DB_PATH}")

    # 加载检查点
    checkpoint = {}
    if resume:
        checkpoint = load_checkpoint()
    elif os.path.exists(CHECKPOINT_FILE) and not full:
        logger.info(
            "检测到检查点文件存在。使用 --resume 继续迁移，或 --full 忽略检查点从头开始"
        )

    db = SessionLocal()

    try:
        for table_config in TABLE_CONFIGS:
            migrate_table(
            conn_m8=conn_m8,
            db=db,
            table_config=table_config,
            batch_size=batch_size,
            dry_run=dry_run,
            checkpoint=checkpoint,
            stats=stats,
        )
    except KeyboardInterrupt:
        logger.warning("迁移被用户中断，检查点已保存")
    except Exception as e:
        logger.error(f"迁移过程中发生严重错误: {e}")
        raise
    finally:
        db.close()
        conn_m8.close()

    stats.end_time = time.time()

    # 输出汇总
    logger.info(stats.summary())

    # 清理检查点（全量迁移成功后删除
    if not dry_run and stats.total_failed == 0:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            logger.info(f"检查点文件已清理: {CHECKPOINT_FILE}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="P1b 批次数据迁移：M8 work_* 表 -> M9 work_* 表"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量迁移模式（忽略检查点，从头开始）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，只统计不写入",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从检查点断点续传",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每批迁移的记录数（默认1000）",
    )

    args = parser.parse_args()

    stats = run_migration(
        full=args.full,
        dry_run=args.dry_run,
        resume=args.resume,
        batch_size=args.batch_size,
    )

    # 返回码：有失败则返回非零
    sys.exit(1 if stats.total_failed > 0 else 0)


if __name__ == "__main__":
    main()
