"""
测试：SQLitePersistence 持久化层
"""

import pytest
import sys

sys.path.insert(0, "/workspace/agent_cluster")

from persistence import SQLitePersistence


@pytest.fixture
def db():
    persistence = SQLitePersistence(":memory:")
    yield persistence
    persistence.close()


def test_save_and_load_ltm(db):
    entry = {
        "entry_id": "ltm_1",
        "content": "用户喜欢咖啡",
        "memory_type": "preference",
        "source": "agent.emotion",
        "importance": 0.9,
        "created_at": 1234567890,
        "last_accessed": 1234567890,
        "access_count": 3,
        "tags": ["preference", "food"],
        "metadata": {"confirmed": True},
    }
    db.save_ltm_entry(entry)

    loaded = db.load_ltm_entries()
    assert len(loaded) == 1
    assert loaded[0]["content"] == "用户喜欢咖啡"
    assert loaded[0]["tags"] == ["preference", "food"]


def test_search_ltm(db):
    db.save_ltm_entry({
        "entry_id": "ltm_1", "content": "用户喜欢咖啡", "importance": 0.9,
        "tags": [], "metadata": {},
    })
    db.save_ltm_entry({
        "entry_id": "ltm_2", "content": "用户喜欢茶", "importance": 0.8,
        "tags": [], "metadata": {},
    })

    results = db.search_ltm_by_content("咖啡")
    assert len(results) == 1
    assert results[0]["entry_id"] == "ltm_1"


def test_save_and_load_trace(db):
    trace = {
        "trace_id": "trace_1",
        "start_time": 1000,
        "end_time": 1500,
        "duration_ms": 500,
        "span_count": 3,
        "is_success": True,
        "metadata": {"user": "test"},
        "spans": [{"name": "span1"}],
    }
    db.save_trace(trace)

    loaded = db.load_traces()
    assert len(loaded) == 1
    assert loaded[0]["trace_id"] == "trace_1"
    assert loaded[0]["is_success"] is True


def test_save_and_load_feedback(db):
    fb = {
        "feedback_id": "fb_1",
        "trace_id": "trace_1",
        "agent_id": "agent.note",
        "intent": "note.create",
        "feedback_type": "explicit",
        "rating": 5,
        "comment": "很好",
        "metadata": {},
        "created_at": 1234567890,
    }
    db.save_feedback(fb)

    loaded = db.load_feedbacks(agent_id="agent.note")
    assert len(loaded) == 1
    assert loaded[0]["rating"] == 5


def test_save_and_load_event(db):
    event = {
        "event_id": "evt_1",
        "event_type": "user.input_received",
        "trace_id": "trace_1",
        "timestamp": 1234567890,
        "version": 1,
        "payload": {"input": "hello"},
        "metadata": {},
    }
    db.save_event(event)

    loaded = db.load_events(trace_id="trace_1")
    assert len(loaded) == 1
    assert loaded[0]["event_type"] == "user.input_received"


def test_save_and_load_route_record(db):
    record = {
        "route_id": "intent -> agent",
        "intent": "intent",
        "target_agent": "agent",
        "execution_count": 10,
        "success_count": 8,
        "total_latency_ms": 5000,
        "avg_score": 0.8,
        "last_used": 1234567890,
        "active": True,
    }
    db.save_route_record(record)

    loaded = db.load_route_records()
    assert len(loaded) == 1
    assert loaded[0]["success_count"] == 8


def test_stats(db):
    db.save_ltm_entry({
        "entry_id": "e1", "content": "c1", "tags": [], "metadata": {},
    })
    db.save_trace({
        "trace_id": "t1", "is_success": True, "metadata": {}, "spans": [],
    })

    stats = db.get_stats()
    assert stats["ltm_entries"] == 1
    assert stats["traces"] == 1


def test_clear_all(db):
    db.save_ltm_entry({
        "entry_id": "e1", "content": "c1", "tags": [], "metadata": {},
    })
    db.clear_all()
    assert len(db.load_ltm_entries()) == 0
