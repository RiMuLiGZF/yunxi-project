"""M7 积木平台 - 存储层.

基于 JSON 文件的持久化存储，后续可扩展为数据库。
数据存储路径：~/.yunxi/m7_workflows.json, ~/.yunxi/m7_runs.json
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class JsonStorage:
    """JSON 文件存储.

    提供线程安全的 JSON 文件读写操作。
    使用文件锁防止并发写入冲突。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化存储.

        Args:
            data_dir: 数据目录，默认使用 ~/.yunxi
        """
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path.home() / ".yunxi"

        self._workflows_file = self._data_dir / "m7_workflows.json"
        self._runs_file = self._data_dir / "m7_runs.json"
        self._lock = threading.RLock()

        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _read_json(self, file_path: Path, default: Any) -> Any:
        """读取 JSON 文件.

        Args:
            file_path: 文件路径
            default: 文件不存在或解析失败时的默认值

        Returns:
            解析后的数据
        """
        with self._lock:
            if not file_path.exists():
                return default
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return default

    def _write_json(self, file_path: Path, data: Any) -> None:
        """写入 JSON 文件.

        Args:
            file_path: 文件路径
            data: 要写入的数据
        """
        with self._lock:
            # 确保父目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写入：先写临时文件再重命名
            tmp_path = file_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(file_path)

    # ------------------------------------------------------------------
    # 工作流 CRUD
    # ------------------------------------------------------------------

    def load_workflows(self) -> Dict[str, Dict[str, Any]]:
        """加载所有工作流.

        Returns:
            {workflow_id: workflow_dict} 字典
        """
        return self._read_json(self._workflows_file, {})

    def save_workflows(self, workflows: Dict[str, Dict[str, Any]]) -> None:
        """保存所有工作流.

        Args:
            workflows: {workflow_id: workflow_dict} 字典
        """
        self._write_json(self._workflows_file, workflows)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """获取单个工作流.

        Args:
            workflow_id: 工作流 ID

        Returns:
            工作流字典，不存在返回 None
        """
        workflows = self.load_workflows()
        return workflows.get(workflow_id)

    def upsert_workflow(self, workflow_id: str, workflow: Dict[str, Any]) -> None:
        """插入或更新工作流.

        Args:
            workflow_id: 工作流 ID
            workflow: 工作流字典
        """
        workflows = self.load_workflows()
        workflows[workflow_id] = workflow
        self.save_workflows(workflows)

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流.

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否成功删除
        """
        workflows = self.load_workflows()
        if workflow_id not in workflows:
            return False
        del workflows[workflow_id]
        self.save_workflows(workflows)
        return True

    def increment_run_count(self, workflow_id: str) -> None:
        """增加工作流的运行次数.

        Args:
            workflow_id: 工作流 ID
        """
        workflows = self.load_workflows()
        if workflow_id in workflows:
            workflows[workflow_id]["run_count"] = (
                workflows[workflow_id].get("run_count", 0) + 1
            )
            self.save_workflows(workflows)

    # ------------------------------------------------------------------
    # 运行记录 CRUD
    # ------------------------------------------------------------------

    def load_runs(self) -> Dict[str, List[Dict[str, Any]]]:
        """加载所有运行记录.

        Returns:
            {workflow_id: [run_record, ...]} 字典
        """
        return self._read_json(self._runs_file, {})

    def save_runs(self, runs: Dict[str, List[Dict[str, Any]]]) -> None:
        """保存所有运行记录.

        Args:
            runs: {workflow_id: [run_record, ...]} 字典
        """
        self._write_json(self._runs_file, runs)

    def get_workflow_runs(
        self, workflow_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取指定工作流的运行历史.

        Args:
            workflow_id: 工作流 ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            运行记录列表（按时间倒序）
        """
        runs = self.load_runs()
        run_list = runs.get(workflow_id, [])
        return run_list[offset : offset + limit]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """根据 run_id 获取单次运行记录.

        Args:
            run_id: 运行 ID

        Returns:
            运行记录字典，不存在返回 None
        """
        runs = self.load_runs()
        for run_list in runs.values():
            for run in run_list:
                if run.get("run_id") == run_id:
                    return run
        return None

    def add_run(self, workflow_id: str, run_record: Dict[str, Any], max_records: int = 100) -> None:
        """添加运行记录.

        Args:
            workflow_id: 工作流 ID
            run_record: 运行记录字典
            max_records: 每个工作流保留的最大记录数
        """
        runs = self.load_runs()
        if workflow_id not in runs:
            runs[workflow_id] = []
        runs[workflow_id].insert(0, run_record)
        # 限制记录数量
        if len(runs[workflow_id]) > max_records:
            runs[workflow_id] = runs[workflow_id][:max_records]
        self.save_runs(runs)

    def update_run(self, workflow_id: str, run_id: str, updates: Dict[str, Any]) -> bool:
        """更新运行记录.

        Args:
            workflow_id: 工作流 ID
            run_id: 运行 ID
            updates: 要更新的字段

        Returns:
            是否成功更新
        """
        runs = self.load_runs()
        if workflow_id not in runs:
            return False
        for i, run in enumerate(runs[workflow_id]):
            if run.get("run_id") == run_id:
                runs[workflow_id][i].update(updates)
                self.save_runs(runs)
                return True
        return False

    def delete_workflow_runs(self, workflow_id: str) -> bool:
        """删除指定工作流的所有运行记录.

        Args:
            workflow_id: 工作流 ID

        Returns:
            是否有记录被删除
        """
        runs = self.load_runs()
        if workflow_id not in runs:
            return False
        del runs[workflow_id]
        self.save_runs(runs)
        return True

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息.

        Returns:
            统计数据字典
        """
        workflows = self.load_workflows()
        runs = self.load_runs()

        total_runs = sum(len(run_list) for run_list in runs.values())
        total_run_count = sum(w.get("run_count", 0) for w in workflows.values())

        # 状态统计
        status_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        for wf in workflows.values():
            status = wf.get("status", "draft")
            status_counts[status] = status_counts.get(status, 0) + 1
            category = wf.get("category", "未分类")
            category_counts[category] = category_counts.get(category, 0) + 1

        return {
            "total_workflows": len(workflows),
            "total_runs": total_runs,
            "total_run_count": total_run_count,
            "workflow_status": status_counts,
            "workflow_categories": category_counts,
            "storage_path": str(self._data_dir),
            "workflows_file": str(self._workflows_file),
            "runs_file": str(self._runs_file),
        }



class DbStorage:
    """数据库存储（P2-25/P2-26）.

    提供与 JsonStorage 完全相同的 API，但底层使用 SQLite 数据库。
    数据库不可用时自动降级到 JSON 存储。
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化数据库存储.

        Args:
            data_dir: 数据目录，默认使用 ~/.yunxi
        """
        self._data_dir = data_dir
        self._db_available = False

        # 尝试初始化数据库
        try:
            from ..db import get_session, init_db
            init_db(data_dir)
            self._session = get_session()
            self._db_available = True
        except Exception:
            self._db_available = False

        # 如果数据库不可用，降级到 JSON
        if not self._db_available:
            self._json_fallback = JsonStorage(data_dir)
        else:
            self._json_fallback = None
            # 初始化仓库（自动迁移）
            from ..repositories import WorkflowRepository, RunRepository
            self._wf_repo = WorkflowRepository(self._session, data_dir)
            self._run_repo = RunRepository(self._session, data_dir)

    def _fallback(self) -> JsonStorage:
        """获取降级存储."""
        if self._json_fallback is None:
            self._json_fallback = JsonStorage(self._data_dir)
        return self._json_fallback

    # ------------------------------------------------------------------
    # 工作流 CRUD
    # ------------------------------------------------------------------

    def load_workflows(self) -> Dict[str, Dict[str, Any]]:
        """加载所有工作流."""
        if not self._db_available:
            return self._fallback().load_workflows()
        try:
            return self._wf_repo.get_all_dict()
        except Exception:
            return self._fallback().load_workflows()

    def save_workflows(self, workflows: Dict[str, Dict[str, Any]]) -> None:
        """保存所有工作流（全量覆盖，慎用）."""
        if not self._db_available:
            self._fallback().save_workflows(workflows)
            return
        try:
            # 全量覆盖：先删后写
            from ..models_db import WorkflowDefinition
            self._session.query(WorkflowDefinition).delete()
            for wf_id, wf_data in workflows.items():
                self._wf_repo.create(wf_id, wf_data)
        except Exception:
            self._fallback().save_workflows(workflows)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """获取单个工作流."""
        if not self._db_available:
            return self._fallback().get_workflow(workflow_id)
        try:
            wf = self._wf_repo.get(workflow_id)
            return wf.to_dict() if wf else None
        except Exception:
            return self._fallback().get_workflow(workflow_id)

    def upsert_workflow(self, workflow_id: str, workflow: Dict[str, Any]) -> None:
        """插入或更新工作流."""
        if not self._db_available:
            self._fallback().upsert_workflow(workflow_id, workflow)
            return
        try:
            existing = self._wf_repo.get(workflow_id)
            if existing:
                self._wf_repo.update(workflow_id, workflow)
            else:
                self._wf_repo.create(workflow_id, workflow)
        except Exception:
            self._fallback().upsert_workflow(workflow_id, workflow)

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流."""
        if not self._db_available:
            return self._fallback().delete_workflow(workflow_id)
        try:
            # 同时删除运行记录
            self._run_repo.delete_by_workflow(workflow_id)
            return self._wf_repo.delete(workflow_id)
        except Exception:
            return self._fallback().delete_workflow(workflow_id)

    def increment_run_count(self, workflow_id: str) -> None:
        """增加工作流的运行次数."""
        if not self._db_available:
            self._fallback().increment_run_count(workflow_id)
            return
        try:
            self._wf_repo.increment_run_count(workflow_id)
        except Exception:
            self._fallback().increment_run_count(workflow_id)

    # ------------------------------------------------------------------
    # 运行记录 CRUD
    # ------------------------------------------------------------------

    def load_runs(self) -> Dict[str, List[Dict[str, Any]]]:
        """加载所有运行记录."""
        if not self._db_available:
            return self._fallback().load_runs()
        try:
            # 全量加载并按 workflow_id 分组
            from ..models_db import WorkflowRunRecord
            all_runs = self._session.query(WorkflowRunRecord).all()
            result: Dict[str, List[Dict[str, Any]]] = {}
            for run in all_runs:
                wf_id = run.workflow_id
                if wf_id not in result:
                    result[wf_id] = []
                result[wf_id].append(run.to_dict())
            # 按时间倒序
            for wf_id in result:
                result[wf_id].sort(key=lambda x: x.get("started_at", ""), reverse=True)
            return result
        except Exception:
            return self._fallback().load_runs()

    def save_runs(self, runs: Dict[str, List[Dict[str, Any]]]) -> None:
        """保存所有运行记录（全量覆盖，慎用）."""
        if not self._db_available:
            self._fallback().save_runs(runs)
            return
        try:
            from ..models_db import WorkflowRunRecord
            self._session.query(WorkflowRunRecord).delete()
            for wf_id, run_list in runs.items():
                for run_data in run_list:
                    self._run_repo.add(wf_id, run_data)
        except Exception:
            self._fallback().save_runs(runs)

    def get_workflow_runs(
        self, workflow_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取指定工作流的运行历史."""
        if not self._db_available:
            return self._fallback().get_workflow_runs(workflow_id, limit, offset)
        try:
            runs = self._run_repo.list_by_workflow(workflow_id, limit=limit, offset=offset)
            return [r.to_dict() for r in runs]
        except Exception:
            return self._fallback().get_workflow_runs(workflow_id, limit, offset)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """根据 run_id 获取单次运行记录."""
        if not self._db_available:
            return self._fallback().get_run(run_id)
        try:
            run = self._run_repo.get(run_id)
            return run.to_dict() if run else None
        except Exception:
            return self._fallback().get_run(run_id)

    def add_run(self, workflow_id: str, run_record: Dict[str, Any], max_records: int = 100) -> None:
        """添加运行记录."""
        if not self._db_available:
            self._fallback().add_run(workflow_id, run_record, max_records)
            return
        try:
            self._run_repo.add(workflow_id, run_record)
            # 限制记录数（超出则删除最旧的）
            count = self._run_repo.count_by_workflow(workflow_id)
            if count > max_records:
                from ..models_db import WorkflowRunRecord
                from sqlalchemy import asc
                # 找出超出的记录并删除
                excess = count - max_records
                old_runs = (
                    self._session.query(WorkflowRunRecord)
                    .filter(WorkflowRunRecord.workflow_id == workflow_id)
                    .order_by(asc(WorkflowRunRecord.started_at))
                    .limit(excess)
                    .all()
                )
                for r in old_runs:
                    self._session.delete(r)
                self._session.commit()
        except Exception:
            self._fallback().add_run(workflow_id, run_record, max_records)

    def update_run(self, workflow_id: str, run_id: str, updates: Dict[str, Any]) -> bool:
        """更新运行记录."""
        if not self._db_available:
            return self._fallback().update_run(workflow_id, run_id, updates)
        try:
            return self._run_repo.update(run_id, updates)
        except Exception:
            return self._fallback().update_run(workflow_id, run_id, updates)

    def delete_workflow_runs(self, workflow_id: str) -> bool:
        """删除指定工作流的所有运行记录."""
        if not self._db_available:
            return self._fallback().delete_workflow_runs(workflow_id)
        try:
            count = self._run_repo.delete_by_workflow(workflow_id)
            return count > 0
        except Exception:
            return self._fallback().delete_workflow_runs(workflow_id)

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息."""
        if not self._db_available:
            return self._fallback().get_stats()
        try:
            wf_stats = self._wf_repo.get_stats()
            total_runs = self._run_repo.count()
            return {
                **wf_stats,
                "total_runs": total_runs,
                "storage_path": str(self._data_dir or (Path.home() / ".yunxi")),
                "storage_backend": "database",
            }
        except Exception:
            return self._fallback().get_stats()


# 全局单例
_storage: Optional[JsonStorage] = None


def get_storage(data_dir: Optional[str] = None) -> "Union[JsonStorage, DbStorage]":
    """获取存储单例.

    P2-25: 优先使用数据库存储，不可用时降级到 JSON 文件存储。

    Args:
        data_dir: 数据目录（首次调用时有效）

    Returns:
        存储实例（DbStorage 或 JsonStorage），两者 API 完全一致
    """
    global _storage
    if _storage is None:
        try:
            _storage = DbStorage(data_dir)
        except Exception:
            _storage = JsonStorage(data_dir)
    return _storage
