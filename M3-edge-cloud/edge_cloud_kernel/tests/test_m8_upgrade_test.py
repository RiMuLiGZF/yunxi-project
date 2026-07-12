"""M8 管理接口测试 — 升级管理 + 测试管理.

测试类别：升级管理接口(8) + 测试管理接口(4) = 12个
"""

from __future__ import annotations

import asyncio

import pytest

from edge_cloud_kernel.m8_api.upgrade_endpoints import UpgradeManager, UpgradeStatus
from edge_cloud_kernel.m8_api.test_endpoints import TestManager, TestStatus


# ---------------------------------------------------------------------------
# 升级管理接口测试（8个）
# ---------------------------------------------------------------------------

class TestUpgradeManager:
    """升级管理器测试."""

    def test_code_snapshot(self):
        """测试代码快照."""
        mgr = UpgradeManager()
        snap = mgr.get_code_snapshot()
        assert "version" in snap
        assert "commit_hash" in snap
        assert "build_time" in snap
        assert "branch" in snap
        assert snap["module"] == "m3"
        assert len(snap["commit_hash"]) == 40

    def test_preview_upgrade_compatible(self):
        """测试兼容版本升级预览."""
        mgr = UpgradeManager()
        result = mgr.preview_upgrade(target_version="2.2.0")
        assert result["compatible"] is True
        assert result["current_version"] == "2.1.2"
        assert result["target_version"] == "2.2.0"
        assert "impact_level" in result
        assert "estimated_duration_seconds" in result
        assert isinstance(result["changes"], list)
        assert isinstance(result["risks"], list)

    def test_preview_upgrade_incompatible(self):
        """测试不兼容版本升级预览."""
        mgr = UpgradeManager()
        result = mgr.preview_upgrade(target_version="3.0.0")
        assert result["compatible"] is False
        assert result["impact_level"] == "critical"

    def test_preview_upgrade_invalid(self):
        """测试无效版本预览."""
        mgr = UpgradeManager()
        result = mgr.preview_upgrade(target_version="")
        assert result["compatible"] is False

    @pytest.mark.asyncio
    async def test_apply_upgrade(self):
        """测试应用升级."""
        mgr = UpgradeManager()
        result = await mgr.apply_upgrade(target_version="2.2.0")
        assert "task_id" in result
        assert result["status"] in ("pending", "running")
        assert result["target_version"] == "2.2.0"

    @pytest.mark.asyncio
    async def test_apply_upgrade_progress(self):
        """测试升级进度更新."""
        mgr = UpgradeManager()
        result = await mgr.apply_upgrade(target_version="2.2.0")
        task_id = result["task_id"]
        # 等待升级完成
        await asyncio.sleep(2.5)
        status = mgr.get_task_status(task_id)
        assert status is not None
        assert status["status"] == "completed"
        assert status["progress"] == 100

    @pytest.mark.asyncio
    async def test_rollback(self):
        """测试回滚."""
        mgr = UpgradeManager()
        # 先应用一次升级
        await mgr.apply_upgrade(target_version="2.2.0")
        await asyncio.sleep(2.5)
        # 回滚
        result = await mgr.rollback()
        assert "task_id" in result
        assert result["rollback_to_version"] == "2.1.2"
        # 等待回滚完成
        await asyncio.sleep(1.5)
        assert mgr.current_version == "2.1.2"

    @pytest.mark.asyncio
    async def test_rollback_no_previous(self):
        """测试无历史版本时回滚失败."""
        mgr = UpgradeManager()
        result = await mgr.rollback()
        assert result["status"] == "failed"
        assert result["rollback_to_version"] is None


# ---------------------------------------------------------------------------
# 测试管理接口测试（4个）
# ---------------------------------------------------------------------------

class TestTestManager:
    """测试管理器测试."""

    @pytest.mark.asyncio
    async def test_run_tests(self):
        """测试运行测试."""
        mgr = TestManager()
        result = await mgr.run_tests(suite="test_m8_config.py", timeout_sec=60)
        assert "task_id" in result
        assert result["status"] in ("pending", "running")
        assert result["suite"] == "test_m8_config.py"

    @pytest.mark.asyncio
    async def test_get_result_pending(self):
        """测试获取测试结果（进行中）."""
        mgr = TestManager()
        result = await mgr.run_tests(suite="test_m8_config.py", timeout_sec=60)
        task_id = result["task_id"]
        # 立即查询，应该是 running 状态
        status = mgr.get_result(task_id)
        assert status is not None
        assert "task_id" in status
        assert "status" in status

    @pytest.mark.asyncio
    async def test_get_result_not_found(self):
        """测试查询不存在的任务."""
        mgr = TestManager()
        result = mgr.get_result("nonexistent_task")
        assert result is None

    @pytest.mark.asyncio
    async def test_run_tests_invalid_suite(self):
        """测试无效测试套件仍返回任务."""
        mgr = TestManager()
        result = await mgr.run_tests(suite="nonexistent_test_file.py", timeout_sec=10)
        assert "task_id" in result
        # 即使套件不存在，也会创建任务（pytest 自己会处理失败）
