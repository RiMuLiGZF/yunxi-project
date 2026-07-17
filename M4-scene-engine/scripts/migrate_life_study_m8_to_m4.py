"""
M8 → M4 P1a 批次数据迁移脚本
============================

迁移范围：生活管理(9表) + 学业规划(7表)，共16张表。

迁移特性：
- MigrationStats 数据类统计迁移结果
- 分批迁移（batch_size=1000）
- 幂等性检查（业务ID去重）
- 重试机制（指数退避，max_retries=3）
- 断点续传（checkpoint JSON文件）
- ProgressTracker 进度报告 + ETA
- 详细的日志输出
- 支持 --full, --start-date, --dry-run, --resume, --batch-size 参数

使用方式：
    # dry-run 模式
    python migrate_life_study_m8_to_m4.py --dry-run

    # 全量迁移
    python migrate_life_study_m8_to_m4.py --full

    # 从指定日期开始迁移
    python migrate_life_study_m8_to_m4.py --start-date 2026-01-01

    # 断点续传
    python migrate_life_study_m8_to_m4.py --resume

    # 指定批次大小
    python migrate_life_study_m8_to_m4.py --full --batch-size 500
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 确保 src 目录也在路径中
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

M8_DB_PATH = PROJECT_ROOT.parent / "M8-control-tower" / "backend" / "data" / "m8.db"
M4_DB_PATH = PROJECT_ROOT / "data" / "m4.db"
CHECKPOINT_PATH = SCRIPT_DIR / "checkpoint_p1a_life_study.json"

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("p1a_migration")


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class TableMigrationStats:
    """单表迁移统计."""
    table_name: str
    total_m8: int = 0
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
    """整体迁移统计."""
    tables: Dict[str, TableMigrationStats] = field(default_factory=dict)
    total_m8: int = 0
    total_migrated: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    dry_run: bool = False

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    def add_table_stats(self, stats: TableMigrationStats) -> None:
        self.tables[stats.table_name] = stats
        self.total_m8 += stats.total_m8
        self.total_migrated += stats.migrated
        self.total_skipped += stats.skipped
        self.total_failed += stats.failed

    def summary(self) -> str:
        lines = [
            "",
            "=" * 70,
            "  P1a 迁移统计摘要",
            "=" * 70,
            f"  模式: {'DRY-RUN' if self.dry_run else 'FULL MIGRATION'}",
            f"  总耗时: {self.duration:.2f} 秒",
            f"  迁移表数: {len(self.tables)}",
            f"  M8 总记录数: {self.total_m8:,}",
            f"  成功迁移: {self.total_migrated:,}",
            f"  跳过(重复): {self.total_skipped:,}",
            f"  失败: {self.total_failed:,}",
            "-" * 70,
            f"  {'表名':<30} {'M8数量':>10} {'已迁移':>10} {'跳过':>8} {'失败':>8}",
            "  " + "-" * 68,
        ]
        for name, s in self.tables.items():
            lines.append(
                f"  {name:<30} {s.total_m8:>10,} {s.migrated:>10,} "
                f"{s.skipped:>8,} {s.failed:>8,}"
            )
        lines.append("=" * 70)
        return "\n".join(lines)


class ProgressTracker:
    """进度跟踪器，带ETA计算."""

    def __init__(self, total: int, label: str = "进度", update_interval: float = 1.0):
        self.total = total
        self.label = label
        self.update_interval = update_interval
        self.current = 0
        self.start_time = time.time()
        self.last_update = 0.0

    def update(self, n: int = 1) -> None:
        self.current += n
        now = time.time()
        if now - self.last_update >= self.update_interval or self.current >= self.total:
            self._print_progress()
            self.last_update = now

    def _print_progress(self) -> None:
        elapsed = max(time.time() - self.start_time, 0.001)  # 避免除以零
        if self.current > 0 and elapsed > 0:
            rate = self.current / elapsed
            eta = (self.total - self.current) / rate if rate > 0 else 0
            eta_str = f"{eta:.0f}s" if eta < 60 else f"{eta/60:.1f}min"
        else:
            rate = 0
            eta_str = "N/A"

        pct = (self.current / self.total * 100) if self.total > 0 else 0
        bar_len = 30
        filled = int(bar_len * self.current / self.total) if self.total > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)

        print(
            f"\r  {self.label}: [{bar}] {pct:5.1f}% "
            f"({self.current:,}/{self.total:,}) "
            f"速率: {rate:,.0f}/s ETA: {eta_str}",
            end="",
            flush=True,
        )
        if self.current >= self.total:
            print()  # newline on completion

    def finish(self) -> None:
        self.current = self.total
        self._print_progress()


# ---------------------------------------------------------------------------
# 表配置与字段映射
# ---------------------------------------------------------------------------

# 字段映射配置: M8字段 -> M4字段
# 特殊标记:
#   "$ignore" - M8有但M4没有的字段，跳过
#   "$default" - M4有但M8没有的字段，使用默认值
#   相同字段名直接映射

# 幂等键：用于去重检查的业务字段
TABLE_CONFIG: Dict[str, Dict[str, Any]] = {
    # ---------- 生活管理 9 表 ----------
    "life_schedules": {
        "m4_model": "LifeScheduleDB",
        "idempotent_key": "schedule_id",
        "m8_fields": [
            "schedule_id", "title", "description", "start_time", "end_time",
            "time_range", "date", "repeat_type", "category", "tag_color",
            "all_day", "priority", "status", "user_id", "created_at",
        ],
        "m4_fields": [
            "schedule_id", "title", "description", "start_time", "end_time",
            "time_range", "date", "repeat_type", "category", "tag_color",
            "all_day", "priority", "status", "user_id", "created_at",
        ],
        "field_map": {},  # 字段名完全一致
        "date_field": "date",
    },
    "life_todos": {
        "m4_model": "LifeTodoDB",
        "idempotent_key": "todo_id",
        "m8_fields": [
            "todo_id", "title", "description", "priority", "status",
            "progress", "due_date", "category", "user_id",
            "completed_at", "created_at",
        ],
        "m4_fields": [
            "todo_id", "title", "description", "priority", "status",
            "progress", "due_date", "category", "user_id",
            "completed_at", "created_at",
        ],
        "field_map": {},
        "date_field": "due_date",
    },
    "life_habits": {
        "m4_model": "LifeHabitDB",
        "idempotent_key": "habit_id",
        "m8_fields": [
            "habit_id", "name", "description", "category", "icon",
            "streak", "longest_streak", "target_count", "current_count",
            "done", "frequency", "status", "user_id", "created_at",
        ],
        "m4_fields": [
            "habit_id", "name", "description", "category", "icon",
            "streak", "longest_streak", "target_count", "current_count",
            "done", "frequency", "status", "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": None,
    },
    "life_habit_records": {
        "m4_model": "LifeHabitRecordDB",
        "idempotent_composite": ["user_id", "habit_id", "date"],
        "m8_fields": [
            "habit_id", "date", "completed", "note",
            "user_id", "created_at",
        ],
        "m4_fields": [
            "habit_id", "date", "completed", "note",
            "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": "date",
    },
    "life_scenes": {
        "m4_model": "LifeSceneDB",
        "idempotent_key": "scene_id",
        "m8_fields": [
            "scene_id", "name", "description", "icon", "active",
            "is_active", "settings_json", "user_id", "created_at",
        ],
        "m4_fields": [
            "scene_id", "name", "description", "icon", "active",
            "is_active", "settings_json", "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": None,
    },
    "life_rules": {
        "m4_model": "LifeRuleDB",
        "idempotent_key": "rule_id",
        "m8_fields": [
            "rule_id", "title", "description", "condition", "action",
            "category", "enabled", "user_id", "created_at",
        ],
        "m4_fields": [
            "rule_id", "title", "description", "condition", "action",
            "category", "enabled", "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": None,
    },
    "life_finance_categories": {
        "m4_model": "LifeFinanceCategoryDB",
        "idempotent_key": "category_id",
        "m8_fields": [
            "category_id", "name", "type", "budget", "spent",
            "percentage", "color", "user_id", "created_at",
        ],
        "m4_fields": [
            "category_id", "name", "type", "budget", "spent",
            "percentage", "color", "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": None,
    },
    "life_finance_records": {
        "m4_model": "LifeFinanceRecordDB",
        "idempotent_composite": ["user_id", "transaction_date", "amount", "category", "description"],
        "m8_fields": [
            "type", "amount", "category", "description",
            "transaction_date", "user_id", "created_at",
        ],
        "m4_fields": [
            "type", "amount", "category", "description",
            "transaction_date", "user_id", "created_at",
        ],
        "field_map": {},
        "date_field": "transaction_date",
    },
    "life_meta": {
        "m4_model": "LifeMetaDB",
        "idempotent_key": "meta_key",  # meta表用 user_id + meta_key 唯一
        "idempotent_composite": ["user_id", "meta_key"],
        "m8_fields": [
            "meta_key", "meta_value", "user_id",
        ],
        "m4_fields": [
            "meta_key", "meta_value", "user_id", "created_at", "updated_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
            "updated_at": lambda: datetime.utcnow(),
        },
        "date_field": None,
    },

    # ---------- 学业规划 7 表 ----------
    "study_goals": {
        "m4_model": "StudyGoalDB",
        "idempotent_key": "goal_id",
        "m8_fields": [
            "goal_id", "title", "description", "parent_id", "status",
            "progress", "priority", "deadline", "order_index", "icon",
            "expanded", "level", "extra", "user_id",
        ],
        "m4_fields": [
            "goal_id", "title", "description", "parent_id", "status",
            "progress", "priority", "deadline", "order_index", "icon",
            "expanded", "level", "extra", "user_id",
            "created_at", "updated_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
            "updated_at": lambda: datetime.utcnow(),
        },
        "date_field": "deadline",
    },
    "study_plans": {
        "m4_model": "StudyPlanDB",
        "idempotent_key": "plan_id",
        "m8_fields": [
            "plan_id", "title", "content", "subject", "status",
            "start_time", "end_time", "date", "duration", "priority",
            "completed", "user_id",
        ],
        "m4_fields": [
            "plan_id", "title", "content", "subject", "status",
            "start_time", "end_time", "date", "duration", "priority",
            "completed", "user_id", "created_at", "updated_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
            "updated_at": lambda: datetime.utcnow(),
        },
        "date_field": "date",
    },
    "study_notes": {
        "m4_model": "StudyNoteDB",
        "idempotent_key": "note_id",
        "m8_fields": [
            "note_id", "title", "content", "category", "tags",
            "important", "date_label", "user_id", "created_at", "updated_at",
        ],
        "m4_fields": [
            "note_id", "title", "content", "category", "tags",
            "important", "date_label", "user_id", "created_at", "updated_at",
        ],
        "field_map": {},
        "date_field": "date_label",
    },
    "study_knowledge_categories": {
        "m4_model": "StudyKnowledgeCategoryDB",
        "idempotent_key": "category_id",
        "m8_fields": [
            "category_id", "name", "description", "parent_id",
            "note_count", "icon", "unit", "user_id",
        ],
        "m4_fields": [
            "category_id", "name", "description", "parent_id",
            "note_count", "icon", "unit", "user_id", "created_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
        },
        "date_field": None,
    },
    "study_exams": {
        "m4_model": "StudyExamDB",
        "idempotent_key": "exam_id",
        "m8_fields": [
            "exam_id", "name", "subject", "exam_date", "location",
            "score", "status", "urgency", "color_theme", "user_id",
        ],
        "m4_fields": [
            "exam_id", "name", "subject", "exam_date", "location",
            "score", "status", "urgency", "color_theme", "user_id",
            "created_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
        },
        "date_field": "exam_date",
    },
    "study_progress": {
        "m4_model": "StudyProgressDB",
        "idempotent_composite": ["user_id", "subject"],
        "m8_fields": [
            "subject", "progress", "total_hours",
            "mastered_topics", "total_topics", "color", "user_id",
        ],
        "m4_fields": [
            "subject", "progress", "total_hours",
            "mastered_topics", "total_topics", "color", "user_id",
            "created_at", "updated_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
            "updated_at": lambda: datetime.utcnow(),
        },
        "date_field": None,
    },
    "study_meta": {
        "m4_model": "StudyMetaDB",
        "idempotent_key": "meta_key",
        "idempotent_composite": ["user_id", "meta_key"],
        "m8_fields": [
            "meta_key", "meta_value", "user_id",
        ],
        "m4_fields": [
            "meta_key", "meta_value", "user_id", "created_at", "updated_at",
        ],
        "field_map": {},
        "m4_extra_defaults": {
            "created_at": lambda: datetime.utcnow(),
            "updated_at": lambda: datetime.utcnow(),
        },
        "date_field": None,
    },
}


# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------

def get_m8_connection() -> sqlite3.Connection:
    """获取M8数据库只读连接."""
    if not M8_DB_PATH.exists():
        raise FileNotFoundError(f"M8 数据库不存在: {M8_DB_PATH}")
    conn = sqlite3.connect(f"file:{M8_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_m4_session():
    """获取M4 SQLAlchemy 会话."""
    from models.db.base import get_session
    return get_session()


def init_m4_db() -> None:
    """初始化M4数据库表结构."""
    from models.db.base import init_db
    result = init_db(db_path=str(M4_DB_PATH), base_dir=PROJECT_ROOT)
    logger.info(f"M4 数据库初始化完成: {result}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def parse_datetime(val: Any) -> Optional[datetime]:
    """解析日期时间字符串."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


