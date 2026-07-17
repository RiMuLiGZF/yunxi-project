"""P2b批次数据迁移：M8 情绪陪伴 + 形象工坊 -> M4.

迁移范围:
  情绪陪伴 (5表):
    - mood_diary (心情日记)
    - relax_contents (放松内容库)
    - relax_sessions (放松训练记录)
    - sleep_contents (助眠内容库)
    - sleep_records (睡眠记录)
  形象工坊 (2表):
    - appearance_configs (用户形象配置)
    - appearance_snapshots (形象快照)

特性:
  - MigrationStats 数据类统计迁移结果
  - 分批迁移 (batch_size=1000)
  - 幂等性检查 (业务ID/组合键去重)
  - 重试机制 (指数退避, max_retries=3)
  - 断点续传 (checkpoint JSON文件)
  - ProgressTracker 进度报告 + ETA
  - 详细的日志输出
  - 支持 --dry-run, --resume, --batch-size 参数

用法:
  python scripts/migrate_emotion_appearance_m8_to_m4.py --dry-run
  python scripts/migrate_emotion_appearance_m8_to_m4.py
  python scripts/migrate_emotion_appearance_m8_to_m4.py --resume
  python scripts/migrate_emotion_appearance_m8_to_m4.py --batch-size 500
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import sqlite3
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# 路径配置: 将项目根目录加入 sys.path 以便导入 src 包
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.db.base import Base, get_session, init_db  # noqa: E402
from src.models.db.emotion import (  # noqa: E402
    MoodDiaryDB,
    RelaxContentDB,
    RelaxSessionDB,
    SleepContentDB,
    SleepRecordDB,
)
from src.models.db.appearance import (  # noqa: E402
    AppearanceConfigDB,
    AppearanceSnapshotDB,
)

# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------
M8_DB_PATH = r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend\data\m8.db"
M4_DB_PATH = str(PROJECT_ROOT / "data" / "m4.db")
CHECKPOINT_DIR = PROJECT_ROOT / "data" / "migration_checkpoints"
CHECKPOINT_FILE = CHECKPOINT_DIR / "p2b_emotion_appearance_checkpoint.json"
DEFAULT_BATCH_SIZE = 1000
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # 秒


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def parse_datetime(value: Any) -> datetime | None:
    """将字符串或其他类型转换为 datetime 对象.

    支持多种格式: ISO格式, 'YYYY-MM-DD HH:MM:SS', 带微秒等.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        # 尝试多种格式
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        logger.warning(f"无法解析日期时间: {value!r}")
        return None
    return None


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("p2b_migration")


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class TableMigrationStat:
    """单表迁移统计."""
    table_name: str
    total_source: int = 0
    migrated: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_source == 0:
            return 100.0
        return (self.migrated + self.skipped_duplicate) / self.total_source * 100


@dataclass
class MigrationStats:
    """整体迁移统计."""
    batch: str = "P2b"
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    tables: dict[str, TableMigrationStat] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def total_migrated(self) -> int:
        return sum(t.migrated for t in self.tables.values())

    @property
    def total_skipped(self) -> int:
        return sum(t.skipped_duplicate for t in self.tables.values())

    @property
    def total_failed(self) -> int:
        return sum(t.failed for t in self.tables.values())

    @property
    def total_source(self) -> int:
        return sum(t.total_source for t in self.tables.values())

    @property
    def duration(self) -> float:
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    def summary(self) -> str:
        lines = [
            "=" * 70,
            f"P2b 迁移统计 {'(DRY-RUN)' if self.dry_run else ''}",
            "=" * 70,
            f"  开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  结束时间: {(self.end_time or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}",
            f"  耗时: {self.duration:.2f} 秒",
            f"  源数据总数: {self.total_source}",
            f"  成功迁移: {self.total_migrated}",
            f"  跳过(重复): {self.total_skipped}",
            f"  失败: {self.total_failed}",
            "-" * 70,
            "  各表详情:",
        ]
        for name, stat in self.tables.items():
            lines.append(
                f"    {name:<25s} 源:{stat.total_source:>4d}  "
                f"迁移:{stat.migrated:>4d}  "
                f"跳过:{stat.skipped_duplicate:>4d}  "
                f"失败:{stat.failed:>3d}  "
                f"成功率:{stat.success_rate:>5.1f}%"
            )
        lines.append("=" * 70)
        return "\n".join(lines)


# ===========================================================================
# ProgressTracker - 进度跟踪
# ===========================================================================

