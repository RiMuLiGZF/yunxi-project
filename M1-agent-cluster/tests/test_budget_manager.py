"""
测试：BudgetManager Token 预算与成本管理中心
"""

import pytest
import sys
import time

sys.path.insert(0, "/workspace/agent_cluster")

from budget_manager import BudgetManager, BudgetLevel, ModelPricing, UsageRecord


@pytest.fixture
def bm():
    return BudgetManager(
        daily_budget_usd=10.0,
        monthly_budget_usd=100.0,
        request_budget_usd=1.0,
    )


# ── 定价管理 ────────────────────────────────────────


def test_default_pricing(bm):
    p = bm.get_pricing("gpt-4o")
    assert p is not None
    assert p.input_price_per_1k == 2.50


def test_set_pricing(bm):
    bm.set_pricing("custom-model", 0.5, 1.5)
    p = bm.get_pricing("custom-model")
    assert p.input_price_per_1k == 0.5
    assert p.output_price_per_1k == 1.5


# ── 成本估算 ────────────────────────────────────────


def test_estimate_cost():
    p = ModelPricing("test", 1.0, 2.0)
    cost = p.estimate_cost(1000, 500)
    assert cost == 1.0 * 1.0 + 0.5 * 2.0  # 1.0 + 1.0 = 2.0


def test_estimate_cost_zero():
    p = ModelPricing("test", 0.0, 0.0)
    assert p.estimate_cost(10000, 10000) == 0.0


# ── 使用记录 ────────────────────────────────────────


def test_record_usage(bm):
    r = bm.record_usage(
        model="gpt-4o-mini",
        input_tokens=1000,
        output_tokens=500,
        agent_id="agent_a",
        session_id="sess_1",
    )
    assert isinstance(r, UsageRecord)
    assert r.model == "gpt-4o-mini"
    assert r.input_tokens == 1000
    assert r.output_tokens == 500
    assert r.estimated_cost > 0


def test_record_usage_mock_model(bm):
    r = bm.record_usage(
        model="mock-model",
        input_tokens=10000,
        output_tokens=10000,
    )
    assert r.estimated_cost == 0.0


# ── 预算检查 ────────────────────────────────────────


def test_check_request_budget(bm):
    ok, used, limit = bm.check_budget(BudgetLevel.REQUEST, projected_cost=0.5)
    assert ok is True
    assert used == 0.5
    assert limit == 1.0

    ok, used, limit = bm.check_budget(BudgetLevel.REQUEST, projected_cost=1.5)
    assert ok is False


def test_check_daily_budget(bm):
    # 先消耗一部分日预算
    bm.record_usage("gpt-4o-mini", input_tokens=10000, output_tokens=10000)
    # gpt-4o-mini: (10000/1000)*0.15 + (10000/1000)*0.60 = 1.5 + 6.0 = 7.5

    ok, used, limit = bm.check_budget(BudgetLevel.DAILY)
    assert used > 0
    assert limit == 10.0
    assert ok is True


def test_check_monthly_budget(bm):
    ok, used, limit = bm.check_budget(BudgetLevel.MONTHLY)
    assert used == 0.0
    assert limit == 100.0
    assert ok is True


# ── 预算可用性 ────────────────────────────────────────


def test_is_budget_available(bm):
    assert bm.is_budget_available("gpt-4o-mini", 100, 50) is True


def test_is_budget_available_exceeded(bm):
    # 设置一个极低的日预算使其超支
    bm.daily_budget = 0.001
    bm.record_usage("gpt-4o", input_tokens=1000, output_tokens=1000)
    # gpt-4o cost > 0.001
    assert bm.is_budget_available("gpt-4o", 100, 50) is False


# ── 成本感知路由 ────────────────────────────────────


def test_select_model_low_complexity(bm):
    model = bm.select_model_for_task("low")
    assert model == "gpt-4o-mini"


def test_select_model_medium_complexity(bm):
    model = bm.select_model_for_task("medium")
    assert model == "gpt-4o"


def test_select_model_high_complexity(bm):
    model = bm.select_model_for_task("high", preferred_model="claude-3-sonnet")
    assert model == "claude-3-sonnet"


def test_select_model_routing_disabled():
    bm = BudgetManager(enable_routing=False)
    model = bm.select_model_for_task("high", preferred_model="gpt-4o")
    assert model == "gpt-4o"


def test_select_model_budget_tight(bm):
    # 消耗超过 70% 日预算，触发降级
    bm.daily_budget = 10.0
    # 每次 0.75，10 次 = 7.5 (75%)
    for _ in range(10):
        bm.record_usage("gpt-4o-mini", input_tokens=1000, output_tokens=1000)
    # 检查是否降级
    model = bm.select_model_for_task("high")
    assert model == "gpt-4o-mini"  # 预算紧张时强制降级


# ── 统计 ────────────────────────────────────────


def test_get_stats(bm):
    bm.record_usage("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    stats = bm.get_stats()
    assert "daily" in stats
    assert "monthly" in stats
    assert stats["total_records"] >= 1
    assert stats["daily"]["requests"] >= 1


def test_get_model_usage(bm):
    bm.record_usage("gpt-4o-mini", input_tokens=1000, output_tokens=500)
    bm.record_usage("gpt-4o-mini", input_tokens=2000, output_tokens=1000)
    usage = bm.get_model_usage("gpt-4o-mini")
    assert usage["requests"] == 2
    assert usage["input_tokens"] == 3000


# ── 边界条件 ────────────────────────────────────────


def test_record_usage_unknown_model(bm):
    r = bm.record_usage("unknown-model", input_tokens=1000, output_tokens=500)
    assert r.estimated_cost == 0.0


def test_check_budget_unknown_level(bm):
    ok, used, limit = bm.check_budget("unknown_level")  # type: ignore
    assert ok is True
    assert limit == float("inf")
