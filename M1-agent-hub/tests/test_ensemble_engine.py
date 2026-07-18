"""
测试：EnsembleEngine 多 Agent 集成引擎
"""

import pytest
import sys
from ensemble_engine import (
    EnsembleEngine,
    EnsembleStrategy,
    AgentVote,
    EnsembleResult,
)


@pytest.fixture
def engine():
    return EnsembleEngine()


# ── 投票策略 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_voting_strategy(engine):
    async def caller(agent_id, query):
        if agent_id == "a":
            return AgentVote(agent_id="a", response="answer_A", confidence=0.9)
        elif agent_id == "b":
            return AgentVote(agent_id="b", response="answer_A", confidence=0.8)
        else:
            return AgentVote(agent_id="c", response="answer_B", confidence=0.7)

    result = await engine.run(
        query="test",
        agent_ids=["a", "b", "c"],
        caller=caller,
        strategy=EnsembleStrategy.VOTING,
    )

    assert result.final_answer == "answer_A"
    assert result.consensus_reached is True
    assert len(result.dissenting_views) == 1
    assert result.dissenting_views[0].agent_id == "c"


@pytest.mark.asyncio
async def test_voting_empty_responses(engine):
    async def caller(agent_id, query):
        return AgentVote(agent_id=agent_id, response="", confidence=0.0)

    result = await engine.run(
        query="test",
        agent_ids=["a", "b"],
        caller=caller,
        strategy=EnsembleStrategy.VOTING,
    )

    assert result.final_answer == ""
    assert result.consensus_reached is False


@pytest.mark.asyncio
async def test_voting_single_agent(engine):
    async def caller(agent_id, query):
        return AgentVote(agent_id="a", response="only_one", confidence=1.0)

    result = await engine.run(
        query="test",
        agent_ids=["a"],
        caller=caller,
        strategy=EnsembleStrategy.VOTING,
    )

    assert result.final_answer == "only_one"
    assert result.consensus_reached is True


# ── 最优选择策略 ────────────────────────────────────


@pytest.mark.asyncio
async def test_best_of_n_strategy(engine):
    async def caller(agent_id, query):
        responses = {
            "a": AgentVote(agent_id="a", response="good", confidence=0.9),
            "b": AgentVote(agent_id="b", response="better", confidence=0.95),
            "c": AgentVote(agent_id="c", response="ok", confidence=0.5),
        }
        return responses[agent_id]

    result = await engine.run(
        query="test",
        agent_ids=["a", "b", "c"],
        caller=caller,
        strategy=EnsembleStrategy.BEST_OF_N,
    )

    assert result.final_answer == "better"
    assert result.consensus_reached is True
    assert len(result.dissenting_views) == 2


# ── 加权合成策略 ────────────────────────────────────


@pytest.mark.asyncio
async def test_weighted_synthesis_strategy(engine):
    async def caller(agent_id, query):
        responses = {
            "a": AgentVote(agent_id="a", response="high_conf", confidence=0.95),
            "b": AgentVote(agent_id="b", response="low_conf", confidence=0.3),
            "c": AgentVote(agent_id="c", response="mid_conf", confidence=0.6),
        }
        return responses[agent_id]

    result = await engine.run(
        query="test",
        agent_ids=["a", "b", "c"],
        caller=caller,
        strategy=EnsembleStrategy.WEIGHTED_SYNTHESIS,
    )

    # 最高置信度的回答
    assert "high_conf" in result.final_answer
    # 有异议（b 的置信度低于平均值 * 0.8）
    assert len(result.dissenting_views) >= 1


@pytest.mark.asyncio
async def test_weighted_synthesis_zero_confidence(engine):
    async def caller(agent_id, query):
        return AgentVote(agent_id=agent_id, response="ans", confidence=0.0)

    result = await engine.run(
        query="test",
        agent_ids=["a", "b"],
        caller=caller,
        strategy=EnsembleStrategy.WEIGHTED_SYNTHESIS,
    )

    # 零置信度时退化为投票
    assert result.final_answer == "ans"


