"""反馈收集与自优化系统单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest

from agent_cluster.core.feedback_loop import FeedbackCollector, SelfOptimizer
from agent_cluster.core.intent_classifier import IntentClassifier


def test_collect_explicit_feedback():
    """测试显式反馈收集"""
    collector = FeedbackCollector()
    fb = collector.collect_explicit(
        trace_id="t1",
        agent_id="agent.note",
        intent="note.create",
        rating=1,
        comment="很好用",
    )
    assert fb.feedback_type == "explicit"
    assert fb.rating == 1
    assert fb.comment == "很好用"


def test_collect_implicit_feedback_positive():
    """测试隐式正向反馈"""
    collector = FeedbackCollector()
    fb = collector.collect_implicit(
        trace_id="t1",
        agent_id="agent.note",
        intent="note.create",
        session_duration_sec=60,
        retry_count=0,
        was_silent=False,
    )
    assert fb.feedback_type == "implicit"
    assert fb.rating > 0


def test_collect_implicit_feedback_negative():
    """测试隐式负向反馈"""
    collector = FeedbackCollector()
    fb = collector.collect_implicit(
        trace_id="t1",
        agent_id="agent.note",
        intent="note.create",
        session_duration_sec=2,
        retry_count=3,
        was_silent=True,
    )
    assert fb.rating < 0


def test_agent_feedback_summary():
    """测试 Agent 反馈摘要"""
    collector = FeedbackCollector()
    collector.collect_explicit("t1", "agent.note", "note.create", 1)
    collector.collect_explicit("t2", "agent.note", "note.search", -1)
    collector.collect_implicit("t3", "agent.note", "note.create", 30, 0, False)

    summary = collector.get_agent_feedback_summary("agent.note")
    assert summary["total"] == 3
    assert summary["explicit_count"] == 2
    assert summary["implicit_count"] == 1


def test_self_optimizer_insufficient_data():
    """测试数据不足时的优化建议"""
    collector = FeedbackCollector()
    optimizer = SelfOptimizer(collector)
    result = optimizer.analyze_agent("agent.note")
    assert result["status"] == "insufficient_data"


def test_self_optimizer_with_data():
    """测试有足够数据时的优化分析"""
    collector = FeedbackCollector()
    optimizer = SelfOptimizer(collector)

    for i in range(5):
        collector.collect_explicit(f"t{i}", "agent.note", "note.create", -1, "不好用")

    result = optimizer.analyze_agent("agent.note")
    assert result["status"] == "analyzed"
    assert len(result["issues"]) > 0
    assert len(result["suggestions"]) > 0


def test_generate_rule_updates():
    """测试规则更新建议生成"""
    collector = FeedbackCollector()
    optimizer = SelfOptimizer(collector)

    # 负面反馈多的 intent
    for i in range(5):
        collector.collect_explicit(f"t{i}", "agent.note", "note.create", -1)
    # 正面反馈多的 intent
    for i in range(5):
        collector.collect_explicit(f"t{i}", "agent.emotion", "emotion.chat", 1)

    classifier = IntentClassifier()
    updates = optimizer.generate_rule_updates(classifier)
    assert len(updates) > 0
    intents = [u["intent"] for u in updates]
    assert "note.create" in intents or "emotion.chat" in intents
