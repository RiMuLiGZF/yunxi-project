"""持久化执行引擎测试.

测试内容：
1. PersistentRunRepository - CRUD 操作
2. ExecutionContextRepository - 快照管理
3. WorkflowConcurrencyManager - 并发控制
4. DeadLetterManager - 死信队列
5. CrashRecoveryManager - 崩溃恢复
6. 状态流转正确性
"""

from __future__ import annotations

import os
import sys
import types
import importlib.util
import pytest
import time
from pathlib import Path

# ============================================================
# 处理相对导入：创建 m7_src 包
# ============================================================

_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# 创建 m7_src 包
src_pkg = types.ModuleType("m7_src")
src_pkg.__path__ = [_src_dir]
src_pkg.__package__ = "m7_src"
sys.modules["m7_src"] = src_pkg

# 导入 db 模块
db_spec = importlib.util.spec_from_file_location(
    "m7_src.db", os.path.join(_src_dir, "db.py")
)
db_module = importlib.util.module_from_spec(db_spec)
db_module.__package__ = "m7_src"
sys.modules["m7_src.db"] = db_module
src_pkg.db = db_module
db_spec.loader.exec_module(db_module)

Base = db_module.Base

# 导入 models_db 模块
models_db_spec = importlib.util.spec_from_file_location(
    "m7_src.models_db", os.path.join(_src_dir, "models_db.py")
)
models_db_module = importlib.util.module_from_spec(models_db_spec)
models_db_module.__package__ = "m7_src"
sys.modules["m7_src.models_db"] = models_db_module
src_pkg.models_db = models_db_module
models_db_spec.loader.exec_module(models_db_module)

# 创建 services 子包
services_dir = os.path.join(_src_dir, "services")
services_pkg = types.ModuleType("m7_src.services")
services_pkg.__path__ = [services_dir]
services_pkg.__package__ = "m7_src.services"
sys.modules["m7_src.services"] = services_pkg
src_pkg.services = services_pkg

# 导入 persistence 模块
persistence_spec = importlib.util.spec_from_file_location(
    "m7_src.services.persistence",
    os.path.join(services_dir, "persistence.py"),
)
persistence_module = importlib.util.module_from_spec(persistence_spec)
persistence_module.__package__ = "m7_src.services"
sys.modules["m7_src.services.persistence"] = persistence_module
services_pkg.persistence = persistence_module
persistence_spec.loader.exec_module(persistence_module)

PersistentRunRepository = persistence_module.PersistentRunRepository
ExecutionContextRepository = persistence_module.ExecutionContextRepository
DeadLetterManager = persistence_module.DeadLetterManager
WorkflowConcurrencyManager = persistence_module.WorkflowConcurrencyManager
CrashRecoveryManager = persistence_module.CrashRecoveryManager


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = f"sqlite:///{tmp_path / 'test_m7.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def run_repo(db_session):
    return PersistentRunRepository(session=db_session)


@pytest.fixture
def ctx_repo(db_session):
    return ExecutionContextRepository(session=db_session)


@pytest.fixture
def dlq_manager(run_repo):
    return DeadLetterManager(repo=run_repo)


# ============================================================
# 测试 1: 创建运行记录
# ============================================================

