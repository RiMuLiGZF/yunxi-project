"""
产物索引生成器 (Artifact Indexer)

扫描 artifacts/ 目录下所有文件，自动识别文件类型和所属模块，
生成/更新 index.json 索引文件，支持增量更新。
"""

import json
import os
import re
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 模块映射规则
MODULE_MAP = {
    "M1": "M1-agent-cluster",
    "M2": "M2-skills-cluster",
    "M3": "M3-edge-cloud",
    "M4": "M4-scene-engine",
    "M5": "M5-tide-memory",
    "M6": "M6-hardware-peripheral",
    "M7": "M7-workflow-builder",
    "M8": "M8-control-tower",
    "M9": "M9-programming-dev",
    "M10": "M10-system-guard",
}

# 类型映射规则（按扩展名）
TYPE_MAP = {
    ".md": "doc",
    ".txt": "doc",
    ".rst": "doc",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".sh": "script",
    ".bat": "script",
    ".ps1": "script",
    ".yaml": "config",
    ".yml": "config",
    ".json": "config",
    ".ini": "config",
    ".cfg": "config",
    ".html": "proto",
    ".css": "proto",
    ".pdf": "report",
    ".xlsx": "report",
    ".csv": "report",
    ".docx": "doc",
    ".pptx": "doc",
    ".png": "proto",
    ".jpg": "proto",
    ".jpeg": "proto",
    ".gif": "proto",
    ".svg": "proto",
}

# 报告类关键词（文件名包含这些词时类型升级为 report）
REPORT_KEYWORDS = ["报告", "report", "测试报告", "测试", "验收", "评审", "总结", "分析", "test-report", "test_report"]
# 原型类关键词
PROTO_KEYWORDS = ["原型", "proto", "demo", "演示"]
# 脚本类关键词
SCRIPT_KEYWORDS = ["脚本", "script", "工具", "tool"]


def get_artifacts_root() -> Path:
    """获取 artifacts 根目录路径"""
    return Path(__file__).resolve().parent.parent


def detect_type(filepath: Path) -> str:
    """
    根据文件路径和扩展名检测产物类型。

    优先级：
    1. 代码/脚本扩展名（code/script）- 高优先级，不被关键词覆盖
    2. 文件名关键词（report/proto）
    3. 扩展名映射（doc/config 等）
    4. 默认 doc
    """
    name = filepath.name.lower()
    suffix = filepath.suffix.lower()

    # 代码/脚本类扩展名优先级最高，不被文件名关键词覆盖
    code_extensions = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h"}
    script_extensions = {".sh", ".bat", ".ps1"}
    if suffix in code_extensions:
        # 检查是否是工具脚本
        for kw in SCRIPT_KEYWORDS:
            if kw in name:
                return "script"
        return "code"
    if suffix in script_extensions:
        return "script"

    # 检查文件名关键词（仅对文档类扩展名生效）
    for kw in REPORT_KEYWORDS:
        if kw in name:
            return "report"
    for kw in PROTO_KEYWORDS:
        if kw in name:
            return "proto"

    # 扩展名映射
    return TYPE_MAP.get(suffix, "doc")


def detect_module(filepath: Path) -> Optional[str]:
    """
    根据文件路径检测所属模块。

    规则：
    1. by-module/Mx-xxx/ 下的文件 -> Mx
    2. 文件名包含 Mx 标识 -> Mx
    3. 路径中包含模块名关键词 -> Mx
    """
    parts = filepath.parts

    # 规则1: by-module 目录
    if "by-module" in parts:
        idx = parts.index("by-module")
        if idx + 1 < len(parts):
            module_dir = parts[idx + 1]
            # 按模块编号倒序匹配，避免 M10 被误匹配为 M1
            sorted_keys = sorted(MODULE_MAP.keys(), key=lambda k: int(k[1:]), reverse=True)
            for key in sorted_keys:
                if module_dir.startswith(key):
                    return key

    # 规则2: 文件名包含 Mx（使用单词边界，避免 m10 被匹配为 m1）
    name = filepath.stem
    match = re.search(r"(?<!\d)M(\d+)(?!\d)", name, re.IGNORECASE)
    if match:
        num = int(match.group(1))
        key = f"M{num}"
        if key in MODULE_MAP:
            return key

    # 规则3: 路径关键词
    path_str = str(filepath).lower()
    keyword_map = {
        "agent-cluster": "M1",
        "skills-cluster": "M2",
        "skill": "M2",
        "edge-cloud": "M3",
        "scene-engine": "M4",
        "tide-memory": "M5",
        "tide": "M5",
        "hardware": "M6",
        "peripheral": "M6",
        "workflow": "M7",
        "control-tower": "M8",
        "programming": "M9",
        "programming-dev": "M9",
        "system-guard": "M10",
        "guard": "M10",
    }
    for kw, module in keyword_map.items():
        if kw in path_str:
            return module

    return None