class ProgressTracker:
    """进度跟踪器，带 ETA 估算."""

    def __init__(self, total: int, description: str = "迁移"):
        self.total = total
        self.description = description
        self.current = 0
        self.start_time = time.time()
        self.last_report = 0.0
        self.report_interval = 5.0  # 秒

    def update(self, n: int = 1) -> None:
        self.current += n
        now = time.time()
        if now - self.last_report >= self.report_interval or self.current == self.total:
            self._report()
            self.last_report = now

    def _report(self) -> None:
        if self.total == 0:
            pct = 100.0
        else:
            pct = self.current / self.total * 100
        elapsed = time.time() - self.start_time
        if self.current > 0 and self.total > 0:
            eta = elapsed / self.current * (self.total - self.current)
            eta_str = f"ETA: {eta:.0f}s"
        else:
            eta_str = "ETA: --"
        bar_len = 30
        filled = int(bar_len * self.current / max(self.total, 1))
        bar = "█" * filled + "░" * (bar_len - filled)
        logger.info(
            f"{self.description}: [{bar}] {self.current}/{self.total} "
            f"({pct:.1f}%) {eta_str}"
        )


# ===========================================================================
# Checkpoint 管理 - 断点续传
# ===========================================================================

class CheckpointManager:
    """断点续传检查点管理."""

    def __init__(self, checkpoint_path: Path):
        self.checkpoint_path = checkpoint_path
        self.data: dict[str, Any] = {}

    def load(self) -> bool:
        """加载检查点，返回是否成功."""
        if not self.checkpoint_path.exists():
            return False
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            logger.info(f"加载检查点: {self.checkpoint_path}")
            return True
        except Exception as e:
            logger.warning(f"加载检查点失败: {e}")
            return False

    def save(self, table_name: str, last_offset: int, stats: dict) -> None:
        """保存检查点."""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.data["last_table"] = table_name
        self.data["last_offset"] = last_offset
        self.data["updated_at"] = datetime.now().isoformat()
        if "tables" not in self.data:
            self.data["tables"] = {}
        self.data["tables"][table_name] = {
            "last_offset": last_offset,
            "stats": stats,
        }
        try:
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存检查点失败: {e}")

    def get_table_offset(self, table_name: str) -> int:
        """获取某表的上次偏移量."""
        return self.data.get("tables", {}).get(table_name, {}).get("last_offset", 0)

    def mark_complete(self) -> None:
        """标记迁移完成."""
        self.data["status"] = "completed"
        self.data["completed_at"] = datetime.now().isoformat()
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_completed(self) -> bool:
        return self.data.get("status") == "completed"


# ===========================================================================
# 重试机制
# ===========================================================================