def parse_json(val: Any) -> Any:
    """解析JSON字段."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def convert_user_id(val: Any) -> str:
    """转换user_id为字符串类型."""
    if val is None:
        return "default"
    return str(val)


def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 0.5):
    """指数退避重试机制."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"  操作失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}, "
                    f"{delay:.1f}s 后重试..."
                )
                time.sleep(delay)
            else:
                logger.error(f"  操作失败，已达最大重试次数: {e}")
    raise last_exc  # type: ignore


# ---------------------------------------------------------------------------
# 检查点管理
# ---------------------------------------------------------------------------

def load_checkpoint() -> Dict[str, Any]:
    """加载断点续传检查点."""
    if CHECKPOINT_PATH.exists():
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载检查点失败: {e}，将从头开始迁移")
    return {
        "completed_tables": [],
        "table_offsets": {},
        "last_update": None,
    }


def save_checkpoint(checkpoint: Dict[str, Any]) -> None:
    """保存断点续传检查点."""
    checkpoint["last_update"] = datetime.now().isoformat()
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"保存检查点失败: {e}")


# ---------------------------------------------------------------------------
# 核心迁移逻辑
# ---------------------------------------------------------------------------

def get_m8_table_count(conn: sqlite3.Connection, table: str, start_date: Optional[str] = None) -> int:
    """获取M8表的记录数."""
    config = TABLE_CONFIG[table]
    query = f"SELECT COUNT(*) as cnt FROM {table}"
    params: Tuple = ()

    if start_date and config.get("date_field"):
        date_field = config["date_field"]
        query += f" WHERE {date_field} >= ?"
        params = (start_date,)

    cursor = conn.execute(query, params)
    return cursor.fetchone()["cnt"]


