"""
M8 ↔ M6 可穿戴数据对账脚本
==========================

P0 批次迁移配套工具：校验 M8 与 M6 中可穿戴数据的一致性。

对账内容：
- 设备表数据一致性
- 健康数据条数一致性
- 通知表数据一致性
- 配置表数据一致性
- 关键字段抽样对比

输出：
- JSON 格式对账报告
- 控制台表格摘要
- 不一致数据详情

使用方式：
    python reconcile_wearable.py [--table devices] [--output report.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

M8_DB_PATH = PROJECT_ROOT / "M8-control-tower" / "backend" / "data" / "m8.db"
M6_DB_PATH = PROJECT_ROOT / "M6-hardware-peripheral" / "data" / "m6_sensors.db"


# ---------------------------------------------------------------------------
# 对账配置
# ---------------------------------------------------------------------------

# 表名映射：M8表名 → M6表名
TABLE_MAPPING = {
    "devices": {
        "m8_table": "watch_devices",
        "m6_table": "wearable_devices",
        "m8_pk": "device_id",
        "m6_pk": "device_id",
        "fields": [
            "device_id", "name", "device_type", "brand", "model",
            "status", "mac_address",
        ],
    },
    "health_data": {
        "m8_table": "watch_health_data",
        "m6_table": "wearable_health_data",
        "m8_pk": "id",
        "m6_pk": "id",
        "count_only": True,  # 健康数据只对账数量，不对账逐条内容
        "fields": [
            "device_id", "data_type", "value", "unit",
        ],
    },
    "notifications": {
        "m8_table": "watch_notifications",
        "m6_table": "wearable_notifications",
        "m8_pk": "notification_id",
        "m6_pk": "notification_id",
        "fields": [
            "notification_id", "device_id", "title", "status", "source",
        ],
    },
    "settings": {
        "m8_table": "watch_settings",
        "m6_table": "wearable_settings",
        "m8_pk": "device_id",
        "m6_pk": "device_id",
        "fields": ["device_id"],
    },
}


# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------

def get_m8_connection() -> sqlite3.Connection:
    if not M8_DB_PATH.exists():
        raise FileNotFoundError(f"M8 数据库不存在: {M8_DB_PATH}")
    conn = sqlite3.connect(f"file:{M8_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_m6_connection() -> sqlite3.Connection:
    if not M6_DB_PATH.exists():
        raise FileNotFoundError(f"M6 数据库不存在: {M6_DB_PATH}")
    conn = sqlite3.connect(f"file:{M6_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 对账工具函数
# ---------------------------------------------------------------------------

def get_table_count(conn: sqlite3.Connection, table: str) -> int:
    """获取表行数"""
    cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
    return cursor.fetchone()["cnt"]


def get_table_sample(
    conn: sqlite3.Connection,
    table: str,
    fields: List[str],
    pk: str,
    limit: int = 100,
) -> Dict[str, Dict[str, Any]]:
    """获取表抽样数据，以 pk 为键"""
    fields_str = ", ".join(fields)
    cursor = conn.execute(
        f"SELECT {fields_str} FROM {table} ORDER BY {pk} LIMIT ?",
        (limit,),
    )
    return {row[pk]: dict(row) for row in cursor.fetchall()}


def compare_records(
    m8_record: Dict[str, Any],
    m6_record: Dict[str, Any],
    fields: List[str],
) -> List[str]:
    """对比两条记录的指定字段，返回不一致的字段列表"""
    diffs = []
    for field in fields:
        m8_val = m8_record.get(field)
        m6_val = m6_record.get(field)

        # 特殊处理：user_id 类型可能不同（M8 是 int，M6 是 str）
        if field == "user_id":
            if str(m8_val) != str(m6_val):
                diffs.append(field)
            continue

        if m8_val != m6_val:
            diffs.append(field)
    return diffs


# ---------------------------------------------------------------------------
# 单表对账
# ---------------------------------------------------------------------------

def reconcile_table(
    table_key: str,
    config: Dict[str, Any],
    m8_conn: sqlite3.Connection,
    m6_conn: sqlite3.Connection,
    sample_size: int = 100,
) -> Dict[str, Any]:
    """
    对单张表进行对账

    Returns:
        对账结果字典
    """
    m8_table = config["m8_table"]
    m6_table = config["m6_table"]
    m8_pk = config["m8_pk"]
    m6_pk = config["m6_pk"]
    fields = config["fields"]
    count_only = config.get("count_only", False)

    result = {
        "table_key": table_key,
        "m8_table": m8_table,
        "m6_table": m6_table,
        "m8_count": 0,
        "m6_count": 0,
        "count_match": False,
        "count_diff": 0,
        "sample_checked": 0,
        "sample_matched": 0,
        "sample_mismatched": 0,
        "mismatched_details": [],
        "only_in_m8": [],
        "only_in_m6": [],
        "status": "pending",
    }

    try:
        # 1. 数量对账
        result["m8_count"] = get_table_count(m8_conn, m8_table)
        result["m6_count"] = get_table_count(m6_conn, m6_table)
        result["count_diff"] = result["m6_count"] - result["m8_count"]
        result["count_match"] = result["m8_count"] == result["m6_count"]

        if count_only:
            # 只对账数量的表（如健康数据）
            result["status"] = "count_only"
            return result

        # 2. 抽样对比
        m8_sample = get_table_sample(m8_conn, m8_table, fields, m8_pk, sample_size)
        m6_sample = get_table_sample(m6_conn, m6_table, fields, m6_pk, sample_size)

        m8_keys = set(m8_sample.keys())
        m6_keys = set(m6_sample.keys())

        result["only_in_m8"] = list(m8_keys - m6_keys)[:20]
        result["only_in_m6"] = list(m6_keys - m8_keys)[:20]

        common_keys = m8_keys & m6_keys
        result["sample_checked"] = len(common_keys)

        for key in common_keys:
            diffs = compare_records(m8_sample[key], m6_sample[key], fields)
            if diffs:
                result["sample_mismatched"] += 1
                if len(result["mismatched_details"]) < 10:  # 最多保留10条详情
                    result["mismatched_details"].append({
                        "pk": key,
                        "fields": diffs,
                        "m8_values": {f: m8_sample[key].get(f) for f in diffs},
                        "m6_values": {f: m6_sample[key].get(f) for f in diffs},
                    })
            else:
                result["sample_matched"] += 1

        # 3. 状态判定
        if result["count_match"] and result["sample_mismatched"] == 0:
            result["status"] = "passed"
        elif result["count_match"]:
            result["status"] = "count_pass_sample_fail"
        else:
            result["status"] = "count_mismatch"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 生成报告
# ---------------------------------------------------------------------------

def generate_report(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """生成完整的对账报告"""
    total_m8 = sum(r["m8_count"] for r in results.values())
    total_m6 = sum(r["m6_count"] for r in results.values())

    passed_tables = [k for k, r in results.items() if r["status"] == "passed"]
    failed_tables = [k for k, r in results.items() if r["status"] not in ("passed", "count_only", "pending")]
    count_only_tables = [k for k, r in results.items() if r["status"] == "count_only"]

    overall = "PASSED" if not failed_tables else "FAILED"

    return {
        "report_time": datetime.now().isoformat(),
        "m8_database": str(M8_DB_PATH),
        "m6_database": str(M6_DB_PATH),
        "overall_status": overall,
        "total_m8_records": total_m8,
        "total_m6_records": total_m6,
        "total_diff": total_m6 - total_m8,
        "passed_tables": passed_tables,
        "failed_tables": failed_tables,
        "count_only_tables": count_only_tables,
        "table_results": results,
    }


def print_summary(report: Dict[str, Any]) -> None:
    """在控制台打印对账摘要"""
    print("\n" + "=" * 70)
    print("  M8 ↔ M6 可穿戴数据对账报告")
    print("=" * 70)
    print(f"  对账时间: {report['report_time']}")
    print(f"  总体状态: {report['overall_status']}")
    print(f"  M8 总记录: {report['total_m8_records']:,}")
    print(f"  M6 总记录: {report['total_m6_records']:,}")
    print(f"  差异: {report['total_diff']:+,}")
    print("-" * 70)

    print(f"\n  {'表名':<15} {'M8数量':>10} {'M6数量':>10} {'差异':>8} {'状态':<15}")
    print("  " + "-" * 62)

    for table_key, result in report["table_results"].items():
        status_icon = {
            "passed": "✓ PASS",
            "count_only": "○ COUNT",
            "count_mismatch": "✗ COUNT",
            "count_pass_sample_fail": "△ SAMPLE",
            "error": "✗ ERROR",
        }.get(result["status"], "?")

        print(
            f"  {table_key:<15} {result['m8_count']:>10,} "
            f"{result['m6_count']:>10,} {result['count_diff']:>+8,} "
            f"{status_icon:<15}"
        )

    # 打印失败详情
    failed = report["failed_tables"]
    if failed:
        print(f"\n  失败的表: {', '.join(failed)}")
        for table_key in failed:
            result = report["table_results"][table_key]
            if result.get("mismatched_details"):
                print(f"\n  [{table_key}] 抽样不一致详情 (前10条):")
                for detail in result["mismatched_details"][:5]:
                    print(f"    - {result['m8_pk'] if False else 'pk'}={detail['pk']}: "
                          f"字段 {', '.join(detail['fields'])} 不一致")

    print("\n" + "=" * 70)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_reconcile(
    tables: List[str] = None,
    sample_size: int = 100,
    output_path: str = None,
) -> Dict[str, Any]:
    """
    执行对账

    Args:
        tables: 指定要对账的表，None 表示全部
        sample_size: 抽样数量
        output_path: 报告输出路径

    Returns:
        对账报告字典
    """
    # 确定要对账的表
    if tables:
        invalid = [t for t in tables if t not in TABLE_MAPPING]
        if invalid:
            raise ValueError(f"无效的表名: {invalid}，可选: {list(TABLE_MAPPING.keys())}")
        targets = {k: TABLE_MAPPING[k] for k in tables}
    else:
        targets = TABLE_MAPPING

    print(f"\n开始对账，共 {len(targets)} 张表...")

    m8_conn = get_m8_connection()
    m6_conn = get_m6_connection()

    results = {}
    for table_key, config in targets.items():
        print(f"  对账: {table_key}...", end=" ")
        result = reconcile_table(table_key, config, m8_conn, m6_conn, sample_size)
        results[table_key] = result
        print(result["status"])

    m8_conn.close()
    m6_conn.close()

    # 生成报告
    report = generate_report(results)

    # 打印摘要
    print_summary(report)

    # 保存报告
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n  报告已保存: {output_file}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="M8 ↔ M6 可穿戴数据对账工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 对账所有表
  python reconcile_wearable.py

  # 只对账设备表
  python reconcile_wearable.py --table devices

  # 对账多张表，保存报告
  python reconcile_wearable.py --table devices,notifications --output report.json

  # 增加抽样数量
  python reconcile_wearable.py --sample-size 500
        """,
    )
    parser.add_argument(
        "--table", "-t",
        type=str,
        default=None,
        help="指定对账的表，逗号分隔，可选: devices, health_data, notifications, settings",
    )
    parser.add_argument(
        "--sample-size", "-s",
        type=int,
        default=100,
        help="抽样对比数量（默认 100）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="报告输出路径（JSON格式）",
    )

    args = parser.parse_args()

    tables = args.table.split(",") if args.table else None

    try:
        report = run_reconcile(
            tables=tables,
            sample_size=args.sample_size,
            output_path=args.output,
        )
        if report["overall_status"] == "FAILED":
            sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 对账失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