def detect_dialog(filepath: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    检测文件所属的对话窗口。

    返回 (dialog_id, dialog_name)
    """
    parts = filepath.parts

    if "by-dialog" in parts:
        idx = parts.index("by-dialog")
        if idx + 1 < len(parts):
            dialog_dir = parts[idx + 1]
            # 解析 dialog-001-xxx 格式
            match = re.match(r"(dialog-\d+)-(.+)", dialog_dir)
            if match:
                return match.group(1), match.group(2)
            return dialog_dir, dialog_dir

    return None, None


def extract_tags(filepath: Path, module: Optional[str], artifact_type: str) -> List[str]:
    """
    从文件路径和名称中提取标签。
    """
    tags = []
    name = filepath.stem

    if module and module in MODULE_MAP:
        tags.append(module)
        module_name = MODULE_MAP.get(module, "")
        if module_name:
            # 提取模块中文名或描述
            parts = module_name.split("-", 1)
            if len(parts) > 1:
                tags.append(parts[1])

    tags.append(artifact_type)

    # 从文件名提取关键词（中英文）
    keywords = [
        # 中文关键词
        "开发方案", "架构", "设计", "测试", "报告", "接口", "API",
        "配置", "部署", "优化", "验收", "评审", "规范", "指南",
        "开发", "联调", "自检", "总结", "分析", "方案", "文档",
        # 英文关键词
        "architecture", "design", "test", "report", "api",
        "config", "deploy", "guide", "dev", "spec",
    ]
    for kw in keywords:
        if kw in name:
            tags.append(kw)

    return list(set(tags))


def compute_file_hash(filepath: Path) -> str:
    """计算文件内容的 MD5 哈希，用于检测变更。"""
    try:
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def generate_artifact_id(index: int) -> str:
    """生成产物 ID。"""
    return f"artifact-{index:03d}"


def scan_directory(root: Path, exclude_dirs: Optional[List[str]] = None) -> List[Path]:
    """
    递归扫描目录，返回所有文件路径。

    排除：
    - 以 . 开头的目录（隐藏目录）
    - __pycache__ 目录
    - tools/ 目录本身（管理工具不算产物）
    - templates/ 目录（模板不算产物）
    - index.json
    """
    if exclude_dirs is None:
        exclude_dirs = [".git", "__pycache__", ".pytest_cache", "node_modules"]

    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in exclude_dirs]

        for filename in filenames:
            if filename.startswith("."):
                continue
            if filename == "index.json":
                continue
            filepath = Path(dirpath) / filename
            files.append(filepath)

    return files


def build_artifact_record(
    filepath: Path,
    artifacts_root: Path,
    artifact_id: str,
    existing_records: Dict[str, dict],
) -> dict:
    """
    构建单个产物的记录。
    """
    rel_path = filepath.relative_to(artifacts_root).as_posix()
    file_size = filepath.stat().st_size
    file_hash = compute_file_hash(filepath)

    # 检查是否已存在且未变更
    if artifact_id in existing_records:
        old = existing_records[artifact_id]
        if (old.get("path") == rel_path
                and old.get("size_bytes") == file_size
                and old.get("content_hash") == file_hash):
            # 文件未变更，保留原记录
            return old

    artifact_type = detect_type(filepath)
    module = detect_module(filepath)
    dialog_id, dialog_name = detect_dialog(filepath)
    tags = extract_tags(filepath, module, artifact_type)

    name = filepath.stem
    description = f"{name} - {artifact_type}类型产物"

    now = datetime.now().isoformat(timespec="seconds")
    created_at = existing_records.get(artifact_id, {}).get("created_at", now)

    return {
        "id": artifact_id,
        "name": name,
        "type": artifact_type,
        "module": module,
        "dialog_id": dialog_id,
        "dialog_name": dialog_name,
        "description": description,
        "path": rel_path,
        "tags": tags,
        "created_at": created_at,
        "updated_at": now,
        "version": "1.0",
        "status": "active",
        "related_artifacts": [],
        "size_bytes": file_size,
        "content_hash": file_hash,
    }


def load_index(index_path: Path) -> dict:
    """加载现有的索引文件。"""
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return {
        "version": "1.0",
        "generated_at": "",
        "artifact_count": 0,
        "artifacts": {},
    }


def save_index(index_path: Path, index_data: dict) -> None:
    """保存索引文件，确保 UTF-8 编码和中文正常显示。"""
    index_data["generated_at"] = datetime.now().isoformat(timespec="seconds")
    index_data["artifact_count"] = len(index_data.get("artifacts", {}))

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def build_index(incremental: bool = True) -> dict:
    """
    构建产物索引。

    Args:
        incremental: 是否增量更新。True 时保留已有记录的元数据。

    Returns:
        索引数据字典
    """
    artifacts_root = get_artifacts_root()
    index_path = artifacts_root / "index.json"

    # 加载现有索引
    existing_index = load_index(index_path)
    existing_records = existing_index.get("artifacts", {}) if incremental else {}

    # 扫描所有文件
    files = scan_directory(artifacts_root)

    # 构建路径到 ID 的映射（用于增量更新时匹配已有记录）
    path_to_id = {}
    for aid, record in existing_records.items():
        path_to_id[record.get("path", "")] = aid

    # 生成新索引
    new_artifacts = {}
    next_id = 1

    # 按路径排序，确保 ID 稳定
    files.sort(key=lambda f: f.relative_to(artifacts_root).as_posix())

    for filepath in files:
        rel_path = filepath.relative_to(artifacts_root).as_posix()

        # 跳过工具、模板、测试目录和根目录说明文件
        if rel_path.startswith("tools/") or rel_path.startswith("templates/"):
            continue
        if rel_path == "README.md" or rel_path == "index.json":
            continue
        # 排除对话清单文件（元数据，不是产物）
        if "by-dialog" in rel_path and rel_path.endswith("manifest.json"):
            continue
        if rel_path.startswith("tests/"):
            continue

        # 尝试匹配已有 ID
        if rel_path in path_to_id:
            artifact_id = path_to_id[rel_path]
        else:
            # 找下一个可用 ID
            while generate_artifact_id(next_id) in existing_records:
                next_id += 1
            artifact_id = generate_artifact_id(next_id)
            next_id += 1

        record = build_artifact_record(
            filepath, artifacts_root, artifact_id, existing_records
        )
        new_artifacts[artifact_id] = record

    index_data = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_count": len(new_artifacts),
        "artifacts": new_artifacts,
    }

    save_index(index_path, index_data)
    return index_data


def add_artifact(
    name: str,
    artifact_type: str,
    module: str,
    filepath: str,
    description: str = "",
    dialog_id: str = "",
    dialog_name: str = "",
    tags: Optional[List[str]] = None,
) -> str:
    """
    手动登记一个新产物到索引。

    Returns:
        新产物的 ID
    """
    artifacts_root = get_artifacts_root()
    index_path = artifacts_root / "index.json"
    index_data = load_index(index_path)

    # 找下一个可用 ID
    existing_ids = index_data.get("artifacts", {}).keys()
    next_num = 1
    while f"artifact-{next_num:03d}" in existing_ids:
        next_num += 1
    artifact_id = f"artifact-{next_num:03d}"

    now = datetime.now().isoformat(timespec="seconds")
    file_path = Path(filepath)
    size_bytes = 0
    content_hash = ""
    abs_path = artifacts_root / filepath if not Path(filepath).is_absolute() else Path(filepath)
    if abs_path.exists():
        size_bytes = abs_path.stat().st_size
        content_hash = compute_file_hash(abs_path)

    if tags is None:
        tags = [module, artifact_type]

    record = {
        "id": artifact_id,
        "name": name,
        "type": artifact_type,
        "module": module,
        "dialog_id": dialog_id,
        "dialog_name": dialog_name,
        "description": description or name,
        "path": filepath,
        "tags": tags,
        "created_at": now,
        "updated_at": now,
        "version": "1.0",
        "status": "active",
        "related_artifacts": [],
        "size_bytes": size_bytes,
        "content_hash": content_hash,
    }

    index_data.setdefault("artifacts", {})[artifact_id] = record
    save_index(index_path, index_data)

    return artifact_id


def main():
    """命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="云汐系统产物索引生成器")
    parser.add_argument(
        "--full",
        action="store_true",
        help="全量重建索引（默认增量更新）",
    )
    parser.add_argument(
        "--add",
        nargs=5,
        metavar=("NAME", "TYPE", "MODULE", "FILEPATH", "DESCRIPTION"),
        help="手动登记一个产物：名称 类型 模块 路径 描述",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="显示索引统计信息",
    )

    args = parser.parse_args()

    if args.add:
        name, atype, module, filepath, desc = args.add
        aid = add_artifact(name, atype, module, filepath, desc)
        print(f"已登记产物: {aid} - {name}")
        return

    incremental = not args.full
    mode = "增量更新" if incremental else "全量重建"
    print(f"开始构建产物索引（{mode}）...")

    index_data = build_index(incremental=incremental)
    count = index_data["artifact_count"]

    print(f"索引构建完成，共 {count} 个产物")

    if args.stats:
        artifacts = index_data.get("artifacts", {})
        # 按类型统计
        type_stats = {}
        module_stats = {}
        for record in artifacts.values():
            t = record.get("type", "unknown")
            m = record.get("module", "unknown")
            type_stats[t] = type_stats.get(t, 0) + 1
            module_stats[m] = module_stats.get(m, 0) + 1

        print("\n按类型统计:")
        for t, c in sorted(type_stats.items()):
            print(f"  {t:10s}: {c}")

        print("\n按模块统计:")
        for m, c in sorted(module_stats.items()):
            print(f"  {m:10s}: {c}")


if __name__ == "__main__":
    main()
