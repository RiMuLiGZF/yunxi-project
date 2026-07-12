"""M8 测试管理接口.

实现 2 个测试管理标准接口：
1. POST /api/v2/test/run           — 运行测试套件
2. GET  /api/v2/test/result/{id}  — 查询测试结果

支持的测试套件：all / unit / integration / smoke

测试执行异步化，不阻塞 API 响应。
结果保留最近 10 条。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
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
    from fastapi import APIRouter, Header
    _fastapi_available = True
except ImportError:
    APIRouter = None  # type: ignore[assignment, misc]


# ---- 请求/响应模型 ----

class TestRunRequest(BaseModel):
    """运行测试请求."""
    suite: str = Field(default="all", description="测试套件: all/unit/integration/smoke")
    timeout_sec: int = Field(default=300, ge=10, le=3600, description="超时时间(秒)")


class TestTaskResponse(BaseModel):
    """测试任务响应."""
    task_id: str
    status: str  # running / completed / failed / timeout
    suite: str
    started_at: str


class TestResultData(BaseModel):
    """测试结果数据."""
    task_id: str
    status: str
    suite: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    failures: list[dict] = Field(default_factory=list)
    summary: str = ""


# ---- 测试执行器 ----

class TestManager:
    """测试管理器.

    负责异步执行测试套件，管理测试任务和结果。
    """

    # 套件对应的测试路径
    SUITE_PATHS = {
        "all": "skill_cluster/tests skills_core/tests",
        "unit": "skill_cluster/tests",
        "integration": "skills_core/tests",
        "smoke": "skill_cluster/tests/test_skill_discovery.py",
    }

    def __init__(self, max_results: int = 10) -> None:
        self._results: dict[str, dict] = {}  # task_id -> result
        self._max_results = max_results
        self._result_order: list[str] = []  # 按时间顺序的 task_id 列表

    def run_tests(self, suite: str = "all", timeout_sec: int = 300) -> dict[str, Any]:
        """触发测试运行（异步）.

        Args:
            suite: 测试套件名称
            timeout_sec: 超时时间（秒）

        Returns:
            任务信息字典
        """
        task_id = f"test-m2-{uuid.uuid4().hex[:8]}"

        result = {
            "task_id": task_id,
            "status": "running",
            "suite": suite,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration_ms": 0.0,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "finished_at": "",
            "failures": [],
            "summary": "",
        }

        self._results[task_id] = result
        self._result_order.append(task_id)
        self._trim_results()

        # 异步执行
        asyncio.create_task(self._execute_tests(task_id, suite, timeout_sec))

        return {
            "task_id": task_id,
            "status": "running",
            "suite": suite,
            "started_at": result["started_at"],
        }

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        """获取测试结果."""
        return self._results.get(task_id)

    def list_tasks(self, limit: int = 10) -> list[dict]:
        """列出最近的测试任务."""
        tasks = []
        for tid in reversed(self._result_order[-limit:]):
            r = self._results.get(tid)
            if r:
                tasks.append({
                    "task_id": r["task_id"],
                    "status": r["status"],
                    "suite": r["suite"],
                    "total": r["total"],
                    "passed": r["passed"],
                    "failed": r["failed"],
                    "duration_ms": r["duration_ms"],
                    "started_at": r["started_at"],
                })
        return tasks

    async def _execute_tests(self, task_id: str, suite: str, timeout_sec: int) -> None:
        """执行测试（异步，实际运行 pytest）."""
        result = self._results.get(task_id)
        if not result:
            return

        start_time = time.time()

        try:
            test_path = self.SUITE_PATHS.get(suite, self.SUITE_PATHS["all"])

            # 创建临时文件存 JSON 报告
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as f:
                report_path = f.name

            # 运行 pytest
            cmd = [
                "python", "-m", "pytest",
                test_path,
                "--json-report",
                f"--json-report-file={report_path}",
                "--tb=short",
                "-q",
            ]

            # 在事件循环中运行子进程
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(os.path.dirname(__file__)) + "/..",
            )

            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_sec)
                stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
                exit_code = proc.returncode
            except asyncio.TimeoutError:
                proc.kill()
                result["status"] = "timeout"
                result["summary"] = f"测试超时（>{timeout_sec}秒）"
                result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                result["duration_ms"] = (time.time() - start_time) * 1000
                return

            # 解析 JSON 报告
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    report = json.load(f)

                result["total"] = report.get("total", 0)
                result["passed"] = report.get("passed", 0)
                result["failed"] = report.get("failed", 0)
                result["skipped"] = report.get("skipped", 0)

                # 提取失败用例
                failures = []
                for test in report.get("tests", []):
                    if test.get("outcome") == "failed":
                        failures.append({
                            "name": test.get("name", ""),
                            "file": test.get("file", ""),
                            "error": test.get("call", {}).get("longrepr", "")[:500],
                        })
                result["failures"] = failures[:10]  # 最多10个失败详情

                if result["failed"] > 0:
                    result["status"] = "failed"
                    result["summary"] = f"{result['passed']}/{result['total']} passed, {result['failed']} failed"
                else:
                    result["status"] = "completed"
                    result["summary"] = "All tests passed"

            except (json.JSONDecodeError, FileNotFoundError):
                # JSON 报告不存在或解析失败，用 stderr 估算
                result["status"] = "failed"
                result["summary"] = stderr_text[:500] if stderr_text else "测试执行失败"
                result["total"] = 0
                result["failed"] = 1
                result["failures"] = [{"name": "execution_error", "error": stderr_text[:500]}]

            finally:
                # 清理临时文件
                try:
                    os.unlink(report_path)
                except OSError:
                    pass

        except Exception as e:
            result["status"] = "failed"
            result["summary"] = f"执行异常: {str(e)}"
            result["failed"] = 1
            result["failures"] = [{"name": "execution_error", "error": str(e)}]

        result["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result["duration_ms"] = round((time.time() - start_time) * 1000, 1)

        logger.info(
            "test_completed",
            task_id=task_id,
            suite=suite,
            status=result["status"],
            total=result["total"],
            passed=result["passed"],
            failed=result["failed"],
            duration_ms=result["duration_ms"],
        )

    def _trim_results(self) -> None:
        """清理过期结果，保留最近 N 条."""
        if len(self._result_order) > self._max_results:
            to_remove = self._result_order[:-self._max_results]
            for tid in to_remove:
                self._results.pop(tid, None)
            self._result_order = self._result_order[-self._max_results:]


# ---- FastAPI 路由注册 ----

def register_test_routes(
    router: Any,
    test_manager: TestManager | None = None,
) -> TestManager:
    """注册测试管理路由到 FastAPI 路由器.

    Args:
        router: FastAPI APIRouter 或 FastAPI 实例
        test_manager: 测试管理器实例（可选，不传则创建新的）

    Returns:
        TestManager 实例
    """
    if not _fastapi_available:
        logger.warning("test_routes_disabled", reason="fastapi not installed")
        return test_manager or TestManager()

    mgr = test_manager or TestManager()

    @router.post("/api/v2/test/run")
    async def run_test(
        req: TestRunRequest,
        x_trace_id: str | None = Header(default=None),
    ):
        """运行测试接口.

        异步触发测试套件，返回任务ID，可通过结果接口轮询状态。
        """
        trace_id = x_trace_id or str(uuid.uuid4())

        # 校验套件名称
        if req.suite not in TestManager.SUITE_PATHS:
            return make_error_response(
                ErrorCode.INVALID_PARAMS,
                message=f"不支持的测试套件: {req.suite}，支持: {', '.join(TestManager.SUITE_PATHS.keys())}",
                trace_id=trace_id,
            )

        try:
            data = mgr.run_tests(req.suite, req.timeout_sec)
            return make_success_response(
                data=data,
                message="test_task_created",
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("run_test_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    @router.get("/api/v2/test/result/{task_id}")
    async def get_test_result(
        task_id: str,
        x_trace_id: str | None = Header(default=None),
    ):
        """查询测试结果接口.

        根据任务ID查询测试执行结果。
        """
        trace_id = x_trace_id or str(uuid.uuid4())

        result = mgr.get_result(task_id)
        if not result:
            return make_error_response(
                ErrorCode.NOT_FOUND,
                message=f"测试任务 {task_id} 不存在",
                trace_id=trace_id,
            )

        return make_success_response(data=result, trace_id=trace_id)

    @router.get("/api/v2/test/tasks")
    async def list_test_tasks(
        limit: int = 10,
        x_trace_id: str | None = Header(default=None),
    ):
        """列出最近的测试任务."""
        trace_id = x_trace_id or str(uuid.uuid4())

        try:
            tasks = mgr.list_tasks(limit=limit)
            return make_success_response(
                data={"tasks": tasks, "total": len(tasks)},
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("list_test_tasks_error", error=str(e), trace_id=trace_id)
            return make_error_response(
                ErrorCode.INTERNAL_ERROR,
                message=str(e),
                trace_id=trace_id,
            )

    return mgr
