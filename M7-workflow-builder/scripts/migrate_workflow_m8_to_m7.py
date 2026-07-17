"""P2d 工作流引擎数据迁移脚本 - M8 → M7.

迁移范围:
  - workflow_definitions (工作流定义表)
  - workflow_runs (工作流运行记录表)

特性:
  - MigrationStats 数据类统计迁移结果
  - 分批迁移 (batch_size=1000)
  - 幂等性检查 (业务ID去重)
  - 重试机制 (指数退避, max_retries=3)
  - 断点续传 (checkpoint JSON文件)
  - ProgressTracker 进度报告 + ETA
  - 详细日志输出
  - 支持 --dry-run, --resume, --batch-size 参数

用法:
  python scripts/migrate_workflow_m8_to_m7.py --dry-run
  python scripts/migrate_workflow_m8_to_m7.py
  python scripts/migrate_workflow_m8_to_m7.py --resume --batch-size 500
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import sqlite3

# 确保能 import M7 项目模块
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.orm import Session

from src.db import init_db, get_session
from src.models_db import WorkflowDefinition, WorkflowRunRecord


# ============================================================
# 日志配置
# ============================================================
def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    logger = logging.getLogger("workflow_migration")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# ============================================================
# 数据类
# ============================================================
@dataclass
class TableMigrationStats:
    """单表迁移统计."""
    table_name: str
    source_total: int = 0
    migrated: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    @property
    def success_rate(self) -> str:
        total = self.migrated + self.failed
        if total == 0:
            return "N/A"
        return f"{self.migrated / total * 100:.1f}%"


@dataclass
class MigrationStats:
    """整体迁移统计."""
    migration_id: str = ""
    dry_run: bool = False
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    tables: Dict[str, TableMigrationStats] = field(default_factory=dict)

    @property
    def total_source(self) -> int:
        return sum(t.source_total for t in self.tables.values())

    @property
    def total_migrated(self) -> int:
        return sum(t.migrated for t in self.tables.values())

    @property
    def total_failed(self) -> int:
        return sum(t.failed for t in self.tables.values())

    @property
    def total_skipped(self) -> int:
        return sum(t.skipped_duplicate for t in self.tables.values())

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 3)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "migration_id": self.migration_id,
            "dry_run": self.dry_run,
            "duration_seconds": self.duration_seconds,
            "total_source": self.total_source,
            "total_migrated": self.total_migrated,
            "total_failed": self.total_failed,
            "total_skipped": self.total_skipped,
            "tables": {
                name: {
                    "source_total": t.source_total,
                    "migrated": t.migrated,
                    "skipped_duplicate": t.skipped_duplicate,
                    "failed": t.failed,
                    "success_rate": t.success_rate,
                    "duration_seconds": t.duration_seconds,
                    "errors": t.errors[:10],  # 只保留前10条错误
                }
                for name, t in self.tables.items()
            },
        }


# ============================================================
# 进度追踪
# ============================================================
class ProgressTracker:
    """迁移进度追踪器 + ETA 估算."""

    def __init__(self, total: int, logger: logging.Logger, label: str = "迁移"):
        self.total = total
        self.logger = logger
        self.label = label
        self.done = 0
        self.start_time = time.time()
        self.last_report = 0.0
        self.report_interval = 5.0  # 每5秒至少报告一次

    def update(self, n: int = 1) -> None:
        self.done += n
        now = time.time()
        if now - self.last_report >= self.report_interval or self.done >= self.total:
            self._report()
            self.last_report = now

    def _report(self) -> None:
        if self.total == 0:
            self.logger.info(f"[{self.label}] 0/0 (无数据)")
            return
        elapsed = time.time() - self.start_time
        pct = self.done / self.total * 100
        if self.done > 0:
            eta = elapsed / self.done * (self.total - self.done)
            eta_str = f", ETA: {eta:.0f}s"
        else:
            eta_str = ""
        rate = self.done / elapsed if elapsed > 0 else 0
        self.logger.info(
            f"[{self.label}] {self.done}/{self.total} ({pct:.1f}%) "
            f"速度: {rate:.1f} 条/秒{eta_str}"
        )


# ============================================================
# 重试装饰器
# ============================================================
def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """指数退避重试装饰器."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        time.sleep(delay)
                    else:
                        raise last_exc
            return None
        return wrapper
    return decorator


