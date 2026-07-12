"""
对话产物清单生成器 (Manifest Generator)

为每个对话窗口生成 manifest.json，记录该对话的所有产出，支持追加新产物。
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


def get_artifacts_root() -> Path:
    """获取 artifacts 根目录路径。"""
    return Path(__file__).resolve().parent.parent


def get_dialog_dir(dialog_id: str) -> Path:
    """获取对话目录路径。"""
    by_dialog = get_artifacts_root() / "by-dialog"
    # 先尝试精确匹配
    direct_path = by_dialog / dialog_id
    if direct_path.exists():
        return direct_path
    # 尝试匹配 dialog-xxx-yyy 格式（用前缀匹配）
    if by_dialog.exists():
        for d in by_dialog.iterdir():
            if d.is_dir() and d.name.startswith(dialog_id + "-"):
                return d
    # 都不存在时返回标准路径（用于创建新目录）
    return direct_path


def get_manifest_path(dialog_id: str) -> Path:
    """获取对话 manifest.json 路径。"""
    return get_dialog_dir(dialog_id) / "manifest.json"


def load_manifest(dialog_id: str) -> dict:
    """加载对话的 manifest.json。"""
    manifest_path = get_manifest_path(dialog_id)
    if manifest_path.exists():
        try:
            # 使用 utf-8-sig 自动处理 BOM
            with open(manifest_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                # 确保 dialog_id 字段正确
                if "dialog_id" not in data:
                    data["dialog_id"] = dialog_id
                return data
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return {
        "dialog_id": dialog_id,
        "dialog_name": "",
        "created_at": "",
        "updated_at": "",
        "artifact_count": 0,
        "modules": [],
        "artifacts": [],
    }


def save_manifest(dialog_id: str, manifest_data: dict) -> None:
    """保存 manifest.json，确保 UTF-8 编码。"""
    dialog_dir = get_dialog_dir(dialog_id)
    dialog_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = dialog_dir / "manifest.json"
    manifest_data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    manifest_data["artifact_count"] = len(manifest_data.get("artifacts", []))

    # 更新模块列表
    modules = set()
    for a in manifest_data.get("artifacts", []):
        m = a.get("module")
        if m:
            modules.add(m)
    manifest_data["modules"] = sorted(list(modules))

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)


def create_dialog(dialog_id: str, dialog_name: str = "",
                  description: str = "") -> dict:
    """
    创建一个新的对话条目。

    Args:
        dialog_id: 对话ID，如 dialog-001
        dialog_name: 对话名称
        description: 对话描述

    Returns:
        manifest 数据
    """
    manifest_path = get_manifest_path(dialog_id)

    if manifest_path.exists():
        raise ValueError(f"对话 {dialog_id} 已存在")

    now = datetime.now().isoformat(timespec="seconds")
    manifest_data = {
        "dialog_id": dialog_id,
        "dialog_name": dialog_name or dialog_id,
        "description": description,
        "created_at": now,
        "updated_at": now,
        "artifact_count": 0,
        "modules": [],
        "artifacts": [],
    }

    save_manifest(dialog_id, manifest_data)
    return manifest_data


def add_artifact_to_dialog(
    dialog_id: str,
    artifact_id: str,
    name: str,
    artifact_type: str,
    module: str,
    path: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    dialog_name: str = "",
) -> dict:
    """
    向对话清单中添加一个产物。

    Args:
        dialog_id: 对话ID
        artifact_id: 产物ID
        name: 产物名称
        artifact_type: 产物类型
        module: 所属模块
        path: 产物相对路径
        description: 描述
        tags: 标签列表
        dialog_name: 对话名称（如果清单不存在则创建时使用）

    Returns:
        更新后的 manifest 数据
    """
    manifest = load_manifest(dialog_id)

    # 如果是新创建的
    if not manifest.get("created_at"):
        manifest["dialog_name"] = dialog_name or dialog_id
        manifest["created_at"] = datetime.now().isoformat(timespec="seconds")

    # 检查是否已存在
    artifacts = manifest.get("artifacts", [])
    for a in artifacts:
        if a.get("artifact_id") == artifact_id:
            # 更新已存在的
            a.update({
                "name": name,
                "type": artifact_type,
                "module": module,
                "path": path,
                "description": description or name,
                "tags": tags or [],
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            save_manifest(dialog_id, manifest)
            return manifest

    # 新增
    now = datetime.now().isoformat(timespec="seconds")
    artifact_entry = {
        "artifact_id": artifact_id,
        "name": name,
        "type": artifact_type,
        "module": module,
        "path": path,
        "description": description or name,
        "tags": tags or [],
        "added_at": now,
    }
    artifacts.append(artifact_entry)
    manifest["artifacts"] = artifacts

    save_manifest(dialog_id, manifest)
    return manifest


def remove_artifact_from_dialog(dialog_id: str, artifact_id: str) -> bool:
    """
    从对话清单中移除一个产物。

    Returns:
        是否成功移除
    """
    manifest = load_manifest(dialog_id)
    artifacts = manifest.get("artifacts", [])

    new_artifacts = [a for a in artifacts if a.get("artifact_id") != artifact_id]
    if len(new_artifacts) == len(artifacts):
        return False

    manifest["artifacts"] = new_artifacts
    save_manifest(dialog_id, manifest)
    return True


def list_dialogs() -> List[str]:
    """列出所有对话目录名称。"""
    by_dialog_dir = get_artifacts_root() / "by-dialog"
    if not by_dialog_dir.exists():
        return []

    dialogs = []
    for item in by_dialog_dir.iterdir():
        if item.is_dir() and item.name.startswith("dialog-"):
            dialogs.append(item.name)
    return sorted(dialogs)


def get_dialog_summary(dialog_id: str) -> Dict[str, Any]:
    """获取对话的摘要信息。"""
    manifest = load_manifest(dialog_id)
    artifacts = manifest.get("artifacts", [])

    type_stats = {}
    module_stats = {}
    for a in artifacts:
        t = a.get("type", "unknown")
        m = a.get("module", "unknown")
        type_stats[t] = type_stats.get(t, 0) + 1
        module_stats[m] = module_stats.get(m, 0) + 1

    return {
        "dialog_id": manifest.get("dialog_id", dialog_id),
        "dialog_name": manifest.get("dialog_name", ""),
        "artifact_count": len(artifacts),
        "created_at": manifest.get("created_at", ""),
        "updated_at": manifest.get("updated_at", ""),
        "modules": list(module_stats.keys()),
        "by_type": type_stats,
        "by_module": module_stats,
    }


def generate_from_index(dialog_id: str, dialog_name: str = "",
                        index_data: Optional[dict] = None) -> dict:
    """
    从全局索引中生成指定对话的 manifest。

    扫描 index.json 中所有属于该对话的产物，生成 manifest.json。
    """
    if index_data is None:
        index_path = get_artifacts_root() / "index.json"
        if index_path.exists():
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        else:
            index_data = {"artifacts": {}}

    manifest = load_manifest(dialog_id)
    if not manifest.get("created_at"):
        manifest["dialog_name"] = dialog_name or dialog_id
        manifest["created_at"] = datetime.now().isoformat(timespec="seconds")

    # 收集该对话的所有产物
    artifacts = []
    for aid, record in index_data.get("artifacts", {}).items():
        if record.get("dialog_id") == dialog_id:
            artifacts.append({
                "artifact_id": aid,
                "name": record.get("name", ""),
                "type": record.get("type", ""),
                "module": record.get("module", ""),
                "path": record.get("path", ""),
                "description": record.get("description", ""),
                "tags": record.get("tags", []),
                "added_at": record.get("created_at", ""),
            })

    manifest["artifacts"] = artifacts
    save_manifest(dialog_id, manifest)
    return manifest


def main():
    """命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="云汐系统对话产物清单生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python manifest_generator.py --create dialog-001 "M1开发对话"   # 创建新对话
  python manifest_generator.py --add dialog-001 --artifact artifact-001 --name "设计文档" --type doc --module M1 --path by-module/M1/design.md
  python manifest_generator.py --list                                  # 列出所有对话
  python manifest_generator.py --show dialog-001                      # 显示对话详情
  python manifest_generator.py --generate dialog-001                   # 从索引生成清单
        """,
    )

    parser.add_argument("--create", nargs=2, metavar=("DIALOG_ID", "NAME"),
                        help="创建新对话：对话ID 对话名称")
    parser.add_argument("--add", metavar="DIALOG_ID",
                        help="向对话添加产物")
    parser.add_argument("--artifact", help="产物ID")
    parser.add_argument("--name", help="产物名称")
    parser.add_argument("--type", dest="artifact_type", help="产物类型")
    parser.add_argument("--module", help="所属模块")
    parser.add_argument("--path", help="产物路径")
    parser.add_argument("--desc", help="产物描述")
    parser.add_argument("--remove", nargs=2, metavar=("DIALOG_ID", "ARTIFACT_ID"),
                        help="从对话移除产物")
    parser.add_argument("--list", action="store_true", help="列出所有对话")
    parser.add_argument("--show", metavar="DIALOG_ID", help="显示对话详情")
    parser.add_argument("--generate", metavar="DIALOG_ID",
                        help="从全局索引生成对话清单")
    parser.add_argument("--dialog-name", help="对话名称")

    args = parser.parse_args()

    # 创建对话
    if args.create:
        dialog_id, name = args.create
        try:
            manifest = create_dialog(dialog_id, name)
            print(f"已创建对话: {dialog_id} - {name}")
            print(f"目录: {get_dialog_dir(dialog_id)}")
        except ValueError as e:
            print(f"错误: {e}")
        return

    # 添加产物
    if args.add:
        if not all([args.artifact, args.name, args.artifact_type, args.module, args.path]):
            print("错误：添加产物需要指定 --artifact, --name, --type, --module, --path")
            return
        manifest = add_artifact_to_dialog(
            dialog_id=args.add,
            artifact_id=args.artifact,
            name=args.name,
            artifact_type=args.artifact_type,
            module=args.module,
            path=args.path,
            description=args.desc or "",
            dialog_name=args.dialog_name or "",
        )
        print(f"已添加产物到 {args.add}，当前共 {manifest['artifact_count']} 个产物")
        return

    # 移除产物
    if args.remove:
        dialog_id, artifact_id = args.remove
        success = remove_artifact_from_dialog(dialog_id, artifact_id)
        if success:
            print(f"已从 {dialog_id} 移除产物 {artifact_id}")
        else:
            print(f"未找到产物 {artifact_id}")
        return

    # 列出所有对话
    if args.list:
        dialogs = list_dialogs()
        if not dialogs:
            print("暂无对话记录。")
            return
        print(f"共 {len(dialogs)} 个对话：\n")
        for d in dialogs:
            summary = get_dialog_summary(d)
            print(f"  {summary['dialog_id']:15s} {summary['dialog_name']:20s} "
                  f"({summary['artifact_count']} 个产物)")
        return

    # 显示对话详情
    if args.show:
        manifest = load_manifest(args.show)
        if not manifest.get("artifacts") and not manifest.get("created_at"):
            print(f"对话 {args.show} 不存在或为空。")
            return
        print(f"\n对话: {manifest['dialog_id']} - {manifest.get('dialog_name', '')}")
        print(f"创建: {manifest.get('created_at', 'N/A')}")
        print(f"更新: {manifest.get('updated_at', 'N/A')}")
        print(f"产物数: {manifest['artifact_count']}")
        print(f"涉及模块: {', '.join(manifest.get('modules', []))}")
        print(f"\n产物列表:")
        for a in manifest.get("artifacts", []):
            print(f"  [{a.get('module','?'):3s}] [{a.get('type','?'):6s}] "
                  f"{a.get('artifact_id',''):12s} {a.get('name','')}")
        print()
        return

    # 从索引生成
    if args.generate:
        manifest = generate_from_index(args.generate, args.dialog_name or "")
        print(f"已从索引生成 {args.generate} 的清单，共 {manifest['artifact_count']} 个产物")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
