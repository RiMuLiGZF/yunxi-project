"""M7 积木平台 - 工作流版本管理.

提供工作流的版本化管理功能：
- 每次发布创建新版本
- 版本列表查询
- 版本对比
- 版本回滚
- 运行时指定版本执行

版本存储在 JSON 文件中：~/.yunxi/m7_workflow_versions.json
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("m7.versioning")


class WorkflowVersionManager:
    """工作流版本管理器.

    管理工作流的版本历史，支持版本对比和回滚。
    版本号采用语义化版本（major.minor.patch），
    发布时自动递增。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化版本管理器.

        Args:
            data_dir: 数据目录
        """
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path.home() / ".yunxi"

        self._versions_file = self._data_dir / "m7_workflow_versions.json"
        self._lock = threading.RLock()
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _load_versions(self) -> Dict[str, List[Dict[str, Any]]]:
        """加载所有版本数据.

        Returns:
            {workflow_id: [version_record, ...]} 字典
        """
        with self._lock:
            if not self._versions_file.exists():
                return {}
            try:
                with open(self._versions_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}

    def _save_versions(self, versions: Dict[str, List[Dict[str, Any]]]) -> None:
        """保存版本数据."""
        with self._lock:
            self._versions_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._versions_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(versions, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self._versions_file)

    def _next_version(self, current_version: Optional[str], bump_type: str = "patch") -> str:
        """计算下一个版本号.

        Args:
            current_version: 当前版本号（None 表示首次发布）
            bump_type: 递增类型（major/minor/patch）

        Returns:
            新版本号
        """
        if not current_version:
            return "1.0.0"

        parts = current_version.split(".")
        if len(parts) != 3:
            return "1.0.0"

        try:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, TypeError):
            return "1.0.0"

        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"

    # ------------------------------------------------------------------
    # 版本管理 API
    # ------------------------------------------------------------------

    def create_version(
        self,
        workflow_id: str,
        workflow_data: Dict[str, Any],
        version_note: str = "",
        bump_type: str = "patch",
        created_by: str = "",
    ) -> Dict[str, Any]:
        """创建工作流新版本.

        Args:
            workflow_id: 工作流 ID
            workflow_data: 工作流数据（完整定义）
            version_note: 版本说明
            bump_type: 版本递增类型
            created_by: 创建者

        Returns:
            新版本记录
        """
        versions = self._load_versions()

        if workflow_id not in versions:
            versions[workflow_id] = []

        # 计算新版本号
        current_version = None
        if versions[workflow_id]:
            current_version = versions[workflow_id][0].get("version", "1.0.0")

        new_version = self._next_version(current_version, bump_type)

        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        version_id = f"v_{workflow_id}_{uuid.uuid4().hex[:8]}"

        version_record = {
            "version_id": version_id,
            "workflow_id": workflow_id,
            "version": new_version,
            "version_note": version_note,
            "workflow_data": copy.deepcopy(workflow_data),
            "created_at": now,
            "created_by": created_by,
            "block_count": len(workflow_data.get("blocks", [])),
            "variable_count": len(workflow_data.get("variables", [])),
        }

        versions[workflow_id].insert(0, version_record)

        # 限制每个工作流保留的版本数量（默认 50 个）
        max_versions = 50
        if len(versions[workflow_id]) > max_versions:
            versions[workflow_id] = versions[workflow_id][:max_versions]

        self._save_versions(versions)

        logger.info(
            f"[Version] 工作流 {workflow_id} 创建新版本 {new_version} "
            f"({version_id})"
        )

        return version_record

    def list_versions(
        self,
        workflow_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """获取工作流的版本列表.

        Args:
            workflow_id: 工作流 ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            版本列表信息
        """
        versions = self._load_versions()
        workflow_versions = versions.get(workflow_id, [])

        total = len(workflow_versions)
        paged = workflow_versions[offset : offset + limit]

        # 返回时不包含完整的 workflow_data（节省带宽）
        simplified = []
        for v in paged:
            simplified.append({
                "version_id": v["version_id"],
                "workflow_id": v["workflow_id"],
                "version": v["version"],
                "version_note": v.get("version_note", ""),
                "created_at": v.get("created_at", ""),
                "created_by": v.get("created_by", ""),
                "block_count": v.get("block_count", 0),
                "variable_count": v.get("variable_count", 0),
            })

        return {
            "total": total,
            "items": simplified,
            "limit": limit,
            "offset": offset,
            "workflow_id": workflow_id,
        }

    def get_version(
        self,
        workflow_id: str,
        version_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取指定版本的工作流数据.

        可以通过 version_id 或 version 号查询。

        Args:
            workflow_id: 工作流 ID
            version_id: 版本 ID
            version: 版本号（如 "1.0.0"）

        Returns:
            版本记录（含完整 workflow_data），不存在返回 None
        """
        versions = self._load_versions()
        workflow_versions = versions.get(workflow_id, [])

        for v in workflow_versions:
            if version_id and v.get("version_id") == version_id:
                return v
            if version and v.get("version") == version:
                return v

        return None

    def get_latest_version(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """获取最新版本.

        Args:
            workflow_id: 工作流 ID

        Returns:
            最新版本记录
        """
        versions = self._load_versions()
        workflow_versions = versions.get(workflow_id, [])
        return workflow_versions[0] if workflow_versions else None

    def compare_versions(
        self,
        workflow_id: str,
        version_a_id: str,
        version_b_id: str,
    ) -> Dict[str, Any]:
        """对比两个版本的差异.

        Args:
            workflow_id: 工作流 ID
            version_a_id: 版本 A 的 ID
            version_b_id: 版本 B 的 ID

        Returns:
            版本对比结果
        """
        ver_a = self.get_version(workflow_id, version_id=version_a_id)
        ver_b = self.get_version(workflow_id, version_id=version_b_id)

        if not ver_a or not ver_b:
            return {
                "success": False,
                "error": "版本不存在",
                "missing": ["version_a" if not ver_a else "version_b"],
            }

        data_a = ver_a.get("workflow_data", {})
        data_b = ver_b.get("workflow_data", {})

        # 对比基本信息
        basic_diff = {}
        for key in ["name", "description", "category", "status"]:
            val_a = data_a.get(key)
            val_b = data_b.get(key)
            if val_a != val_b:
                basic_diff[key] = {"old": val_a, "new": val_b}

        # 对比积木块
        blocks_a = {b["id"]: b for b in data_a.get("blocks", [])}
        blocks_b = {b["id"]: b for b in data_b.get("blocks", [])}

        added_blocks = [bid for bid in blocks_b if bid not in blocks_a]
        removed_blocks = [bid for bid in blocks_a if bid not in blocks_b]
        modified_blocks = []
        for bid in blocks_a:
            if bid in blocks_b and blocks_a[bid] != blocks_b[bid]:
                modified_blocks.append({
                    "block_id": bid,
                    "old_name": blocks_a[bid].get("name", ""),
                    "new_name": blocks_b[bid].get("name", ""),
                })

        # 对比变量
        vars_a = {v["name"]: v for v in data_a.get("variables", [])}
        vars_b = {v["name"]: v for v in data_b.get("variables", [])}

        added_vars = [name for name in vars_b if name not in vars_a]
        removed_vars = [name for name in vars_a if name not in vars_b]
        modified_vars = [name for name in vars_a if name in vars_b and vars_a[name] != vars_b[name]]

        # 对比触发器
        trigger_changed = data_a.get("trigger") != data_b.get("trigger")

        # 统计变更数
        total_changes = (
            len(basic_diff)
            + len(added_blocks)
            + len(removed_blocks)
            + len(modified_blocks)
            + len(added_vars)
            + len(removed_vars)
            + len(modified_vars)
            + (1 if trigger_changed else 0)
        )

        return {
            "success": True,
            "version_a": {
                "version_id": ver_a["version_id"],
                "version": ver_a["version"],
                "created_at": ver_a.get("created_at", ""),
            },
            "version_b": {
                "version_id": ver_b["version_id"],
                "version": ver_b["version"],
                "created_at": ver_b.get("created_at", ""),
            },
            "basic_info": basic_diff,
            "blocks": {
                "added": added_blocks,
                "removed": removed_blocks,
                "modified": modified_blocks,
            },
            "variables": {
                "added": added_vars,
                "removed": removed_vars,
                "modified": modified_vars,
            },
            "trigger_changed": trigger_changed,
            "total_changes": total_changes,
        }

    def rollback_to_version(
        self,
        workflow_id: str,
        version_id: str,
        storage: Any = None,
        rollback_note: str = "",
    ) -> Dict[str, Any]:
        """回滚到指定版本.

        会创建一个新版本，内容与目标版本相同。
        如果提供了 storage 实例，会同步更新工作流主记录。

        Args:
            workflow_id: 工作流 ID
            version_id: 要回滚到的版本 ID
            storage: 存储实例（用于更新主工作流记录）
            rollback_note: 回滚说明

        Returns:
            回滚结果
        """
        target_version = self.get_version(workflow_id, version_id=version_id)
        if not target_version:
            return {
                "success": False,
                "error": f"版本 {version_id} 不存在",
            }

        target_data = target_version.get("workflow_data", {})

        # 创建新版本（作为回滚结果）
        new_version = self.create_version(
            workflow_id=workflow_id,
            workflow_data=target_data,
            version_note=f"回滚到 v{target_version['version']}：{rollback_note}".strip("："),
            bump_type="patch",
            created_by="rollback",
        )

        # 如果提供了 storage，更新主工作流记录
        if storage is not None:
            try:
                updated_data = copy.deepcopy(target_data)
                updated_data["id"] = workflow_id
                updated_data["status"] = "draft"  # 回滚后置为草稿
                if hasattr(storage, "upsert_workflow"):
                    storage.upsert_workflow(workflow_id, updated_data)
            except Exception as e:
                logger.error(f"[Version] 回滚时更新主记录失败: {e}")

        return {
            "success": True,
            "rolled_back_to": target_version["version"],
            "new_version": new_version.get("version"),
            "new_version_id": new_version.get("version_id"),
            "version_note": new_version.get("version_note", ""),
        }

    def delete_version(
        self,
        workflow_id: str,
        version_id: str,
    ) -> bool:
        """删除指定版本.

        Args:
            workflow_id: 工作流 ID
            version_id: 版本 ID

        Returns:
            是否成功删除
        """
        versions = self._load_versions()
        if workflow_id not in versions:
            return False

        original_len = len(versions[workflow_id])
        versions[workflow_id] = [
            v for v in versions[workflow_id]
            if v.get("version_id") != version_id
        ]

        if len(versions[workflow_id]) == original_len:
            return False

        self._save_versions(versions)
        return True

    def get_stats(self) -> Dict[str, Any]:
        """获取版本管理统计信息."""
        versions = self._load_versions()

        total_versions = sum(len(v) for v in versions.values())
        workflow_count = len(versions)

        # 计算每个工作流的版本数
        version_counts = {
            wf_id: len(v_list) for wf_id, v_list in versions.items()
        }

        return {
            "total_workflows": workflow_count,
            "total_versions": total_versions,
            "avg_versions_per_workflow": round(total_versions / max(workflow_count, 1), 2),
            "version_counts": version_counts,
            "storage_path": str(self._versions_file),
        }


# 全局单例
_version_manager: Optional[WorkflowVersionManager] = None


def get_version_manager(data_dir: Optional[str] = None) -> WorkflowVersionManager:
    """获取版本管理器单例."""
    global _version_manager
    if _version_manager is None:
        _version_manager = WorkflowVersionManager(data_dir)
    return _version_manager
