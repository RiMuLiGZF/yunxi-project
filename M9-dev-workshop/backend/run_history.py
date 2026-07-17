"""M9 开发者工坊 - 运行配置和历史记录.

提供代码运行配置和历史记录管理：
- 自定义运行命令
- 环境变量配置
- 工作目录配置
- 运行历史记录
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .core.path_safety import safe_join, assert_path_safe, PathSecurityError
except ImportError:
    from core.path_safety import safe_join, assert_path_safe, PathSecurityError

try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class RunConfiguration:
    """运行配置模型."""

    def __init__(
        self,
        name: str = "default",
        language: str = "python",
        command: str = "",
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        working_dir: str = "",
        timeout: int = 30,
    ):
        self.name = name
        self.language = language
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.working_dir = working_dir
        self.timeout = timeout

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "working_dir": self.working_dir,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunConfiguration":
        return cls(
            name=data.get("name", "default"),
            language=data.get("language", "python"),
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            working_dir=data.get("working_dir", ""),
            timeout=data.get("timeout", 30),
        )


class RunHistoryManager:
    """运行历史记录管理器."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._history_dir = Path(self.settings.workspace_root) / ".run_history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._max_records = 100

    def _get_history_file(self, project_path: str) -> Path:
        """获取项目的历史记录文件路径."""
        # 使用项目路径的哈希作为文件名
        import hashlib
        path_hash = hashlib.md5(project_path.encode()).hexdigest()[:16]
        return self._history_dir / f"{path_hash}.json"

    def add_run_record(
        self,
        project_path: str,
        config: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """添加运行记录.

        Args:
            project_path: 项目路径
            config: 运行配置
            result: 运行结果

        Returns:
            记录信息
        """
        history_file = self._get_history_file(project_path)

        # 读取现有记录
        records = []
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (json.JSONDecodeError, OSError):
                records = []

        # 创建新记录
        record_id = f"run_{uuid.uuid4().hex[:12]}"
        record = {
            "run_id": record_id,
            "timestamp": time.time(),
            "config": config,
            "result": {
                "success": result.get("success", False),
                "exit_code": result.get("exit_code"),
                "stdout": result.get("stdout", "")[:5000],  # 限制长度
                "stderr": result.get("stderr", "")[:5000],
                "execution_time": result.get("execution_time", 0),
            },
            "language": config.get("language", "python"),
        }

        records.insert(0, record)

        # 限制记录数量
        if len(records) > self._max_records:
            records = records[: self._max_records]

        # 保存
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        return record

    def get_run_history(
        self,
        project_path: str,
        limit: int = 20,
        offset: int = 0,
        success_only: bool = False,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取运行历史.

        Args:
            project_path: 项目路径
            limit: 返回数量限制
            offset: 偏移量
            success_only: 仅返回成功的记录
            language: 按语言过滤

        Returns:
            历史记录
        """
        history_file = self._get_history_file(project_path)

        if not history_file.exists():
            return {
                "total": 0,
                "items": [],
                "limit": limit,
                "offset": offset,
            }

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            records = []

        # 过滤
        if success_only:
            records = [r for r in records if r.get("result", {}).get("success", False)]

        if language:
            records = [r for r in records if r.get("language") == language]

        total = len(records)
        paged = records[offset : offset + limit]

        return {
            "total": total,
            "items": paged,
            "limit": limit,
            "offset": offset,
        }

    def get_run_detail(
        self,
        project_path: str,
        run_id: str,
    ) -> Optional[Dict[str, Any]]:
        """获取单次运行详情.

        Args:
            project_path: 项目路径
            run_id: 运行 ID

        Returns:
            运行详情
        """
        history_file = self._get_history_file(project_path)

        if not history_file.exists():
            return None

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        for record in records:
            if record.get("run_id") == run_id:
                return record

        return None

    def clear_history(self, project_path: str) -> bool:
        """清除运行历史.

        Args:
            project_path: 项目路径

        Returns:
            是否成功
        """
        history_file = self._get_history_file(project_path)
        if history_file.exists():
            try:
                history_file.unlink()
                return True
            except OSError:
                return False
        return True

    def get_stats(self, project_path: str) -> Dict[str, Any]:
        """获取运行统计.

        Args:
            project_path: 项目路径

        Returns:
            统计信息
        """
        history_file = self._get_history_file(project_path)

        if not history_file.exists():
            return {
                "total_runs": 0,
                "success_count": 0,
                "failed_count": 0,
                "success_rate": 0,
                "avg_execution_time": 0,
                "last_run_at": None,
            }

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError):
            records = []

        total = len(records)
        success_count = sum(1 for r in records if r.get("result", {}).get("success", False))
        failed_count = total - success_count
        success_rate = round(success_count / max(total, 1) * 100, 2)

        exec_times = [r.get("result", {}).get("execution_time", 0) for r in records]
        avg_time = round(sum(exec_times) / max(len(exec_times), 1), 3) if exec_times else 0

        last_run = records[0]["timestamp"] if records else None

        # 按语言统计
        by_language: Dict[str, Dict[str, Any]] = {}
        for r in records:
            lang = r.get("language", "unknown")
            if lang not in by_language:
                by_language[lang] = {"count": 0, "success": 0}
            by_language[lang]["count"] += 1
            if r.get("result", {}).get("success"):
                by_language[lang]["success"] += 1

        return {
            "total_runs": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "success_rate": success_rate,
            "avg_execution_time": avg_time,
            "last_run_at": last_run,
            "by_language": by_language,
        }


# 全局单例
_run_history_manager: Optional[RunHistoryManager] = None


def get_run_history_manager() -> RunHistoryManager:
    """获取运行历史管理器单例."""
    global _run_history_manager
    if _run_history_manager is None:
        _run_history_manager = RunHistoryManager()
    return _run_history_manager