def fetch_m8_batch(
    conn: sqlite3.Connection,
    table: str,
    offset: int,
    batch_size: int,
    start_date: Optional[str] = None,
) -> List[sqlite3.Row]:
    """分批获取M8数据."""
    config = TABLE_CONFIG[table]
    fields = config["m8_fields"]
    fields_str = ", ".join(fields)
    query = f"SELECT {fields_str} FROM {table}"
    params: Tuple = ()

    if start_date and config.get("date_field"):
        date_field = config["date_field"]
        query += f" WHERE {date_field} >= ?"
        params = (start_date,)

    # 使用id排序保证一致性
    query += " ORDER BY id LIMIT ? OFFSET ?"
    params = params + (batch_size, offset)

    cursor = conn.execute(query, params)
    return cursor.fetchall()


def build_m4_record(table: str, m8_row: sqlite3.Row) -> Dict[str, Any]:
    """将M8行数据转换为M4记录字典."""
    config = TABLE_CONFIG[table]
    field_map = config.get("field_map", {})
    extra_defaults = config.get("m4_extra_defaults", {})
    m8_fields = config["m8_fields"]

    record: Dict[str, Any] = {}

    for m8_field in m8_fields:
        m4_field = field_map.get(m8_field, m8_field)
        val = m8_row[m8_field] if m8_field in m8_row.keys() else None

        # 特殊字段处理
        if m4_field == "user_id":
            val = convert_user_id(val)
        elif m4_field in ("created_at", "updated_at", "completed_at"):
            val = parse_datetime(val)
        elif m4_field in ("settings_json", "meta_value", "extra", "tags"):
            val = parse_json(val)
        elif m8_field == "id" and config.get("idempotent_key") == "id":
            # 保留自增id字段用于幂等检查
            pass

        record[m4_field] = val

    # 添加M4有但M8没有的字段默认值
    for field, default_func in extra_defaults.items():
        if field not in record or record[field] is None:
            record[field] = default_func()

    return record


