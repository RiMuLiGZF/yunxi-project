"""P2d 工作流引擎数据对账脚本 - M8 vs M7.

功能:
  - 各表记录数对比
  - 抽样数据字段级对比
  - 输出不一致报告

用法:
  python scripts/reconcile_workflow.py
  python scripts/reconcile_workflow.py --sample-size 20
  python scripts/reconcile_workflow.py --output report.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.orm import Session

from src.db import init_db, get_session
from src.models_db import WorkflowDefinition, WorkflowRunRecord


# ============================================================
# 数据类
# ============================================================
@dataclass
class TableReconcileResult:
    """单表对账结果."""
    table_name: str
    m8_count: int = 0
    m7_count: int = 0
    count_match: bool = True
    sample_size: int = 0
    samples_checked: int = 0
    samples_matched: int = 0
    samples_mismatched: int = 0
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    m8_only_ids: List[str] = field(default_factory=list)
    m7_only_ids: List[str] = field(default_factory=list)

    @property
    def sample_match_rate(self) -> str:
        if self.samples_checked == 0:
            return "N/A"
        return f"{self.samples_matched / self.samples_checked * 100:.1f}%"

    @property
    def status(self) -> str:
        if self.count_match and self.samples_mismatched == 0:
            return "PASS"
        return "FAIL"


@dataclass
class ReconcileReport:
    """整体对账报告."""
    report_id: str = ""
    generated_at: str = ""
    m8_db: str = ""
    m7_data_dir: str = ""
    tables: Dict[str, TableReconcileResult] = field(default_factory=dict)

    @property
    def overall_pass(self) -> bool:
        return all(t.status == "PASS" for t in self.tables.values())

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "m8_db": self.m8_db,
            "m7_data_dir": self.m7_data_dir,
            "overall_pass": self.overall_pass,
            "tables": {
                name: {
                    "m8_count": t.m8_count,
                    "m7_count": t.m7_count,
                    "count_match": t.count_match,
                    "status": t.status,
                    "sample_size": t.sample_size,
                    "samples_checked": t.samples_checked,
                    "samples_matched": t.samples_matched,
                    "samples_mismatched": t.samples_mismatched,
                    "sample_match_rate": t.sample_match_rate,
                    "m8_only_ids": t.m8_only_ids[:20],
                    "m7_only_ids": t.m7_only_ids[:20],
                    "mismatches": t.mismatches[:10],
                }
                for name, t in self.tables.items()
            },
        }


# ============================================================
# 工具函数
# ============================================================
def _parse_datetime(val: Optional[str]) -> Optional[str]:
    """标准化时间字符串格式用于对比."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(str(val), fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return str(val)


def _normalize_json(val: Any) -> Any:
    """标准化 JSON 值用于对比."""
    if val is None:
        return None
    if isinstance(val, str):
        if not val.strip():
            return None
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _safe_str(val: Any, default: str = "") -> str:
    if val is None:
        return default
    return str(val)


# ============================================================
# 对账字段配置（M8字段 → M7字段映射，用于对比）
# ============================================================
COMPARE_FIELDS = {
    "workflow_definitions": [
        # (M8字段名, M7字段名, 类型)
        ("id", "id", "string"),
        ("name", "name", "string"),
        ("description", "description", "string"),
        ("category", "category", "string"),
        ("blocks", "blocks", "json"),
        ("status", "status", "string"),
        ("created_at", "created_at", "datetime"),
        ("updated_at", "updated_at", "datetime"),
        ("user_id", "created_by", "user_id"),  # M8 INTEGER → M7 String
    ],
    "workflow_runs": [
        ("id", "id", "string"),
        ("workflow_id", "workflow_id", "string"),
        ("workflow_name", "workflow_name", "string"),
        ("status", "status", "string"),
        ("inputs", "inputs", "json"),
        ("outputs", "outputs", "json"),
        ("error_message", "error", "string"),
        ("started_at", "started_at", "datetime"),
        ("finished_at", "finished_at", "datetime"),
        ("duration_ms", "duration_ms", "int"),
    ],
}


