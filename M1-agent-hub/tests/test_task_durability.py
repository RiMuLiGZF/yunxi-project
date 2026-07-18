"""
测试：TaskDurabilityManager / DurableTask 任务耐久性执行引擎
"""

import pytest
import sys
import os
from task_durability import (
    TaskDurabilityManager,
    DurableTask,
    TaskStatus,
    Checkpoint,
)
from persistence import SQLitePersistence


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "durability_test.db"
    persist = SQLitePersistence(str(db_path))
    yield persist
    persist.close()


# ── DurableTask 基本执行 ────────────────────────────


@pytest.mark.asyncio
async def test_durable_task_execute():
    async def step1(state):
        return {"step1_done": True, "value": 10}

    async def step2(state):
        return {"step2_done": True, "value": state.get("value", 0) + 5}

    task = DurableTask("task_1", [("step1", step1), ("step2", step2)])
    result = await task.execute({"initial": True})

    assert result["initial"] is True
    assert result["step1_done"] is True
    assert result["step2_done"] is True
    assert result["value"] == 15
    assert task.get_status() == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_durable_task_single_step():
    async def only_step(state):
        return {"result": "done"}

    task = DurableTask("task_single", [("only", only_step)])
    result = await task.execute({})
    assert result["result"] == "done"


@pytest.mark.asyncio
async def test_durable_task_failure():
    async def bad_step(state):
        raise ValueError("intentional failure")

    task = DurableTask("task_fail", [("bad", bad_step)])
    with pytest.raises(ValueError, match="intentional failure"):
        await task.execute({})

    assert task.get_status() == TaskStatus.FAILED


# ── 检查点 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkpoint_serialization():
    cp = Checkpoint(
        checkpoint_id="cp_123",
        task_id="task_1",
        step_index=1,
        step_name="step2",
        state={"key": "value"},
        timestamp=1234567890.0,
    )
    json_str = cp.to_json()
    assert "cp_123" in json_str
    assert "task_1" in json_str


@pytest.mark.asyncio
async def test_checkpoint_from_dict():
    data = {
        "checkpoint_id": "cp_456",
        "task_id": "task_2",
        "step_index": 2,
        "step_name": "step3",
        "state": {"a": 1},
        "timestamp": 123.0,
    }
    cp = Checkpoint.from_dict(data)
    assert cp.checkpoint_id == "cp_456"
    assert cp.step_index == 2
    assert cp.state == {"a": 1}


# ── 带持久化的执行与恢复 ──────────────────────────────


@pytest.mark.asyncio
async def test_durable_task_with_persistence(temp_db):
    async def step1(state):
        return {"s1": True}

    async def step2(state):
        return {"s2": True}

    task = DurableTask("persist_task", [("step1", step1), ("step2", step2)], temp_db)
    result = await task.execute({"start": True})

    assert result["s1"] is True
    assert result["s2"] is True
    assert task.get_status() == TaskStatus.COMPLETED
    assert len(task._checkpoints) == 2


@pytest.mark.asyncio
async def test_durable_task_recovery(temp_db):
    call_count = 0

    async def step1(state):
        nonlocal call_count
        call_count += 1
        return {"s1": True}

    async def step2(state):
        return {"s2": True}

    # 第一次执行
    task1 = DurableTask("recover_task", [("step1", step1), ("step2", step2)], temp_db)
    result1 = await task1.execute({"start": True})
    assert result1["s1"] is True
    assert call_count == 1

    # 第二次执行同名任务，应该从检查点恢复，跳过 step1
    task2 = DurableTask("recover_task", [("step1", step1), ("step2", step2)], temp_db)
    result2 = await task2.execute({"start": True})
    # step1 不应再被调用（因为检查点已保存到 step1 完成）
    # 注意：由于 task2 是新实例，_recover 会将 _current_step 设为 1
    # 所以 step1 不会执行，call_count 保持 1
    assert task2.get_status() == TaskStatus.COMPLETED
    assert call_count == 1  # step1 只执行了一次


# ── 进度查询 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_progress():
    async def step1(state):
        return {"s1": True}

    task = DurableTask("progress_task", [("step1", step1)])
    progress_before = task.get_progress()
    assert progress_before["status"] == "pending"
    assert progress_before["progress_ratio"] == 0

    await task.execute({})
    progress_after = task.get_progress()
    assert progress_after["status"] == "completed"
    assert progress_after["progress_ratio"] == 1.0
    assert progress_after["checkpoints"] == 1


# ── TaskDurabilityManager ───────────────────────────


def test_manager_create_and_get():
    manager = TaskDurabilityManager()
    async def dummy(state):
        return {}

    task = manager.create_task("t1", [("s1", dummy)])
    assert task.task_id == "t1"
    assert manager.get_task("t1") is task
    assert manager.get_task("nonexistent") is None


def test_manager_list_tasks():
    manager = TaskDurabilityManager()
    async def dummy(state):
        return {}

    manager.create_task("t1", [("s1", dummy)])
    manager.create_task("t2", [("s2", dummy)])
    assert sorted(manager.list_tasks()) == ["t1", "t2"]


def test_manager_stats():
    manager = TaskDurabilityManager()
    async def dummy(state):
        return {}

    manager.create_task("t1", [("s1", dummy)])
    stats = manager.stats()
    assert stats["total_tasks"] == 1
    assert "pending" in stats["status_distribution"]


# ── 空活动列表 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_activities():
    task = DurableTask("empty", [])
    result = await task.execute({"x": 1})
    assert result == {"x": 1}
    assert task.get_status() == TaskStatus.COMPLETED
