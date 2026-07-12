"""Tests for SkillHandbook."""

import pytest

from skill_cluster.skill_experience import SkillExperienceBank
from skill_cluster.skill_handbook import SkillHandbook


@pytest.fixture
def bank():
    return SkillExperienceBank(max_records=1000)


@pytest.fixture
def handbook(bank):
    return SkillHandbook(bank, lambda_cost=0.3, min_calls_for_trust=3)


def test_get_profile_no_data(handbook):
    profile = handbook.get_profile("agent1", "skill.doc_proc", "parse")
    assert profile.success_rate == 0.5
    assert profile.total_calls == 0


def test_get_profile_with_data(handbook, bank):
    for i in range(5):
        bank.record(
            skill_id="skill.doc_proc",
            action="parse",
            params={"file": f"doc{i}.txt"},
            outcome="success",
            latency_ms=100.0 + i * 10,
            agent_id="agent1",
        )
    profile = handbook.get_profile("agent1", "skill.doc_proc", "parse")
    assert profile.success_rate == 1.0
    assert profile.total_calls == 5
    assert profile.avg_latency_ms > 0


def test_utility_calculation(handbook, bank):
    bank.record(
        skill_id="skill.doc_proc",
        action="parse",
        params={"file": "doc.txt"},
        outcome="success",
        latency_ms=500.0,
        agent_id="agent1",
    )
    bank.record(
        skill_id="skill.doc_proc",
        action="parse",
        params={"file": "doc.txt"},
        outcome="success",
        latency_ms=600.0,
        agent_id="agent1",
    )
    bank.record(
        skill_id="skill.doc_proc",
        action="parse",
        params={"file": "doc.txt"},
        outcome="success",
        latency_ms=700.0,
        agent_id="agent1",
    )
    u = handbook.utility("agent1", "skill.doc_proc", "parse")
    assert u > 0.0
    # success_rate=1.0, avg_cost ~ 0.12, lambda=0.3 -> u ~ 0.964
    assert u < 1.0


def test_recommend_best_agent(handbook, bank):
    for i in range(5):
        bank.record(
            skill_id="skill.doc_proc",
            action="parse",
            params={"file": f"doc{i}.txt"},
            outcome="success",
            latency_ms=100.0,
            agent_id="agent_a",
        )
    for i in range(3):
        bank.record(
            skill_id="skill.doc_proc",
            action="parse",
            params={"file": f"doc{i}.txt"},
            outcome="failure",
            latency_ms=5000.0,
            agent_id="agent_b",
        )
    best = handbook.recommend_best_agent(
        "skill.doc_proc", "parse", ["agent_a", "agent_b"]
    )
    assert best == "agent_a"


def test_recommend_best_agent_empty(handbook):
    assert handbook.recommend_best_agent("s", "a", []) is None


def test_rank_skills_for_agent(handbook, bank):
    bank.record("skill.a", "act1", {}, "success", 100.0, agent_id="agent1")
    bank.record("skill.a", "act1", {}, "success", 120.0, agent_id="agent1")
    bank.record("skill.a", "act1", {}, "success", 110.0, agent_id="agent1")
    bank.record("skill.b", "act1", {}, "failure", 5000.0, agent_id="agent1")
    bank.record("skill.b", "act1", {}, "failure", 5000.0, agent_id="agent1")
    bank.record("skill.b", "act1", {}, "failure", 5000.0, agent_id="agent1")

    ranked = handbook.rank_skills_for_agent(
        "agent1", [("skill.a", "act1"), ("skill.b", "act1")]
    )
    assert ranked[0][0] == "skill.a"
    assert ranked[1][0] == "skill.b"
    assert ranked[0][2] > ranked[1][2]


def test_failure_patterns(handbook, bank):
    for i in range(3):
        bank.record(
            "skill.x",
            "act",
            {},
            "failure",
            1000.0,
            error="Connection timeout",
            agent_id="agent1",
        )
    profile = handbook.get_profile("agent1", "skill.x", "act")
    assert "Connection timeout" in profile.failure_patterns
