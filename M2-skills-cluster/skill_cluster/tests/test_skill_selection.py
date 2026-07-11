"""Tests for Skill Selection Strategy unified interface."""

import pytest

from skill_cluster.skill_selection import (
    AdaptiveSelection,
    BanditSelection,
    CompositeSelection,
    ISkillSelectionStrategy,
    RoundRobinSelection,
    SelectionContext,
    SelectionResult,
    SelectionStrategyType,
    SkillSelectionOrchestrator,
)
from skill_cluster.adaptive_router import AdaptiveRouter
from skill_cluster.skill_bandit_router import SkillBanditRouter


# ---- SelectionContext / SelectionResult ----

def test_selection_context_defaults():
    ctx = SelectionContext(candidates=["a", "b"])
    assert ctx.candidates == ["a", "b"]
    assert ctx.urgency == 0.5
    assert ctx.user_feedback is None


def test_selection_context_with_extra():
    ctx = SelectionContext(
        candidates=["a"],
        task_type="code_gen",
        urgency=0.9,
    )
    assert ctx.task_type == "code_gen"
    assert ctx.urgency == 0.9


def test_selection_result():
    r = SelectionResult(skill_id="s1", strategy_name="test", confidence=0.85)
    assert r.skill_id == "s1"
    assert r.confidence == 0.85


# ---- RoundRobinSelection ----

def test_round_robin_basic():
    strat = RoundRobinSelection()
    ctx = SelectionContext(candidates=["a", "b", "c"])
    assert strat.select(ctx).skill_id == "a"
    assert strat.select(ctx).skill_id == "b"
    assert strat.select(ctx).skill_id == "c"
    assert strat.select(ctx).skill_id == "a"  # wrap


def test_round_robin_empty():
    strat = RoundRobinSelection()
    assert strat.select(SelectionContext(candidates=[])) is None


def test_round_robin_record_noop():
    strat = RoundRobinSelection()
    strat.record_feedback("a", True, 10.0)  # no error


# ---- AdaptiveSelection ----

def test_adaptive_selection():
    router = AdaptiveRouter(epsilon=0.0)
    strat = AdaptiveSelection(router)
    ctx = SelectionContext(candidates=["skill.a", "skill.b"])
    result = strat.select(ctx)
    assert result is not None
    assert result.skill_id in ("skill.a", "skill.b")
    assert result.strategy_name == "adaptive_score"
    assert 0.0 <= result.confidence <= 1.0


def test_adaptive_selection_empty():
    router = AdaptiveRouter()
    strat = AdaptiveSelection(router)
    assert strat.select(SelectionContext(candidates=[])) is None


def test_adaptive_record_feedback():
    from skill_cluster.adaptive_router import SkillMetrics
    router = AdaptiveRouter(epsilon=0.0)
    # 预注册 metrics 确保后续 record_feedback 可找到
    router._metrics["skill.a"] = SkillMetrics(skill_id="skill.a")
    strat = AdaptiveSelection(router)
    strat.record_feedback("skill.a", True, 50.0)
    metrics = router.get_metrics("skill.a")
    assert metrics is not None
    assert metrics.total_calls == 1


def test_adaptive_selection_type_check():
    with pytest.raises(TypeError):
        AdaptiveSelection("not_a_router")


# ---- BanditSelection ----

def test_bandit_selection():
    router = SkillBanditRouter(explore_rate=0.0)
    strat = BanditSelection(router)
    ctx = SelectionContext(candidates=["s1", "s2"])
    result = strat.select(ctx)
    assert result is not None
    assert result.skill_id in ("s1", "s2")
    assert result.strategy_name == "bandit_thompson"


def test_bandit_selection_empty():
    router = SkillBanditRouter()
    strat = BanditSelection(router)
    assert strat.select(SelectionContext(candidates=[])) is None


def test_bandit_record_feedback():
    router = SkillBanditRouter(explore_rate=0.0)
    strat = BanditSelection(router)
    strat.select(SelectionContext(candidates=["s1"]))
    strat.record_feedback("s1", True, 100.0)
    stats = router.get_arm_stats("s1", "default")
    assert stats["total_calls"] == 1