def retry_with_backoff(
    func: Callable,
    max_retries: int = MAX_RETRIES,
    base_delay: float = RETRY_BASE_DELAY,
) -> Any:
    """带指数退避的重试机制."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"操作失败 (第{attempt + 1}/{max_retries + 1}次尝试): {e} "
                    f"等待 {delay:.1f}s 后重试..."
                )
                time.sleep(delay)
            else:
                logger.error(f"操作失败，已达最大重试次数 ({max_retries + 1}次): {e}")
    raise last_exc  # type: ignore[misc]


# ===========================================================================
# 表迁移配置
# ===========================================================================

@dataclass
class TableMigrationConfig:
    """单表迁移配置."""
    m8_table: str
    m4_model: type
    biz_id_field: str | None  # M8中的业务ID字段名，None表示用组合键
    dedup_fields: list[str]  # 幂等性检查字段列表（M4模型字段名）
    field_mapping: dict[str, str]  # M8字段名 -> M4字段名
    has_user_id: bool = True  # 是否有 user_id 字段（用于用户维度过滤）
    transforms: dict[str, Callable[[Any], Any]] | None = None  # 字段转换函数


# 表迁移配置定义
TABLE_CONFIGS: list[TableMigrationConfig] = [
    # ---------- 情绪陪伴 ----------
    TableMigrationConfig(
        m8_table="mood_diary",
        m4_model=MoodDiaryDB,
        biz_id_field=None,  # 无业务ID，用组合键
        dedup_fields=["user_id", "date", "mood"],
        field_mapping={
            "mood": "mood",
            "content": "content",
            "tags": "tags",
            "date": "date",
            "user_id": "user_id",
            "created_at": "created_at",
        },
        has_user_id=True,
        transforms={
            "user_id": lambda v: str(v) if v is not None else "default",
            "tags": lambda v: json.loads(v) if isinstance(v, str) else (v or []),
            "created_at": parse_datetime,
        },
    ),
    TableMigrationConfig(
        m8_table="relax_contents",
        m4_model=RelaxContentDB,
        biz_id_field=None,  # 内容库表，用 title+category 去重
        dedup_fields=["title", "category"],
        field_mapping={
            "title": "title",
            "category": "category",
            "content_type": "content_type",
            "content_url": "content_url",
            "content_text": "content_text",
            "duration_seconds": "duration_seconds",
            "difficulty": "difficulty",
            "description": "description",
            "steps": "steps",
            "created_at": "created_at",
        },
        has_user_id=False,  # 全局内容库，无 user_id
        transforms={
            "steps": lambda v: json.loads(v) if isinstance(v, str) else (v or []),
            "created_at": parse_datetime,
        },
    ),
    TableMigrationConfig(
        m8_table="relax_sessions",
        m4_model=RelaxSessionDB,
        biz_id_field=None,  # 无业务ID，用组合键
        dedup_fields=["user_id", "content_id", "started_at"],
        field_mapping={
            "content_id": "content_id",
            "duration_seconds": "duration_seconds",
            "completed": "completed",
            "rating": "rating",
            "user_id": "user_id",
            "started_at": "started_at",
            "completed_at": "completed_at",
            "created_at": "created_at",
        },
        has_user_id=True,
        transforms={
            "user_id": lambda v: str(v) if v is not None else "default",
            "completed": lambda v: bool(v) if v is not None else False,
            "started_at": parse_datetime,
            "completed_at": parse_datetime,
            "created_at": parse_datetime,
        },
    ),
    TableMigrationConfig(
        m8_table="sleep_contents",
        m4_model=SleepContentDB,
        biz_id_field=None,  # 内容库表，用 title+category 去重
        dedup_fields=["title", "category"],
        field_mapping={
            "title": "title",
            "category": "category",
            "content_type": "content_type",
            "content_url": "content_url",
            "duration_seconds": "duration_seconds",
            "description": "description",
            "created_at": "created_at",
        },
        has_user_id=False,  # 全局内容库，无 user_id
        transforms={
            "created_at": parse_datetime,
        },
    ),
    TableMigrationConfig(
        m8_table="sleep_records",
        m4_model=SleepRecordDB,
        biz_id_field=None,  # 无业务ID，用组合键
        dedup_fields=["user_id", "date"],
        field_mapping={
            "date": "date",
            "sleep_duration": "sleep_duration",
            "sleep_quality": "sleep_quality",
            "sleep_score": "sleep_score",
            "bed_time": "bed_time",
            "wake_time": "wake_time",
            "note": "note",
            "user_id": "user_id",
            "created_at": "created_at",
        },
        has_user_id=True,
        transforms={
            "user_id": lambda v: str(v) if v is not None else "default",
            "created_at": parse_datetime,
        },
    ),
    # ---------- 形象工坊 ----------
    TableMigrationConfig(
        m8_table="appearance_configs",
        m4_model=AppearanceConfigDB,
        biz_id_field=None,  # 每个用户只有一份配置
        dedup_fields=["user_id"],
        field_mapping={
            "user_id": "user_id",
            "theme": "theme",
            "primary_color": "primary_color",
            "secondary_color": "secondary_color",
            "accent_color": "accent_color",
            "bg_color": "bg_color",
            "particle_count": "particle_count",
            "particle_speed": "particle_speed",
            "glow_intensity": "glow_intensity",
            "avatar_style": "avatar_style",
            "mood": "mood",
            "personality_tags": "personality_tags",
            "voice_type": "voice_type",
            "voice_speed": "voice_speed",
            "voice_pitch": "voice_pitch",
            "quality": "quality",
            "model": "model",
            "sync_enabled": "sync_enabled",
            "relationship_level": "relationship_level",
            "intimacy": "intimacy",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
        has_user_id=True,
        transforms={
            "user_id": lambda v: str(v) if v is not None else "default",
            "personality_tags": lambda v: json.loads(v) if isinstance(v, str) else (v or []),
            "sync_enabled": lambda v: bool(v) if v is not None else True,
            "created_at": parse_datetime,
            "updated_at": parse_datetime,
        },
    ),
    TableMigrationConfig(
        m8_table="appearance_snapshots",
        m4_model=AppearanceSnapshotDB,
        biz_id_field=None,  # 无业务ID，用组合键
        dedup_fields=["user_id", "name"],
        field_mapping={
            "user_id": "user_id",
            "name": "name",
            "theme": "theme",
            "mood": "mood",
            "snapshot_data": "snapshot_data",
            "created_at": "created_at",
        },
        has_user_id=True,
        transforms={
            "user_id": lambda v: str(v) if v is not None else "default",
            "snapshot_data": lambda v: json.loads(v) if isinstance(v, str) else (v or {}),
            "created_at": parse_datetime,
        },
    ),
]


# ===========================================================================
# 核心迁移逻辑
# ===========================================================================

class MigrationRunner:
    """P2b 迁移执行器."""

    def __init__(
        self,
        m8_db_path: str,
        m4_db_path: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        dry_run: bool = False,
        resume: bool = False,
    ):
        self.m8_db_path = m8_db_path
        self.m4_db_path = m4_db_path
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.resume = resume

        self.stats = MigrationStats(dry_run=dry_run)
        self.checkpoint = CheckpointManager(CHECKPOINT_FILE)

        # M8 连接 (sqlite3 直连)
        self.m8_conn: sqlite3.Connection | None = None
        # M4 session
        self.m4_session: Session | None = None

    def setup(self) -> None:
        """初始化数据库连接."""
        logger.info("初始化数据库连接...")

        # M8 数据库
        if not os.path.exists(self.m8_db_path):
            raise FileNotFoundError(f"M8 数据库不存在: {self.m8_db_path}")
        self.m8_conn = sqlite3.connect(self.m8_db_path)
        self.m8_conn.row_factory = sqlite3.Row
        logger.info(f"M8 数据库已连接: {self.m8_db_path}")

        # M4 数据库 - 确保表已创建
        init_db(db_path=self.m4_db_path)
        self.m4_session = get_session()
        logger.info(f"M4 数据库已连接: {self.m4_db_path}")

        # 加载检查点
        if self.resume:
            self.checkpoint.load()
            if self.checkpoint.is_completed():
                logger.warning("检查点显示迁移已完成，无需重复执行")

    def teardown(self) -> None:
        """清理资源."""
        if self.m8_conn:
            self.m8_conn.close()
        if self.m4_session:
            self.m4_session.close()

    def get_m8_count(self, table_name: str) -> int:
        """获取 M8 表记录数."""
        assert self.m8_conn is not None
        cursor = self.m8_conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]

    def fetch_m8_batch(self, table_name: str, offset: int, limit: int) -> list[sqlite3.Row]:
        """分批获取 M8 数据."""
        assert self.m8_conn is not None
        cursor = self.m8_conn.cursor()
        cursor.execute(
            f"SELECT * FROM {table_name} ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return cursor.fetchall()

    def check_duplicate(
        self,
        model_cls: type,
        dedup_fields: list[str],
        row_data: dict[str, Any],
    ) -> bool:
        """检查 M4 中是否已存在重复记录."""
        assert self.m4_session is not None
        try:
            query = self.m4_session.query(model_cls)
            for field in dedup_fields:
                value = row_data.get(field)
                if value is None:
                    # 如果去重字段值为 None，跳过（可能导致重复，但避免误判）
                    continue
                query = query.filter(getattr(model_cls, field) == value)
            return query.first() is not None
        except Exception:
            # 查询失败时回滚session，避免事务状态损坏
            try:
                self.m4_session.rollback()
            except Exception:
                pass
            raise

    def transform_row(
        self,
        row: sqlite3.Row,
        config: TableMigrationConfig,
    ) -> dict[str, Any]:
        """转换单行数据：字段映射 + 类型转换."""
        result: dict[str, Any] = {}
        for m8_field, m4_field in config.field_mapping.items():
            value = row[m8_field] if m8_field in row.keys() else None
            # 应用转换函数
            if config.transforms and m8_field in config.transforms:
                try:
                    value = config.transforms[m8_field](value)
                except Exception as e:
                    logger.warning(f"字段 {m8_field} 转换失败: {e}, 值: {value!r}")
                    # 使用默认值
                    value = None
            result[m4_field] = value
        return result

    def migrate_table(self, config: TableMigrationConfig) -> TableMigrationStat:
        """迁移单张表."""
        table_name = config.m8_table
        logger.info(f"\n{'=' * 60}")
        logger.info(f"开始迁移表: {table_name}")
        logger.info(f"{'=' * 60}")

        stat = TableMigrationStat(table_name=table_name)
        stat.total_source = self.get_m8_count(table_name)
        self.stats.tables[table_name] = stat

        if stat.total_source == 0:
            logger.info(f"表 {table_name} 无数据，跳过")
            return stat

        # 断点续传：获取上次偏移量
        start_offset = 0
        if self.resume:
            start_offset = self.checkpoint.get_table_offset(table_name)
            if start_offset > 0:
                logger.info(f"断点续传: 从偏移量 {start_offset} 继续 "
                            f"(已完成 {start_offset}/{stat.total_source})")

        progress = ProgressTracker(stat.total_source, description=table_name)
        if start_offset > 0:
            progress.current = start_offset

        offset = start_offset
        while offset < stat.total_source:
            batch = self.fetch_m8_batch(table_name, offset, self.batch_size)
            if not batch:
                break

            for row in batch:
                try:
                    # 转换数据
                    row_data = self.transform_row(row, config)

                    # 幂等性检查
                    is_dup = retry_with_backoff(
                        lambda: self.check_duplicate(
                            config.m4_model, config.dedup_fields, row_data
                        )
                    )
                    if is_dup:
                        stat.skipped_duplicate += 1
                        progress.update()
                        continue

                    # 实际插入（或 dry-run）
                    if not self.dry_run:
                        self._insert_record(config.m4_model, row_data)

                    stat.migrated += 1

                except Exception as e:
                    stat.failed += 1
                    error_msg = f"行 id={row['id'] if 'id' in row.keys() else '?'}: {e}"
                    stat.errors.append(error_msg)
                    logger.error(f"迁移失败 - {error_msg}")

                progress.update()

            offset += len(batch)

            # 保存检查点
            if not self.dry_run:
                self.checkpoint.save(
                    table_name, offset,
                    {
                        "migrated": stat.migrated,
                        "skipped": stat.skipped_duplicate,
                        "failed": stat.failed,
                    }
                )

            # 提交事务
            if not self.dry_run and self.m4_session:
                try:
                    self.m4_session.commit()
                except Exception as e:
                    self.m4_session.rollback()
                    logger.error(f"批次提交失败: {e}")
                    raise

        logger.info(
            f"表 {table_name} 迁移完成: "
            f"迁移 {stat.migrated}, 跳过 {stat.skipped_duplicate}, "
            f"失败 {stat.failed}"
        )
        return stat

    def _insert_record(self, model_cls: type, data: dict[str, Any]) -> None:
        """插入单条记录到 M4，带重试.

        注意：失败时会回滚session，确保后续操作不受影响。
        """
        assert self.m4_session is not None

        def _do_insert():
            record = model_cls(**data)
            self.m4_session.add(record)
            self.m4_session.flush()
            return record

        try:
            retry_with_backoff(_do_insert)
        except Exception:
            # 插入失败，回滚当前事务以恢复session可用状态
            try:
                self.m4_session.rollback()
            except Exception:
                pass
            raise

    def run(self) -> MigrationStats:
        """执行完整迁移."""
        try:
            self.setup()

            logger.info(f"\n{'#' * 70}")
            logger.info(f"# P2b 批次数据迁移开始 {'(DRY-RUN模式)' if self.dry_run else ''}")
            logger.info(f"# 迁移表数: {len(TABLE_CONFIGS)}")
            logger.info(f"# 批大小: {self.batch_size}")
            logger.info(f"{'#' * 70}\n")

            for config in TABLE_CONFIGS:
                self.migrate_table(config)

            self.stats.end_time = datetime.now()

            # 标记完成
            if not self.dry_run:
                self.checkpoint.mark_complete()

            # 输出统计
            logger.info("\n" + self.stats.summary())

            return self.stats

        except Exception as e:
            logger.error(f"迁移过程中发生致命错误: {e}", exc_info=True)
            raise
        finally:
            self.teardown()


# ===========================================================================
# 命令行入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="P2b批次数据迁移: M8情绪陪伴+形象工坊 -> M4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式，不实际写入数据",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从上次中断处继续迁移",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批处理记录数 (默认: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--m8-db",
        type=str,
        default=M8_DB_PATH,
        help="M8数据库路径",
    )
    parser.add_argument(
        "--m4-db",
        type=str,
        default=M4_DB_PATH,
        help="M4数据库路径",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = MigrationRunner(
        m8_db_path=args.m8_db,
        m4_db_path=args.m4_db,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        resume=args.resume,
    )

    try:
        stats = runner.run()
        if stats.total_failed > 0:
            logger.warning(f"迁移完成，但有 {stats.total_failed} 条记录失败")
            sys.exit(1)
        logger.info("迁移完成，无失败记录")
        sys.exit(0)
    except Exception as e:
        logger.error(f"迁移失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