def check_duplicate(session, table: str, record: Dict[str, Any]) -> bool:
    """幂等性检查：判断记录是否已存在."""
    config = TABLE_CONFIG[table]
    model_name = config["m4_model"]

    # 动态导入模型
    from models.db.life import (
        LifeScheduleDB, LifeTodoDB, LifeHabitDB, LifeHabitRecordDB,
        LifeSceneDB, LifeRuleDB, LifeFinanceCategoryDB, LifeFinanceRecordDB,
        LifeMetaDB,
    )
    from models.db.study import (
        StudyGoalDB, StudyPlanDB, StudyNoteDB, StudyKnowledgeCategoryDB,
        StudyExamDB, StudyProgressDB, StudyMetaDB,
    )

    model_map = {
        "LifeScheduleDB": LifeScheduleDB,
        "LifeTodoDB": LifeTodoDB,
        "LifeHabitDB": LifeHabitDB,
        "LifeHabitRecordDB": LifeHabitRecordDB,
        "LifeSceneDB": LifeSceneDB,
        "LifeRuleDB": LifeRuleDB,
        "LifeFinanceCategoryDB": LifeFinanceCategoryDB,
        "LifeFinanceRecordDB": LifeFinanceRecordDB,
        "LifeMetaDB": LifeMetaDB,
        "StudyGoalDB": StudyGoalDB,
        "StudyPlanDB": StudyPlanDB,
        "StudyNoteDB": StudyNoteDB,
        "StudyKnowledgeCategoryDB": StudyKnowledgeCategoryDB,
        "StudyExamDB": StudyExamDB,
        "StudyProgressDB": StudyProgressDB,
        "StudyMetaDB": StudyMetaDB,
    }

    model = model_map[model_name]
    query = session.query(model)

    # 复合主键检查
    if "idempotent_composite" in config:
        filters = {}
        for key in config["idempotent_composite"]:
            filters[key] = record.get(key)
        for k, v in filters.items():
            query = query.filter(getattr(model, k) == v)
    else:
        idem_key = config["idempotent_key"]
        query = query.filter(getattr(model, idem_key) == record.get(idem_key))
        # 加上user_id过滤，确保多用户场景下的正确性
        if hasattr(model, "user_id") and "user_id" in record:
            query = query.filter(model.user_id == record["user_id"])

    return query.first() is not None


