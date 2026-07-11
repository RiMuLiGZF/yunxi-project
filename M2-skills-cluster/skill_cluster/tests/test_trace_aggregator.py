"""Tests for Trace Aggregator."""

import time

from skill_cluster.trace_aggregator import (
    TraceAggregator,
    TraceChain,
    TraceSpan,
)


def test_start_span_basic():
    agg = TraceAggregator()
    sid = agg.start_span(
        trace_id="trace_001",
        skill_id="skill.a",
        action="run",
        agent_id="agent_1",
    )
    assert sid.startswith("span_")
    chain = agg.get_chain("trace_001")
    assert chain is not None
    assert chain.root_span_id == sid
    assert len(chain.spans) == 1


def test_parent_child_span():
    agg = TraceAggregator()
    parent_id = agg.start_span("t1", "skill.a", "run", "agent_1")
    child_id = agg.start_span("t1", "skill.b", "sub", "agent_1", parent_span_id=parent_id)
    chain = agg.get_chain("t1")
    assert len(chain.spans) == 2
    assert parent_id in chain.spans[child_id].parent_span_id or chain.spans[parent_id].children == [child_id]


def test_finish_span():
    agg = TraceAggregator()
    sid = agg.start_span("t2", "skill.a", "run", "agent_1")
    time.sleep(0.001)  # 确保有可测量的延迟
    agg.finish_span("t2", sid, status="success")
    span = agg.get_chain("t2").spans[sid]
    assert span.status == "success"
    assert span.end_time > 0
    assert span.duration_ms > 0


def test_finish_span_error():
    agg = TraceAggregator()
    sid = agg.start_span("t3", "skill.a", "run", "agent_1")
    time.sleep(0.001)
    agg.finish_span("t3", sid, status="failure", error="boom")
    chain = agg.get_chain("t3")
    assert chain.status == "failure"
    assert chain.error_summary == "boom"


def test_chain_summary():
    agg = TraceAggregator()
    sid = agg.start_span("t4", "skill.a", "run", "agent_1")
    time.sleep(0.001)
    agg.finish_span("t4", sid, status="success")
    summary = agg.get_chain("t4").to_summary()
    assert summary["trace_id"] == "t4"
    assert summary["span_count"] == 1
    assert summary["status"] == "success"
    assert summary["total_latency_ms"] > 0
    assert len(summary["topology"]) == 1


def test_topology_depth():
    agg = TraceAggregator()
    p1 = agg.start_span("t5", "skill.a", "run", "a1")
    c1 = agg.start_span("t5", "skill.b", "sub1", "a1", parent_span_id=p1)
    c2 = agg.start_span("t5", "skill.c", "sub2", "a1", parent_span_id=c1)
    agg.finish_span("t5", c2, "success")
    agg.finish_span("t5", c1, "success")
    agg.finish_span("t5", p1, "success")
    topo = agg.get_chain("t5").to_summary()["topology"]
    assert topo[0]["depth"] == 0
    assert topo[1]["depth"] == 1
    assert topo[2]["depth"] == 2


def test_max_chains_eviction():
    agg = TraceAggregator(max_chains=2)
    agg.start_span("t1", "s1", "a", "a1")
    agg.start_span("t2", "s2", "a", "a1")
    agg.start_span("t3", "s3", "a", "a1")  # should evict t1
    assert agg.get_chain("t1") is None
    assert agg.get_chain("t2") is not None
    assert agg.get_chain("t3") is not None


def test_cleanup_expired():
    agg = TraceAggregator()
    sid = agg.start_span("t_old", "s1", "a", "a1")
    agg.finish_span("t_old", sid, "success")
    # Manually set end_time to past
    chain = agg.get_chain("t_old")
    chain.spans[sid].end_time = time.time() - 4000  # expired
    removed = agg.cleanup_expired(max_age_seconds=3600)
    assert removed == 1
    assert agg.get_chain("t_old") is None


def test_get_stats():
    agg = TraceAggregator(max_chains=100)
    sid = agg.start_span("t6", "s1", "a", "a1")
    agg.finish_span("t6", sid, "success")
    stats = agg.get_stats()
    assert stats["total_traces"] == 1
    assert stats["running_traces"] == 0
    assert stats["failed_traces"] == 0


def test_get_active_traces():
    agg = TraceAggregator()
    sid = agg.start_span("t7", "s1", "a", "a1")
    # span is running (not finished)
    active = agg.get_active_traces()
    assert len(active) == 1
    assert active[0]["trace_id"] == "t7"
    # finish it
    agg.finish_span("t7", sid, "success")
    active2 = agg.get_active_traces()
    assert len(active2) == 0


def test_span_duration_property():
    span = TraceSpan(
        trace_id="t", span_id="s", skill_id="s1",
        action="a", agent_id="a1",
        start_time=100.0, end_time=100.5,
    )
    assert span.duration_ms == 500.0


def test_span_duration_before_finish():
    span = TraceSpan(
        trace_id="t", span_id="s", skill_id="s1",
        action="a", agent_id="a1",
        start_time=100.0,
    )
    assert span.duration_ms == 0.0


def test_finish_nonexistent():
    agg = TraceAggregator()
    # Should not raise
    agg.finish_span("nonexistent", "nonexistent", "success")


def test_chain_status_worst():
    agg = TraceAggregator()
    p = agg.start_span("t8", "s1", "a", "a1")
    c = agg.start_span("t8", "s2", "a", "a1", parent_span_id=p)
    agg.finish_span("t8", c, "success")
    agg.finish_span("t8", p, "timeout", error="timeout")
    chain = agg.get_chain("t8")
    assert chain.status == "timeout"