# ── 共识策略 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_consensus_reached_immediately(engine):
    """第一轮即达成共识"""
    async def caller(agent_id, query):
        return AgentVote(agent_id=agent_id, response="same", confidence=0.9)

    result = await engine.run(
        query="test",
        agent_ids=["a", "b", "c"],
        caller=caller,
        strategy=EnsembleStrategy.CONSENSUS,
    )

    assert result.final_answer == "same"
    assert result.consensus_reached is True
    assert result.rounds == 1


@pytest.mark.asyncio
async def test_consensus_not_reached(engine):
    """无法达成共识，返回多数答案"""
    call_count = 0

    async def caller(agent_id, query):
        nonlocal call_count
        call_count += 1
        responses = {
            "a": AgentVote(agent_id="a", response="A", confidence=0.9),
            "b": AgentVote(agent_id="b", response="B", confidence=0.9),
            "c": AgentVote(agent_id="c", response="C", confidence=0.9),
        }
        return responses[agent_id]

    result = await engine.run(
        query="test",
        agent_ids=["a", "b", "c"],
        caller=caller,
        strategy=EnsembleStrategy.CONSENSUS,
    )

    # 未达成共识但返回了某答案
    assert result.final_answer in ("A", "B", "C")
    assert result.rounds >= 1


# ── 异常处理 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_caller_failure(engine):
    async def caller(agent_id, query):
        if agent_id == "fail":
            raise ValueError("boom")
        return AgentVote(agent_id=agent_id, response="ok", confidence=0.8)

    result = await engine.run(
        query="test",
        agent_ids=["ok", "fail"],
        caller=caller,
        strategy=EnsembleStrategy.VOTING,
    )

    assert result.final_answer == "ok"
    # 失败的 agent 也会被记录
    assert len(result.votes) == 2
    assert result.votes[1].confidence == 0.0


# ── 策略推荐 ────────────────────────────────────────


def test_recommend_strategy_reasoning(engine):
    s = engine.recommend_strategy("为什么会这样？", task_type="reasoning")
    assert s == EnsembleStrategy.VOTING


def test_recommend_strategy_knowledge(engine):
    s = engine.recommend_strategy("Python 是什么？", task_type="knowledge")
    assert s == EnsembleStrategy.CONSENSUS


def test_recommend_strategy_creative(engine):
    s = engine.recommend_strategy("写一首诗", task_type="creative")
    assert s == EnsembleStrategy.BEST_OF_N


def test_recommend_strategy_high_stakes(engine):
    s = engine.recommend_strategy("重大决策", task_type="high_stakes")
    assert s == EnsembleStrategy.WEIGHTED_SYNTHESIS


def test_recommend_strategy_heuristic(engine):
    s = engine.recommend_strategy("如何计算这个？")
    assert s == EnsembleStrategy.VOTING

    s = engine.recommend_strategy("历史的定义是什么？")
    assert s == EnsembleStrategy.CONSENSUS


def test_recommend_strategy_default(engine):
    s = engine.recommend_strategy("hello world")
    assert s == engine.default_strategy


# ── 结果序列化 ──────────────────────────────────────


def test_ensemble_result_to_dict():
    result = EnsembleResult(
        final_answer="test",
        strategy=EnsembleStrategy.VOTING,
        votes=[AgentVote(agent_id="a", response="test", confidence=0.9)],
        consensus_reached=True,
        rounds=1,
        latency_ms=123.456,
    )
    d = result.to_dict()
    assert d["final_answer"] == "test"
    assert d["strategy"] == "voting"
    assert d["consensus_reached"] is True
    assert d["rounds"] == 1
    assert d["latency_ms"] == 123.46


# ── 默认策略 ────────────────────────────────────────


def test_default_strategy():
    engine = EnsembleEngine(default_strategy=EnsembleStrategy.BEST_OF_N)
    assert engine.default_strategy == EnsembleStrategy.BEST_OF_N
