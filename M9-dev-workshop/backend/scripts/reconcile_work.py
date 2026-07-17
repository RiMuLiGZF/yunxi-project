"""
P1b 批次数据对账脚本：M8 work_* 表 <-> M9 work_* 表
工作开发模块（4张表）数据一致性校验

功能：
- 各表记录数对比
- 抽样数据对比（按业务ID）
- 全量字段级对比
- 输出不一致报告（JSON + 控制台）

用法：
  python reconcile_work.py
  python reconcile_work.py --sample-size 10
  python reconcile_work.py --full-compare
  python reconcile_work.py --output report.json
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple

# 添加父目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from sqlalchemy.orm import Session

from models import (
    SessionLocal,
    WorkProject,
    WorkTask,
    WorkCommit,
    WorkDevCodeUsage,
)

# ===== 日志配置 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("reconcile_work")

# ===== 路径配置 =====
M8_DB_PATH = r"C:\云汐\工作台\yunxi-project\M8-control-tower\backend\data\m8.db"

# ===== 对账配置 =====
TABLE_CONFIGS = [
    {
        "m8_table": "work_projects",
        "m9_model": WorkProject,
        "m9_table": "work_projects",
        "biz_id_field_m8": "project_id",
        "biz_id_field_m9": "project_id",
        "compare_fields": [
            "project_id", "name", "description", "status", "progress",
            "repo_url", "language", "file_count", "line_count", "commit_count",
            "user_id", "created_at", "updated_at",
        ],
    },
    {
        "m8_table": "work_tasks",
        "m9_model": WorkTask,
        "m9_table": "work_tasks",
        "biz_id_field_m8": "task_id",
        "biz_id_field_m9": "task_id",
        "compare_fields": [
            "task_id", "title", "description", "status", "priority",
            "project_id", "assignee", "due_date", "user_id",
            "created_at", "updated_at",
        ],
    },
    {
        "m8_table": "work_commits",
        "m9_model": WorkCommit,
        "m9_table": "work_commits",
        "biz_id_field_m8": "commit_id",
        "biz_id_field_m9": "commit_id",
        "compare_fields": [
            "commit_id", "hash", "message", "author", "branch",
            "project_id", "additions", "deletions", "files_changed",
            "committed_at", "user_id",
        ],
    },
    {
        "m8_table": "work_dev_code_usage",
        "m9_model": WorkDevCodeUsage,
        "m9_table": "work_dev_code_usage",
        "biz_id_field_m8": "usage_id",
        "biz_id_field_m9": "usage_id",
        "compare_fields": [
            "usage_id", "action_type", "operation_type", "language",
            "tokens_used", "project_id", "is_fallback", "user_id",
            "created_at",
        ],
    },
]


# ===== 数据类 =====
@dataclass
class FieldDiff:
    """字段差异"""
    field: str
    m8_value: Any
    m9_value: Any


@dataclass
class RowDiff:
    """行差异"""
    biz_id: Any
    diff_type: str  # missing_in_m9 / missing_in_m8 / field_mismatch
    fields: List[FieldDiff] = field(default_factory=list)


@dataclass
class TableReconcileResult:
    """单表对账结果"""
    table_name: str
    m8_count: int = 0
    m9_count: int = 0
    count_match: bool = False
    sample_checked: int = 0
    sample_matched: int = 0
    sample_mismatched: int = 0
    diffs: List[RowDiff] = field(default_factory=list)
    full_compare: bool = False

    @property
    def count_diff(self) -> int:
        return self.m9_count - self.m8_count

    @property
    def sample_pass_rate(self) -> float:
        if self.sample_checked == 0:
            return 0.0
        return (self.sample_matched / self.sample_checked) * 100


@dataclass
class ReconcileReport:
    """整体对账报告"""
    report_time: str = ""
    tables: Dict[str, TableReconcileResult] = field(default_factory=dict)

    @property
    def all_count_match(self) -> bool:
        return all(r.count_match for r in self.tables.values())

    @property
    def all_sample_match(self) -> bool:
        return all(r.sample_matched == r.sample_checked for r in self.tables.values() if r.sample_checked > 0)

    @property
    def total_m8(self) -> int:
        return sum(r.m8_count for r in self.tables.values())

    @property
    def total_m9(self) -> int:
        return sum(r.m9_count for r in self.tables.values())

    def to_dict(self) -> Dict:
        return {
            "report_time": self.report_time,
            "all_count_match": self.all_count_match,
            "all_sample_match": self.all_sample_match,
            "total_m8": self.total_m8,
            "total_m9": self.total_m9,
            "tables": {
                name: {
                    "table_name": r.table_name,
                    "m8_count": r.m8_count,
                    "m9_count": r.m9_count,
                    "count_match": r.count_match,
                    "count_diff": r.count_diff,
                    "sample_checked": r.sample_checked,
                    "sample_matched": r.sample_matched,
                    "sample_mismatched": r.sample_mismatched,
                    "sample_pass_rate": round(r.sample_pass_rate, 2),
                    "full_compare": r.full_compare,
                    "diffs": [
                        {
                            "biz_id": d.biz_id,
                            "diff_type": d.diff_type,
                            "fields": [
                                {"field": f.field, "m8_value": f.m8_value, "m9_value": f.m9_value}
                                for f in d.fields
                            ],
                        }
                        for d in r.diffs
                    ],
                }
                for name, r in self.tables.items()
            },
        }

    def summary(self) -> str:
        lines = [
            "",
            "=" * 60,
            "  数据对账报告",
            "=" * 60,
            f"  对账时间: {self.report_time}",
            f"  M8 总记录数: {self.total_m8}",
            f"  M9 总记录数: {self.total_m9}",
            f"  记录数一致: {'是' if self.all_count_match else '否'}",
            f"  抽样全部匹配: {'是' if self.all_sample_match else '否'}",
            "-" * 60,
        ]
        for name, r in self.tables.items():
            status = "PASS" if r.count_match and (r.sample_matched == r.sample_checked) else "FAIL"
            lines.append(
                f"  [{status}] {name}: M8={r.m8_count}, M9={r.m9_count}, "
                f"抽样={r.sample_matched}/{r.sample_checked} "
                f"({r.sample_pass_rate:.1f}%)"
            )
        lines.append("=" * 60)
        return "\n".join(lines)


# ===== 工具函数 =====
def normalize_value(value: Any, field: str) -> Any:
    """标准化值以便比较"""
    # user_id: Integer to String comparison
    if field == "user_id" and value is not None:
        return str(value)

    # 日期时间字段：统一解析为 datetime 再格式化，兼容 M8 字符串格式和 M9 datetime 对象
    datetime_fields = {"created_at", "updated_at", "committed_at"}
    if field in datetime_fields:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            # 尝试解析 M8 的字符串格式（空格分隔）
            try:
                return datetime.fromisoformat(value.replace(" ", "T")).isoformat()
            except (ValueError, TypeError):
                return value
        return str(value)

    # None 统一处理
    if value is None:
        return None

    # JSON 字段：序列化后比较
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    return value


def get_m8_count(conn: sqlite3.Connection, table_name: str) -> int:
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def get_m9_count(db: Session, model) -> int:
    return db.query(model).count()


def get_m8_sample(
    conn: sqlite3.Connection,
    table_name: str,
    biz_id_field: str,
    sample_size: int,
) -> List[Dict]:
    """从M8获取样本数据"""
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM {table_name} ORDER BY {biz_id_field} ASC LIMIT ?",
        (sample_size,),
    )
    col_names = [d[0] for d in cursor.description]
    return [dict(zip(col_names, row)) for row in cursor.fetchall()]


def get_m9_by_biz_id(
    db: Session,
    model,
    biz_id_field: str,
    biz_id_value: Any,
) -> Optional[Any]:
    """按业务ID从M9获取单条记录"""
    return db.query(model).filter(
        getattr(model, biz_id_field) == biz_id_value
    ).first()


def compare_rows(
    m8_row: Dict,
    m9_obj: Any,
    compare_fields: List[str],
) -> List[FieldDiff]:
    """对比单条记录的指定字段，返回差异列表"""
    diffs = []
    for field in compare_fields:
        m8_val = normalize_value(m8_row.get(field), field)
        m9_val = normalize_value(getattr(m9_obj, field, None), field)

        if m8_val != m9_val:
            diffs.append(FieldDiff(
                field=field,
                m8_value=m8_val,
                m9_value=m9_val,
            ))
    return diffs


# ===== 对账核心逻辑 =====
def reconcile_table(
    conn_m8: sqlite3.Connection,
    db: Session,
    table_config: Dict,
    sample_size: int,
    full_compare: bool,
) -> TableReconcileResult:
    """单表对账"""
    m8_table = table_config["m8_table"]
    m9_model = table_config["m9_model"]
    biz_id_m8 = table_config["biz_id_field_m8"]
    biz_id_m9 = table_config["biz_id_field_m9"]
    compare_fields = table_config["compare_fields"]

    result = TableReconcileResult(table_name=m8_table, full_compare=full_compare)

    # 1. 记录数对比
    result.m8_count = get_m8_count(conn_m8, m8_table)
    result.m9_count = get_m9_count(db, m9_model)
    result.count_match = (result.m8_count == result.m9_count)

    logger.info(
        f"[{m8_table}] 记录数: M8={result.m8_count}, M9={result.m9_count}, "
        f"{'一致' if result.count_match else '不一致'}"
    )

    # 2. 确定实际抽样量
    actual_sample_size = sample_size
    if full_compare:
        actual_sample_size = result.m8_count
    else:
        actual_sample_size = min(sample_size, result.m8_count)

    if actual_sample_size == 0:
        return result

    # 3. 获取M8样本
    m8_samples = get_m8_sample(conn_m8, m8_table, biz_id_m8, actual_sample_size)
    result.sample_checked = len(m8_samples)

    logger.info(f"[{m8_table}] 开始抽样对比，样本数: {actual_sample_size}")

    # 4. 逐条对比
    for m8_row in m8_samples:
        biz_id = m8_row.get(biz_id_m8)

        # 查找M9对应记录
        m9_obj = get_m9_by_biz_id(db, m9_model, biz_id_m9, biz_id)

        if m9_obj is None:
            result.sample_mismatched += 1
            result.diffs.append(RowDiff(
                biz_id=biz_id,
                diff_type="missing_in_m9",
                fields=[FieldDiff(
                    field="*",
                    m8_value="存在",
                    m9_value=None,
                )],
            ))
            continue

        # 字段级对比
        field_diffs = compare_rows(m8_row, m9_obj, compare_fields)
        if field_diffs:
            result.sample_mismatched += 1
            result.diffs.append(RowDiff(
                biz_id=biz_id,
                diff_type="field_mismatch",
                fields=field_diffs,
            ))
            # 打印前几个差异
            if len(result.diffs) <= 3:
                diff_str = ", ".join(
                    f"{d.field}: M8={d.m8_value} vs M9={d.m9_value}"
                    for d in field_diffs[:3]
                )
                logger.warning(f"  差异 biz_id={biz_id}: {diff_str}")
        else:
            result.sample_matched += 1

    logger.info(
        f"[{m8_table}] 抽样结果: {result.sample_matched}/{result.sample_checked} "
        f"匹配 ({result.sample_pass_rate:.1f}%)"
    )

    return result


def run_reconcile(sample_size: int = 5, full_compare: bool = False) -> ReconcileReport:
    """执行对账主流程"""
    report = ReconcileReport(report_time=datetime.now().isoformat())

    logger.info("=" * 60)
    logger.info("  P1b 批次数据对账：M8 work_* <-> M9 work_*")
    logger.info(f"  抽样数量: {sample_size}" if not full_compare else "  模式: 全量对比")
    logger.info("=" * 60)

    # 连接M8
    if not os.path.exists(M8_DB_PATH):
        logger.error(f"M8 数据库不存在: {M8_DB_PATH}")
        sys.exit(1)

    conn_m8 = sqlite3.connect(M8_DB_PATH)
    db = SessionLocal()

    try:
        for table_config in TABLE_CONFIGS:
            result = reconcile_table(
                conn_m8=conn_m8,
                db=db,
                table_config=table_config,
                sample_size=sample_size,
                full_compare=full_compare,
            )
            report.tables[table_config["m8_table"]] = result
    finally:
        db.close()
        conn_m8.close()

    # 输出汇总
    logger.info(report.summary())

    return report


def main():
    parser = argparse.ArgumentParser(
        description="P1b 批次数据对账：M8 work_* 表 <-> M9 work_* 表"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="每表抽样数量（默认5）",
    )
    parser.add_argument(
        "--full-compare",
        action="store_true",
        help="全量字段级对比（不只是抽样）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出JSON报告文件路径",
    )

    args = parser.parse_args()

    report = run_reconcile(
        sample_size=args.sample_size,
        full_compare=args.full_compare,
    )

    # 输出JSON报告
    if args.output:
        output_path = args.output
    else:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"reconcile_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"对账报告已保存: {output_path}")

    # 返回码：有差异则非零
    has_diff = not report.all_count_match or not report.all_sample_match
    sys.exit(1 if has_diff else 0)


if __name__ == "__main__":
    main()