def insert_m4_records(session, table: str, records: List[Dict[str, Any]]) -> Tuple[int, int]:
    """批量插入M4记录，返(成功数, 跳过数).

    注意：由于SQLAlchemy的bulk_insert_mappings不支持冲突检测，
    这里使用逐条检查+批量提交的方式。
    """
    config = TABLE_CONFIG[table]
    model_name = config["m4_model"]

    from models.db.life import (
        LifeScheduleDB, LifeTodoDB, LifeHabitDB, LifeHabitRecordDB,
        LifeSceneDB, LifeRuleDB, LifeFinanceCategoryDB, LifeFinanceRecordDB,
        LifeMetaDB,
    )
    from models.db.study import (
        StudyGoalDB, StudyPlanDB, StudyNoteDB, StudyKnowledgeCategoryDB,
        StudyExamDB, StudyProgressDB, StudyMetaDB,
    )

    model_map = {
        "LifeScheduleDB": LifeScheduleDB,
        "LifeTodoDB": LifeTodoDB,
        "LifeHabitDB": LifeHabitDB,
        "LifeHabitRecordDB": LifeHabitRecordDB,
        "LifeSceneDB": LifeSceneDB,
        "LifeRuleDB": LifeRuleDB,
        "LifeFinanceCategoryDB": LifeFinanceCategoryDB,
        "LifeFinanceRecordDB": LifeFinanceRecordDB,
        "LifeMetaDB": LifeMetaDB,
        "StudyGoalDB": StudyGoalDB,
        "StudyPlanDB": StudyPlanDB,
        "StudyNoteDB": StudyNoteDB,
        "StudyKnowledgeCategoryDB": StudyKnowledgeCategoryDB,
        "StudyExamDB": StudyExamDB,
        "StudyProgressDB": StudyProgressDB,
        "StudyMetaDB": StudyMetaDB,
    }

    model = model_map[model_name]
    new_records = []
    skipped = 0

    for record in records:
        if check_duplicate(session, table, record):
            skipped += 1
            continue
        new_records.append(record)

    if new_records:
        try:
            session.bulk_insert_mappings(model, new_records)
            session.commit()
        except Exception:
            session.rollback()
            raise

    return len(new_records), skipped


