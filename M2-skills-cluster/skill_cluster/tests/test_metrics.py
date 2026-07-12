from __future__ import annotations

"""Metrics 单元测试."""

from skill_cluster.metrics import Counter, Histogram, MetricsCollector


def test_counter_basic() -> None:
    c = Counter("test_counter")
    c.inc({"label1": "a"})
    c.inc({"label1": "a"}, amount=2)
    assert c.get({"label1": "a"}) == 3


def test_counter_no_labels() -> None:
    c = Counter("test_counter")
    c.inc()
    assert c.get() == 1


def test_histogram_basic() -> None:
    h = Histogram("test_hist", buckets=[10, 50, 100])
    h.observe(5)
    h.observe(25)
    h.observe(75)

    stats = h.get()
    assert stats["count"] == 3
    assert stats["sum"] == 105
    assert stats["avg"] == 35.0
    assert stats["buckets"]["le_10"] == 1
    assert stats["buckets"]["le_50"] == 2
    assert stats["buckets"]["le_100"] == 3


def test_metrics_collector_record() -> None:
    collector = MetricsCollector()
    collector.record(
        skill_id="skill.test",
        action="action1",
        agent_id="agent1",
        status="success",
        latency_ms=50.0,
    )
    collector.record(
        skill_id="skill.test",
        action="action1",
        agent_id="agent1",
        status="failure",
        latency_ms=100.0,
    )

    total = collector.counter("skill_invocations_total")
    assert total.get({"skill_id": "skill.test", "action": "action1", "agent_id": "agent1", "status": "success"}) == 1
    assert total.get({"skill_id": "skill.test", "action": "action1", "agent_id": "agent1", "status": "failure"}) == 1

    latency = collector.histogram("skill_invocation_latency_ms")
    stats = latency.get({"skill_id": "skill.test", "action": "action1"})
    assert stats["count"] == 2
    assert stats["sum"] == 150.0


def test_metrics_collector_get_all() -> None:
    collector = MetricsCollector()
    collector.record(
        skill_id="skill.test",
        action="action1",
        agent_id="agent1",
        status="success",
        latency_ms=50.0,
    )
    all_metrics = collector.get_all_metrics()
    assert "counters" in all_metrics
    assert "histograms" in all_metrics
    assert "skill_invocations_total" in all_metrics["counters"]


def test_histogram_with_labels() -> None:
    h = Histogram("latency")
    h.observe(10, {"endpoint": "/api/a"})
    h.observe(20, {"endpoint": "/api/a"})
    h.observe(100, {"endpoint": "/api/b"})

    stats_a = h.get({"endpoint": "/api/a"})
    assert stats_a["count"] == 2

    stats_b = h.get({"endpoint": "/api/b"})
    assert stats_b["count"] == 1


def test_prometheus_export() -> None:
    collector = MetricsCollector()
    collector.record(
        skill_id="skill.test",
        action="action1",
        agent_id="agent1",
        status="success",
        latency_ms=50.0,
    )
    output = collector.export_prometheus_format()
    assert "skill_invocations_total" in output
    assert "skill_invocation_latency_ms" in output