# ============================================================
# Checkpoint 管理
# ============================================================
class CheckpointManager:
    """断点续传 checkpoint 管理."""

    def __init__(self, checkpoint_path: Path, logger: logging.Logger):
        self.path = checkpoint_path
        self.logger = logger
        self.data: Dict[str, Any] = {}

    def load(self) -> bool:
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                self.logger.info(f"加载 checkpoint: {self.path}")
                return True
            except Exception as e:
                self.logger.warning(f"加载 checkpoint 失败: {e}, 从头开始")
                self.data = {}
        return False

    def save(self, table_name: str, last_id: str, processed: int) -> None:
        self.data.setdefault("tables", {})
        self.data["tables"][table_name] = {
            "last_id": last_id,
            "processed": processed,
            "updated_at": datetime.now().isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_last_id(self, table_name: str) -> Optional[str]:
        return self.data.get("tables", {}).get(table_name, {}).get("last_id")

    def get_processed(self, table_name: str) -> int:
        return self.data.get("tables", {}).get(table_name, {}).get("processed", 0)

    def mark_table_complete(self, table_name: str) -> None:
        self.data.setdefault("tables", {})
        self.data["tables"].setdefault(table_name, {})
        self.data["tables"][table_name]["complete"] = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_table_complete(self, table_name: str) -> bool:
        return self.data.get("tables", {}).get(table_name, {}).get("complete", False)


# ============================================================
# 工具函数
# ============================================================
def _parse_datetime(val: Optional[str]) -> Optional[datetime]:
    """多格式解析时间字符串."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _parse_json(val: Optional[str]) -> Any:
    """解析 JSON 字段."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        if not val.strip():
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _safe_str(val: Any, default: str = "") -> str:
    """安全字符串转换."""
    if val is None:
        return default
    return str(val)


# ============================================================
# 字段映射配置
# ============================================================
FIELD_MAPPING = {
    "workflow_definitions": {
        # M8 字段 → M7 字段映射
        "id": "id",
        "name": "name",
        "description": "description",
        "category": "category",
        # icon: M8 有，M7 无 → 存入 tags 或忽略（此处忽略，M7无对应字段）
        "blocks": "blocks",
        "status": "status",
        "created_at": "created_at",
        "updated_at": "updated_at",
        # user_id (M8 INTEGER) → created_by (M7 String)
        "user_id": "created_by",
        # M7 新增字段（设置默认值）
        "_defaults": {
            "connections": [],
            "variables": [],
            "trigger": {},
            "run_count": 0,
            "tags": [],
        }
    },
    "workflow_runs": {
        "id": "id",
        "workflow_id": "workflow_id",
        "workflow_name": "workflow_name",
        "status": "status",
        "inputs": "inputs",
        "outputs": "outputs",
        # error_message (M8 TEXT) → error (M7 Text)
        "error_message": "error",
        "started_at": "started_at",
        "finished_at": "finished_at",
        "duration_ms": "duration_ms",
        # user_id (M8 INTEGER) → triggered_by 前缀标记 (M7 String)
        "user_id": "_user_to_triggered_by",
        # M7 新增字段（设置默认值）
        "_defaults": {
            "steps": [],
            "triggered_by": "m8_migrated",
        }
    },
}


# ============================================================
# 数据转换函数
# ============================================================
def convert_workflow_definition(m8_row: Dict[str, Any]) -> Dict[str, Any]:
    """将 M8 workflow_definitions 行转换为 M7 格式."""
    mapping = FIELD_MAPPING["workflow_definitions"]
    defaults = mapping["_defaults"]

    result = {}
    for m8_field, m7_field in mapping.items():
        if m8_field.startswith("_"):
            continue
        if m8_field in m8_row:
            val = m8_row[m8_field]
            # 特殊字段处理
            if m8_field == "blocks":
                val = _parse_json(val) or []
            elif m8_field in ("created_at", "updated_at"):
                val = _parse_datetime(val)
            elif m8_field == "user_id":
                # M8 INTEGER user_id → M7 String created_by
                val = _safe_str(val, default="")

            result[m7_field] = val

    # 应用默认值（M7有但M8无的字段）
    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val

    return result


def convert_workflow_run(m8_row: Dict[str, Any]) -> Dict[str, Any]:
    """将 M8 workflow_runs 行转换为 M7 格式."""
    mapping = FIELD_MAPPING["workflow_runs"]
    defaults = mapping["_defaults"]

    result = {}
    for m8_field, m7_field in mapping.items():
        if m8_field.startswith("_"):
            continue
        if m8_field in m8_row:
            val = m8_row[m8_field]

            if m7_field == "_user_to_triggered_by":
                # user_id → triggered_by 标记
                user_str = _safe_str(val, default="")
                if user_str:
                    result["triggered_by"] = f"m8_user_{user_str}"
                continue

            # 特殊字段处理
            if m8_field in ("inputs", "outputs"):
                val = _parse_json(val) or {}
            elif m8_field in ("started_at", "finished_at"):
                val = _parse_datetime(val)
            elif m8_field == "duration_ms":
                val = int(val) if val else 0
            elif m8_field == "error_message":
                val = _safe_str(val, default="")
                result["error"] = val
                continue

            result[m7_field] = val

    # 应用默认值（M7有但M8无的字段）
    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val

    return result


# ============================================================
# M8 数据读取
# ============================================================
class M8Reader:
    """M8 数据库读取器 (使用原生 sqlite3 读取源数据)."""

    def __init__(self, db_path: str, logger: logging.Logger):
        self.db_path = db_path
        self.logger = logger
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.logger.info(f"M8 数据库连接成功: {self.db_path}")

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.logger.debug("M8 数据库连接已关闭")

    def count_table(self, table_name: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]

    def fetch_batch(
        self,
        table_name: str,
        last_id: Optional[str] = None,
        batch_size: int = 1000,
    ) -> List[Dict[str, Any]]:
        """按 id 排序分批读取."""
        cursor = self.conn.cursor()
        if last_id:
            cursor.execute(
                f"SELECT * FROM {table_name} WHERE id > ? ORDER BY id LIMIT ?",
                (last_id, batch_size),
            )
        else:
            cursor.execute(
                f"SELECT * FROM {table_name} ORDER BY id LIMIT ?",
                (batch_size,),
            )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


# ============================================================
# 迁移执行器
# ============================================================
class WorkflowMigrator:
    """工作流数据迁移执行器."""

    def __init__(
        self,
        m8_db_path: str,
        m7_data_dir: Optional[str],
        batch_size: int = 1000,
        max_retries: int = 3,
        dry_run: bool = False,
        checkpoint_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.m8_db_path = m8_db_path
        self.m7_data_dir = m7_data_dir
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.dry_run = dry_run
        self.logger = logger or logging.getLogger("workflow_migration")

        self.stats = MigrationStats(
            migration_id=f"p2d_workflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            dry_run=dry_run,
        )

        self.checkpoint = CheckpointManager(
            checkpoint_path or Path("data/migration_checkpoints/p2d_workflow_checkpoint.json"),
            self.logger,
        )

        self.m8_reader = M8Reader(m8_db_path, self.logger)
        self._m7_session: Optional[Session] = None

    @property
    def m7_session(self) -> Session:
        if self._m7_session is None:
            init_db(self.m7_data_dir)
            self._m7_session = get_session()
        return self._m7_session

    def run(self, resume: bool = False) -> MigrationStats:
        """执行完整迁移."""
        self.stats.start_time = time.time()
        self.logger.info("=" * 60)
        self.logger.info(f"P2d 工作流引擎数据迁移开始")
        self.logger.info(f"  模式: {'DRY-RUN' if self.dry_run else '实际迁移'}")
        self.logger.info(f"  M8 数据库: {self.m8_db_path}")
        self.logger.info(f"  M7 数据目录: {self.m7_data_dir or '默认 (~/.yunxi)'}")
        self.logger.info(f"  批次大小: {self.batch_size}")
        self.logger.info(f"  最大重试: {self.max_retries}")
        self.logger.info("=" * 60)

        if resume:
            self.checkpoint.load()

        try:
            self.m8_reader.connect()

            # 迁移各表
            self._migrate_table(
                "workflow_definitions",
                WorkflowDefinition,
                convert_workflow_definition,
            )

            self._migrate_table(
                "workflow_runs",
                WorkflowRunRecord,
                convert_workflow_run,
            )

        except Exception as e:
            self.logger.error(f"迁移执行异常: {e}", exc_info=True)
        finally:
            self.m8_reader.close()
            if self._m7_session:
                self._m7_session.close()

        self.stats.end_time = time.time()
        self._print_summary()
        return self.stats

    def _migrate_table(
        self,
        table_name: str,
        model_class: Any,
        converter_func,
    ) -> None:
        """迁移单张表."""
        table_stats = TableMigrationStats(table_name=table_name)
        self.stats.tables[table_name] = table_stats
        table_stats.start_time = time.time()

        self.logger.info(f"\n{'─' * 50}")
        self.logger.info(f"迁移表: {table_name}")
        self.logger.info(f"{'─' * 50}")

        # 检查是否已完成（断点续传）
        if self.checkpoint.is_table_complete(table_name):
            source_total = self.m8_reader.count_table(table_name)
            table_stats.source_total = source_total
            self.logger.info(f"  [跳过] checkpoint 标记已完成，跳过该表")
            table_stats.end_time = time.time()
            return

        # 获取源数据总数
        source_total = self.m8_reader.count_table(table_name)
        table_stats.source_total = source_total
        self.logger.info(f"  源数据总数: {source_total}")

        if source_total == 0:
            self.logger.info(f"  [跳过] 源表无数据")
            self.checkpoint.mark_table_complete(table_name)
            table_stats.end_time = time.time()
            return

        # 进度追踪
        progress = ProgressTracker(source_total, self.logger, label=table_name)

        # 起始位置
        last_id = self.checkpoint.get_last_id(table_name)
        processed_before = self.checkpoint.get_processed(table_name)
        if last_id:
            self.logger.info(f"  断点续传: 从 id > {last_id} 继续 (已处理 {processed_before} 条)")
            progress.done = processed_before

        # 分批迁移
        while True:
            batch = self.m8_reader.fetch_batch(table_name, last_id, self.batch_size)
            if not batch:
                break

            migrated_in_batch = 0
            for row in batch:
                try:
                    result = self._migrate_single_row(
                        table_name, model_class, row, converter_func
                    )
                    if result == "migrated":
                        table_stats.migrated += 1
                        migrated_in_batch += 1
                    elif result == "skipped":
                        table_stats.skipped_duplicate += 1
                except Exception as e:
                    table_stats.failed += 1
                    err_msg = f"id={row.get('id')}: {str(e)}"
                    table_stats.errors.append(err_msg)
                    self.logger.error(f"  [失败] {err_msg}")

                progress.update(1)
                last_id = row["id"]

            # 保存 checkpoint
            if not self.dry_run:
                self.checkpoint.save(
                    table_name, last_id, progress.done
                )

        # 标记表完成
        self.checkpoint.mark_table_complete(table_name)
        table_stats.end_time = time.time()

        self.logger.info(
            f"  完成: 迁移 {table_stats.migrated} 条, "
            f"跳过重复 {table_stats.skipped_duplicate} 条, "
            f"失败 {table_stats.failed} 条, "
            f"耗时 {table_stats.duration_seconds}s"
        )

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def _migrate_single_row(
        self,
        table_name: str,
        model_class: Any,
        row: Dict[str, Any],
        converter_func,
    ) -> str:
        """迁移单行数据. 返回 'migrated' / 'skipped'."""
        row_id = row["id"]

        # 幂等性检查
        existing = self.m7_session.query(model_class).filter(
            model_class.id == row_id
        ).first()
        if existing:
            self.logger.debug(f"  [跳过] {table_name} id={row_id} 已存在")
            return "skipped"

        # 数据转换
        converted = converter_func(row)

        if self.dry_run:
            self.logger.debug(f"  [DRY-RUN] {table_name} id={row_id}")
            return "migrated"

        # 写入 M7
        obj = model_class(**converted)
        self.m7_session.add(obj)
        self.m7_session.commit()

        return "migrated"

    def _print_summary(self) -> None:
        """打印迁移总结."""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("迁移统计汇总")
        self.logger.info("=" * 60)

        for name, t in self.stats.tables.items():
            self.logger.info(f"\n  【{name}】")
            self.logger.info(f"    源数据总数:   {t.source_total}")
            self.logger.info(f"    成功迁移:     {t.migrated}")
            self.logger.info(f"    跳过(重复):   {t.skipped_duplicate}")
            self.logger.info(f"    失败:         {t.failed}")
            self.logger.info(f"    成功率:       {t.success_rate}")
            self.logger.info(f"    耗时:         {t.duration_seconds}s")

        self.logger.info(f"\n  总计: 源 {self.stats.total_source} 条, "
                         f"迁移 {self.stats.total_migrated} 条, "
                         f"跳过 {self.stats.total_skipped} 条, "
                         f"失败 {self.stats.total_failed} 条")
        self.logger.info(f"  总耗时: {self.stats.duration_seconds}s")
        self.logger.info("=" * 60)


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="P2d 工作流引擎数据迁移 - M8 → M7"
    )
    parser.add_argument(
        "--m8-db",
        default=r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend\data\m8.db",
        help="M8 数据库路径",
    )
    parser.add_argument(
        "--m7-data-dir",
        default=None,
        help="M7 数据目录（默认 ~/.yunxi）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="每批迁移记录数 (默认 1000)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="最大重试次数 (默认 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，不实际写入数据",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从 checkpoint 断点续传",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="checkpoint 文件路径",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="日志文件路径",
    )

    args = parser.parse_args()

    # 日志
    log_file = Path(args.log_file) if args.log_file else None
    logger = setup_logging(log_file)

    # checkpoint 路径
    checkpoint_path = None
    if args.checkpoint:
        checkpoint_path = Path(args.checkpoint)
    else:
        checkpoint_path = PROJECT_ROOT / "data" / "migration_checkpoints" / "p2d_workflow_checkpoint.json"

    # 执行迁移
    migrator = WorkflowMigrator(
        m8_db_path=args.m8_db,
        m7_data_dir=args.m7_data_dir,
        batch_size=args.batch_size,
        max_retries=args.max_retries,
        dry_run=args.dry_run,
        checkpoint_path=checkpoint_path,
        logger=logger,
    )

    stats = migrator.run(resume=args.resume)

    # 输出 JSON 统计
    report_path = checkpoint_path.parent / f"p2d_migration_report_{stats.migration_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(stats.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"\n迁移报告已保存: {report_path}")

    # 退出码
    sys.exit(1 if stats.total_failed > 0 else 0)


if __name__ == "__main__":
    main()
