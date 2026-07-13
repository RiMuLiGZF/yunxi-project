"""自适应路由优化器单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest

from agent_cluster.adaptive_router import AdaptiveRouter


def test_register_and_select_single():
    """测试单一路由选择"""
    router = AdaptiveRouter()
    router.register_route("note.create", "agent.note")
    agent, is_explore = router.select_agent("note.create")
    assert agent == "agent.note"
    assert not is_explore


def test_epsilon_greedy_exploration():
    """测试 epsilon-greedy 探索"""
    router = AdaptiveRouter(epsilon=1.0)  # 100% 探索
    router.register_route("intent.a", "agent.a")
    router.register_route("intent.a", "agent.b")
    _, is_explore = router.select_agent("intent.a")
    assert is_explore


def test_utilization_best_agent():
    """测试利用最优 Agent"""
    router = AdaptiveRouter(epsilon=0.0, min_samples=1)
    router.register_route("intent.a", "agent.a")
    router.register_route("intent.a", "agent.b")

    # agent.a 成功率更高
    router.report_result("intent.a", "agent.a", success=True, latency_ms=100, score=1.0)
    router.report_result("intent.a", "agent.b", success=False, latency_ms=5000, score=0.0)

    best, _ = router.select_agent("intent.a")
    assert best == "agent.a"


def test_report_result_updates_stats():
    """测试结果上报更新统计"""
    router = AdaptiveRouter(decay_factor=1.0)  # 无衰减
    router.register_route("intent.x", "agent.x")
    router.report_result("intent.x", "agent.x", success=True, latency_ms=200)
    router.report_result("intent.x", "agent.x", success=True, latency_ms=300)

    stats = router.get_route_stats("intent.x")
    route = stats["routes"][0]
    assert route["success_rate"] == 1.0
    assert route["avg_latency_ms"] == 250.0


def test_decay_factor():
    """测试历史数据衰减"""
    router = AdaptiveRouter(decay_factor=0.5, min_samples=1)
    router.register_route("intent.a", "agent.a")
    router.report_result("intent.a", "agent.a", success=True, latency_ms=100, score=1.0)
    # 衰减后，旧数据权重降低，新数据影响更大
    router.report_result("intent.a", "agent.a", success=False, latency_ms=5000, score=0.0)
    stats = router.get_route_stats("intent.a")
    assert stats["routes"][0]["success_rate"] < 1.0


def test_recommendations():
    """测试路由优化建议"""
    router = AdaptiveRouter(min_samples=2)
    router.register_route("intent.a", "agent.good")
    router.register_route("intent.a", "agent.bad")

    # agent.good 表现远好于 agent.bad
    for _ in range(5):
        router.report_result("intent.a", "agent.good", success=True, latency_ms=100, score=1.0)
    for _ in range(5):
        router.report_result("intent.a", "agent.bad", success=False, latency_ms=5000, score=0.0)

    recs = router.get_recommendations()
    assert len(recs) > 0
    assert recs[0]["type"] == "deprecate_route"
    assert recs[0]["agent"] == "agent.bad"


def test_unknown_intent_fallback():
    """测试未知意图回退到默认 Agent"""
    router = AdaptiveRouter()
    agent, _ = router.select_agent("unknown.intent", default_agent="master_scheduler")
    assert agent == "master_scheduler"
