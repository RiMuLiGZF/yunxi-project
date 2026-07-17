"""P2b批次数据对账脚本：验证 M8 -> M4 情绪陪伴+形象工坊数据一致性.

功能:
  - 各表记录数对比
  - 抽样数据对比
  - 字段级对比
  - 输出不一致报告

用法:
  python scripts/reconcile_emotion_appearance.py
  python scripts/reconcile_emotion_appearance.py --sample-size 10
  python scripts/reconcile_emotion_appearance.py --output report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

M8_DB_PATH = r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend\data\m8.db"
M4_DB_PATH = str(PROJECT_ROOT / "data" / "m4.db")
DEFAULT_SAMPLE_SIZE = 5
DEFAULT_M8_USER_ID = 1
DEFAULT_M4_USER_ID = "1"

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("p2b_reconcile")


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class TableReconcileResult:
    """单表对账结果."""
    table_name: str
    m8_count: int = 0
    m4_count: int = 0
    count_match: bool = False
    samples_checked: int = 0
    samples_matched: int = 0
    samples_mismatched: int = 0
    mismatched_fields: dict[str, int] = field(default_factory=dict)
    mismatch_details: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def sample_match_rate(self) -> float:
        if self.samples_checked == 0:
            return 100.0
        return self.samples_matched / self.samples_checked * 100

    @property
    def passed(self) -> bool:
        return self.count_match and self.samples_mismatched == 0


@dataclass
class ReconcileReport:
    """整体对账报告."""
    batch: str = "P2b"
    report_time: datetime = field(default_factory=datetime.now)
    tables: dict[str, TableReconcileResult] = field(default_factory=dict)

    @property
    def total_m8(self) -> int:
        return sum(t.m8_count for t in self.tables.values())

    @property
    def total_m4(self) -> int:
        return sum(t.m4_count for t in self.tables.values())

    @property
    def total_samples(self) -> int:
        return sum(t.samples_checked for t in self.tables.values())

    @property
    def total_matched(self) -> int:
        return sum(t.samples_matched for t in self.tables.values())

    @property
    def all_passed(self) -> bool:
        return all(t.passed for t in self.tables.values())

    @property
    def overall_match_rate(self) -> float:
        if self.total_samples == 0:
            return 100.0
        return self.total_matched / self.total_samples * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "report_time": self.report_time.isoformat(),
            "summary": {
                "total_m8_records": self.total_m8,
                "total_m4_records": self.total_m4,
                "total_samples_checked": self.total_samples,
                "total_samples_matched": self.total_matched,
                "overall_match_rate": f"{self.overall_match_rate:.2f}%",
                "all_passed": self.all_passed,
            },
            "tables": {
                name: {
                    "m8_count": r.m8_count,
                    "m4_count": r.m4_count,
                    "count_match": r.count_match,
                    "samples_checked": r.samples_checked,
                    "samples_matched": r.samples_matched,
                    "samples_mismatched": r.samples_mismatched,
                    "sample_match_rate": f"{r.sample_match_rate:.2f}%",
                    "passed": r.passed,
                    "mismatched_fields": r.mismatched_fields,
                    "mismatch_details": r.mismatch_details,
                    "errors": r.errors,
                }
                for name, r in self.tables.items()
            },
        }

    def summary_text(self) -> str:
        lines = [
            "=" * 70,
            f"P2b 数据对账报告",
            "=" * 70,
            f"  报告时间: {self.report_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  M8总记录数: {self.total_m8}",
            f"  M4总记录数: {self.total_m4}",
            f"  抽样检查数: {self.total_samples}",
            f"  抽样匹配率: {self.overall_match_rate:.2f}%",
            f"  整体结果: {'通过' if self.all_passed else '不通过'}",
            "-" * 70,
            "  各表详情:",
        ]
        for name, r in self.tables.items():
            status = "PASS" if r.passed else "FAIL"
            lines.append(
                f"    [{status}] {name:<25s} "
                f"M8:{r.m8_count:>4d} M4:{r.m4_count:>4d} "
                f"抽样:{r.samples_checked:>3d} 匹配率:{r.sample_match_rate:>5.1f}%"
            )
        lines.append("=" * 70)
        return "\n".join(lines)


# ===========================================================================
# 对账配置
# ===========================================================================

@dataclass
class ReconcileConfig:
    """单表对账配置."""
    m8_table: str
    m4_table: str
    m8_biz_id: str | None  # M8业务ID字段（用于抽样排序）
    m4_biz_id: str | None  # M4业务ID字段
    compare_fields: list[str]  # 需要对比的字段列表（M4字段名）
    field_mapping: dict[str, str]  # M8字段名 -> M4字段名
    has_user_id: bool = True  # 是否有 user_id 字段
    lookup_fields: list[str] | None = None  # 用于查找M4记录的字段列表（M4字段名）
    transforms: dict[str, callable] | None = None  # M8字段转换函数


RECONCILE_CONFIGS: list[ReconcileConfig] = [
    # ---------- 情绪陪伴 ----------
    ReconcileConfig(
        m8_table="mood_diary",
        m4_table="mood_diary",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=True,
        lookup_fields=["date", "mood"],
        compare_fields=[
            "mood", "content", "tags", "date",
        ],
        field_mapping={
            "id": "id",
            "mood": "mood",
            "content": "content",
            "tags": "tags",
            "date": "date",
            "user_id": "user_id",
            "created_at": "created_at",
        },
        transforms={
            "tags": lambda v: json.loads(v) if isinstance(v, str) else v,
        },
    ),
    ReconcileConfig(
        m8_table="relax_contents",
        m4_table="relax_contents",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=False,  # 全局内容库
        lookup_fields=["title", "category"],
        compare_fields=[
            "title", "category", "content_type", "content_url",
            "content_text", "duration_seconds", "difficulty",
            "description", "steps",
        ],
        field_mapping={
            "id": "id",
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
        transforms={
            "steps": lambda v: json.loads(v) if isinstance(v, str) else v,
        },
    ),
    ReconcileConfig(
        m8_table="relax_sessions",
        m4_table="relax_sessions",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=True,
        lookup_fields=["content_id", "started_at"],
        compare_fields=[
            "content_id", "duration_seconds", "completed", "rating",
            "started_at", "completed_at",
        ],
        field_mapping={
            "id": "id",
            "content_id": "content_id",
            "duration_seconds": "duration_seconds",
            "completed": "completed",
            "rating": "rating",
            "user_id": "user_id",
            "started_at": "started_at",
            "completed_at": "completed_at",
            "created_at": "created_at",
        },
        transforms={
            "completed": lambda v: bool(v) if v is not None else None,
        },
    ),
    ReconcileConfig(
        m8_table="sleep_contents",
        m4_table="sleep_contents",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=False,  # 全局内容库
        lookup_fields=["title", "category"],
        compare_fields=[
            "title", "category", "content_type", "content_url",
            "duration_seconds", "description",
        ],
        field_mapping={
            "id": "id",
            "title": "title",
            "category": "category",
            "content_type": "content_type",
            "content_url": "content_url",
            "duration_seconds": "duration_seconds",
            "description": "description",
            "created_at": "created_at",
        },
    ),
    ReconcileConfig(
        m8_table="sleep_records",
        m4_table="sleep_records",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=True,
        lookup_fields=["date"],
        compare_fields=[
            "date", "sleep_duration", "sleep_quality", "sleep_score",
            "bed_time", "wake_time", "note",
        ],
        field_mapping={
            "id": "id",
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
    ),
    # ---------- 形象工坊 ----------
    ReconcileConfig(
        m8_table="appearance_configs",
        m4_table="appearance_configs",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=True,
        lookup_fields=["user_id"],
        compare_fields=[
            "theme", "primary_color", "secondary_color", "accent_color",
            "bg_color", "particle_count", "particle_speed", "glow_intensity",
            "avatar_style", "mood", "personality_tags", "voice_type",
            "voice_speed", "voice_pitch", "quality", "model",
            "sync_enabled", "relationship_level", "intimacy",
        ],
        field_mapping={
            "id": "id",
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
        transforms={
            "personality_tags": lambda v: json.loads(v) if isinstance(v, str) else v,
            "sync_enabled": lambda v: bool(v) if v is not None else None,
        },
    ),
    ReconcileConfig(
        m8_table="appearance_snapshots",
        m4_table="appearance_snapshots",
        m8_biz_id="id",
        m4_biz_id="id",
        has_user_id=True,
        lookup_fields=["name"],
        compare_fields=[
            "name", "theme", "mood", "snapshot_data",
        ],
        field_mapping={
            "id": "id",
            "user_id": "user_id",
            "name": "name",
            "theme": "theme",
            "mood": "mood",
            "snapshot_data": "snapshot_data",
            "created_at": "created_at",
        },
        transforms={
            "snapshot_data": lambda v: json.loads(v) if isinstance(v, str) else v,
        },
    ),
]


# ===========================================================================
# 对账执行器
# ===========================================================================

class ReconcileRunner:
    """P2b 对账执行器."""

    def __init__(
        self,
        m8_db_path: str,
        m4_db_path: str,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        m8_user_id: Any = DEFAULT_M8_USER_ID,
        m4_user_id: Any = DEFAULT_M4_USER_ID,
    ):
        self.m8_db_path = m8_db_path
        self.m4_db_path = m4_db_path
        self.sample_size = sample_size
        self.m8_user_id = m8_user_id
        self.m4_user_id = m4_user_id
        self.report = ReconcileReport()

        self.m8_conn: sqlite3.Connection | None = None
        self.m4_conn: sqlite3.Connection | None = None

    def setup(self) -> None:
        """初始化数据库连接."""
        self.m8_conn = sqlite3.connect(self.m8_db_path)
        self.m8_conn.row_factory = sqlite3.Row
        logger.info(f"M8 数据库已连接: {self.m8_db_path}")

        self.m4_conn = sqlite3.connect(self.m4_db_path)
        self.m4_conn.row_factory = sqlite3.Row
        logger.info(f"M4 数据库已连接: {self.m4_db_path}")

    def teardown(self) -> None:
        if self.m8_conn:
            self.m8_conn.close()
        if self.m4_conn:
            self.m4_conn.close()

    def get_count(
        self, conn: sqlite3.Connection, table: str,
        user_id: Any = None, has_user_id: bool = True,
    ) -> int:
        cursor = conn.cursor()
        if has_user_id and user_id is not None:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,))
        else:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]

    def get_sample_m8(
        self, table: str, biz_id: str, n: int, has_user_id: bool = True,
    ) -> list[sqlite3.Row]:
        """从 M8 抽样（按用户过滤或全局）."""
        cursor = self.m8_conn.cursor()
        if has_user_id:
            cursor.execute(
                f"SELECT * FROM {table} WHERE user_id = ? ORDER BY {biz_id} LIMIT ?",
                (self.m8_user_id, n),
            )
        else:
            cursor.execute(
                f"SELECT * FROM {table} ORDER BY {biz_id} LIMIT ?",
                (n,),
            )
        return cursor.fetchall()

    def find_m4_record(
        self,
        m4_table: str,
        lookup_fields: list[str],
        lookup_values: dict[str, Any],
        has_user_id: bool = True,
    ) -> sqlite3.Row | None:
        """在 M4 中查找对应记录."""
        assert self.m4_conn is not None
        cursor = self.m4_conn.cursor()
        where_clauses: list[str] = []
        params: list[Any] = []

        if has_user_id:
            where_clauses.append("user_id = ?")
            params.append(self.m4_user_id)

        for f in lookup_fields:
            where_clauses.append(f"{f} = ?")
            params.append(lookup_values.get(f))

        where_sql = " AND ".join(where_clauses)
        cursor.execute(
            f"SELECT * FROM {m4_table} WHERE {where_sql} LIMIT 1",
            params,
        )
        return cursor.fetchone()

    def compare_records(
        self,
        m8_row: sqlite3.Row,
        m4_row: sqlite3.Row | None,
        config: ReconcileConfig,
    ) -> tuple[bool, dict[str, tuple[Any, Any]]]:
        """对比两条记录的指定字段.

        Returns:
            (是否匹配, 不匹配字段字典 {字段名: (M8值, M4值)})
        """
        if m4_row is None:
            return False, {"__missing__": (m8_row[config.m8_biz_id], None)}

        mismatches: dict[str, tuple[Any, Any]] = {}

        for m8_field, m4_field in config.field_mapping.items():
            if m4_field not in config.compare_fields:
                continue

            m8_val = m8_row[m8_field] if m8_field in m8_row.keys() else None
            m4_val = m4_row[m4_field] if m4_field in m4_row.keys() else None

            # 应用 M8 转换函数
            if config.transforms and m8_field in config.transforms:
                try:
                    m8_val = config.transforms[m8_field](m8_val)
                except Exception:
                    pass

            # 应用 M4 转换函数（JSON字段M4也是JSON字符串存储，需要解析）
            if isinstance(m4_val, str) and m8_field in (
                config.transforms or {}
            ):
                # 对于JSON字段，M4中SQLAlchemy会自动序列化，但直接sqlite查询是字符串
                try:
                    m4_val_parsed = json.loads(m4_val)
                    m4_val = m4_val_parsed
                except (json.JSONDecodeError, TypeError):
                    pass

            # 比较
            if m8_val != m4_val:
                # 特殊处理：datetime字符串比较（忽略微秒差异）
                if isinstance(m8_val, str) and isinstance(m4_val, str):
                    if m8_val.startswith("20") and m4_val.startswith("20"):
                        # 都是日期时间字符串，粗略比较（前19位）
                        if m8_val[:19] == m4_val[:19]:
                            continue
                mismatches[m4_field] = (m8_val, m4_val)

        return len(mismatches) == 0, mismatches

    def reconcile_table(self, config: ReconcileConfig) -> TableReconcileResult:
        """对单张表进行对账."""
        result = TableReconcileResult(table_name=config.m8_table)

        try:
            # 1. 记录数对比
            result.m8_count = self.get_count(
                self.m8_conn, config.m8_table,
                self.m8_user_id if config.has_user_id else None,
                config.has_user_id,
            )
            result.m4_count = self.get_count(
                self.m4_conn, config.m4_table,
                self.m4_user_id if config.has_user_id else None,
                config.has_user_id,
            )
            result.count_match = result.m8_count == result.m4_count

            if not result.count_match:
                logger.warning(
                    f"[{config.m8_table}] 记录数不匹配: "
                    f"M8={result.m8_count}, M4={result.m4_count} "
                    f"(差 {result.m4_count - result.m8_count:+d})"
                )

            # 2. 抽样对比
            if result.m8_count == 0:
                logger.info(f"[{config.m8_table}] M8无数据，跳过抽样")
                return result

            sample_size = min(self.sample_size, result.m8_count)
            m8_samples = self.get_sample_m8(
                config.m8_table, config.m8_biz_id or "id",
                sample_size, config.has_user_id,
            )

            for m8_row in m8_samples:
                result.samples_checked += 1

                # 构建查找用的字段值
                if config.lookup_fields:
                    # 使用组合键查找
                    lookup_values = {}
                    for m8_field, m4_field in config.field_mapping.items():
                        if m4_field in config.lookup_fields:
                            val = m8_row[m8_field] if m8_field in m8_row.keys() else None
                            # 应用转换
                            if config.transforms and m8_field in config.transforms:
                                try:
                                    val = config.transforms[m8_field](val)
                                except Exception:
                                    pass
                            lookup_values[m4_field] = val
                    m4_row = self.find_m4_record(
                        config.m4_table, config.lookup_fields,
                        lookup_values, config.has_user_id,
                    )
                    biz_id_val = str(lookup_values)
                else:
                    # 使用业务ID查找
                    biz_id_val = m8_row[config.m8_biz_id]
                    m4_row = self.find_m4_record(
                        config.m4_table, [config.m4_biz_id],
                        {config.m4_biz_id: biz_id_val},
                        config.has_user_id,
                    )

                matched, mismatches = self.compare_records(
                    m8_row, m4_row, config
                )

                if matched:
                    result.samples_matched += 1
                else:
                    result.samples_mismatched += 1
                    for field_name in mismatches:
                        result.mismatched_fields[field_name] = (
                            result.mismatched_fields.get(field_name, 0) + 1
                        )
                    # 记录详细不匹配信息（最多保留10条）
                    if len(result.mismatch_details) < 10:
                        detail = {
                            "biz_id": biz_id_val,
                            "mismatched_fields": {
                                f: {"m8": str(v[0]), "m4": str(v[1])}
                                for f, v in mismatches.items()
                            },
                        }
                        result.mismatch_details.append(detail)

            logger.info(
                f"[{config.m8_table}] 抽样 {result.samples_checked} 条, "
                f"匹配 {result.samples_matched}, "
                f"不匹配 {result.samples_mismatched}, "
                f"匹配率 {result.sample_match_rate:.1f}%"
            )

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"[{config.m8_table}] 对账出错: {e}")

        return result

    def run(self) -> ReconcileReport:
        """执行完整对账."""
        try:
            self.setup()

            logger.info(f"\n{'#' * 70}")
            logger.info("# P2b 数据对账开始")
            logger.info(f"# 对比表数: {len(RECONCILE_CONFIGS)}")
            logger.info(f"# 抽样数/表: {self.sample_size}")
            logger.info(f"{'#' * 70}\n")

            for config in RECONCILE_CONFIGS:
                result = self.reconcile_table(config)
                self.report.tables[config.m8_table] = result

            logger.info("\n" + self.report.summary_text())

            return self.report

        finally:
            self.teardown()


# ===========================================================================
# 命令行入口
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="P2b数据对账: M8 vs M4 情绪陪伴+形象工坊",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=DEFAULT_SAMPLE_SIZE,
        help=f"每表抽样数量 (默认: {DEFAULT_SAMPLE_SIZE})",
    )
    parser.add_argument(
        "--m8-user-id",
        type=str,
        default=str(DEFAULT_M8_USER_ID),
        help=f"M8用户ID (默认: {DEFAULT_M8_USER_ID})",
    )
    parser.add_argument(
        "--m4-user-id",
        type=str,
        default=DEFAULT_M4_USER_ID,
        help=f"M4用户ID (默认: {DEFAULT_M4_USER_ID})",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出报告JSON文件路径",
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

    args = parser.parse_args()

    # 解析M8 user_id (可能是整数)
    m8_user_id = args.m8_user_id
    try:
        m8_user_id = int(m8_user_id)
    except (ValueError, TypeError):
        pass

    runner = ReconcileRunner(
        m8_db_path=args.m8_db,
        m4_db_path=args.m4_db,
        sample_size=args.sample_size,
        m8_user_id=m8_user_id,
        m4_user_id=args.m4_user_id,
    )

    report = runner.run()

    # 输出JSON报告
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info(f"报告已保存: {output_path}")

    # 退出码
    if report.all_passed:
        logger.info("对账全部通过")
        sys.exit(0)
    else:
        logger.warning("对账存在不一致，请检查报告详情")
        sys.exit(1)


if __name__ == "__main__":
    main()