def test_bandit_selection_type_check():
    with pytest.raises(TypeError):
        BanditSelection("not_a_router")


# ---- CompositeSelection ----

def test_composite_basic():
    rr = RoundRobinSelection()
    bandit = BanditSelection(SkillBanditRouter(explore_rate=1.0))
    comp = CompositeSelection([bandit, rr], confidence_threshold=0.0)
    ctx = SelectionContext(candidates=["a", "b"])
    result = comp.select(ctx)
    assert result is not None
    assert result.strategy_name.startswith("composite(")


def test_composite_empty_strategies():
    with pytest.raises(ValueError):
        CompositeSelection([])


def test_composite_feedback_broadcast():
    router = SkillBanditRouter(explore_rate=0.0)
    bandit = BanditSelection(router)
    # bandit 先执行确保 arm 注册
    bandit.select(SelectionContext(candidates=["s1"]))
    rr = RoundRobinSelection()
    comp = CompositeSelection([bandit, rr])
    comp.record_feedback("s1", True, 100.0)
    # Bandit 应该收到反馈
    stats = router.get_arm_stats("s1", "default")
    assert stats["total_calls"] == 1


# ---- SkillSelectionOrchestrator ----

def test_orchestrator_basic():
    rr = RoundRobinSelection()
    orch = SkillSelectionOrchestrator(default_strategy=rr)
    result = orch.select(["a", "b", "c"])
    assert result is not None
    assert result.skill_id == "a"
    assert orch.get_active_strategy() == "round_robin"


def test_orchestrator_switch():
    rr = RoundRobinSelection()
    bandit = BanditSelection(SkillBanditRouter(explore_rate=0.0))
    orch = SkillSelectionOrchestrator(default_strategy=rr)
    orch.register_strategy(bandit)
    assert orch.switch_strategy("bandit_thompson") is True
    assert orch.get_active_strategy() == "bandit_thompson"
    # Switch to non-existent
    assert orch.switch_strategy("nonexistent") is False


def test_orchestrator_list_strategies():
    rr = RoundRobinSelection()
    bandit = BanditSelection(SkillBanditRouter(explore_rate=0.0))
    orch = SkillSelectionOrchestrator(default_strategy=rr)
    orch.register_strategy(bandit)
    lst = orch.list_strategies()
    assert len(lst) == 2
    names = {s["name"] for s in lst}
    assert "round_robin" in names
    assert "bandit_thompson" in names
    active = [s for s in lst if s["active"]]
    assert len(active) == 1
    assert active[0]["name"] == "round_robin"


def test_orchestrator_no_strategy():
    orch = SkillSelectionOrchestrator()
    assert orch.select(["a", "b"]) is None
    assert orch.record_feedback("a", True) is None  # no error


def test_orchestrator_record_feedback():
    router = SkillBanditRouter(explore_rate=0.0)
    bandit = BanditSelection(router)
    orch = SkillSelectionOrchestrator(default_strategy=bandit)
    orch.select(["s1"])
    orch.record_feedback("s1", True, 50.0)
    stats = router.get_arm_stats("s1", "default")
    assert stats["total_calls"] == 1


# ---- Interface conformance ----

def test_all_strategies_implement_interface():
    rr = RoundRobinSelection()
    assert isinstance(rr, ISkillSelectionStrategy)
    bandit = BanditSelection(SkillBanditRouter())
    assert isinstance(bandit, ISkillSelectionStrategy)
    adaptive = AdaptiveSelection(AdaptiveRouter())
    assert isinstance(adaptive, ISkillSelectionStrategy)
    comp = CompositeSelection([rr])
    assert isinstance(comp, ISkillSelectionStrategy)


def test_strategy_types():
    rr = RoundRobinSelection()
    assert rr.strategy_type == SelectionStrategyType.ROUND_ROBIN
    adaptive = AdaptiveSelection(AdaptiveRouter())
    assert adaptive.strategy_type == SelectionStrategyType.ADAPTIVE
    bandit = BanditSelection(SkillBanditRouter())
    assert bandit.strategy_type == SelectionStrategyType.BANDIT
    comp = CompositeSelection([rr])
    assert comp.strategy_type == SelectionStrategyType.COMPOSITE