class TestCreateRun:
    def test_create_basic_run(self, run_repo):
        run = run_repo.create_run(
            workflow_id="wf_test_001",
            workflow_name="测试工作流",
            input_data={"key": "value"},
            created_by="test_user",
            priority=5,
        )
        assert run is not None
        assert run["run_id"].startswith("run_")
        assert run["workflow_id"] == "wf_test_001"
        assert run["workflow_name"] == "测试工作流"
        assert run["status"] == "pending"
        assert run["priority"] == 5
        assert run["input_data"] == {"key": "value"}
        assert run["created_by"] == "test_user"
        assert run["version"] == 1

    def test_create_run_with_priority(self, run_repo):
        run_high = run_repo.create_run(workflow_id="wf_1", priority=10)
        run_low = run_repo.create_run(workflow_id="wf_1", priority=1)
        run_default = run_repo.create_run(workflow_id="wf_1")

        assert run_high["priority"] == 10
        assert run_low["priority"] == 1
        assert run_default["priority"] == 5

    def test_create_run_priority_clamped(self, run_repo):
        run_max = run_repo.create_run(workflow_id="wf_1", priority=100)
        run_min = run_repo.create_run(workflow_id="wf_1", priority=-5)

        assert run_max["priority"] == 10
        assert run_min["priority"] == 1

    def test_create_run_with_trigger_info(self, run_repo):
        run = run_repo.create_run(
            workflow_id="wf_1",
            trigger_type="schedule",
            trigger_id="trig_abc123",
        )
        assert run["trigger_type"] == "schedule"
        assert run["trigger_id"] == "trig_abc123"

    def test_create_run_with_retries(self, run_repo):
        run = run_repo.create_run(
            workflow_id="wf_1",
            max_retries=3,
            timeout_seconds=600,
        )
        assert run["max_retries"] == 3
        assert run["retry_count"] == 0
        assert run["timeout_seconds"] == 600


# ============================================================
# 测试 2: 查询运行记录
# ============================================================

class TestGetRun:
    def test_get_existing_run(self, run_repo):
        created = run_repo.create_run(workflow_id="wf_1", workflow_name="Test")
        fetched = run_repo.get_run(created["run_id"])
        assert fetched is not None
        assert fetched["run_id"] == created["run_id"]
        assert fetched["workflow_id"] == "wf_1"

    def test_get_nonexistent_run(self, run_repo):
        result = run_repo.get_run("nonexistent_id")
        assert result is None

    def test_list_runs_pagination(self, run_repo):
        for i in range(15):
            run_repo.create_run(workflow_id=f"wf_{i % 3}")

        result = run_repo.list_runs(page=1, page_size=10)
        assert result["total"] == 15
        assert len(result["items"]) == 10
        assert result["page"] == 1
        assert result["page_size"] == 10

        result2 = run_repo.list_runs(page=2, page_size=10)
        assert len(result2["items"]) == 5

    def test_list_runs_filter_by_workflow(self, run_repo):
        run_repo.create_run(workflow_id="wf_a")
        run_repo.create_run(workflow_id="wf_a")
        run_repo.create_run(workflow_id="wf_b")

        result = run_repo.list_runs(workflow_id="wf_a")
        assert result["total"] == 2

    def test_list_runs_filter_by_status(self, run_repo):
        r1 = run_repo.create_run(workflow_id="wf_1")
        r2 = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(r1["run_id"], "running")
        run_repo.update_run_status(r2["run_id"], "completed")

        result = run_repo.list_runs(status="running")
        assert result["total"] == 1
        assert result["items"][0]["run_id"] == r1["run_id"]

    def test_list_runs_filter_by_trigger_type(self, run_repo):
        run_repo.create_run(workflow_id="wf_1", trigger_type="manual")
        run_repo.create_run(workflow_id="wf_1", trigger_type="schedule")
        run_repo.create_run(workflow_id="wf_1", trigger_type="webhook")

        result = run_repo.list_runs(trigger_type="schedule")
        assert result["total"] == 1


# ============================================================
# 测试 3: 更新运行状态
# ============================================================

