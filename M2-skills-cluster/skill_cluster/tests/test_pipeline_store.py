from __future__ import annotations

"""Pipeline State Store 单元测试."""

import time

import pytest

from skill_cluster.pipeline_store import PipelineStateStore
from skill_cluster.skill_pipeline import PipelineContext


def test_save_and_get(tmp_path) -> None:
    store = PipelineStateStore(db_path=str(tmp_path / "runs.db"))
    ctx = PipelineContext(
        pipeline_id="pipe.test",
        run_id="run_001",
        trace_id="t1",
        agent_id="agent1",
        status="success",
    )
    ctx.started_at = time.time()
    ctx.finished_at = ctx.started_at + 1.0

    store.save(ctx)
    record = store.get("run_001")

    assert record is not None
    assert record.pipeline_id == "pipe.test"
    assert record.status == "success"
    assert record.duration_ms > 0


def test_list_runs(tmp_path) -> None:
    store = PipelineStateStore(db_path=str(tmp_path / "runs.db"))

    for i in range(3):
        ctx = PipelineContext(
            pipeline_id="pipe.a",
            run_id=f"run_{i}",
            trace_id="t1",
            agent_id="agent1",
            status="success" if i < 2 else "failure",
        )
        ctx.started_at = time.time() - i
        ctx.finished_at = ctx.started_at + 0.5
        store.save(ctx)

    runs = store.list_runs(pipeline_id="pipe.a")
    assert len(runs) == 3

    success_runs = store.list_runs(status="success")
    assert len(success_runs) == 2


def test_get_stats(tmp_path) -> None:
    store = PipelineStateStore(db_path=str(tmp_path / "runs.db"))

    for i, status in enumerate(["success", "success", "failure"]):
        ctx = PipelineContext(
            pipeline_id="pipe.stats",
            run_id=f"run_{status}_{i}",
            trace_id="t1",
            agent_id="agent1",
            status=status,
        )
        ctx.started_at = time.time()
        ctx.finished_at = ctx.started_at + 0.1
        store.save(ctx)

    stats = store.get_stats("pipe.stats")
    assert stats["total"] == 3
    assert stats["success"] == 2
    assert stats["failure"] == 1
    assert stats["success_rate"] == 2 / 3
    assert stats["avg_duration_ms"] > 0


def test_delete_old_runs(tmp_path) -> None:
    store = PipelineStateStore(db_path=str(tmp_path / "runs.db"))

    ctx = PipelineContext(
        pipeline_id="pipe.old",
        run_id="run_old",
        trace_id="t1",
        agent_id="agent1",
        status="success",
    )
    ctx.started_at = time.time() - 86400  # 1天前
    ctx.finished_at = ctx.started_at + 0.5
    store.save(ctx)

    count = store.delete_old_runs(time.time() - 3600)
    assert count == 1

    assert store.get("run_old") is None
