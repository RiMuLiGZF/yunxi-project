from __future__ import annotations

import pytest

from skill_cluster.adaptive_router import AdaptiveRouter, SkillMetrics
from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skill_router import SkillRouter
from skill_cluster.tests.test_router import DummySkill


def test_skill_metrics_record() -> None:
    m = SkillMetrics(skill_id="skill.x")
    m.increment_load()
    m.record_call(100.0, True)
    assert m.total_calls == 1
    assert m.success_calls == 1
    assert m.avg_latency_ms == 100.0
    assert m.current_load == 0
    assert m.score > 0.0


def test_skill_metrics_failure() -> None:
    m = SkillMetrics(skill_id="skill.x")
    m.record_call(50.0, False, error="timeout")
    assert m.failed_calls == 1
    assert m.last_error == "timeout"
    assert m.score < 1.0


def test_select_skill_single() -> None:
    router = AdaptiveRouter()
    result = router.select_skill(["skill.a"])
    assert result == "skill.a"


def test_select_skill_epsilon_greedy() -> None:
    router = AdaptiveRouter(epsilon=0.0)  # 纯利用
    router._metrics["skill.a"] = SkillMetrics(skill_id="skill.a")
    router._metrics["skill.b"] = SkillMetrics(skill_id="skill.b")
    router._metrics["skill.a"].score = 0.9
    router._metrics["skill.b"].score = 0.5

    result = router.select_skill(["skill.a", "skill.b"])
    assert result == "skill.a"


def test_select_skill_exploration() -> None:
    router = AdaptiveRouter(epsilon=1.0)  # 纯探索
    result = router.select_skill(["skill.a", "skill.b", "skill.c"])
    assert result in ["skill.a", "skill.b", "skill.c"]


def test_select_skill_empty() -> None:
    router = AdaptiveRouter()
    assert router.select_skill([]) is None


@pytest.mark.asyncio
async def test_adaptive_invoke_updates_metrics() -> None:
    SkillRouter._instance = None
    sr = SkillRouter()
    sr.mount(DummySkill("skill.dummy"))
    router = AdaptiveRouter(router=sr)

    request = SkillInvokeRequest(
        skill_id="skill.dummy", action="echo", trace_id="t1"
    )
    result = await router.invoke(request, "agent1")

    assert result.status == "success"
    metrics = router.get_metrics("skill.dummy")
    assert metrics is not None
    assert metrics.total_calls == 1
    assert metrics.success_calls == 1


@pytest.mark.asyncio
async def test_adaptive_invoke_failure() -> None:
    SkillRouter._instance = None
    sr = SkillRouter()
    router = AdaptiveRouter(router=sr)

    request = SkillInvokeRequest(
        skill_id="skill.not_exist", action="test", trace_id="t1"
    )
    result = await router.invoke(request, "agent1")

    # SkillRouter 对不存在的技能返回 not_found 而非抛出异常
    assert result.status == "not_found"
    metrics = router.get_metrics("skill.not_exist")
    assert metrics is not None
    assert metrics.failed_calls == 1


def test_get_top_skills() -> None:
    router = AdaptiveRouter()
    router._metrics["skill.a"] = SkillMetrics(skill_id="skill.a")
    router._metrics["skill.b"] = SkillMetrics(skill_id="skill.b")
    router._metrics["skill.a"].score = 0.9
    router._metrics["skill.b"].score = 0.5

    top = router.get_top_skills(2)
    assert top[0] == ("skill.a", 0.9)


def test_get_unhealthy_skills() -> None:
    router = AdaptiveRouter()
    router._metrics["skill.a"] = SkillMetrics(skill_id="skill.a")
    router._metrics["skill.b"] = SkillMetrics(skill_id="skill.b")
    router._metrics["skill.a"].score = 0.2
    router._metrics["skill.b"].score = 0.8

    unhealthy = router.get_unhealthy_skills(threshold=0.3)
    assert len(unhealthy) == 1
    assert unhealthy[0][0] == "skill.a"


def test_epsilon_config() -> None:
    router = AdaptiveRouter(epsilon=0.5)
    router.set_epsilon(0.2)
    assert router._epsilon == 0.2

    router.set_epsilon(2.0)
    assert router._epsilon == 1.0

    router.set_epsilon(-1.0)
    assert router._epsilon == 0.0


def test_decay_epsilon() -> None:
    router = AdaptiveRouter(epsilon=0.5)
    router.decay_epsilon(0.9)
    assert router._epsilon == 0.45

    # 多次衰减不会低于最小值
    for _ in range(100):
        router.decay_epsilon(0.9)
    assert router._epsilon >= 0.01


def test_get_stats_empty() -> None:
    router = AdaptiveRouter()
    stats = router.get_stats()
    assert stats["total_skills"] == 0


def test_get_stats_with_data() -> None:
    router = AdaptiveRouter()
    router._metrics["skill.a"] = SkillMetrics(skill_id="skill.a")
    router._metrics["skill.a"].record_call(100.0, True)
    router._metrics["skill.b"] = SkillMetrics(skill_id="skill.b")
    router._metrics["skill.b"].record_call(200.0, False)

    stats = router.get_stats()
    assert stats["total_skills"] == 2
    assert stats["total_calls"] == 2
    assert stats["unhealthy_count"] >= 0
