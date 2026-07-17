"""
M8 ↔ M4 P1a 批次数据对账脚本
============================

P1a 批次迁移配套工具：校验 M8 与 M4 中生活管理+学业规划数据的一致性。

对账内容：
- 各表记录数对比
- 抽样数据字段值对比（随机抽取10条）
- JSON字段序列化对比
- 输出不一致报告

输出：
- JSON 格式对账报告
- 控制台表格摘要
- 不一致数据详情

使用方式：
    python reconcile_life_study.py [--table life_schedules] [--output report.json]
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

M8_DB_PATH = PROJECT_ROOT.parent / "M8-control-tower" / "backend" / "data" / "m8.db"
M4_DB_PATH = PROJECT_ROOT / "data" / "m4.db"


# ---------------------------------------------------------------------------
# 对账配置
# ---------------------------------------------------------------------------

# 表对账配置：M8表名 → M4表名 + 字段映射
TABLE_CONFIG: Dict[str, Dict[str, Any]] = {
    # ---------- 生活管理 9 表 ----------
    "life_schedules": {
        "m8_table": "life_schedules",
        "m4_table": "life_schedules",
        "m8_pk": "schedule_id",
        "m4_pk": "schedule_id",
        "compare_fields": [
            "schedule_id", "title", "description", "start_time", "end_time",
            "time_range", "date", "repeat_type", "category", "tag_color",
            "all_day", "priority", "status",
        ],
        "special_fields": {
            "user_id": "str_compare",  # M8 int → M4 str
            "created_at": "datetime_compare",
        },
    },
    "life_todos": {
        "m8_table": "life_todos",
        "m4_table": "life_todos",
        "m8_pk": "todo_id",
        "m4_pk": "todo_id",
        "compare_fields": [
            "todo_id", "title", "description", "priority", "status",
            "progress", "due_date", "category",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
            "completed_at": "datetime_compare",
        },
    },
    "life_habits": {
        "m8_table": "life_habits",
        "m4_table": "life_habits",
        "m8_pk": "habit_id",
        "m4_pk": "habit_id",
        "compare_fields": [
            "habit_id", "name", "description", "category", "icon",
            "streak", "longest_streak", "target_count", "current_count",
            "done", "frequency", "status",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
        },
    },
    "life_habit_records": {
        "m8_table": "life_habit_records",
        "m4_table": "life_habit_records",
        "m8_pk": "id",
        "m4_pk": "id",
        "compare_fields": [
            "id", "habit_id", "date", "completed", "note",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
        },
    },
    "life_scenes": {
        "m8_table": "life_scenes",
        "m4_table": "life_scenes",
        "m8_pk": "scene_id",
        "m4_pk": "scene_id",
        "compare_fields": [
            "scene_id", "name", "description", "icon", "active", "is_active",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
            "settings_json": "json_compare",
        },
    },
    "life_rules": {
        "m8_table": "life_rules",
        "m4_table": "life_rules",
        "m8_pk": "rule_id",
        "m4_pk": "rule_id",
        "compare_fields": [
            "rule_id", "title", "description", "condition", "action",
            "category", "enabled",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
        },
    },
    "life_finance_categories": {
        "m8_table": "life_finance_categories",
        "m4_table": "life_finance_categories",
        "m8_pk": "category_id",
        "m4_pk": "category_id",
        "compare_fields": [
            "category_id", "name", "type", "budget", "spent",
            "percentage", "color",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
        },
    },
    "life_finance_records": {
        "m8_table": "life_finance_records",
        "m4_table": "life_finance_records",
        "m8_pk": "id",
        "m4_pk": "id",
        "compare_fields": [
            "id", "type", "amount", "category", "description",
            "transaction_date",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "created_at": "datetime_compare",
        },
    },
    "life_meta": {
        "m8_table": "life_meta",
        "m4_table": "life_meta",
        "m8_pk": "meta_key",
        "m4_pk": "meta_key",
        "compare_fields": ["meta_key"],
        "special_fields": {
            "user_id": "str_compare",
            "meta_value": "json_compare",
        },
        "composite_key": ["user_id", "meta_key"],
    },

    # ---------- 学业规划 7 表 ----------
    "study_goals": {
        "m8_table": "study_goals",
        "m4_table": "study_goals",
        "m8_pk": "goal_id",
        "m4_pk": "goal_id",
        "compare_fields": [
            "goal_id", "title", "description", "parent_id", "status",
            "progress", "priority", "deadline", "order_index", "icon",
            "expanded", "level",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "extra": "json_compare",
        },
        "m4_extra_fields": ["created_at", "updated_at"],  # M4新增，M8没有
    },
    "study_plans": {
        "m8_table": "study_plans",
        "m4_table": "study_plans",
        "m8_pk": "plan_id",
        "m4_pk": "plan_id",
        "compare_fields": [
            "plan_id", "title", "content", "subject", "status",
            "start_time", "end_time", "date", "duration", "priority",
            "completed",
        ],
        "special_fields": {
            "user_id": "str_compare",
        },
        "m4_extra_fields": ["created_at", "updated_at"],
    },
    "study_notes": {
        "m8_table": "study_notes",
        "m4_table": "study_notes",
        "m8_pk": "note_id",
        "m4_pk": "note_id",
        "compare_fields": [
            "note_id", "title", "content", "category", "important",
            "date_label",
        ],
        "special_fields": {
            "user_id": "str_compare",
            "tags": "json_compare",
            "created_at": "datetime_compare",
            "updated_at": "datetime_compare",
        },
    },
    "study_knowledge_categories": {
        "m8_table": "study_knowledge_categories",
        "m4_table": "study_knowledge_categories",
        "m8_pk": "category_id",
        "m4_pk": "category_id",
        "compare_fields": [
            "category_id", "name", "description", "parent_id",
            "note_count", "icon", "unit",
        ],
        "special_fields": {
            "user_id": "str_compare",
        },
        "m4_extra_fields": ["created_at"],
    },
    "study_exams": {
        "m8_table": "study_exams",
        "m4_table": "study_exams",
        "m8_pk": "exam_id",
        "m4_pk": "exam_id",
        "compare_fields": [
            "exam_id", "name", "subject", "exam_date", "location",
            "score", "status", "urgency", "color_theme",
        ],
        "special_fields": {
            "user_id": "str_compare",
        },
        "m4_extra_fields": ["created_at"],
    },
    "study_progress": {
        "m8_table": "study_progress",
        "m4_table": "study_progress",
        "m8_pk": "id",
        "m4_pk": "id",
        "compare_fields": [
            "id", "subject", "progress", "total_hours",
            "mastered_topics", "total_topics", "color",
        ],
        "special_fields": {
            "user_id": "str_compare",
        },
        "m4_extra_fields": ["created_at", "updated_at"],
    },
    "study_meta": {
        "m8_table": "study_meta",
        "m4_table": "study_meta",
        "m8_pk": "meta_key",
        "m4_pk": "meta_key",
        "compare_fields": ["meta_key"],
        "special_fields": {
            "user_id": "str_compare",
            "meta_value": "json_compare",
        },
        "composite_key": ["user_id", "meta_key"],
        "m4_extra_fields": ["created_at", "updated_at"],
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


def get_m4_connection() -> sqlite3.Connection:
    if not M4_DB_PATH.exists():
        raise FileNotFoundError(f"M4 数据库不存在: {M4_DB_PATH}")
    conn = sqlite3.connect(f"file:{M4_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 比较工具函数
# ---------------------------------------------------------------------------

def compare_values(m8_val: Any, m4_val: Any, compare_type: str = "exact") -> bool:
    """比较两个值，支持不同类型的比较策略."""

    if compare_type == "str_compare":
        # user_id 类型转换比较
        m8_str = str(m8_val) if m8_val is not None else "default"
        m4_str = str(m4_val) if m4_val is not None else "default"
        return m8_str == m4_str

    elif compare_type == "datetime_compare":
        # 日期时间比较（格式可能不同）
        if m8_val is None and m4_val is None:
            return True
        if m8_val is None or m4_val is None:
            return False
        # 规范化为字符串比较
        m8_str = str(m8_val).replace("T", " ")
        m4_str = str(m4_val).replace("T", " ")
        # 截断到秒级比较
        m8_str = m8_str[:19]
        m4_str = m4_str[:19]
        return m8_str == m4_str

    elif compare_type == "json_compare":
        # JSON字段比较（先解析再比较）
        if m8_val is None and m4_val is None:
            return True
        if m8_val is None or m4_val is None:
            return False
        try:
            m8_parsed = json.loads(m8_val) if isinstance(m8_val, str) else m8_val
            m4_parsed = json.loads(m4_val) if isinstance(m4_val, str) else m4_val
            return m8_parsed == m4_parsed
        except (json.JSONDecodeError, TypeError):
            return str(m8_val) == str(m4_val)

    else:
        # 精确比较
        # 布尔值特殊处理（SQLite中布尔值是0/1）
        if isinstance(m8_val, int) and isinstance(m4_val, int):
            return m8_val == m4_val
        # 处理 None 和 空字符串
        if (m8_val is None or m8_val == "") and (m4_val is None or m4_val == ""):
            return True
        return m8_val == m4_val


# ---------------------------------------------------------------------------
# 单表对账
# ---------------------------------------------------------------------------

def reconcile_table(
    table_key: str,
    config: Dict[str, Any],
    m8_conn: sqlite3.Connection,
    m4_conn: sqlite3.Connection,
    sample_size: int = 10,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对单张表进行对账

    Args:
        table_key: 表配置键名
        config: 表配置字典
        m8_conn: M8 数据库连接
        m4_conn: M4 数据库连接
        sample_size: 抽样数量
        user_id: 按用户ID过滤对账（推荐使用，避免多用户数据混淆）

    Returns:
        对账结果字典
    """
    m8_table = config["m8_table"]
    m4_table = config["m4_table"]
    m8_pk = config["m8_pk"]
    m4_pk = config["m4_pk"]
    compare_fields = config["compare_fields"]
    special_fields = config.get("special_fields", {})
    composite_key = config.get("composite_key")

    # 构造 user_id 过滤条件
    m8_user_filter = ""
    m4_user_filter = ""
    m8_user_params: Tuple = ()
    m4_user_params: Tuple = ()

    if user_id is not None:
        # M8 中 user_id 是整数
        m8_user_filter = " WHERE user_id = ?"
        m8_user_params = (int(user_id) if user_id.isdigit() else user_id,)
        # M4 中 user_id 是字符串
        m4_user_filter = " WHERE user_id = ?"
        m4_user_params = (str(user_id),)

    result: Dict[str, Any] = {
        "table_key": table_key,
        "m8_table": m8_table,
        "m4_table": m4_table,
        "m8_count": 0,
        "m4_count": 0,
        "count_match": False,
        "count_diff": 0,
        "sample_size": 0,
        "sample_checked": 0,
        "sample_matched": 0,
        "sample_mismatched": 0,
        "mismatched_details": [],
        "only_in_m8": [],
        "only_in_m4": [],
        "status": "pending",
        "user_id_filter": user_id,
    }

    try:
        # 1. 数量对账
        m8_cursor = m8_conn.execute(
            f"SELECT COUNT(*) as cnt FROM {m8_table}{m8_user_filter}",
            m8_user_params,
        )
        result["m8_count"] = m8_cursor.fetchone()["cnt"]

        # 检查表是否存在于M4
        m4_check = m4_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (m4_table,)
        )
        if m4_check.fetchone() is None:
            result["status"] = "m4_table_missing"
            result["error"] = f"M4 表 {m4_table} 不存在"
            return result

        m4_cursor = m4_conn.execute(
            f"SELECT COUNT(*) as cnt FROM {m4_table}{m4_user_filter}",
            m4_user_params,
        )
        result["m4_count"] = m4_cursor.fetchone()["cnt"]
        result["count_diff"] = result["m4_count"] - result["m8_count"]
        result["count_match"] = result["m8_count"] == result["m4_count"]

        if result["m8_count"] == 0 and result["m4_count"] == 0:
            result["status"] = "empty"
            return result

        # 2. 抽样对比
        if result["m8_count"] > 0:
            # 获取M8的所有主键值，随机抽样
            if composite_key:
                key_fields = ", ".join(composite_key)
                m8_keys_cursor = m8_conn.execute(
                    f"SELECT {key_fields} FROM {m8_table}{m8_user_filter} ORDER BY rowid",
                    m8_user_params,
                )
                m8_keys = [tuple(row[k] for k in composite_key) for row in m8_keys_cursor.fetchall()]
            else:
                m8_keys_cursor = m8_conn.execute(
                    f"SELECT {m8_pk} FROM {m8_table}{m8_user_filter} ORDER BY rowid",
                    m8_user_params,
                )
                m8_keys = [row[m8_pk] for row in m8_keys_cursor.fetchall()]

            actual_sample = min(sample_size, len(m8_keys))
            result["sample_size"] = actual_sample

            if actual_sample > 0:
                # 随机抽样
                random.seed(42)  # 固定种子，保证可重复
                sample_keys = random.sample(m8_keys, actual_sample)

                # 获取M8抽样数据
                all_fields = compare_fields + list(special_fields.keys())
                fields_str = ", ".join(all_fields)

                m8_sample = {}
                for key in sample_keys:
                    if composite_key:
                        where_clause = " AND ".join(f"{k} = ?" for k in composite_key)
                        cursor = m8_conn.execute(
                            f"SELECT {fields_str} FROM {m8_table} WHERE {where_clause}",
                            key
                        )
                    else:
                        cursor = m8_conn.execute(
                            f"SELECT {fields_str} FROM {m8_table} WHERE {m8_pk} = ?",
                            (key,)
                        )
                    row = cursor.fetchone()
                    if row:
                        m8_sample[key] = dict(row)

                # 获取M4对应数据（加上user_id过滤）
                m4_sample = {}
                for key in sample_keys:
                    if composite_key:
                        where_clause = " AND ".join(f"{k} = ?" for k in composite_key)
                        # user_id 可能是字符串类型
                        m4_key = tuple(
                            str(v) if composite_key[i] == "user_id" else v
                            for i, v in enumerate(key)
                        )
                        cursor = m4_conn.execute(
                            f"SELECT {fields_str} FROM {m4_table} WHERE {where_clause}",
                            m4_key
                        )
                    else:
                        # 非复合键的情况，需要加上user_id过滤
                        if user_id is not None:
                            where_clause = f"{m4_pk} = ? AND user_id = ?"
                            params = (key, str(user_id))
                        else:
                            where_clause = f"{m4_pk} = ?"
                            params = (key,)
                        cursor = m4_conn.execute(
                            f"SELECT {fields_str} FROM {m4_table} WHERE {where_clause}",
                            params
                        )
                    row = cursor.fetchone()
                    if row:
                        m4_sample[key] = dict(row)

                result["only_in_m8"] = [str(k) for k in m8_sample.keys() if k not in m4_sample][:20]
                result["only_in_m4"] = [str(k) for k in m4_sample.keys() if k not in m8_sample][:20]

                common_keys = set(m8_sample.keys()) & set(m4_sample.keys())
                result["sample_checked"] = len(common_keys)

                for key in common_keys:
                    m8_rec = m8_sample[key]
                    m4_rec = m4_sample[key]
                    diff_fields = []

                    # 比较普通字段
                    for field in compare_fields:
                        m8_val = m8_rec.get(field)
                        m4_val = m4_rec.get(field)
                        if not compare_values(m8_val, m4_val, "exact"):
                            diff_fields.append(field)

                    # 比较特殊字段
                    for field, cmp_type in special_fields.items():
                        m8_val = m8_rec.get(field)
                        m4_val = m4_rec.get(field)
                        if not compare_values(m8_val, m4_val, cmp_type):
                            diff_fields.append(field)

                    if diff_fields:
                        result["sample_mismatched"] += 1
                        if len(result["mismatched_details"]) < 10:
                            result["mismatched_details"].append({
                                "pk": str(key),
                                "fields": diff_fields,
                                "m8_values": {f: _safe_str(m8_rec.get(f)) for f in diff_fields},
                                "m4_values": {f: _safe_str(m4_rec.get(f)) for f in diff_fields},
                            })
                    else:
                        result["sample_matched"] += 1

        # 3. 状态判定
        if result["count_match"] and result["sample_mismatched"] == 0:
            result["status"] = "passed"
        elif result["count_match"] and result["sample_mismatched"] > 0:
            result["status"] = "count_pass_sample_fail"
        elif not result["count_match"] and result["sample_mismatched"] == 0:
            result["status"] = "count_mismatch_sample_pass"
        else:
            result["status"] = "failed"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def _safe_str(val: Any, max_len: int = 100) -> str:
    """安全转换为字符串，限制长度."""
    if val is None:
        return "None"
    s = str(val)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s


