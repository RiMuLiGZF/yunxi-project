from __future__ import annotations

import pytest

from skill_cluster.a2a_bus import A2ABus
from skill_cluster.a2a_protocol import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)


@pytest.fixture
def bus() -> A2ABus:
    return A2ABus()


def test_register_card(bus: A2ABus) -> None:
    card = A2AAgentCard(agent_id="a1", name="Agent1", skills=["skill.x"])
    bus.register_card(card)
    assert bus.get_card("a1") is not None
    assert bus.get_card("a1").name == "Agent1"


def test_unregister_card(bus: A2ABus) -> None:
    bus.register_card(A2AAgentCard(agent_id="a1", name="Agent1"))
    bus.unregister_card("a1")
    assert bus.get_card("a1") is None


def test_discover_by_skill(bus: A2ABus) -> None:
    bus.register_card(
        A2AAgentCard(agent_id="a1", name="A1", skills=["skill.x", "skill.y"])
    )
    bus.register_card(
        A2AAgentCard(agent_id="a2", name="A2", skills=["skill.y"])
    )
    results = bus.discover_by_skill("skill.x")
    assert len(results) == 1
    assert results[0].agent_id == "a1"


@pytest.mark.asyncio
async def test_send_message_local(bus: A2ABus) -> None:
    received: list[A2AMessage] = []

    async def handler(msg: A2AMessage) -> None:
        received.append(msg)

    bus.on_message("agent_b", handler)
    msg = await bus.send_message(
        "agent_a",
        "agent_b",
        [A2APart(type="text", content="hello")],
    )
    assert msg.source_agent_id == "agent_a"
    assert len(received) == 1
    assert received[0].parts[0].content == "hello"


@pytest.mark.asyncio
async def test_broadcast(bus: A2ABus) -> None:
    bus.register_card(A2AAgentCard(agent_id="a1", name="A1"))
    bus.register_card(A2AAgentCard(agent_id="a2", name="A2"))
    bus.register_card(A2AAgentCard(agent_id="a3", name="A3"))

    msgs = await bus.broadcast(
        "a1", [A2APart(type="text", content="all")]
    )
    assert len(msgs) == 2  # a1 不会发给自己


@pytest.mark.asyncio
async def test_create_task(bus: A2ABus) -> None:
    task = await bus.create_task(
        creator_agent_id="agent_a",
        handler_agent_id="agent_b",
        metadata={"priority": "high"},
    )
    assert task.creator_agent_id == "agent_a"
    assert task.handler_agent_id == "agent_b"
    assert task.status == "submitted"
    assert bus.get_task(task.task_id) is not None


@pytest.mark.asyncio
async def test_assign_task(bus: A2ABus) -> None:
    task = await bus.create_task(creator_agent_id="agent_a")
    updated = await bus.assign_task(task.task_id, "agent_b")
    assert updated is not None
    assert updated.handler_agent_id == "agent_b"
    assert updated.status == "working"


@pytest.mark.asyncio
async def test_update_task_status(bus: A2ABus) -> None:
    task = await bus.create_task(
        creator_agent_id="agent_a", handler_agent_id="agent_b"
    )
    updated = await bus.update_task_status(
        task.task_id, "completed", reason="done"
    )
    assert updated is not None
    assert updated.status == "completed"


@pytest.mark.asyncio
async def test_task_handler_notification(bus: A2ABus) -> None:
    notifications: list[A2ATask] = []

    async def handler(task: A2ATask) -> None:
        notifications.append(task)

    bus.on_task("agent_b", handler)
    await bus.create_task(
        creator_agent_id="agent_a", handler_agent_id="agent_b"
    )
    assert len(notifications) >= 1


@pytest.mark.asyncio
async def test_list_tasks_filter(bus: A2ABus) -> None:
    t1 = await bus.create_task(
        creator_agent_id="a1", handler_agent_id="a2"
    )
    t2 = await bus.create_task(
        creator_agent_id="a1", handler_agent_id="a3"
    )
    await bus.update_task_status(t1.task_id, "completed")

    all_tasks = bus.list_tasks()
    assert len(all_tasks) == 2

    completed = bus.list_tasks(status="completed")
    assert len(completed) == 1

    a2_tasks = bus.list_tasks(agent_id="a2")
    assert len(a2_tasks) == 1


def test_get_stats(bus: A2ABus) -> None:
    bus.register_card(A2AAgentCard(agent_id="a1", name="A1"))
    stats = bus.get_stats()
    assert stats["registered_agents"] == 1
    assert stats["active_tasks"] == 0
