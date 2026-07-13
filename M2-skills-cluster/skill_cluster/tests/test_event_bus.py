from __future__ import annotations

"""Event Bus 单元测试."""

import asyncio

import pytest

from skill_cluster.infrastructure.event_bus import EventBus, SkillEvent


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_publish_subscribe(bus: EventBus) -> None:
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    await bus.subscribe("skill.test.completed", handler)
    event = SkillEvent(
        event_type="skill.test.completed",
        payload={"result": "ok"},
        source_skill_id="skill.test",
    )
    await bus.publish(event)

    assert len(received) == 1
    assert received[0]["payload"]["result"] == "ok"


@pytest.mark.asyncio
async def test_wildcard_subscribe(bus: EventBus) -> None:
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    await bus.subscribe("skill.*.completed", handler)
    await bus.publish(SkillEvent("skill.a.completed", {"r": 1}))
    await bus.publish(SkillEvent("skill.b.completed", {"r": 2}))
    await bus.publish(SkillEvent("skill.c.failed", {"r": 3}))

    assert len(received) == 2


@pytest.mark.asyncio
async def test_multiple_handlers(bus: EventBus) -> None:
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def handler_a(event: dict) -> None:
        received_a.append(event)

    async def handler_b(event: dict) -> None:
        received_b.append(event)

    await bus.subscribe("skill.test.completed", handler_a)
    await bus.subscribe("skill.test.completed", handler_b)
    await bus.publish(SkillEvent("skill.test.completed", {}))

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_handler_error_does_not_break(bus: EventBus) -> None:
    received: list[dict] = []

    async def bad_handler(event: dict) -> None:
        raise RuntimeError("intentional error")

    async def good_handler(event: dict) -> None:
        received.append(event)

    await bus.subscribe("skill.test.completed", bad_handler)
    await bus.subscribe("skill.test.completed", good_handler)
    await bus.publish(SkillEvent("skill.test.completed", {}))

    assert len(received) == 1


def test_event_history(bus: EventBus) -> None:
    import asyncio

    asyncio.run(bus.publish(SkillEvent("skill.a.completed", {"r": 1})))
    asyncio.run(bus.publish(SkillEvent("skill.b.completed", {"r": 2})))
    asyncio.run(bus.publish(SkillEvent("skill.a.completed", {"r": 3})))

    history = bus.get_history(event_type="skill.a.completed")
    assert len(history) == 2
    assert history[0].payload["r"] == 3


def test_clear_history(bus: EventBus) -> None:
    import asyncio

    asyncio.run(bus.publish(SkillEvent("skill.a.completed", {})))
    bus.clear_history()
    assert len(bus.get_history()) == 0