# ---------------------------------------------------------------------------
# 生成报告
# ---------------------------------------------------------------------------

def generate_report(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """生成完整的对账报告."""
    total_m8 = sum(r["m8_count"] for r in results.values())
    total_m4 = sum(r["m4_count"] for r in results.values())

    passed = [k for k, r in results.items() if r["status"] == "passed"]
    failed = [k for k, r in results.items() if r["status"] in (
        "count_pass_sample_fail", "count_mismatch_sample_pass", "failed", "error", "m4_table_missing"
    )]
    empty = [k for k, r in results.items() if r["status"] == "empty"]

    overall = "PASSED" if not failed else "FAILED"

    # 分类统计
    life_tables = [k for k in results if k.startswith("life_")]
    study_tables = [k for k in results if k.startswith("study_")]

    return {
        "report_time": datetime.now().isoformat(),
        "batch": "P1a",
        "description": "生活管理 + 学业规划数据迁移对账",
        "m8_database": str(M8_DB_PATH),
        "m4_database": str(M4_DB_PATH),
        "overall_status": overall,
        "total_tables": len(results),
        "total_m8_records": total_m8,
        "total_m4_records": total_m4,
        "total_diff": total_m4 - total_m8,
        "passed_tables": passed,
        "failed_tables": failed,
        "empty_tables": empty,
        "life_tables": life_tables,
        "study_tables": study_tables,
        "table_results": results,
    }


def print_summary(report: Dict[str, Any]) -> None:
    """在控制台打印对账摘要."""
    print("\n" + "=" * 75)
    print("  M8 ↔ M4 P1a 批次数据对账报告 (生活管理 + 学业规划)")
    print("=" * 75)
    print(f"  对账时间: {report['report_time']}")
    print(f"  总体状态: {report['overall_status']}")
    print(f"  总表数: {report['total_tables']} (通过: {len(report['passed_tables'])}, "
          f"失败: {len(report['failed_tables'])}, 空表: {len(report['empty_tables'])})")
    print(f"  M8 总记录: {report['total_m8_records']:,}")
    print(f"  M4 总记录: {report['total_m4_records']:,}")
    print(f"  差异: {report['total_diff']:+,}")
    print("-" * 75)

    # 生活管理部分
    print(f"\n  【生活管理】 ({len(report['life_tables'])} 表)")
    print(f"  {'表名':<30} {'M8数量':>10} {'M4数量':>10} {'差异':>8} {'抽样':>6} {'状态':<12}")
    print("  " + "-" * 70)

    for table_key in report["life_tables"]:
        result = report["table_results"][table_key]
        status_icon = _status_icon(result["status"])
        sample_info = f"{result['sample_matched']}/{result['sample_checked']}" if result["sample_checked"] > 0 else "-"
        print(
            f"  {table_key:<30} {result['m8_count']:>10,} "
            f"{result['m4_count']:>10,} {result['count_diff']:>+8,} "
            f"{sample_info:>6} {status_icon:<12}"
        )

    # 学业规划部分
    print(f"\n  【学业规划】 ({len(report['study_tables'])} 表)")
    print(f"  {'表名':<30} {'M8数量':>10} {'M4数量':>10} {'差异':>8} {'抽样':>6} {'状态':<12}")
    print("  " + "-" * 70)

    for table_key in report["study_tables"]:
        result = report["table_results"][table_key]
        status_icon = _status_icon(result["status"])
        sample_info = f"{result['sample_matched']}/{result['sample_checked']}" if result["sample_checked"] > 0 else "-"
        print(
            f"  {table_key:<30} {result['m8_count']:>10,} "
            f"{result['m4_count']:>10,} {result['count_diff']:>+8,} "
            f"{sample_info:>6} {status_icon:<12}"
        )

    # 打印失败详情
    if report["failed_tables"]:
        print(f"\n  失败/异常的表: {', '.join(report['failed_tables'])}")
        for table_key in report["failed_tables"]:
            result = report["table_results"][table_key]
            if result.get("mismatched_details"):
                print(f"\n  [{table_key}] 抽样不一致详情 (前5条):")
                for detail in result["mismatched_details"][:5]:
                    print(f"    - pk={detail['pk']}: 字段 {', '.join(detail['fields'])} 不一致")
                    for f in detail["fields"]:
                        print(f"      M8: {detail['m8_values'].get(f, '?')}")
                        print(f"      M4: {detail['m4_values'].get(f, '?')}")
            if result.get("error"):
                print(f"    错误: {result['error']}")

    print("\n" + "=" * 75)


def _status_icon(status: str) -> str:
    """状态图标映射."""
    return {
        "passed": "PASS",
        "empty": "EMPTY",
        "count_pass_sample_fail": "SAMPLE!",
        "count_mismatch_sample_pass": "COUNT!",
        "failed": "FAIL",
        "error": "ERROR",
        "m4_table_missing": "NO TABLE",
        "pending": "PENDING",
    }.get(status, "?")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def run_reconcile(
    tables: List[str] = None,
    sample_size: int = 10,
    output_path: str = None,
    user_id: str = None,
) -> Dict[str, Any]:
    """
    执行对账

    Args:
        tables: 指定要对账的表，None 表示全部
        sample_size: 抽样数量
        output_path: 报告输出路径
        user_id: 按用户ID过滤对账

    Returns:
        对账报告字典
    """
    # 确定要对账的表
    if tables:
        invalid = [t for t in tables if t not in TABLE_CONFIG]
        if invalid:
            raise ValueError(f"无效的表名: {invalid}，可选: {list(TABLE_CONFIG.keys())}")
        targets = {k: TABLE_CONFIG[k] for k in tables}
    else:
        targets = TABLE_CONFIG

    print(f"\n开始对账，共 {len(targets)} 张表，每表抽样 {sample_size} 条...")
    if user_id:
        print(f"  过滤用户: user_id={user_id}")

    m8_conn = get_m8_connection()
    m4_conn = get_m4_connection()

    results = {}
    for table_key, config in targets.items():
        print(f"  对账: {table_key}...", end=" ")
        result = reconcile_table(
            table_key, config, m8_conn, m4_conn, sample_size, user_id
        )
        results[table_key] = result
        print(result["status"])

    m8_conn.close()
    m4_conn.close()

    # 生成报告
    report = generate_report(results)
    report["user_id_filter"] = user_id

    # 打印摘要
    print_summary(report)

    # 保存报告
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  报告已保存: {output_file}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="M8 ↔ M4 P1a 批次数据对账工具 (生活管理 + 学业规划)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 对账所有表
  python reconcile_life_study.py

  # 按用户ID过滤对账（推荐，避免多用户数据混淆）
  python reconcile_life_study.py --user-id 1

  # 只对账日程表
  python reconcile_life_study.py --table life_schedules --user-id 1

  # 对账多张表，保存报告
  python reconcile_life_study.py --table life_schedules,study_goals --output report.json

  # 增加抽样数量
  python reconcile_life_study.py --sample-size 20 --user-id 1
        """,
    )
    parser.add_argument(
        "--table", "-t",
        type=str,
        default=None,
        help="指定对账的表，逗号分隔",
    )
    parser.add_argument(
        "--sample-size", "-s",
        type=int,
        default=10,
        help="每表抽样对比数量（默认 10）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="报告输出路径（JSON格式）",
    )
    parser.add_argument(
        "--user-id", "-u",
        type=str,
        default=None,
        help="按用户ID过滤对账（M8中为整数，M4中为字符串）",
    )

    args = parser.parse_args()

    tables = args.table.split(",") if args.table else None

    try:
        report = run_reconcile(
            tables=tables,
            sample_size=args.sample_size,
            output_path=args.output,
            user_id=args.user_id,
        )
        if report["overall_status"] == "FAILED":
            sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 对账失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