def migrate_table(
    table: str,
    m8_conn: sqlite3.Connection,
    session,
    stats: TableMigrationStats,
    batch_size: int = 1000,
    start_date: Optional[str] = None,
    dry_run: bool = False,
    resume_offset: int = 0,
) -> TableMigrationStats:
    """迁移单张表."""
    config = TABLE_CONFIG[table]
    stats.start_time = time.time()

    logger.info(f"\n开始迁移表: {table} ({config['m4_model']})")

    # 获取总记录数
    total = get_m8_table_count(m8_conn, table, start_date)
    stats.total_m8 = total
    logger.info(f"  M8 总记录数: {total:,}")

    if total == 0:
        logger.info(f"  表 {table} 无数据，跳过")
        stats.end_time = time.time()
        return stats

    # 进度跟踪
    tracker = ProgressTracker(total, label=table)

    offset = resume_offset
    batch_count = 0

    while offset < total:
        # 读取一批数据
        batch = fetch_m8_batch(m8_conn, table, offset, batch_size, start_date)
        if not batch:
            break

        # 转换数据
        m4_records = []
        for row in batch:
            try:
                m4_rec = build_m4_record(table, row)
                m4_records.append(m4_rec)
            except Exception as e:
                stats.failed += 1
                stats.errors.append(f"row id={row.get('id', '?')}: {e}")

        # 插入M4
        if not dry_run:
            try:
                migrated, skipped = retry_with_backoff(
                    lambda recs=m4_records: insert_m4_records(session, table, recs),
                    max_retries=3,
                    base_delay=0.5,
                )
                stats.migrated += migrated
                stats.skipped += skipped
            except Exception as e:
                stats.failed += len(m4_records)
                stats.errors.append(f"batch offset={offset}: {e}")
                logger.error(f"  批次插入失败 offset={offset}: {e}")
        else:
            # dry-run 模式：统计但不插入
            # 模拟幂等检查（估算跳过数）
            stats.migrated += len(m4_records)

        tracker.update(len(batch))
        offset += len(batch)
        batch_count += 1

        # 每10个批次保存一次检查点
        if batch_count % 10 == 0:
            checkpoint = load_checkpoint()
            checkpoint["table_offsets"][table] = offset
            save_checkpoint(checkpoint)

    tracker.finish()
    stats.end_time = time.time()

    logger.info(
        f"  迁移完成: 成功={stats.migrated:,}, 跳过={stats.skipped:,}, "
        f"失败={stats.failed:,}, 耗时={stats.duration:.2f}s"
    )

    return stats


# ---------------------------------------------------------------------------
# 主迁移流程
# ---------------------------------------------------------------------------

