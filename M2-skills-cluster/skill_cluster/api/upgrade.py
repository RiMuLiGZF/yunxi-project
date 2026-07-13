"""M8 升级管理接口.

实现 4 个升级管理标准接口：
1. GET  /api/v2/code/snapshot    — 代码快照（版本信息）
2. POST /api/v2/upgrade/preview  — 升级预览
3. POST /api/v2/upgrade/apply    — 应用升级
4. POST /api/v2/upgrade/rollback — 版本回滚

【MVP 阶段说明】
当前为 MVP 实现，升级/回滚逻辑为 Mock 状态机模拟。
真实的包下载、安装、重启逻辑后续接入 M8 管理平台时完善。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.error_codes import ErrorCode, make_error_response, make_success_response

logger = structlog.get_logger()

# FastAPI 可选导入
_fastapi_available = False
try:
    from fastapi import APIRouter, HTTPException, Header
    _fastapi_available = True
except ImportError:
    APIRouter = None  # type: ignore[assignment, misc]


# ---- 请求/响应模型 ----

class UpgradePreviewRequest(BaseModel):
    """升级预览请求."""
    target_version: str = Field(..., description="目标版本号")
    package_url: str = Field(default="", description="升级包下载地址")


class UpgradeApplyRequest(BaseModel):
    """应用升级请求."""
    target_version: str = Field(..., description="目标版本号")
    package_url: str = Field(default="", description="升级包下载地址")
    backup_before: bool = Field(default=True, description="升级前是否备份")


class UpgradeTaskResponse(BaseModel):
    """升级任务响应."""
    task_id: str
    status: str  # pending / downloading / installing / restarting / done / failed
    progress: int = 0
    target_version: str = ""


class CodeSnapshotData(BaseModel):
    """代码快照数据."""
    version: str
    commit_hash: str
    build_time: str
    branch: str
    module: str = "m2"


# ---- 升级管理器 ----

class UpgradeManager:
    """升级管理器（MVP 实现）.

    管理升级任务的状态流转和审计日志。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._audit_log: list[dict] = []
        self._backup_versions: list[str] = []  # 可用的备份版本

    def get_code_snapshot(self) -> dict[str, Any]:
        """获取代码快照信息."""
        version = self._get_version()
        commit_hash = self._get_git_commit()
        build_time = self._get_build_time()
        branch = self._get_git_branch()

        return {
            "version": version,
            "commit_hash": commit_hash,
            "build_time": build_time,
            "branch": branch,
            "module": "m2",
        }

    def preview_upgrade(self, target_version: str, package_url: str = "") -> dict[str, Any]:
        """升级预览（兼容性检查）."""
        current_version = self._get_version()

        # 版本比较（简单语义化版本比较）
        impact_level = self._calc_impact_level(current_version, target_version)

        # Mock 变更列表
        changes = [
            {"type": "feature", "description": "新增升级管理接口"},
            {"type": "improvement", "description": "优化推荐引擎准确率"},
            {"type": "bugfix", "description": "修复若干已知问题"},
        ]

        risks: list[str] = []
        if impact_level == "high":
            risks.append("大版本升级，可能存在不兼容变更")

        prerequisites = [
            "M8 管理平台版本 >= 1.0.0",
            "磁盘空间 >= 500MB",
        ]

        return {
            "compatible": True,  # MVP 阶段默认为兼容
            "impact_level": impact_level,
            "estimated_duration_sec": 60 if impact_level == "low" else 120,
            "requires_restart": True,
            "changes": changes,
            "risks": risks,
            "prerequisites": prerequisites,
            "current_version": current_version,
            "target_version": target_version,
        }

    def apply_upgrade(self, target_version: str, package_url: str = "", backup_before: bool = True) -> dict[str, Any]:
        """应用升级（异步执行）.

        MVP 阶段：创建任务并启动模拟升级流程。
        """
        task_id = f"upgrade-m2-{target_version}-{uuid.uuid4().hex[:8]}"

        task = {
            "task_id": task_id,
            "type": "upgrade",
            "target_version": target_version,
            "package_url": package_url,
            "backup_before": backup_before,
            "status": "pending",
            "progress": 0,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

        self._tasks[task_id] = task
        self._log_audit("upgrade_apply", task)

        # 异步执行升级
        asyncio.create_task(self._simulate_upgrade(task_id))

        return {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "target_version": target_version,
        }

    def rollback(self) -> dict[str, Any]:
        """版本回滚.

        MVP 阶段：创建回滚任务并模拟执行。
        """
        # 检查是否有可回滚的版本
        if not self._backup_versions:
            # 如果没有备份，回退到当前版本的上一个小版本（mock）
            current = self._get_version()
            parts = current.split(".")
            if len(parts) >= 3:
                parts[-1] = str(max(0, int(parts[-1]) - 1))
            rollback_to = ".".join(parts)
        else:
            rollback_to = self._backup_versions[-1]

        task_id = f"rollback-m2-{uuid.uuid4().hex[:8]}"

        task = {
            "task_id": task_id,
            "type": "rollback",
            "rollback_to_version": rollback_to,
            "status": "pending",
            "progress": 0,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

        self._tasks[task_id] = task
        self._log_audit("rollback_init", task)

        # 异步执行回滚
        asyncio.create_task(self._simulate_rollback(task_id))

        return {
            "task_id": task_id,
            "status": "pending",
            "rollback_to_version": rollback_to,
        }

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """获取升级/回滚任务状态."""
        return self._tasks.get(task_id)

    async def _simulate_upgrade(self, task_id: str) -> None:
        """模拟升级流程（MVP）."""
        task = self._tasks.get(task_id)
        if not task:
            return

        task["status"] = "downloading"
        task["started_at"] = time.time()
        task["progress"] = 10
        await asyncio.sleep(0.1)

        task["status"] = "installing"
        task["progress"] = 40
        await asyncio.sleep(0.1)

        if task["backup_before"]:
            # 记录备份
            self._backup_versions.append(self._get_version())

        task["status"] = "restarting"
        task["progress"] = 80
        await asyncio.sleep(0.1)

        task["status"] = "done"
        task["progress"] = 100
        task["finished_at"] = time.time()
        self._log_audit("upgrade_done", task)

    async def _simulate_rollback(self, task_id: str) -> None:
        """模拟回滚流程（MVP）."""
        task = self._tasks.get(task_id)
        if not task:
            return

        task["status"] = "pending"
        task["started_at"] = time.time()
        task["progress"] = 10
        await asyncio.sleep(0.1)

        task["status"] = "restarting"
        task["progress"] = 60
        await asyncio.sleep(0.1)

        task["status"] = "done"
        task["progress"] = 100
        task["finished_at"] = time.time()
        self._log_audit("rollback_done", task)

    def _get_version(self) -> str:
        """获取当前版本号."""
        try:
            from skill_cluster.version import __version__
            return __version__
        except ImportError:
            return "0.0.0"

    def _get_git_commit(self) -> str:
        """获取 Git commit hash."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _get_git_branch(self) -> str:
        """获取 Git 分支名."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _get_build_time(self) -> str:
        """获取构建时间."""
        try:
            from skill_cluster.version import BUILD_DATE
            return f"{BUILD_DATE}T00:00:00Z"
        except ImportError:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _calc_impact_level(self, current: str, target: str) -> str:
        """计算升级影响级别.

        主版本不同 → high
        次版本不同 → medium
        修订版本不同 → low
        """
        try:
            cur_parts = [int(p) for p in current.split(".")[:3]]
            tgt_parts = [int(p) for p in target.split(".")[:3]]
            if cur_parts[0] != tgt_parts[0]:
                return "high"
            if cur_parts[1] != tgt_parts[1]:
                return "medium"
            return "low"
        except Exception:
            return "medium"

    def _log_audit(self, action: str, task: dict) -> None:
        """记录审计日志."""
        entry = {
            "timestamp": time.time(),
            "action": action,
            "task_id": task.get("task_id", ""),
            "type": task.get("type", ""),
            "target_version": task.get("target_version", task.get("rollback_to_version", "")),
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-250:]


# ---- FastAPI 路由注册 ----

def register_upgrade_routes(
    router: Any,
    upgrade_manager: UpgradeManager | None = None,
) -> UpgradeManager:
    """注册升级管理路由到 FastAPI 路由器.

    Args:
        router: FastAPI APIRouter 或 FastAPI 实例
        upgrade_manager: 升级管理器实例（可选，不传则创建新的）

    Returns:
        UpgradeManager 实例
    """
    if not _fastapi_available:
        logger.warning("upgrade_routes_disabled", reason="fastapi not installed")
        return upgrade_manager or UpgradeManager()

    mgr = upgrade_manager or UpgradeManager()

    @router.get("/api/v2/code/snapshot")
    async def code_snapshot(x_trace_id: str | None = Header(default=None)):
        """代码快照接口.

        返回当前模块的版本、commit、构建时间等信息。
        """
        trace_id = x_trace_id or str(uuid.uuid4())
        try:
            data = mgr.get_code_snapshot()
            return make_success_response(data=data, trace_id=trace_id)
        except Exception as e:
            logger.error("code_snapshot_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    @router.post("/api/v2/upgrade/preview")
    async def upgrade_preview(
        req: UpgradePreviewRequest,
        x_trace_id: str | None = Header(default=None),
    ):
        """升级预览接口.

        检查目标版本的兼容性、影响级别、预计耗时等。
        """
        trace_id = x_trace_id or str(uuid.uuid4())
        try:
            data = mgr.preview_upgrade(req.target_version, req.package_url)
            return make_success_response(data=data, message="升级预览完成", trace_id=trace_id)
        except Exception as e:
            logger.error("upgrade_preview_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    @router.post("/api/v2/upgrade/apply")
    async def upgrade_apply(
        req: UpgradeApplyRequest,
        x_trace_id: str | None = Header(default=None),
    ):
        """应用升级接口.

        触发升级流程，返回任务ID，支持轮询查询状态。
        """
        trace_id = x_trace_id or str(uuid.uuid4())
        try:
            data = mgr.apply_upgrade(req.target_version, req.package_url, req.backup_before)
            return make_success_response(
                data=data,
                message="upgrade_task_created",
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("upgrade_apply_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    @router.post("/api/v2/upgrade/rollback")
    async def upgrade_rollback(
        x_trace_id: str | None = Header(default=None),
    ):
        """版本回滚接口.

        回滚到上一个备份版本。
        """
        trace_id = x_trace_id or str(uuid.uuid4())
        try:
            data = mgr.rollback()
            return make_success_response(
                data=data,
                message="rollback_initiated",
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("rollback_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    @router.get("/api/v2/upgrade/tasks/{task_id}")
    async def get_upgrade_task(
        task_id: str,
        x_trace_id: str | None = Header(default=None),
    ):
        """查询升级/回滚任务状态."""
        trace_id = x_trace_id or str(uuid.uuid4())
        task = mgr.get_task(task_id)
        if not task:
            return make_error_response(
                ErrorCode.NOT_FOUND,
                message=f"任务 {task_id} 不存在",
                trace_id=trace_id,
            )
        return make_success_response(data=task, trace_id=trace_id)

    return mgr
