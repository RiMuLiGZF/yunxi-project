"""
产物搜索工具 (Artifact Search)

支持按名称、模块、类型、标签搜索产物，支持模糊匹配，提供命令行接口。
"""

import json
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def get_index_path() -> Path:
    """获取索引文件路径。"""
    return Path(__file__).resolve().parent.parent / "index.json"


def load_index() -> dict:
    """加载索引文件。"""
    index_path = get_index_path()
    if not index_path.exists():
        return {"artifacts": {}, "artifact_count": 0}
    try:
        with open(index_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"artifacts": {}, "artifact_count": 0}


def fuzzy_match(text: str, pattern: str) -> float:
    """
    计算模糊匹配得分（0-1）。

    使用简单的子串匹配 + 字符包含率计算。
    """
    if not pattern:
        return 1.0
    if not text:
        return 0.0

    text_lower = text.lower()
    pattern_lower = pattern.lower()

    # 完全匹配
    if text_lower == pattern_lower:
        return 1.0

    # 子串匹配
    if pattern_lower in text_lower:
        return 0.8 + 0.2 * (len(pattern_lower) / len(text_lower))

    # 字符包含率
    pattern_chars = set(pattern_lower)
    text_chars = set(text_lower)
    if not pattern_chars:
        return 0.0
    overlap = pattern_chars & text_chars
    char_ratio = len(overlap) / len(pattern_chars)

    # 顺序匹配（字符按顺序出现）
    if char_ratio > 0.5:
        idx = 0
        match_count = 0
        for ch in pattern_lower:
            pos = text_lower.find(ch, idx)
            if pos >= 0:
                match_count += 1
                idx = pos + 1
        order_ratio = match_count / len(pattern_lower)
        return char_ratio * 0.3 + order_ratio * 0.4

    return char_ratio * 0.3


def search_artifacts(
    name: Optional[str] = None,
    module: Optional[str] = None,
    artifact_type: Optional[str] = None,
    tag: Optional[str] = None,
    dialog_id: Optional[str] = None,
    status: Optional[str] = None,
    min_score: float = 0.3,
    limit: Optional[int] = None,
) -> List[Tuple[dict, float]]:
    """
    搜索产物。

    Args:
        name: 名称关键词（模糊匹配）
        module: 模块筛选（精确匹配，如 M1, M10）
        artifact_type: 类型筛选（精确匹配：doc/code/script/report/proto/config）
        tag: 标签关键词（模糊匹配）
        dialog_id: 对话ID筛选
        status: 状态筛选（active/deprecated/replaced）
        min_score: 最低匹配得分
        limit: 最大返回数量

    Returns:
        列表形式的 (产物记录, 匹配得分) 元组，按得分降序排列
    """
    index_data = load_index()
    artifacts = index_data.get("artifacts", {})

    results = []

    for artifact_id, record in artifacts.items():
        score = 1.0
        matched = True

        # 模块筛选（精确匹配，忽略大小写）
        if module:
            record_module = record.get("module", "") or ""
            if module.upper() != record_module.upper():
                matched = False

        # 类型筛选
        if artifact_type:
            if record.get("type", "") != artifact_type:
                matched = False

        # 状态筛选
        if status:
            if record.get("status", "") != status:
                matched = False

        # 对话ID筛选
        if dialog_id:
            record_dialog = record.get("dialog_id", "") or ""
            if dialog_id.lower() not in record_dialog.lower():
                matched = False

        if not matched:
            continue

        # 名称模糊匹配
        if name:
            name_score = fuzzy_match(record.get("name", ""), name)
            desc_score = fuzzy_match(record.get("description", ""), name) * 0.7
            name_score = max(name_score, desc_score)
            if name_score < min_score:
                continue
            score *= name_score

        # 标签模糊匹配
        if tag:
            tags = record.get("tags", [])
            tag_scores = [fuzzy_match(t, tag) for t in tags]
            max_tag_score = max(tag_scores) if tag_scores else 0.0
            if max_tag_score < min_score:
                continue
            score *= 0.5 + 0.5 * max_tag_score

        results.append((record, score))

    # 按得分降序排列
    results.sort(key=lambda x: x[1], reverse=True)

    if limit:
        results = results[:limit]

    return results


