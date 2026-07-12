"""测试管理接口（M8 标准）.

提供 M8 管理平台需要的测试管理接口：
- POST /api/v3/test/run        # 运行测试
- GET  /api/v3/test/result/{task_id}  # 测试结果
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_TEST_TIMEOUT = 300  # 秒
TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests")


class TestStatus(str, Enum):
    """测试任务状态."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class TestTask:
    """测试任务."""
    task_id: str
    suite: str
    timeout_sec: int
    status: TestStatus = TestStatus.PENDING
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    total: int = 0
    passed: int = 0
    failed: int = 0
    duration_ms: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    output: str = ""


class TestManager:
    """测试管理器.

    封装 pytest 执行，支持异步运行测试和结果查询。

    Attributes:
        _tasks: 测试任务字典.
        _tests_dir: 测试目录路径.
    """

    def __init__(self, tests_dir: str = "") -> None:
        """初始化测试管理器.

        Args:
            tests_dir: 测试目录路径。为空则使用默认路径.
        """
        self._tasks: dict[str, TestTask] = {}
        self._tests_dir = tests_dir or TESTS_DIR
        logger.info("test_manager.initialized", tests_dir=self._tests_dir)

    # -----------------------------------------------------------------------
    # POST /api/v3/test/run
    # -----------------------------------------------------------------------

    async def run_tests(
        self,
        suite: str = "all",
        timeout_sec: int = DEFAULT_TEST_TIMEOUT,
        request_id: str = "",
    ) -> dict[str, Any]:
        """运行测试.

        Args:
            suite: 测试套件名（all / 具体文件名 / 测试路径）.
            timeout_sec: 超时时间（秒）.
            request_id: 请求追踪ID.

        Returns:
            测试任务信息.
        """
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        task_id = f"test_{uuid.uuid4().hex[:12]}"
        task = TestTask(
            task_id=task_id,
            suite=suite,
            timeout_sec=timeout_sec,
        )
        self._tasks[task_id] = task

        # 后台异步执行
        asyncio.create_task(self._run_pytest(task_id, suite, timeout_sec))

        logger.info(
            "test_manager.run_started",
            task_id=task_id,
            suite=suite,
            timeout=timeout_sec,
        )

        return {
            "task_id": task_id,
            "status": task.status.value,
            "suite": suite,
            "started_at": task.started_at,
        }

    async def _run_pytest(self, task_id: str, suite: str, timeout_sec: int) -> None:
        """后台执行 pytest."""
        task = self._tasks.get(task_id)
        if not task:
            return

        task.status = TestStatus.RUNNING

        try:
            # 确定测试目标
            test_target = self._tests_dir
            if suite and suite != "all":
                test_target = os.path.join(self._tests_dir, suite)
                # 如果不是文件，就用整个目录
                if not os.path.exists(test_target):
                    test_target = self._tests_dir

            # 构造 pytest 命令
            cmd = [
                "python", "-m", "pytest",
                test_target,
                "-v",
                "--tb=short",
                "--timeout", str(timeout_sec),
                "--no-header",
                "-q",
            ]

            # 执行
            start_time = time.time()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(self._tests_dir),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout_sec,
                )
                elapsed = time.time() - start_time
                task.duration_ms = int(elapsed * 1000)

                output = stdout.decode("utf-8", errors="replace")
                task.output = output[-5000:]  # 限制输出长度

                # 解析结果
                task.total, task.passed, task.failed, task.failures = self._parse_pytest_output(output)

                if proc.returncode == 0:
                    task.status = TestStatus.COMPLETED
                    task.summary = f"All {task.passed} tests passed"
                else:
                    task.status = TestStatus.FAILED
                    task.summary = f"{task.failed} of {task.total} tests failed"

            except asyncio.TimeoutError:
                proc.kill()
                task.status = TestStatus.TIMEOUT
                task.summary = f"Test timed out after {timeout_sec}s"
                task.duration_ms = timeout_sec * 1000

            task.completed_at = time.time()

        except Exception as e:
            task.status = TestStatus.FAILED
            task.summary = f"Error: {str(e)}"
            task.completed_at = time.time()
            logger.exception("test_manager.run_error", task_id=task_id)

        logger.info(
            "test_manager.run_completed",
            task_id=task_id,
            status=task.status.value,
            total=task.total,
            passed=task.passed,
            failed=task.failed,
            duration_ms=task.duration_ms,
        )

    def _parse_pytest_output(self, output: str) -> tuple[int, int, int, list[dict]]:
        """解析 pytest 输出.

        Returns:
            (total, passed, failed, failures_list).
        """
        total = 0
        passed = 0
        failed = 0
        failures: list[dict[str, Any]] = []

        lines = output.strip().split("\n")

        # 从最后几行找统计信息
        for line in reversed(lines[-20:]):
            line = line.strip()
            # 形如 "5 passed, 2 failed in 1.23s"
            if "passed" in line and "in " in line:
                parts = line.split(",")
                for part in parts:
                    part = part.strip()
                    if "passed" in part:
                        try:
                            passed = int(part.split()[0])
                        except (ValueError, IndexError):
                            pass
                    elif "failed" in part:
                        try:
                            failed = int(part.split()[0])
                        except (ValueError, IndexError):
                            pass
                total = passed + failed
                break

        # 收集失败用例
        current_failure: dict[str, Any] | None = None
        for line in lines:
            if line.startswith("FAILED ") or "::" in line and "FAILED" in line:
                # 提取失败用例名
                test_name = line.strip().split("FAILED")[-1].strip() if "FAILED" in line else line.strip()
                current_failure = {"test": test_name, "error": ""}
                failures.append(current_failure)
            elif current_failure is not None and line.strip().startswith(">"):
                current_failure["error"] += line.strip() + "\n"
                if len(failures) >= 10:  # 最多保留 10 条失败
                    break

        return total, passed, failed, failures[:10]

    # -----------------------------------------------------------------------
    # GET /api/v3/test/result/{task_id}
    # -----------------------------------------------------------------------

    def get_result(self, task_id: str, request_id: str = "") -> dict[str, Any] | None:
        """获取测试结果.

        Args:
            task_id: 测试任务ID.
            request_id: 请求追踪ID.

        Returns:
            测试结果字典，任务不存在返回 None.
        """
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        task = self._tasks.get(task_id)
        if not task:
            return None

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "suite": task.suite,
            "total": task.total,
            "passed": task.passed,
            "failed": task.failed,
            "duration_ms": task.duration_ms,
            "failures": task.failures,
            "summary": task.summary,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        }

    # -----------------------------------------------------------------------
    # 同步运行测试（方便单测）
    # -----------------------------------------------------------------------

    async def run_tests_sync(
        self,
        suite: str = "all",
        timeout_sec: int = DEFAULT_TEST_TIMEOUT,
    ) -> TestTask:
        """同步运行测试（等待完成）.

        仅供测试使用，生产环境使用 run_tests + get_result。
        """
        result = await self.run_tests(suite, timeout_sec)
        task_id = result["task_id"]

        # 等待完成
        while True:
            task = self._tasks.get(task_id)
            if not task:
                break
            if task.status in (TestStatus.COMPLETED, TestStatus.FAILED, TestStatus.TIMEOUT):
                return task
            await asyncio.sleep(0.5)

        return TestTask(task_id=task_id, suite=suite, timeout_sec=timeout_sec, status=TestStatus.FAILED)