def run_migration(
    full: bool = False,
    start_date: Optional[str] = None,
    dry_run: bool = False,
    resume: bool = False,
    batch_size: int = 1000,
    tables: Optional[List[str]] = None,
) -> MigrationStats:
    """执行迁移主流程."""

    global_stats = MigrationStats(dry_run=dry_run)
    global_stats.start_time = time.time()

    logger.info("=" * 70)
    logger.info("  P1a 批次 M8 → M4 数据迁移 (生活管理 + 学业规划)")
    logger.info("=" * 70)
    logger.info(f"  M8 数据库: {M8_DB_PATH}")
    logger.info(f"  M4 数据库: {M4_DB_PATH}")
    logger.info(f"  模式: {'DRY-RUN' if dry_run else 'FULL MIGRATION'}")
    logger.info(f"  批次大小: {batch_size}")
    if start_date:
        logger.info(f"  起始日期: {start_date}")
    if resume:
        logger.info(f"  断点续传: 启用")
    logger.info("=" * 70)

    # 初始化M4数据库
    if not dry_run:
        logger.info("\n初始化M4数据库表结构...")
        init_m4_db()

    # 确定迁移表列表
    if tables:
        table_list = [t for t in tables if t in TABLE_CONFIG]
    else:
        # 默认顺序：先生活管理，再学业规划
        life_tables = [
            "life_schedules", "life_todos", "life_habits", "life_habit_records",
            "life_scenes", "life_rules",
            "life_finance_categories", "life_finance_records", "life_meta",
        ]
        study_tables = [
            "study_goals", "study_plans", "study_notes",
            "study_knowledge_categories", "study_exams",
            "study_progress", "study_meta",
        ]
        table_list = life_tables + study_tables

    logger.info(f"\n共 {len(table_list)} 张表待迁移")

    # 加载检查点
    checkpoint = load_checkpoint() if resume else {"completed_tables": [], "table_offsets": {}}

    # 连接M8数据库
    m8_conn = get_m8_connection()

    # 获取M4会话
    m4_session = get_m4_session() if not dry_run else None

    try:
        for i, table in enumerate(table_list, 1):
            logger.info(f"\n[{i}/{len(table_list)}] 处理表: {table}")

            # 检查是否已完成（断点续传）
            if table in checkpoint.get("completed_tables", []):
                logger.info(f"  检查点显示已完成，跳过")
                # 从M4获取已迁移数量
                stats = TableMigrationStats(table_name=table)
                stats.total_m8 = get_m8_table_count(m8_conn, table, start_date)
                stats.migrated = stats.total_m8  # 假设全部已迁移
                stats.end_time = time.time()
                stats.start_time = time.time()
                global_stats.add_table_stats(stats)
                continue

            # 获取断点偏移量
            resume_offset = checkpoint.get("table_offsets", {}).get(table, 0)
            if resume_offset > 0:
                logger.info(f"  断点续传: 从 offset={resume_offset} 继续")

            stats = TableMigrationStats(table_name=table)
            migrate_table(
                table=table,
                m8_conn=m8_conn,
                session=m4_session,
                stats=stats,
                batch_size=batch_size,
                start_date=start_date,
                dry_run=dry_run,
                resume_offset=resume_offset,
            )
            global_stats.add_table_stats(stats)

            # 标记表为已完成
            if not dry_run:
                checkpoint["completed_tables"].append(table)
                if table in checkpoint.get("table_offsets", {}):
                    del checkpoint["table_offsets"][table]
                save_checkpoint(checkpoint)

    finally:
        m8_conn.close()
        if m4_session:
            m4_session.close()

    global_stats.end_time = time.time()

    # 打印摘要
    print(global_stats.summary())

    # 清理检查点（全量迁移成功后）
    if not dry_run and global_stats.total_failed == 0:
        if CHECKPOINT_PATH.exists():
            CHECKPOINT_PATH.unlink()
            logger.info("迁移全部成功，检查点文件已清理")

    return global_stats


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="M8 → M4 P1a 批次数据迁移 (生活管理 + 学业规划)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # dry-run 模式（预览，不实际写入）
  python migrate_life_study_m8_to_m4.py --dry-run

  # 全量迁移
  python migrate_life_study_m8_to_m4.py --full

  # 从指定日期开始迁移
  python migrate_life_study_m8_to_m4.py --full --start-date 2026-01-01

  # 断点续传
  python migrate_life_study_m8_to_m4.py --resume

  # 指定批次大小
  python migrate_life_study_m8_to_m4.py --full --batch-size 500

  # 只迁移指定表
  python migrate_life_study_m8_to_m4.py --full --tables life_schedules,study_goals
        """,
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="执行完整迁移（写入M4数据库）",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="试运行模式，不实际写入数据",
    )
    parser.add_argument(
        "--start-date", "-d",
        type=str,
        default=None,
        help="只迁移指定日期之后的数据 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="从检查点断点续传",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=1000,
        help="每批迁移记录数 (默认: 1000)",
    )
    parser.add_argument(
        "--tables", "-t",
        type=str,
        default=None,
        help="指定迁移表名，逗号分隔",
    )

    args = parser.parse_args()

    # 参数校验
    if not args.full and not args.dry_run and not args.resume:
        print("错误: 请指定 --full, --dry-run, 或 --resume 之一")
        parser.print_help()
        sys.exit(1)

    if args.resume:
        args.full = True  # resume 模式默认开启实际写入

    tables = args.tables.split(",") if args.tables else None

    try:
        stats = run_migration(
            full=args.full,
            start_date=args.start_date,
            dry_run=args.dry_run,
            resume=args.resume,
            batch_size=args.batch_size,
            tables=tables,
        )
        if stats.total_failed > 0:
            sys.exit(1)
    except Exception as e:
        logger.error(f"\n迁移失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
