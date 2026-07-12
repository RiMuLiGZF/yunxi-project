from __future__ import annotations

import pytest

from skill_cluster.token_budget import BudgetAlert, BudgetEntry, TokenBudget


def test_basic_consume() -> None:
    budget = TokenBudget(total_budget=1000)
    ok, alert = budget.consume(100, "input")
    assert ok is True
    assert alert is None
    assert budget.remaining == 900


def test_consume_exceeds_budget() -> None:
    budget = TokenBudget(total_budget=100)
    budget.consume(80, "input")
    ok, alert = budget.consume(50, "output")
    assert ok is False
    assert alert is not None
    assert alert.alert_type == "exceeded"
    assert budget._consumed == 80  # 未实际扣减


def test_try_consume() -> None:
    budget = TokenBudget(total_budget=100)
    assert budget.try_consume(50) is True
    assert budget.remaining == 50
    assert budget.try_consume(100) is False
    assert budget.remaining == 50  # 回滚


def test_category_budget() -> None:
    budget = TokenBudget(total_budget=1000)
    budget.allocate_category("tool", 100)

    ok1, _ = budget.consume(50, "tool")
    assert ok1 is True

    ok2, _ = budget.consume(60, "tool")
    assert ok2 is False  # 类别预算不足

    # 总预算还有余量，但类别不够
    assert budget.remaining == 950


def test_alert_threshold() -> None:
    budget = TokenBudget(total_budget=100, alert_threshold=0.8)
    budget.consume(70, "input")
    ok, alert = budget.consume(10, "input")
    assert ok is True
    assert alert is not None
    assert alert.alert_type == "warning"


def test_is_exhausted() -> None:
    budget = TokenBudget(total_budget=100)
    budget.consume(100, "input")
    assert budget.is_exhausted is True
    assert budget.remaining == 0


def test_usage_ratio() -> None:
    budget = TokenBudget(total_budget=200)
    budget.consume(50, "input")
    assert budget.usage_ratio == 0.25


def test_suggest_model_tier() -> None:
    budget = TokenBudget(total_budget=100)
    assert budget.suggest_model_tier() == "large"

    budget.consume(40, "input")
    assert budget.suggest_model_tier() == "medium"

    budget.consume(35, "input")
    assert budget.suggest_model_tier() == "small"


def test_trim_context() -> None:
    budget = TokenBudget(total_budget=100)
    budget.consume(30, "input")  # 剩余 70

    items = [
        {"text": "important", "tokens": 40, "priority": 1},
        {"text": "medium", "tokens": 30, "priority": 2},
        {"text": "low", "tokens": 20, "priority": 3},
        {"text": "lowest", "tokens": 50, "priority": 4},
    ]

    trimmed = budget.trim_context(items)
    texts = [i["text"] for i in trimmed]
    assert "important" in texts
    assert "medium" in texts
    assert len(trimmed) <= 3


def test_trim_context_empty() -> None:
    budget = TokenBudget(total_budget=100)
    result = budget.trim_context([])
    assert result == []


def test_get_summary() -> None:
    budget = TokenBudget(total_budget=500)
    budget.allocate_category("input", 300)
    budget.consume(100, "input")
    budget.consume(50, "output")

    summary = budget.get_summary()
    assert summary["total_budget"] == 500
    assert summary["consumed"] == 150
    assert summary["remaining"] == 350
    assert "input" in summary["category_breakdown"]
    assert summary["category_breakdown"]["input"] == 100


def test_get_entries() -> None:
    budget = TokenBudget(total_budget=1000)
    budget.consume(10, "input")
    budget.consume(20, "output")
    entries = budget.get_entries()
    assert len(entries) == 2
    assert entries[0].tokens == 10
    assert entries[1].tokens == 20


def test_get_alerts() -> None:
    budget = TokenBudget(total_budget=100, alert_threshold=0.5)
    budget.consume(60, "input")
    alerts = budget.get_alerts()
    assert len(alerts) >= 1


def test_reset() -> None:
    budget = TokenBudget(total_budget=100)
    budget.consume(50, "input")
    budget.reset()
    assert budget._consumed == 0
    assert budget.remaining == 100
    assert len(budget._entries) == 0


def test_set_total_budget() -> None:
    budget = TokenBudget(total_budget=100)
    budget.set_total_budget(200)
    assert budget.remaining == 200


def test_budget_entry_model() -> None:
    entry = BudgetEntry(category="tool", tokens=50)
    assert entry.category == "tool"
    assert entry.tokens == 50


def test_budget_alert_model() -> None:
    alert = BudgetAlert(
        alert_type="exceeded",
        message="test",
        total_tokens=100,
        budget_limit=100,
        remaining=0,
    )
    assert alert.alert_type == "exceeded"
