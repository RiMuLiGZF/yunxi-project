"""
测试：EventStore 事件溯源存储
"""

import pytest
import sys
import asyncio

sys.path.insert(0, "/workspace/agent_cluster")

from event_store import EventStore, DomainEvent, EventType


@pytest.fixture
def store():
    return EventStore()


@pytest.mark.asyncio
async def test_append_event(store):
    event = DomainEvent(
        event_type=EventType.USER_INPUT_RECEIVED,
        trace_id="trace_1",
        payload={"user_input": "hello"},
    )
    result = await store.append(event)
    assert result.event_id == event.event_id
    assert store.get_all()[0].event_type == EventType.USER_INPUT_RECEIVED


@pytest.mark.asyncio
async def test_get_by_trace(store):
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t1"))
    await store.append(DomainEvent(event_type=EventType.AGENT_TASK_COMPLETED, trace_id="t1"))
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t2"))

    events = store.get_by_trace("t1")
    assert len(events) == 2
    assert all(e.trace_id == "t1" for e in events)


@pytest.mark.asyncio
async def test_get_by_type(store):
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t1"))
    await store.append(DomainEvent(event_type=EventType.AGENT_TASK_COMPLETED, trace_id="t1"))
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t2"))

    events = store.get_by_type(EventType.USER_INPUT_RECEIVED)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_replay(store):
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t1"))
    await store.append(DomainEvent(event_type=EventType.AGENT_TASK_COMPLETED, trace_id="t1"))

    replayed = []
    async def handler(event):
        replayed.append(event)

    result = await store.replay(trace_id="t1", handler=handler)
    assert len(result) == 2
    assert len(replayed) == 2


@pytest.mark.asyncio
async def test_subscribe(store):
    received = []
    async def handler(event):
        received.append(event)

    store.subscribe(EventType.USER_INPUT_RECEIVED, handler)
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t1"))
    assert len(received) == 1

    store.unsubscribe(EventType.USER_INPUT_RECEIVED, handler)
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t2"))
    assert len(received) == 1  # 不再接收


@pytest.mark.asyncio
async def test_eviction(store):
    store.MAX_EVENTS = 5
    for i in range(7):
        await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id=f"t{i}"))

    assert len(store.get_all()) <= 5


@pytest.mark.asyncio
async def test_stats(store):
    await store.append(DomainEvent(event_type=EventType.USER_INPUT_RECEIVED, trace_id="t1"))
    stats = store.stats()
    assert stats["total_events"] == 1
    assert stats["trace_count"] == 1
