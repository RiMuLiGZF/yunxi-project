from __future__ import annotations

import pytest

from skill_cluster.skill_experience import (
    ExperienceRecord,
    SkillExperienceBank,
    SuccessPattern,
)


def test_record_experience() -> None:
    bank = SkillExperienceBank()
    rec = bank.record(
        skill_id="skill.doc",
        action="parse",
        params={"format": "pdf"},
        outcome="success",
        latency_ms=120.0,
        agent_id="agent1",
    )
    assert rec.skill_id == "skill.doc"
    assert rec.quality_score > 0.7


def test_record_failure() -> None:
    bank = SkillExperienceBank()
    rec = bank.record(
        skill_id="skill.doc",
        action="parse",
        params={"format": "xlsx"},
        outcome="failure",
        latency_ms=50.0,
        error="Unsupported format",
    )
    assert rec.quality_score == 0.0


def test_predict_success_rate_no_data() -> None:
    bank = SkillExperienceBank()
    rate = bank.predict_success_rate("skill.unknown", "test")
    assert rate == 0.5


def test_predict_success_rate_with_data() -> None:
    bank = SkillExperienceBank()
    for _ in range(5):
        bank.record("skill.a", "run", {"x": 1}, "success", 100.0)
    for _ in range(2):
        bank.record("skill.a", "run", {"x": 1}, "failure", 200.0, error="err")

    rate = bank.predict_success_rate("skill.a", "run")
    assert rate > 0.5


def test_predict_latency() -> None:
    bank = SkillExperienceBank()
    for lat in [50, 100, 150, 200, 250]:
        bank.record("skill.x", "run", {}, "success", float(lat))

    p50 = bank.predict_latency("skill.x", 0.5)
    p90 = bank.predict_latency("skill.x", 0.9)
    assert p50 is not None
    assert p90 is not None
    assert p90 >= p50


def test_predict_latency_no_data() -> None:
    bank = SkillExperienceBank()
    assert bank.predict_latency("skill.unknown") is None


def test_known_failure_pattern() -> None:
    bank = SkillExperienceBank()
    params = {"key": "bad_value"}
    for _ in range(3):
        bank.record("skill.a", "run", params, "failure", 10.0, error="bad")

    result = bank.is_known_failure_pattern("skill.a", "run", params)
    assert result is not None
    assert "Known failure" in result


def test_not_known_failure() -> None:
    bank = SkillExperienceBank()
    result = bank.is_known_failure_pattern("skill.a", "run", {"x": 1})
    assert result is None


def test_get_best_params() -> None:
    bank = SkillExperienceBank()
    params = {"model": "gpt-4", "temp": 0.7}
    for _ in range(5):
        bank.record("skill.llm", "generate", params, "success", 200.0)

    best = bank.get_best_params("skill.llm", "generate")
    assert best is not None
    assert best["model"] == "gpt-4"


def test_get_best_params_insufficient_data() -> None:
    bank = SkillExperienceBank()
    bank.record("skill.a", "run", {"x": 1}, "success", 100.0)
    assert bank.get_best_params("skill.a", "run") is None


def test_get_skill_stats() -> None:
    bank = SkillExperienceBank()
    bank.record("skill.x", "run", {}, "success", 100.0)
    bank.record("skill.x", "run", {}, "failure", 200.0)

    stats = bank.get_skill_stats("skill.x")
    assert stats["total_calls"] == 2
    assert stats["success_rate"] == 0.5


def test_get_skill_stats_no_data() -> None:
    bank = SkillExperienceBank()
    stats = bank.get_skill_stats("skill.unknown")
    assert stats["total_calls"] == 0


def test_get_top_skills() -> None:
    bank = SkillExperienceBank()
    for _ in range(10):
        bank.record("skill.popular", "run", {}, "success", 50.0)
    for _ in range(3):
        bank.record("skill.rare", "run", {}, "success", 100.0)

    top = bank.get_top_skills(5)
    assert len(top) >= 2
    assert top[0][0] == "skill.popular"


def test_forget_old() -> None:
    bank = SkillExperienceBank()
    import time
    rec = bank.record("skill.x", "run", {}, "success", 100.0)
    rec.timestamp = time.time() - 999999
    removed = bank.forget_old(max_age_hours=1.0)
    assert removed >= 1


def test_export() -> None:
    bank = SkillExperienceBank()
    bank.record("skill.x", "run", {"a": 1}, "success", 100.0)
    data = bank.export()
    assert "records" in data
    assert "patterns" in data


def test_max_records_trim() -> None:
    bank = SkillExperienceBank(max_records=5)
    for i in range(10):
        bank.record(f"skill.{i}", "run", {"i": i}, "success", 100.0)
    assert len(bank._records) == 5