class TestUpdateRunStatus:
    def test_update_status_pending_to_running(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        success = run_repo.update_run_status(run["run_id"], "running")
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "running"
        assert updated["start_time"] is not None
        assert updated["version"] == 2

    def test_update_status_running_to_completed(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")
        success = run_repo.update_run_status(
            run["run_id"],
            "completed",
            result_summary={"success_blocks": 5},
        )
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "completed"
        assert updated["end_time"] is not None
        assert updated["result_summary"] == {"success_blocks": 5}

    def test_update_status_to_failed(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")
        success = run_repo.update_run_status(
            run["run_id"],
            "failed",
            error_message="测试错误",
        )
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "failed"
        assert updated["error_message"] == "测试错误"

    def test_update_nonexistent_run(self, run_repo):
        success = run_repo.update_run_status("nonexistent", "running")
        assert success is False

    def test_update_current_node(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running", current_node_id="node_001")
        updated = run_repo.get_run(run["run_id"])
        assert updated["current_node_id"] == "node_001"


# ============================================================
# 测试 4: 取消运行
# ============================================================

class TestCancelRun:
    def test_cancel_pending_run(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        success = run_repo.cancel_run(run["run_id"], "用户取消")
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "cancelled"
        assert updated["error_message"] == "用户取消"
        assert updated["end_time"] is not None

    def test_cancel_running_run(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")
        success = run_repo.cancel_run(run["run_id"])
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "cancelled"

    def test_cancel_completed_run(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "completed")
        success = run_repo.cancel_run(run["run_id"])
        assert success is False

    def test_cancel_nonexistent_run(self, run_repo):
        success = run_repo.cancel_run("nonexistent")
        assert success is False


# ============================================================
# 测试 5: 上下文快照
# ============================================================

class TestContextSnapshots:
    def test_save_snapshot(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        snap_id = ctx_repo.save_snapshot(
            run_id=run["run_id"],
            node_id="node_001",
            context_data={"var1": "value1"},
            step_results={"node_001": {"status": "success"}},
            variables={"x": 10},
            snapshot_type="node_complete",
        )
        assert snap_id > 0

    def test_get_latest_snapshot(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")

        ctx_repo.save_snapshot(run["run_id"], "node_1", {"v": 1}, {}, {}, "node_complete")
        ctx_repo.save_snapshot(run["run_id"], "node_2", {"v": 2}, {}, {}, "node_complete")
        ctx_repo.save_snapshot(run["run_id"], "node_3", {"v": 3}, {}, {}, "node_complete")

        latest = ctx_repo.get_latest_snapshot(run["run_id"])
        assert latest is not None
        assert latest["node_id"] == "node_3"
        assert latest["context_data"] == {"v": 3}

    def test_list_snapshots(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        for i in range(5):
            ctx_repo.save_snapshot(run["run_id"], f"node_{i}", {"i": i}, {}, {}, "node_complete")

        snaps = ctx_repo.list_snapshots(run["run_id"], limit=10)
        assert len(snaps) == 5
        assert snaps[0]["node_id"] == "node_4"

    def test_list_snapshots_by_type(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        ctx_repo.save_snapshot(run["run_id"], "n1", {}, {}, {}, "node_complete")
        ctx_repo.save_snapshot(run["run_id"], "n2", {}, {}, {}, "error")
        ctx_repo.save_snapshot(run["run_id"], "n3", {}, {}, {}, "node_complete")

        snaps = ctx_repo.list_snapshots(run["run_id"], snapshot_type="error")
        assert len(snaps) == 1
        assert snaps[0]["snapshot_type"] == "error"

    def test_cleanup_snapshots(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        for i in range(20):
            ctx_repo.save_snapshot(run["run_id"], f"node_{i}", {"i": i}, {}, {}, "node_complete")

        deleted = ctx_repo.cleanup_snapshots(run["run_id"], keep_latest=5)
        assert deleted == 15

        remaining = ctx_repo.list_snapshots(run["run_id"], limit=100)
        assert len(remaining) == 5

    def test_get_snapshot_by_id(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        snap_id = ctx_repo.save_snapshot(run["run_id"], "n1", {"k": "v"}, {}, {}, "node_complete")

        snap = ctx_repo.get_snapshot(snap_id)
        assert snap is not None
        assert snap["id"] == snap_id
        assert snap["context_data"] == {"k": "v"}


# ============================================================
# 测试 6: 优先级队列
# ============================================================

class TestPriorityQueue:
    def test_pending_runs_ordered_by_priority(self, run_repo):
        run_repo.create_run(workflow_id="wf_1", priority=3)
        run_repo.create_run(workflow_id="wf_1", priority=9)
        run_repo.create_run(workflow_id="wf_1", priority=6)

        pending = run_repo.get_pending_runs(limit=10)
        assert len(pending) == 3
        assert pending[0]["priority"] == 9
        assert pending[1]["priority"] == 6
        assert pending[2]["priority"] == 3

    def test_pending_runs_fifo_same_priority(self, run_repo):
        r1 = run_repo.create_run(workflow_id="wf_1", priority=5)
        time.sleep(0.01)
        r2 = run_repo.create_run(workflow_id="wf_1", priority=5)
        time.sleep(0.01)
        r3 = run_repo.create_run(workflow_id="wf_1", priority=5)

        pending = run_repo.get_pending_runs(limit=10)
        assert pending[0]["run_id"] == r1["run_id"]
        assert pending[1]["run_id"] == r2["run_id"]
        assert pending[2]["run_id"] == r3["run_id"]


# ============================================================
# 测试 7: 心跳检测
# ============================================================

class TestHeartbeat:
    def test_update_heartbeat(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")

        success = run_repo.update_heartbeat(run["run_id"])
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["last_heartbeat"] is not None

    def test_get_stuck_runs(self, run_repo):
        r1 = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(r1["run_id"], "running")

        stuck = run_repo.get_stuck_runs(timeout_seconds=60)
        assert len(stuck) >= 1


# ============================================================
# 测试 8: 死信队列
# ============================================================

class TestDeadLetter:
    def test_move_to_dead_letter(self, run_repo, dlq_manager):
        run = run_repo.create_run(workflow_id="wf_1", max_retries=2)
        run_repo.update_run_status(run["run_id"], "failed")

        run_repo.move_to_dead_letter(run["run_id"], reason="超过最大重试次数")
        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "dead_letter"
        assert "超过最大重试次数" in updated["error_message"]

    def test_list_dead_letters(self, run_repo, dlq_manager):
        for i in range(3):
            r = run_repo.create_run(workflow_id="wf_1")
            run_repo.move_to_dead_letter(r["run_id"], reason=f"reason_{i}")

        result = dlq_manager.list_dead_letters(page=1, page_size=10)
        assert result["total"] == 3

    def test_requeue_dead_letter(self, run_repo, dlq_manager):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.move_to_dead_letter(run["run_id"], reason="测试")

        success = dlq_manager.requeue(run["run_id"])
        assert success is True

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "pending"
        assert updated["retry_count"] == 0

    def test_remove_dead_letter(self, run_repo, dlq_manager):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.move_to_dead_letter(run["run_id"], reason="测试")

        success = dlq_manager.remove(run["run_id"])
        assert success is True
        assert run_repo.get_run(run["run_id"]) is None

    def test_dead_letter_count(self, run_repo, dlq_manager):
        for i in range(5):
            r = run_repo.create_run(workflow_id="wf_1")
            run_repo.move_to_dead_letter(r["run_id"])

        assert dlq_manager.get_count() == 5


# ============================================================
# 测试 9: 重试计数
# ============================================================

class TestRetryCount:
    def test_increment_retry(self, run_repo):
        run = run_repo.create_run(workflow_id="wf_1", max_retries=3)
        assert run["retry_count"] == 0

        count = run_repo.increment_retry(run["run_id"])
        assert count == 1

        count = run_repo.increment_retry(run["run_id"])
        assert count == 2

    def test_increment_retry_nonexistent(self, run_repo):
        result = run_repo.increment_retry("nonexistent")
        assert result == -1


# ============================================================
# 测试 10: 运行统计
# ============================================================

class TestRunStats:
    def test_get_stats(self, run_repo):
        for i in range(5):
            r = run_repo.create_run(workflow_id="wf_1")
            if i < 2:
                run_repo.update_run_status(r["run_id"], "completed")
            elif i < 4:
                run_repo.update_run_status(r["run_id"], "failed")

        stats = run_repo.get_stats()
        assert stats["total"] == 5
        assert stats["completed"] == 2
        assert stats["failed"] == 2
        assert stats["pending"] == 1

    def test_get_stats_by_workflow(self, run_repo):
        run_repo.create_run(workflow_id="wf_a")
        run_repo.create_run(workflow_id="wf_a")
        run_repo.create_run(workflow_id="wf_b")

        stats_a = run_repo.get_stats(workflow_id="wf_a")
        assert stats_a["total"] == 2

        stats_b = run_repo.get_stats(workflow_id="wf_b")
        assert stats_b["total"] == 1


# ============================================================
# 测试 11: 清理过期记录
# ============================================================

class TestCleanup:
    def test_cleanup_expired_zero(self, run_repo):
        for i in range(3):
            r = run_repo.create_run(workflow_id="wf_1")
            run_repo.update_run_status(r["run_id"], "completed")

        deleted = run_repo.cleanup_expired(days=30)
        assert deleted == 0


# ============================================================
# 测试 12: 并发控制
# ============================================================

class TestConcurrencyManager:
    @pytest.mark.asyncio
    async def test_acquire_release_slot(self):
        mgr = WorkflowConcurrencyManager()
        mgr._global_limit = 5
        mgr._default_wf_limit = 2

        assert await mgr.acquire_slot("wf_1") is True
        assert await mgr.acquire_slot("wf_1") is True
        assert await mgr.acquire_slot("wf_1") is False

        assert mgr.get_running_count("wf_1") == 2

        await mgr.release_slot("wf_1")
        assert mgr.get_running_count("wf_1") == 1

    @pytest.mark.asyncio
    async def test_global_concurrency_limit(self):
        mgr = WorkflowConcurrencyManager()
        mgr._global_limit = 3
        mgr._default_wf_limit = 10

        assert await mgr.acquire_slot("wf_a") is True
        assert await mgr.acquire_slot("wf_b") is True
        assert await mgr.acquire_slot("wf_c") is True
        assert await mgr.acquire_slot("wf_d") is False

        assert mgr.get_running_count() == 3

    @pytest.mark.asyncio
    async def test_set_workflow_limit(self):
        mgr = WorkflowConcurrencyManager()
        mgr._global_limit = 10

        mgr.set_workflow_limit("wf_special", 5)
        assert mgr.get_workflow_limit("wf_special") == 5
        assert mgr.get_workflow_limit("wf_normal") == mgr._default_wf_limit

    @pytest.mark.asyncio
    async def test_get_stats(self):
        mgr = WorkflowConcurrencyManager()
        mgr._global_limit = 10

        await mgr.acquire_slot("wf_1")
        stats = mgr.get_stats()
        assert stats["global_running"] == 1
        assert stats["global_limit"] == 10
        assert "wf_1" in stats["workflow_running"]


# ============================================================
# 测试 13: 崩溃恢复
# ============================================================

class TestCrashRecovery:
    def test_recover_no_stuck_runs(self, run_repo, ctx_repo):
        recovery = CrashRecoveryManager(run_repo=run_repo, ctx_repo=ctx_repo)

        result = recovery.recover_on_startup()
        assert result["total"] == 0
        assert result["recovered"] == 0
        assert result["failed"] == 0

    def test_recover_stuck_run_with_snapshot(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")

        ctx_repo.save_snapshot(
            run_id=run["run_id"],
            node_id="node_1",
            context_data={"v": 1},
            step_results={"node_1": {"status": "success"}},
            variables={},
            snapshot_type="node_complete",
        )

        recovery = CrashRecoveryManager(run_repo=run_repo, ctx_repo=ctx_repo)
        result = recovery.recover_on_startup()

        assert result["total"] == 1
        assert result["recovered"] == 1
        assert result["failed"] == 0

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "pending"

    def test_recover_stuck_run_without_snapshot(self, run_repo, ctx_repo):
        run = run_repo.create_run(workflow_id="wf_1")
        run_repo.update_run_status(run["run_id"], "running")

        recovery = CrashRecoveryManager(run_repo=run_repo, ctx_repo=ctx_repo)
        result = recovery.recover_on_startup()

        assert result["total"] == 1
        assert result["recovered"] == 0
        assert result["failed"] == 1

        updated = run_repo.get_run(run["run_id"])
        assert updated["status"] == "failed"
