"""性能指标收集系统单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest

from agent_cluster.observability.metrics_collector import MetricsCollector


def test_record_latency():
    """测试延迟记录"""
    mc = MetricsCollector()
    mc.record_latency("agent.note", 150)
    mc.record_latency("agent.note", 250)
    metrics = mc.get_agent_metrics("agent.note")
    assert metrics["avg_latency_ms"] == 200
    assert metrics["total_executions"] == 0  # 只记录延迟不增加执行计数


def test_record_result():
    """测试结果记录"""
    mc = MetricsCollector()
    mc.record_result("agent.note", "success")
    mc.record_result("agent.note", "success")
    mc.record_result("agent.note", "failure")

    metrics = mc.get_agent_metrics("agent.note")
    assert metrics["total_executions"] == 3
    assert metrics["success_rate"] == 2 / 3
    assert metrics["failure_rate"] == 1 / 3


def test_percentile():
    """测试百分位数计算"""
    data = [10, 20, 30, 40, 50]
    assert MetricsCollector._percentile(data, 0.0) == 10
    assert MetricsCollector._percentile(data, 0.5) == 30
    assert MetricsCollector._percentile(data, 1.0) == 50


def test_system_metrics():
    """测试系统级指标"""
    mc = MetricsCollector()
    mc.record_result("agent.a", "success")
    mc.record_result("agent.b", "failure")
    mc.record_latency("agent.a", 100)
    mc.record_latency("agent.b", 200)

    sys_metrics = mc.get_system_metrics()
    assert sys_metrics["active_agents"] == 2
    assert sys_metrics["total_executions"] == 2
    assert sys_metrics["overall_success_rate"] == 0.5


def test_intent_classification_stats():
    """测试意图分类统计"""
    mc = MetricsCollector()
    mc.record_intent_classification("记笔记", "note.create", 0.95)
    mc.record_intent_classification("查笔记", "note.search", 0.85)
    mc.record_intent_classification("abc", "general.fallback", 0.2)

    stats = mc.get_intent_classification_stats()
    assert stats["total_classifications"] == 3
    assert stats["high_confidence_rate"] == round(2 / 3, 3)


def test_dashboard_export():
    """测试 Dashboard 数据导出"""
    mc = MetricsCollector()
    mc.record_result("agent.note", "success")
    dashboard = mc.export_dashboard_data()
    assert "timestamp" in dashboard
    assert "system" in dashboard
    assert "intent_classification" in dashboard
