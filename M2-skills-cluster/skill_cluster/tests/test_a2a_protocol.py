from __future__ import annotations

import pytest

from skill_cluster.a2a_protocol import (
    A2AAgentCard,
    A2AArtifact,
    A2AMessage,
    A2APart,
    A2ATask,
)


def test_a2a_part_model() -> None:
    part = A2APart(type="text", content="hello", mime_type="text/plain")
    assert part.type == "text"
    assert part.content == "hello"


def test_a2a_message_model() -> None:
    msg = A2AMessage(
        role="agent",
        source_agent_id="agent_a",
        target_agent_id="agent_b",
        parts=[A2APart(type="text", content="hi")],
    )
    assert msg.role == "agent"
    assert msg.source_agent_id == "agent_a"
    assert len(msg.parts) == 1


def test_a2a_artifact_model() -> None:
    art = A2AArtifact(
        name="result.json",
        parts=[A2APart(type="data", content={"x": 1})],
    )
    assert art.name == "result.json"
    assert art.parts[0].content == {"x": 1}


def test_a2a_task_defaults() -> None:
    task = A2ATask(creator_agent_id="agent_a")
    assert task.status == "submitted"
    assert task.handler_agent_id is None
    assert len(task.messages) == 0


def test_a2a_task_transition() -> None:
    task = A2ATask(creator_agent_id="agent_a")
    task.transition("working", "started")
    assert task.status == "working"
    assert len(task.history) == 1
    assert task.history[0]["event"] == "status_changed"


def test_a2a_task_add_message() -> None:
    task = A2ATask(creator_agent_id="agent_a")
    msg = A2AMessage(
        role="user",
        source_agent_id="agent_b",
        target_agent_id="agent_a",
        parts=[A2APart(type="text", content="question")],
    )
    task.add_message(msg)
    assert len(task.messages) == 1
    assert task.messages[0].source_agent_id == "agent_b"


def test_a2a_task_add_artifact() -> None:
    task = A2ATask(creator_agent_id="agent_a")
    art = A2AArtifact(name="output", parts=[])
    task.add_artifact(art)
    assert task.status == "completed"
    assert len(task.artifacts) == 1


def test_a2a_agent_card_model() -> None:
    card = A2AAgentCard(
        agent_id="agent_x",
        name="Analyzer",
        skills=["skill.data_analysis"],
        capabilities=["streaming"],
    )
    assert card.agent_id == "agent_x"
    assert "skill.data_analysis" in card.skills
    assert card.auth_scheme == "none"
