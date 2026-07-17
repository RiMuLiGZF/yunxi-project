"""反思与评估引擎单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest

from agent_cluster.core.reflection_engine import (
    Evaluator,
    Reflector,
    ReflectionEngine,
    MultiAgentPeerReview,
    EvaluationResult,
)
from agent_cluster.tools.interfaces import AgentResult


def test_evaluate_success():
    """测试成功结果评估"""
    evaluator = Evaluator()
    result = AgentResult(
        task_id="t1",
        agent_id="agent.note",
        status="success",
        output={"reply": "笔记已创建"},
        latency_ms=100,
    )
    eval_result = evaluator.evaluate(result)
    assert eval_result.passed
    assert eval_result.score >= 0.8
    assert eval_result.criteria["completeness"] == 1.0


def test_evaluate_failure():
    """测试失败结果评估"""
    evaluator = Evaluator()
    result = AgentResult(
        task_id="t1",
        agent_id="agent.note",
        status="failure",
        error="timeout",
        latency_ms=5000,
    )
    eval_result = evaluator.evaluate(result)
    assert not eval_result.passed
    assert eval_result.score < 0.6


def test_evaluate_partial():
    """测试部分成功评估"""
    evaluator = Evaluator()
    result = AgentResult(
        task_id="t1",
        agent_id="agent.note",
        status="partial",
        output={},
        latency_ms=300,
    )
    eval_result = evaluator.evaluate(result)
    assert eval_result.criteria["completeness"] == 0.5


def test_evaluate_safety_check():
    """测试安全性评估"""
    evaluator = Evaluator()
    result = AgentResult(
        task_id="t1",
        agent_id="agent.note",
        status="success",
        output={"reply": "我的身份证号是 123456"},
        latency_ms=100,
    )
    eval_result = evaluator.evaluate(result)
    assert eval_result.criteria["safety"] < 1.0


def test_reflector_generate():
    """测试反思生成"""
    reflector = Reflector()
    evaluation = EvaluationResult(
        passed=True,
        score=0.85,
        criteria={"completeness": 1.0, "latency": 0.7},
        suggestions=["优化响应速度"],
    )
    reflection = reflector.reflect("trace1", "agent.note", "task1", evaluation)
    assert reflection.reflection_id
    assert reflection.agent_id == "agent.note"
    assert "0.85" in reflection.reflection_text
    assert len(reflection.action_items) > 0


def test_reflector_failed_task():
    """测试失败任务的反思"""
    reflector = Reflector()
    evaluation = EvaluationResult(
        passed=False,
        score=0.3,
        criteria={"completeness": 0.0},
        suggestions=["修复超时问题"],
    )
    reflection = reflector.reflect("trace1", "agent.note", "task1", evaluation)
    assert "未通过" in reflection.reflection_text
    assert "修复超时问题" in reflection.action_items


@pytest.mark.asyncio
async def test_reflection_engine_full_loop():
    """测试反思引擎完整闭环"""
    engine = ReflectionEngine()
    result = AgentResult(
        task_id="t1",
        agent_id="agent.note",
        status="success",
        output={"reply": "done"},
        latency_ms=200,
    )
    reflection = await engine.evaluate_and_reflect(
        trace_id="trace1",
        agent_id="agent.note",
        task_id="t1",
        agent_result=result,
    )
    assert reflection.evaluation is not None
    assert reflection.evaluation.passed

    stats = engine.get_reflection_stats("agent.note")
    assert stats["total"] == 1
    assert stats["pass_rate"] == 1.0


def test_reflection_stats_trend():
    """测试反思趋势判断"""
    engine = ReflectionEngine()
    # 模拟多次执行，分数逐步提升
    for i, score in enumerate([0.5, 0.6, 0.8]):
        result = AgentResult(
            task_id=f"t{i}",
            agent_id="agent.test",
            status="success" if score > 0.5 else "failure",
            latency_ms=100,
        )
        eval_result = engine.evaluator.evaluate(result)
        eval_result.score = score
        reflection = engine.reflector.reflect("trace", "agent.test", f"t{i}", eval_result)
        engine._reflections.append(reflection)
        engine._agent_reflections.setdefault("agent.test", []).append(reflection)

    stats = engine.get_reflection_stats("agent.test")
    assert stats["avg_score"] > 0


def test_improvement_suggestions():
    """测试改进建议聚合"""
    engine = ReflectionEngine()
    for i in range(5):
        eval_result = EvaluationResult(
            passed=False,
            score=0.3,
            suggestions=["优化响应速度", "增加容错"],
        )
        reflection = engine.reflector.reflect("t", "agent.a", f"task{i}", eval_result)
        engine._reflections.append(reflection)
        engine._agent_reflections.setdefault("agent.a", []).append(reflection)

    suggestions = engine.get_improvement_suggestions("agent.a")
    assert len(suggestions) > 0
    assert "优化响应速度" in suggestions or "增加容错" in suggestions


@pytest.mark.asyncio
async def test_multi_agent_peer_review():
    """测试多 Agent 互评"""
    engine = ReflectionEngine()
    peer_review = MultiAgentPeerReview(engine)
    result = AgentResult(
        task_id="t1",
        agent_id="agent.target",
        status="success",
        output={"reply": "ok"},
        latency_ms=100,
    )
    review = await peer_review.peer_review(
        trace_id="trace1",
        target_agent_id="agent.target",
        task_id="t1",
        agent_result=result,
        reviewer_agent_ids=["agent.a", "agent.b", "agent.c"],
    )
    assert "consensus_score" in review
    assert "individual_reviews" in review
    assert len(review["individual_reviews"]) == 3
    # 不同评审者有不同 profile（strict/standard/lenient），产生不同分数
    scores = [r["score"] for r in review["individual_reviews"]]
    assert len(set(scores)) > 1, "不同评审者应产生不同分数"