# ============================================================
# M8 读取
# ============================================================
class M8Source:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def count(self, table: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]

    def get_all_ids(self, table: str) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT id FROM {table} ORDER BY id")
        return [r[0] for r in cursor.fetchall()]

    def get_by_id(self, table: str, row_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_sample(self, table: str, limit: int) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(f"SELECT * FROM {table} ORDER BY id LIMIT ?", (limit,))
        return [dict(r) for r in cursor.fetchall()]


# ============================================================
# M7 读取
# ============================================================
class M7Source:
    def __init__(self, data_dir: Optional[str]):
        self.data_dir = data_dir
        self._session: Optional[Session] = None

    @property
    def session(self) -> Session:
        if self._session is None:
            init_db(self.data_dir)
            self._session = get_session()
        return self._session

    def close(self):
        if self._session:
            self._session.close()

    def count(self, model_class) -> int:
        return self.session.query(model_class).count()

    def get_all_ids(self, model_class) -> List[str]:
        rows = self.session.query(model_class.id).order_by(model_class.id).all()
        return [r[0] for r in rows]

    def get_by_id(self, model_class, row_id: str) -> Optional[Any]:
        return self.session.query(model_class).filter(model_class.id == row_id).first()

    def get_sample(self, model_class, limit: int) -> List[Any]:
        return self.session.query(model_class).order_by(model_class.id).limit(limit).all()


# ============================================================
# 对账执行器
# ============================================================
class WorkflowReconciler:
    """工作流数据对账执行器."""

    def __init__(
        self,
        m8_db_path: str,
        m7_data_dir: Optional[str],
        sample_size: int = 10,
    ):
        self.m8 = M8Source(m8_db_path)
        self.m7 = M7Source(m7_data_dir)
        self.sample_size = sample_size

        self.report = ReconcileReport(
            report_id=f"p2d_reconcile_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            generated_at=datetime.now().isoformat(),
            m8_db=m8_db_path,
            m7_data_dir=m7_data_dir or "默认 (~/.yunxi)",
        )

    def run(self) -> ReconcileReport:
        print("=" * 60)
        print("P2d 工作流引擎数据对账")
        print("=" * 60)

        self.m8.connect()

        try:
            self._reconcile_workflow_definitions()
            self._reconcile_workflow_runs()
        finally:
            self.m8.close()
            self.m7.close()

        self._print_summary()
        return self.report

    def _reconcile_workflow_definitions(self):
        """对账 workflow_definitions 表."""
        result = TableReconcileResult(table_name="workflow_definitions")
        result.sample_size = self.sample_size
        self.report.tables["workflow_definitions"] = result

        print(f"\n{'─' * 50}")
        print(f"对账: workflow_definitions")
        print(f"{'─' * 50}")

        # 1. 记录数对比
        result.m8_count = self.m8.count("workflow_definitions")
        result.m7_count = self.m7.count(WorkflowDefinition)
        result.count_match = result.m8_count == result.m7_count
        print(f"  记录数: M8={result.m8_count}, M7={result.m7_count} "
              f"{'✓' if result.count_match else '✗ 不匹配'}")

        if result.m8_count == 0 and result.m7_count == 0:
            print(f"  两边均为空表，跳过抽样对比")
            return

        # 2. ID 差异
        m8_ids = set(self.m8.get_all_ids("workflow_definitions"))
        m7_ids = set(self.m7.get_all_ids(WorkflowDefinition))
        result.m8_only_ids = sorted(m8_ids - m7_ids)
        result.m7_only_ids = sorted(m7_ids - m8_ids)

        if result.m8_only_ids:
            print(f"  仅 M8 存在的 ID: {len(result.m8_only_ids)} 个")
        if result.m7_only_ids:
            print(f"  仅 M7 存在的 ID: {len(result.m7_only_ids)} 个")

        # 3. 抽样字段级对比
        common_ids = sorted(m8_ids & m7_ids)
        sample_ids = common_ids[:self.sample_size]
        result.samples_checked = len(sample_ids)

        compare_fields = COMPARE_FIELDS["workflow_definitions"]

        for row_id in sample_ids:
            m8_row = self.m8.get_by_id("workflow_definitions", row_id)
            m7_obj = self.m7.get_by_id(WorkflowDefinition, row_id)

            if not m8_row or not m7_obj:
                result.samples_mismatched += 1
                result.mismatches.append({"id": row_id, "reason": "某端数据缺失"})
                continue

            field_diffs = {}
            for m8_field, m7_field, field_type in compare_fields:
                m8_val = m8_row.get(m8_field)
                m7_val = getattr(m7_obj, m7_field, None)

                # 类型标准化
                if field_type == "datetime":
                    m8_norm = _parse_datetime(m8_val)
                    m7_norm = _parse_datetime(m7_val)
                elif field_type == "json":
                    m8_norm = _normalize_json(m8_val)
                    m7_norm = _normalize_json(m7_val)
                elif field_type == "user_id":
                    # M8 INTEGER → M7 String 转换
                    m8_norm = _safe_str(m8_val, default="")
                    m7_norm = _safe_str(m7_val, default="")
                elif field_type == "int":
                    m8_norm = int(m8_val) if m8_val is not None else 0
                    m7_norm = int(m7_val) if m7_val is not None else 0
                else:
                    m8_norm = m8_val
                    m7_norm = m7_val

                if m8_norm != m7_norm:
                    field_diffs[m8_field] = {
                        "m8": m8_norm if not isinstance(m8_norm, (dict, list)) else str(m8_norm)[:100],
                        "m7": m7_norm if not isinstance(m7_norm, (dict, list)) else str(m7_norm)[:100],
                    }

            if field_diffs:
                result.samples_mismatched += 1
                result.mismatches.append({
                    "id": row_id,
                    "field_diffs": field_diffs,
                })
            else:
                result.samples_matched += 1

        print(f"  抽样对比: {result.samples_matched}/{result.samples_checked} 匹配 "
              f"({result.sample_match_rate})")

    def _reconcile_workflow_runs(self):
        """对账 workflow_runs 表."""
        result = TableReconcileResult(table_name="workflow_runs")
        result.sample_size = self.sample_size
        self.report.tables["workflow_runs"] = result

        print(f"\n{'─' * 50}")
        print(f"对账: workflow_runs")
        print(f"{'─' * 50}")

        # 1. 记录数对比
        result.m8_count = self.m8.count("workflow_runs")
        result.m7_count = self.m7.count(WorkflowRunRecord)
        result.count_match = result.m8_count == result.m7_count
        print(f"  记录数: M8={result.m8_count}, M7={result.m7_count} "
              f"{'✓' if result.count_match else '✗ 不匹配'}")

        if result.m8_count == 0 and result.m7_count == 0:
            print(f"  两边均为空表，跳过抽样对比")
            return

        # 2. ID 差异
        m8_ids = set(self.m8.get_all_ids("workflow_runs"))
        m7_ids = set(self.m7.get_all_ids(WorkflowRunRecord))
        result.m8_only_ids = sorted(m8_ids - m7_ids)
        result.m7_only_ids = sorted(m7_ids - m8_ids)

        if result.m8_only_ids:
            print(f"  仅 M8 存在的 ID: {len(result.m8_only_ids)} 个")
        if result.m7_only_ids:
            print(f"  仅 M7 存在的 ID: {len(result.m7_only_ids)} 个")

        # 3. 抽样字段级对比
        common_ids = sorted(m8_ids & m7_ids)
        sample_ids = common_ids[:self.sample_size]
        result.samples_checked = len(sample_ids)

        compare_fields = COMPARE_FIELDS["workflow_runs"]

        for row_id in sample_ids:
            m8_row = self.m8.get_by_id("workflow_runs", row_id)
            m7_obj = self.m7.get_by_id(WorkflowRunRecord, row_id)

            if not m8_row or not m7_obj:
                result.samples_mismatched += 1
                result.mismatches.append({"id": row_id, "reason": "某端数据缺失"})
                continue

            field_diffs = {}
            for m8_field, m7_field, field_type in compare_fields:
                m8_val = m8_row.get(m8_field)
                m7_val = getattr(m7_obj, m7_field, None)

                if field_type == "datetime":
                    m8_norm = _parse_datetime(m8_val)
                    m7_norm = _parse_datetime(m7_val)
                elif field_type == "json":
                    m8_norm = _normalize_json(m8_val)
                    m7_norm = _normalize_json(m7_val)
                elif field_type == "int":
                    m8_norm = int(m8_val) if m8_val is not None else 0
                    m7_norm = int(m7_val) if m7_val is not None else 0
                else:
                    m8_norm = m8_val
                    m7_norm = m7_val

                if m8_norm != m7_norm:
                    field_diffs[m8_field] = {
                        "m8": m8_norm if not isinstance(m8_norm, (dict, list)) else str(m8_norm)[:100],
                        "m7": m7_norm if not isinstance(m7_norm, (dict, list)) else str(m7_norm)[:100],
                    }

            if field_diffs:
                result.samples_mismatched += 1
                result.mismatches.append({
                    "id": row_id,
                    "field_diffs": field_diffs,
                })
            else:
                result.samples_matched += 1

        print(f"  抽样对比: {result.samples_matched}/{result.samples_checked} 匹配 "
              f"({result.sample_match_rate})")

    def _print_summary(self):
        print(f"\n{'=' * 60}")
        print("对账汇总")
        print(f"{'=' * 60}")

        all_pass = True
        for name, t in self.report.tables.items():
            status_icon = "✓" if t.status == "PASS" else "✗"
            print(f"\n  【{name}】 {status_icon} {t.status}")
            print(f"    记录数: M8={t.m8_count}, M7={t.m7_count} "
                  f"{'✓' if t.count_match else '✗'}")
            print(f"    抽样匹配: {t.sample_match_rate} "
                  f"({t.samples_matched}/{t.samples_checked})")
            if t.m8_only_ids:
                print(f"    仅 M8: {len(t.m8_only_ids)} 个")
            if t.m7_only_ids:
                print(f"    仅 M7: {len(t.m7_only_ids)} 个")
            if t.mismatches:
                print(f"    字段差异: {len(t.mismatches)} 条样本不一致")

            if t.status != "PASS":
                all_pass = False

        print(f"\n  总体结果: {'PASS ✓' if all_pass else 'FAIL ✗'}")
        print(f"{'=' * 60}")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="P2d 工作流引擎数据对账 - M8 vs M7"
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
        "--sample-size",
        type=int,
        default=10,
        help="每表抽样数量 (默认 10)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="对账报告输出路径 (JSON)",
    )

    args = parser.parse_args()

    reconciler = WorkflowReconciler(
        m8_db_path=args.m8_db,
        m7_data_dir=args.m7_data_dir,
        sample_size=args.sample_size,
    )

    report = reconciler.run()

    # 输出报告
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = PROJECT_ROOT / "data" / "migration_checkpoints" / f"p2d_reconcile_{report.report_id}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"\n对账报告已保存: {output_path}")

    # 退出码
    sys.exit(0 if report.overall_pass else 1)


if __name__ == "__main__":
    main()
