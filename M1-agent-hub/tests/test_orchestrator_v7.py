"""
测试：OrchestratorV7 整合编排器
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, PropertyMock
from orchestrator_v7 import OrchestratorV7
from ensemble_engine import EnsembleStrategy, AgentVote, EnsembleResult
from budget_manager import BudgetManager
from task_durability import TaskDurabilityManager


@pytest.fixture
def mock_v5():
    v5 = MagicMock()
    v5.process = AsyncMock(return_value={
        "reply": "mock reply",
        "status": "success",
        "latency_ms": 100,
    })

    class _Stream:
        async def __call__(self, *args, **kwargs):
            yield {"chunk": "hello"}
            yield {"chunk": " world"}

    v5.process_stream = _Stream()
    v5.diagnose = MagicMock(return_value={"v5": {"test": True}})
    v5.get_config = MagicMock(return_value="gpt-4o-mini")
    return v5


@pytest.fixture
def v7(mock_v5):
    budget = BudgetManager(daily_budget_usd=100.0)
    durability = TaskDurabilityManager()
    return OrchestratorV7(
        orchestrator_v5=mock_v5,
        budget_manager=budget,
        durability_manager=durability,
    )


# ── 集成处理 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_ensemble(v7, mock_v5):
    result = await v7.process_ensemble(
        query="test query",
        agent_ids=["agent_a", "agent_b"],
        strategy=EnsembleStrategy.VOTING,
    )

    assert isinstance(result, EnsembleResult)
    assert result.strategy == EnsembleStrategy.VOTING
    assert len(result.votes) == 2
    assert result.latency_ms >= 0
    # V5 process 被调用了 2 次（每个 agent 一次）
    assert mock_v5.process.call_count == 2


@pytest.mark.asyncio
async def test_process_ensemble_default_strategy(v7, mock_v5):
    result = await v7.process_ensemble(
        query="test",
        agent_ids=["a"],
    )
    assert result.strategy == EnsembleStrategy.VOTING  # 默认策略


# ── 预算感知处理 ────────────────────────────────────


@pytest.mark.asyncio
async def test_process_budget_aware(v7, mock_v5):
    result = await v7.process_budget_aware(
        user_input="hello",
        task_complexity="medium",
    )

    assert result["reply"] == "mock reply"
    assert result["model_used"] == "gpt-4o"
    assert "budget_stats" in result
    mock_v5.process.assert_called()


@pytest.mark.asyncio
async def test_process_budget_aware_exceeded(mock_v5):
    """预算超支时返回提示"""
    budget = BudgetManager(daily_budget_usd=0.001)
    # 先消耗预算
    budget.record_usage("gpt-4o", input_tokens=10000, output_tokens=10000)

    v7 = OrchestratorV7(mock_v5, budget_manager=budget)
    result = await v7.process_budget_aware("hello")

    assert result["status"] == "budget_exceeded"
    assert "预算已用尽" in result["reply"]


# ── 耐久性任务 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_durable_task(v7):
    async def step1(state):
        return {"step1": True}

    async def step2(state):
        return {"step2": True}

    result = await v7.run_durable_task(
        task_id="durable_1",
        activities=[("s1", step1), ("s2", step2)],
        initial_state={"start": True},
    )

    assert result["start"] is True
    assert result["step1"] is True
    assert result["step2"] is True


@pytest.mark.asyncio
async def test_run_durable_task_without_manager(mock_v5):
    """没有 durability manager 时退化为普通执行"""
    v7 = OrchestratorV7(mock_v5, durability_manager=None)

    async def step1(state):
        return {"s1": True}

    result = await v7.run_durable_task(
        task_id="no_durability",
        activities=[("s1", step1)],
        initial_state={},
    )
    assert result["s1"] is True


# ── 兼容入口 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_delegation(v7, mock_v5):
    result = await v7.process("hello", trace_id="t1")
    assert result["reply"] == "mock reply"
    mock_v5.process.assert_called_with("hello", trace_id="t1", override_intent=None)


@pytest.mark.asyncio
async def test_process_stream_delegation(v7, mock_v5):
    chunks = []
    async for chunk in v7.process_stream("hello", trace_id="t1"):
        chunks.append(chunk)
    assert len(chunks) == 2


# ── 策略推荐 ────────────────────────────────────────


def test_recommend_strategy(v7):
    s = v7.recommend_strategy("为什么？", task_type="reasoning")
    assert s == EnsembleStrategy.VOTING


# ── 预算查询 ────────────────────────────────────────


def test_get_budget_stats(v7):
    stats = v7.get_budget_stats()
    assert "daily" in stats
    assert "monthly" in stats


def test_get_model_usage(v7):
    v7._budget.record_usage("gpt-4o-mini", 1000, 500)
    usage = v7.get_model_usage("gpt-4o-mini")
    assert usage["model"] == "gpt-4o-mini"
    assert usage["requests"] >= 1


# ── 诊断 ────────────────────────────────────────────


def test_diagnose(v7):
    diag = v7.diagnose()
    assert "v5" in diag
    assert "v7" in diag
    assert "ensemble" in diag["v7"]
    assert "budget" in diag["v7"]
    assert "durability" in diag["v7"]


# ── 属性透传 ────────────────────────────────────────


def test_getattr_pass_through(v7, mock_v5):
    # 测试 V5 方法透传
    mock_v5.submit_feedback = MagicMock()
    v7.submit_feedback("test")
    mock_v5.submit_feedback.assert_called_once_with("test")