def format_result(record: dict, score: float, verbose: bool = False) -> str:
    """
    格式化搜索结果为字符串。
    """
    artifact_id = record.get("id", "unknown")
    name = record.get("name", "未命名")
    atype = record.get("type", "?")
    module = record.get("module", "-") or "-"
    status = record.get("status", "active")
    path = record.get("path", "")
    description = record.get("description", "")
    dialog = record.get("dialog_id", "") or "-"

    status_icon = {
        "active": "[●]",
        "deprecated": "[○]",
        "replaced": "[→]",
    }.get(status, "[?]")

    if verbose:
        tags = ", ".join(record.get("tags", []))
        size_kb = record.get("size_bytes", 0) / 1024
        created = record.get("created_at", "")
        updated = record.get("updated_at", "")
        return (
            f"\n{'='*60}\n"
            f"{status_icon} {artifact_id}  {name}\n"
            f"{'─'*60}\n"
            f"  类型:     {atype}\n"
            f"  模块:     {module}\n"
            f"  状态:     {status}\n"
            f"  对话:     {dialog}\n"
            f"  路径:     {path}\n"
            f"  大小:     {size_kb:.1f} KB\n"
            f"  标签:     {tags}\n"
            f"  创建:     {created}\n"
            f"  更新:     {updated}\n"
            f"  描述:     {description}\n"
            f"  匹配度:   {score:.1%}\n"
        )
    else:
        return f"  {status_icon} {artifact_id:12s} [{module:3s}] [{atype:6s}] {name}  ({score:.0%})"


def list_all() -> List[dict]:
    """列出所有产物。"""
    index_data = load_index()
    return list(index_data.get("artifacts", {}).values())


def get_stats() -> Dict[str, Any]:
    """获取索引统计信息。"""
    index_data = load_index()
    artifacts = index_data.get("artifacts", {})

    type_stats: Dict[str, int] = {}
    module_stats: Dict[str, int] = {}
    status_stats: Dict[str, int] = {}
    total_size = 0

    for record in artifacts.values():
        t = record.get("type", "unknown")
        m = record.get("module", "unknown") or "unknown"
        s = record.get("status", "unknown")
        type_stats[t] = type_stats.get(t, 0) + 1
        module_stats[m] = module_stats.get(m, 0) + 1
        status_stats[s] = status_stats.get(s, 0) + 1
        total_size += record.get("size_bytes", 0)

    return {
        "total": len(artifacts),
        "total_size_bytes": total_size,
        "by_type": type_stats,
        "by_module": module_stats,
        "by_status": status_stats,
        "generated_at": index_data.get("generated_at", ""),
    }


def main():
    """命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="云汐系统产物搜索工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python artifact_search.py --name "M10"              # 按名称搜索
  python artifact_search.py --module M1 --type doc    # 按模块和类型筛选
  python artifact_search.py --tag "开发方案"           # 按标签搜索
  python artifact_search.py --list                    # 列出所有产物
  python artifact_search.py --stats                   # 显示统计信息
  python artifact_search.py -n "测试" -v              # 详细模式搜索
        """,
    )

    parser.add_argument("-n", "--name", help="名称关键词（模糊匹配）")
    parser.add_argument("-m", "--module", help="模块筛选（如 M1, M10）")
    parser.add_argument("-t", "--type", dest="artifact_type",
                        help="类型筛选（doc/code/script/report/proto/config）")
    parser.add_argument("--tag", help="标签关键词")
    parser.add_argument("--dialog", help="对话ID筛选")
    parser.add_argument("--status", help="状态筛选（active/deprecated/replaced）")
    parser.add_argument("--min-score", type=float, default=0.3,
                        help="最低匹配得分（0-1，默认0.3）")
    parser.add_argument("-l", "--limit", type=int, help="最大返回数量")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="显示详细信息")
    parser.add_argument("--list", action="store_true",
                        help="列出所有产物")
    parser.add_argument("--stats", action="store_true",
                        help="显示统计信息")

    args = parser.parse_args()

    # 统计信息
    if args.stats:
        stats = get_stats()
        print(f"产物总数: {stats['total']}")
        print(f"总大小: {stats['total_size_bytes'] / 1024:.1f} KB")
        print(f"生成时间: {stats['generated_at']}")
        print()
        print("按类型分布:")
        for t, c in sorted(stats["by_type"].items()):
            print(f"  {t:10s}: {c}")
        print()
        print("按模块分布:")
        for m, c in sorted(stats["by_module"].items()):
            print(f"  {m:10s}: {c}")
        print()
        print("按状态分布:")
        for s, c in sorted(stats["by_status"].items()):
            print(f"  {s:10s}: {c}")
        return

    # 列出所有
    if args.list:
        all_artifacts = list_all()
        if not all_artifacts:
            print("索引为空，请先运行 artifact_indexer.py 构建索引。")
            return
        print(f"共 {len(all_artifacts)} 个产物：\n")
        for record in sorted(all_artifacts, key=lambda r: r.get("id", "")):
            print(format_result(record, 1.0, args.verbose))
        return

    # 搜索
    has_query = any([
        args.name, args.module, args.artifact_type,
        args.tag, args.dialog, args.status,
    ])

    if not has_query:
        parser.print_help()
        return

    results = search_artifacts(
        name=args.name,
        module=args.module,
        artifact_type=args.artifact_type,
        tag=args.tag,
        dialog_id=args.dialog,
        status=args.status,
        min_score=args.min_score,
        limit=args.limit,
    )

    if not results:
        print("未找到匹配的产物。")
        return

    print(f"找到 {len(results)} 个匹配的产物：\n")
    for record, score in results:
        print(format_result(record, score, args.verbose))


if __name__ == "__main__":
    main()
