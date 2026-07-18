"""
M10 系统卫士 - 防护引擎单元测试

测试阈值拦截、分级策略、过载限流、告警管理等功能。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
from m10_system_guard.guard_engine import (
    GuardEngine, get_guard_engine,
)
from m10_system_guard.models import (
    GuardLevel, GuardPolicy, GuardAlert, MetricType,
)


class TestGuardEngine:
    """防护引擎测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        GuardEngine._instance = None
        GuardEngine._initialized = False
        self.engine = GuardEngine()

    def test_singleton_pattern(self):
        """测试单例模式."""
        e1 = GuardEngine()
        e2 = GuardEngine()
        assert e1 is e2

    def test_get_guard_engine_function(self):
        """测试全局单例获取函数."""
        import m10_system_guard.guard_engine as ge
        ge._guard_engine_instance = None
        instance = get_guard_engine()
        assert instance is not None
        assert isinstance(instance, GuardEngine)

    def test_initial_policies(self):
        """测试初始防护策略."""
        policies = self.engine.get_all_policies()
        # 应该有 CPU、内存、温度、磁盘 四种策略
        assert MetricType.CPU in policies
        assert MetricType.MEMORY in policies
        assert MetricType.TEMPERATURE in policies
        assert MetricType.DISK in policies
        assert len(policies) == 4

    def test_policy_structure(self):
        """测试策略结构完整性."""
        policy = self.engine.get_policy(MetricType.CPU)
        assert policy is not None
        assert isinstance(policy, GuardPolicy)
        assert policy.info_threshold > 0
        assert policy.warning_threshold > policy.info_threshold
        assert policy.critical_threshold > policy.warning_threshold
        assert policy.emergency_threshold > policy.critical_threshold
        assert policy.enabled is True

    def test_check_all_returns_correct_structure(self):
        """测试 check_all 返回结构."""
        result = self.engine.check_all()
        assert "overall_level" in result
        assert "metrics" in result
        assert "throttling_active" in result
        assert "heavy_tasks_paused" in result
        assert "current_concurrency_limit" in result

    def test_check_metric_cpu(self):
        """测试 CPU 指标检查."""
        result = self.engine.check_metric(MetricType.CPU)
        assert "level" in result
        assert "value" in result
        assert "threshold" in result
        assert "enabled" in result
        assert "message" in result

    def test_check_metric_memory(self):
        """测试内存指标检查."""
        result = self.engine.check_metric(MetricType.MEMORY)
        assert "level" in result
        assert result["value"] >= 0

    def test_current_level_default(self):
        """测试默认防护级别."""
        # 沙盒模式下模拟数据可能触发任意级别
        level = self.engine.get_current_level(MetricType.CPU)
        assert isinstance(level, GuardLevel)

    def test_get_overall_level(self):
        """测试获取总体级别."""
        level = self.engine.get_overall_level()
        assert isinstance(level, GuardLevel)
        assert level in [GuardLevel.INFO, GuardLevel.WARNING, GuardLevel.CRITICAL, GuardLevel.EMERGENCY]

    def test_level_priority_order(self):
        """测试级别优先级顺序."""
        assert self.engine._level_priority(GuardLevel.INFO) == 0
        assert self.engine._level_priority(GuardLevel.WARNING) == 1
        assert self.engine._level_priority(GuardLevel.CRITICAL) == 2
        assert self.engine._level_priority(GuardLevel.EMERGENCY) == 3

    def test_determine_level(self):
        """测试级别判定逻辑."""
        policy = self.engine.get_policy(MetricType.CPU)

        # 低于 info 阈值
        level = self.engine._determine_level(policy.info_threshold - 10, policy)
        assert level == GuardLevel.INFO

        # 在 info 和 warning 之间
        mid_value = (policy.info_threshold + policy.warning_threshold) / 2
        level = self.engine._determine_level(mid_value, policy)
        assert level == GuardLevel.INFO  # info 级别是 >= info_threshold 的

        # 高于 emergency 阈值
        level = self.engine._determine_level(policy.emergency_threshold + 10, policy)
        assert level == GuardLevel.EMERGENCY

    def test_get_alerts_empty(self):
        """测试获取告警（初始可能为空或有少量）."""
        alerts = self.engine.get_alerts(limit=10)
        assert isinstance(alerts, list)

    def test_get_alerts_by_level(self):
        """测试按级别过滤告警."""
        alerts = self.engine.get_alerts(limit=10, level="warning")
        assert isinstance(alerts, list)
        # 所有返回的都应该是 warning 级别
        for alert in alerts:
            assert alert.level == GuardLevel.WARNING

    def test_update_policy(self):
        """测试更新防护策略."""
        # 更新 CPU 策略的警告阈值
        original = self.engine.get_policy(MetricType.CPU)
        original_warning = original.warning_threshold

        success = self.engine.update_policy(MetricType.CPU, warning_threshold=88.0)
        assert success is True

        updated = self.engine.get_policy(MetricType.CPU)
        assert updated.warning_threshold == 88.0

        # 恢复
        self.engine.update_policy(MetricType.CPU, warning_threshold=original_warning)

    def test_update_policy_nonexistent(self):
        """测试更新不存在的策略."""
        success = self.engine.update_policy(MetricType.GPU, warning_threshold=80.0)
        assert success is False

    def test_can_run_heavy_task(self):
        """测试重型任务运行检查."""
        result = self.engine.can_run_heavy_task()
        assert isinstance(result, bool)

    def test_concurrency_limit(self):
        """测试并发限制."""
        limit = self.engine.get_concurrency_limit()
        assert isinstance(limit, int)
        assert limit > 0

    def test_set_base_concurrency(self):
        """测试设置基础并发数."""
        self.engine.set_base_concurrency(20)
        assert self.engine._base_concurrency == 20
        # 重置
        self.engine.set_base_concurrency(10)

    def test_set_base_concurrency_minimum(self):
        """测试基础并发数最小值."""
        self.engine.set_base_concurrency(0)
        assert self.engine._base_concurrency == 1
        # 重置
        self.engine.set_base_concurrency(10)

    def test_acknowledge_alert_not_found(self):
        """测试确认不存在的告警."""
        result = self.engine.acknowledge_alert("nonexistent_id")
        assert result is False

    def test_alert_callback(self):
        """测试告警回调函数."""
        callback_called = []

        def my_callback(alert):
            callback_called.append(alert)

        self.engine.register_alert_callback(my_callback)

        # 触发一次检查（可能产生告警）
        self.engine.check_all()

        # 回调函数应该被正确注册
        assert my_callback in self.engine._on_alert_callbacks

    def test_status_summary(self):
        """测试状态摘要."""
        status = self.engine.get_status_summary()
        assert "overall_level" in status
        assert "metric_levels" in status
        assert "throttling_active" in status
        assert "heavy_tasks_paused" in status
        assert "current_concurrency_limit" in status
        assert "total_alerts" in status
        assert "policies_count" in status

    def test_alert_to_dict(self):
        """测试告警转字典."""
        # 触发一些检查以可能产生告警
        self.engine.check_all()
        alerts = self.engine.get_alerts(limit=5)
        if alerts:
            d = alerts[0].to_dict()
            assert isinstance(d, dict)
            assert "alert_id" in d
            assert "level" in d
            assert "metric_type" in d
            assert "metric_value" in d
            assert "message" in d
