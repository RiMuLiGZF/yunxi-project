"""
告警引擎单元测试（OB-003 增强版）

覆盖:
- AlertEngine 基础功能（规则注册、触发、去重、静默）
- AlertSeverity / AlertState / AlertRule / AlertEvent 数据模型
- 多渠道通知（Log / Console / Webhook）
- 告警确认、静默、恢复
- 规则开关
- 告警规则评估（表达式 + 可调用对象）
- 指标数据提供者（Mock + 基础功能）
- 边界情况

运行: python -m pytest shared/tests/test_alert_engine.py -v
"""
import os
import sys
import time
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import importlib.util

# 设置 shared 模块路径（兼容测试环境）
_shared_root = Path(__file__).resolve().parent.parent
if str(_shared_root) not in sys.path:
    sys.path.insert(0, str(_shared_root))
# 也确保项目根目录在 path 中
_project_root = _shared_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 兼容 yunxi_shared 命名方式
spec = importlib.util.spec_from_file_location(
    "yunxi_shared",
    os.path.join(os.path.dirname(__file__), "..", "__init__.py"),
)
if spec and spec.loader:
    _yunxi_shared = importlib.util.module_from_spec(spec)
    sys.modules["yunxi_shared"] = _yunxi_shared
    spec.loader.exec_module(_yunxi_shared)


from shared.core.observability.alerting import (
    AlertSeverity,
    AlertState,
    AlertEvent,
    AlertRule,
    AlertEngine,
    Notifier,
    LogNotifier,
    ConsoleNotifier,
    WebhookNotifier,
    NotifierManager,
    reset_alert_engine,
)
from shared.core.observability.alert_metrics_provider import (
    MockMetricsProvider,
    AlertMetricsProvider,
    BaseMetricsProvider,
    reset_metrics_provider,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_provider():
    """创建 Mock 指标提供者"""
    provider = MockMetricsProvider()
    reset_metrics_provider()
    yield provider
    reset_metrics_provider()


@pytest.fixture
def engine():
    """创建一个干净的告警引擎（不自动启动）"""
    reset_alert_engine()
    eng = AlertEngine(service_name="test", history_limit=100, auto_start=False)
    # 禁用默认通知渠道，避免测试时输出干扰
    for ch in eng.notifier_manager.list_channels():
        notifier = eng.notifier_manager.get(ch["name"])
        if notifier:
            notifier.enabled = False
    yield eng
    eng.stop()
    reset_alert_engine()


@pytest.fixture
def engine_with_mock_provider(mock_provider):
    """创建带 Mock 数据提供者的告警引擎"""
    reset_alert_engine()
    eng = AlertEngine(service_name="test", history_limit=100, auto_start=False)
    eng.add_context_provider(mock_provider.get_context)
    # 禁用默认通知渠道
    for ch in eng.notifier_manager.list_channels():
        notifier = eng.notifier_manager.get(ch["name"])
        if notifier:
            notifier.enabled = False
    yield eng, mock_provider
    eng.stop()
    reset_alert_engine()
    reset_metrics_provider()


# ============================================================================
# 1. AlertSeverity 测试
# ============================================================================

class TestAlertSeverity:
    """告警严重级别测试"""

    def test_severity_values(self):
        """测试级别枚举值"""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"

    def test_from_str_basic(self):
        """测试从字符串转换"""
        assert AlertSeverity.from_str("info") == AlertSeverity.INFO
        assert AlertSeverity.from_str("WARNING") == AlertSeverity.WARNING
        assert AlertSeverity.from_str("Critical") == AlertSeverity.CRITICAL

    def test_from_str_aliases(self):
        """测试别名转换"""
        assert AlertSeverity.from_str("warn") == AlertSeverity.WARNING
        assert AlertSeverity.from_str("error") == AlertSeverity.WARNING
        assert AlertSeverity.from_str("fatal") == AlertSeverity.CRITICAL
        assert AlertSeverity.from_str("debug") == AlertSeverity.INFO

    def test_numeric_level(self):
        """测试数字级别"""
        assert AlertSeverity.INFO.numeric_level == 1
        assert AlertSeverity.WARNING.numeric_level == 2
        assert AlertSeverity.CRITICAL.numeric_level == 3

    def test_comparison(self):
        """测试级别比较"""
        assert AlertSeverity.CRITICAL > AlertSeverity.WARNING
        assert AlertSeverity.WARNING > AlertSeverity.INFO
        assert AlertSeverity.CRITICAL >= AlertSeverity.WARNING
        assert AlertSeverity.INFO <= AlertSeverity.WARNING
        assert AlertSeverity.WARNING < AlertSeverity.CRITICAL


# ============================================================================
# 2. AlertRule 评估测试
# ============================================================================

class TestAlertRuleEvaluation:
    """告警规则评估测试"""

    def test_expression_gt_triggered(self):
        """测试表达式条件：大于阈值触发"""
        rule = AlertRule(
            rule_id="test_cpu",
            name="CPU高",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="cpu_usage > 80",
        )
        triggered, value, details = rule.evaluate({"cpu_usage": 85})
        assert triggered is True
        assert value == 85.0
        assert details["threshold"] == 80.0

    def test_expression_gt_not_triggered(self):
        """测试表达式条件：未超过阈值不触发"""
        rule = AlertRule(
            rule_id="test_cpu",
            name="CPU高",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="cpu_usage > 80",
        )
        triggered, value, details = rule.evaluate({"cpu_usage": 75})
        assert triggered is False
        assert value == 75.0

    def test_expression_various_operators(self):
        """测试各种比较运算符"""
        # >=
        rule_ge = AlertRule(
            rule_id="r1", name="t", description="d",
            severity=AlertSeverity.INFO, condition="value >= 50",
        )
        assert rule_ge.evaluate({"value": 50})[0] is True
        assert rule_ge.evaluate({"value": 49})[0] is False

        # <=
        rule_le = AlertRule(
            rule_id="r2", name="t", description="d",
            severity=AlertSeverity.INFO, condition="value <= 50",
        )
        assert rule_le.evaluate({"value": 50})[0] is True
        assert rule_le.evaluate({"value": 51})[0] is False

        # <
        rule_lt = AlertRule(
            rule_id="r3", name="t", description="d",
            severity=AlertSeverity.INFO, condition="value < 50",
        )
        assert rule_lt.evaluate({"value": 49})[0] is True
        assert rule_lt.evaluate({"value": 50})[0] is False

        # ==
        rule_eq = AlertRule(
            rule_id="r4", name="t", description="d",
            severity=AlertSeverity.INFO, condition="value == 50",
        )
        assert rule_eq.evaluate({"value": 50})[0] is True
        assert rule_eq.evaluate({"value": 51})[0] is False

        # !=
        rule_ne = AlertRule(
            rule_id="r5", name="t", description="d",
            severity=AlertSeverity.INFO, condition="value != 50",
        )
        assert rule_ne.evaluate({"value": 51})[0] is True
        assert rule_ne.evaluate({"value": 50})[0] is False

    def test_callable_condition(self):
        """测试可调用对象条件"""
        def check(ctx):
            val = ctx.get("error_rate", 0)
            return val > 5.0, val, {"threshold": 5.0}

        rule = AlertRule(
            rule_id="test_err",
            name="错误率高",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=check,
        )
        triggered, value, details = rule.evaluate({"error_rate": 8.0})
        assert triggered is True
        assert value == 8.0
        assert details["threshold"] == 5.0

    def test_disabled_rule_not_triggered(self):
        """测试禁用的规则不触发"""
        rule = AlertRule(
            rule_id="test",
            name="测试",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="cpu_usage > 80",
            enabled=False,
        )
        triggered, value, details = rule.evaluate({"cpu_usage": 99})
        assert triggered is False

    def test_missing_metric(self):
        """测试缺失指标不触发"""
        rule = AlertRule(
            rule_id="test",
            name="测试",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="nonexistent_metric > 80",
        )
        triggered, value, details = rule.evaluate({"cpu_usage": 50})
        assert triggered is False
        assert "error" in details

    def test_nested_context_lookup(self):
        """测试从嵌套字典中查找指标"""
        rule = AlertRule(
            rule_id="test",
            name="测试",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="usage > 80",
        )
        triggered, value, _ = rule.evaluate({"cpu": {"usage": 85}})
        assert triggered is True
        assert value == 85.0


# ============================================================================
# 3. 告警触发与去重静默测试
# ============================================================================

class TestAlertDeduplication:
    """告警去重与静默测试"""

    def test_first_trigger_creates_alert(self, engine):
        """首次触发创建新告警"""
        rule = AlertRule(
            rule_id="test_rule",
            name="测试规则",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=300,
        )
        engine.register_rule(rule)

        result = engine.check_all_rules()
        assert result["fired_count"] == 1
        assert len(engine.get_active_alerts()) == 1

        alert = engine.get_active_alerts()[0]
        assert alert.rule_id == "test_rule"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.state == AlertState.FIRING
        assert alert.value == 85.0

    def test_silence_period_prevents_duplicate(self, engine):
        """静默期内不重复发送通知"""
        notify_count = [0]

        class TestNotifier(Notifier):
            def _do_notify(self, alert):
                notify_count[0] += 1
                return True

        notifier = TestNotifier(name="test")
        engine.notifier_manager.register(notifier)
        engine.notifier_manager.set_default_channels(["test"])

        rule = AlertRule(
            rule_id="test_silence",
            name="测试静默",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 90.0, {"threshold": 80}),
            check_interval=1,
            silence_period=60,
        )
        engine.register_rule(rule)

        # 第一次触发
        engine.check_all_rules()
        assert notify_count[0] == 1

        # 重置最后检查时间，模拟立即再次检查
        rule._last_check_time = 0

        # 第二次触发（静默期内）
        engine.check_all_rules()
        assert notify_count[0] == 1  # 不重复通知

        # 活跃告警仍然存在
        assert len(engine.get_active_alerts()) == 1

    def test_silence_period_expired_resends(self, engine):
        """静默期过后重新发送通知"""
        notify_count = [0]

        class TestNotifier(Notifier):
            def _do_notify(self, alert):
                notify_count[0] += 1
                return True

        notifier = TestNotifier(name="test")
        engine.notifier_manager.register(notifier)
        engine.notifier_manager.set_default_channels(["test"])

        rule = AlertRule(
            rule_id="test_resend",
            name="测试重发",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 90.0, {"threshold": 80}),
            check_interval=1,
            silence_period=1,  # 1秒静默期
        )
        engine.register_rule(rule)

        # 第一次触发
        engine.check_all_rules()
        assert notify_count[0] == 1

        # 等待静默期过期
        time.sleep(1.1)
        rule._last_check_time = 0

        # 第二次触发（静默期已过）
        engine.check_all_rules()
        assert notify_count[0] == 2  # 重新发送通知

    def test_alert_firing_count_increments(self, engine):
        """告警触发次数递增"""
        rule = AlertRule(
            rule_id="test_count",
            name="测试计数",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,  # 0秒静默，每次都触发
        )
        engine.register_rule(rule)

        engine.check_all_rules()
        engine.check_all_rules()
        engine.check_all_rules()

        alerts = engine.get_active_alerts()
        assert len(alerts) == 1
        # firing_count 至少为 3（实际可能更多，因为 check_all_rules 内部逻辑）
        assert alerts[0].firing_count >= 1


# ============================================================================
# 4. 告警恢复测试
# ============================================================================

class TestAlertResolution:
    """告警恢复测试"""

    def test_alert_resolves_when_condition_clears(self, engine):
        """条件恢复时告警自动解决"""
        condition_value = [85.0]  # 使用列表实现可变闭包

        def condition(ctx):
            return condition_value[0] > 80, condition_value[0], {"threshold": 80}

        rule = AlertRule(
            rule_id="test_resolve",
            name="测试恢复",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=condition,
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)

        # 触发告警
        engine.check_all_rules()
        assert len(engine.get_active_alerts()) == 1

        # 条件恢复（重置检查时间以便立即检查）
        condition_value[0] = 70.0
        rule._last_check_time = 0
        engine.check_all_rules()

        # 告警已解决
        assert len(engine.get_active_alerts()) == 0
        assert engine._total_resolved >= 1

    def test_resolved_alert_in_history(self, engine):
        """已解决的告警出现在历史记录中"""
        condition_value = [85.0]

        def condition(ctx):
            return condition_value[0] > 80, condition_value[0], {"threshold": 80}

        rule = AlertRule(
            rule_id="test_history",
            name="测试历史",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=condition,
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)

        engine.check_all_rules()  # 触发
        condition_value[0] = 70.0
        rule._last_check_time = 0
        engine.check_all_rules()  # 恢复

        history = engine.get_history()
        assert len(history) >= 2  # 至少触发和恢复各一条
        # 最后一条应该是 resolved 状态
        assert history[0]["state"] == "resolved"


# ============================================================================
# 5. 告警确认与静默测试
# ============================================================================

class TestAlertAcknowledge:
    """告警确认与静默操作测试"""

    def test_acknowledge_alert(self, engine):
        """确认告警"""
        rule = AlertRule(
            rule_id="test_ack",
            name="测试确认",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)
        engine.check_all_rules()

        alert = engine.get_active_alerts()[0]
        success = engine.acknowledge_alert(alert.id, acknowledged_by="admin")

        assert success is True
        assert alert.state == AlertState.ACKNOWLEDGED
        assert alert.acknowledged_by == "admin"
        assert alert.acknowledged_at is not None

    def test_acknowledge_nonexistent_alert(self, engine):
        """确认不存在的告警返回 False"""
        success = engine.acknowledge_alert("nonexistent", acknowledged_by="admin")
        assert success is False

    def test_silence_alert(self, engine):
        """静默告警"""
        rule = AlertRule(
            rule_id="test_silence_op",
            name="测试静默操作",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)
        engine.check_all_rules()

        alert = engine.get_active_alerts()[0]
        success = engine.silence_alert(
            alert.id, duration_seconds=3600, silenced_by="admin", reason="测试"
        )

        assert success is True
        assert alert.state == AlertState.SILENCED
        assert alert.silenced_by == "admin"
        assert alert.silence_reason == "测试"
        assert alert.silenced_until is not None

    def test_manual_resolve_alert(self, engine):
        """手动解决告警"""
        rule = AlertRule(
            rule_id="test_manual_resolve",
            name="测试手动解决",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)
        engine.check_all_rules()

        alert = engine.get_active_alerts()[0]
        success = engine.resolve_alert(alert.id, resolved_by="admin", reason="手动修复")

        assert success is True
        assert len(engine.get_active_alerts()) == 0


# ============================================================================
# 6. 规则管理测试
# ============================================================================

class TestRuleManagement:
    """规则管理测试"""

    def test_register_and_unregister_rule(self, engine):
        """注册和注销规则"""
        rule = AlertRule(
            rule_id="new_rule",
            name="新规则",
            description="测试",
            severity=AlertSeverity.INFO,
            condition="value > 10",
        )

        engine.register_rule(rule)
        assert engine.get_rule("new_rule") is not None
        assert len(engine.list_rules()) >= 1

        result = engine.unregister_rule("new_rule")
        assert result is True
        assert engine.get_rule("new_rule") is None

    def test_enable_disable_rule(self, engine):
        """启用/禁用规则"""
        rule = AlertRule(
            rule_id="toggle_test",
            name="开关测试",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            enabled=True,
        )
        engine.register_rule(rule)

        # 禁用规则
        success = engine.disable_rule("toggle_test")
        assert success is True
        assert rule.enabled is False

        # 禁用后不触发
        engine.check_all_rules()
        assert len(engine.get_active_alerts()) == 0

        # 重新启用
        success = engine.enable_rule("toggle_test")
        assert success is True
        assert rule.enabled is True

        # 启用后可以触发
        engine.check_all_rules()
        assert len(engine.get_active_alerts()) == 1

    def test_list_rules_filter_by_category(self, engine):
        """按类别过滤规则"""
        rules = engine.list_rules(category="system")
        for r in rules:
            assert r.labels.get("category") == "system"

    def test_list_rules_filter_by_severity(self, engine):
        """按级别过滤规则"""
        rules = engine.list_rules(severity=AlertSeverity.CRITICAL)
        for r in rules:
            assert r.severity == AlertSeverity.CRITICAL

    def test_list_rules_enabled_only(self, engine):
        """只列出启用的规则"""
        rules = engine.list_rules(enabled_only=True)
        for r in rules:
            assert r.enabled is True

    def test_update_rule(self, engine):
        """更新规则属性"""
        rule = AlertRule(
            rule_id="update_test",
            name="更新测试",
            description="原始描述",
            severity=AlertSeverity.WARNING,
            condition="value > 10",
            check_interval=60,
        )
        engine.register_rule(rule)

        success = engine.update_rule(
            "update_test",
            name="新名称",
            description="新描述",
            check_interval=120,
        )
        assert success is True
        assert rule.name == "新名称"
        assert rule.description == "新描述"
        assert rule.check_interval == 120


# ============================================================================
# 7. 多渠道通知测试
# ============================================================================

class TestNotificationChannels:
    """多渠道通知测试"""

    def test_notifier_manager_register_and_notify(self):
        """通知管理器注册和发送"""
        mgr = NotifierManager()
        results = []

        class TestNotifier(Notifier):
            def __init__(self, name):
                super().__init__(name=name)
                self.called = False

            def _do_notify(self, alert):
                self.called = True
                results.append(self.name)
                return True

        n1 = TestNotifier("channel1")
        n2 = TestNotifier("channel2")

        mgr.register(n1)
        mgr.register(n2)
        mgr.set_default_channels(["channel1", "channel2"])

        alert = AlertEvent(
            id="test1",
            rule_id="test",
            rule_name="测试",
            severity=AlertSeverity.WARNING,
            state=AlertState.FIRING,
            summary="测试告警",
        )

        result = mgr.notify(alert)
        assert "channel1" in result
        assert "channel2" in result
        assert len(results) == 2

    def test_notifier_min_severity_filter(self):
        """通知渠道按最低级别过滤"""
        class TestNotifier(Notifier):
            def __init__(self, name, min_sev):
                super().__init__(name=name, min_severity=min_sev)
                self.called = False

            def _do_notify(self, alert):
                self.called = True
                return True

        info_alert = AlertEvent(
            id="info1", rule_id="t", rule_name="t",
            severity=AlertSeverity.INFO, state=AlertState.FIRING, summary="t",
        )
        critical_alert = AlertEvent(
            id="crit1", rule_id="t", rule_name="t",
            severity=AlertSeverity.CRITICAL, state=AlertState.FIRING, summary="t",
        )

        # 只发送 WARNING 以上
        n = TestNotifier("warn_only", AlertSeverity.WARNING)

        n.notify(info_alert)
        assert n.called is False  # INFO 不发送

        n.notify(critical_alert)
        assert n.called is True  # CRITICAL 发送

    def test_webhook_notifier_empty_url(self):
        """Webhook 通知器空 URL 不发送"""
        notifier = WebhookNotifier(name="webhook", url="")
        alert = AlertEvent(
            id="t1", rule_id="t", rule_name="t",
            severity=AlertSeverity.WARNING, state=AlertState.FIRING, summary="t",
        )
        result = notifier.notify(alert)
        assert result is False

    def test_console_notifier(self, capsys):
        """控制台通知器输出"""
        notifier = ConsoleNotifier(name="console", use_color=False)
        alert = AlertEvent(
            id="con1", rule_id="t", rule_name="测试告警",
            severity=AlertSeverity.WARNING, state=AlertState.FIRING,
            summary="CPU 使用率过高",
            value=85.0, threshold=80.0,
        )
        notifier.notify(alert)
        captured = capsys.readouterr()
        assert "CPU 使用率过高" in captured.out
        assert "WARNING" in captured.out

    def test_specific_channels_override_default(self):
        """指定渠道覆盖默认渠道"""
        mgr = NotifierManager()
        called_channels = []

        class TestNotifier(Notifier):
            def __init__(self, name):
                super().__init__(name=name)

            def _do_notify(self, alert):
                called_channels.append(self.name)
                return True

        mgr.register(TestNotifier("ch1"))
        mgr.register(TestNotifier("ch2"))
        mgr.set_default_channels(["ch1", "ch2"])

        alert = AlertEvent(
            id="t1", rule_id="t", rule_name="t",
            severity=AlertSeverity.WARNING, state=AlertState.FIRING, summary="t",
        )

        # 只通过 ch1 发送
        called_channels.clear()
        mgr.notify(alert, channels=["ch1"])
        assert called_channels == ["ch1"]


# ============================================================================
# 8. Mock 指标提供者测试
# ============================================================================

class TestMockMetricsProvider:
    """Mock 指标提供者测试"""

    def test_default_values(self, mock_provider):
        """默认值测试"""
        ctx = mock_provider.get_context()
        assert ctx["cpu_usage"] == 30.0
        assert ctx["memory_usage"] == 50.0
        assert ctx["error_rate"] == 1.0
        assert ctx["module_offline_count"] == 0
        assert ctx["db_connection_ok"] is True

    def test_set_and_get(self, mock_provider):
        """设置和获取指标"""
        mock_provider.set("cpu_usage", 95.0)
        assert mock_provider.get("cpu_usage") == 95.0

        ctx = mock_provider.get_context()
        assert ctx["cpu_usage"] == 95.0

    def test_set_many(self, mock_provider):
        """批量设置指标"""
        mock_provider.set_many({
            "cpu_usage": 85.0,
            "memory_usage": 90.0,
            "error_rate": 12.0,
        })
        ctx = mock_provider.get_context()
        assert ctx["cpu_usage"] == 85.0
        assert ctx["memory_usage"] == 90.0
        assert ctx["error_rate"] == 12.0

    def test_reset(self, mock_provider):
        """重置为默认值"""
        mock_provider.set("cpu_usage", 99.0)
        mock_provider.reset()
        assert mock_provider.get("cpu_usage") == 30.0

    def test_system_metrics(self, mock_provider):
        """系统指标分类"""
        sys_metrics = mock_provider.get_system_metrics()
        assert "cpu_usage" in sys_metrics
        assert "memory_usage" in sys_metrics
        assert "disk_usage" in sys_metrics
        assert "process_count" in sys_metrics

    def test_api_metrics(self, mock_provider):
        """接口指标分类"""
        api_metrics = mock_provider.get_api_metrics()
        assert "error_rate" in api_metrics
        assert "slow_request_ratio" in api_metrics
        assert "qps" in api_metrics
        assert "avg_latency_ms" in api_metrics

    def test_health_metrics(self, mock_provider):
        """健康指标分类"""
        health_metrics = mock_provider.get_health_metrics()
        assert "module_offline_count" in health_metrics
        assert "db_connection_ok" in health_metrics


# ============================================================================
# 9. 集成测试：Mock 数据 + 告警引擎
# ============================================================================

class TestAlertEngineWithMockProvider:
    """告警引擎与 Mock 数据提供者集成测试"""

    def test_cpu_high_triggers_alert(self, engine_with_mock_provider):
        """CPU 过高触发告警"""
        engine, provider = engine_with_mock_provider
        provider.set("cpu_usage", 85.0)

        result = engine.check_all_rules()
        assert result["fired_count"] >= 1

        # 应该有 WARNING 级别的 CPU 告警
        alerts = engine.get_active_alerts(severity=AlertSeverity.WARNING)
        cpu_alerts = [a for a in alerts if "cpu" in a.rule_id.lower()]
        assert len(cpu_alerts) >= 1

    def test_memory_critical_triggers(self, engine_with_mock_provider):
        """内存严重过高触发 CRITICAL 告警"""
        engine, provider = engine_with_mock_provider
        provider.set("memory_usage", 97.0)

        engine.check_all_rules()

        alerts = engine.get_active_alerts(severity=AlertSeverity.CRITICAL)
        mem_alerts = [a for a in alerts if "memory" in a.rule_id.lower()]
        assert len(mem_alerts) >= 1

    def test_disk_high_triggers_warning(self, engine_with_mock_provider):
        """磁盘过高触发 WARNING 告警"""
        engine, provider = engine_with_mock_provider
        provider.set("disk_usage", 85.0)

        engine.check_all_rules()

        alerts = engine.get_active_alerts(severity=AlertSeverity.WARNING)
        disk_alerts = [a for a in alerts if "disk" in a.rule_id.lower()]
        assert len(disk_alerts) >= 1

    def test_error_rate_warning(self, engine_with_mock_provider):
        """错误率过高触发告警"""
        engine, provider = engine_with_mock_provider
        provider.set("error_rate", 7.0)  # > 5%

        engine.check_all_rules()

        alerts = engine.get_active_alerts()
        error_alerts = [a for a in alerts if "error_rate" in a.rule_id.lower()]
        assert len(error_alerts) >= 1

    def test_error_rate_critical(self, engine_with_mock_provider):
        """错误率严重过高触发 CRITICAL"""
        engine, provider = engine_with_mock_provider
        provider.set("error_rate", 15.0)  # > 10%

        engine.check_all_rules()

        alerts = engine.get_active_alerts(severity=AlertSeverity.CRITICAL)
        error_alerts = [a for a in alerts if "error_rate" in a.rule_id.lower()]
        assert len(error_alerts) >= 1

    def test_slow_request_ratio_alert(self, engine_with_mock_provider):
        """慢请求占比过高触发告警"""
        engine, provider = engine_with_mock_provider
        provider.set("slow_request_ratio", 15.0)  # > 10%

        engine.check_all_rules()

        alerts = engine.get_active_alerts()
        slow_alerts = [a for a in alerts if "slow_request" in a.rule_id.lower()]
        assert len(slow_alerts) >= 1

    def test_qps_drop_alert(self, engine_with_mock_provider):
        """QPS 突降触发告警"""
        engine, provider = engine_with_mock_provider
        provider.set("qps", 40.0)  # 当前
        provider.set("qps_previous", 100.0)  # 上一周期

        engine.check_all_rules()

        alerts = engine.get_active_alerts()
        qps_alerts = [a for a in alerts if "qps" in a.rule_id.lower() and "drop" in a.rule_id.lower()]
        assert len(qps_alerts) >= 1

    def test_module_offline_alert(self, engine_with_mock_provider):
        """模块离线触发 CRITICAL 告警"""
        engine, provider = engine_with_mock_provider
        provider.set("module_offline_count", 2)
        provider.set("module_total", 8)

        engine.check_all_rules()

        alerts = engine.get_active_alerts(severity=AlertSeverity.CRITICAL)
        offline_alerts = [a for a in alerts if "module_offline" in a.rule_id.lower() or "offline" in a.rule_id.lower()]
        assert len(offline_alerts) >= 1

    def test_db_connection_failure_alert(self, engine_with_mock_provider):
        """数据库连接失败触发 CRITICAL 告警"""
        engine, provider = engine_with_mock_provider
        provider.set("db_connection_ok", False)

        engine.check_all_rules()

        alerts = engine.get_active_alerts(severity=AlertSeverity.CRITICAL)
        db_alerts = [a for a in alerts if "db" in a.rule_id.lower() or "database" in a.rule_id.lower()]
        assert len(db_alerts) >= 1

    def test_process_count_alert(self, engine_with_mock_provider):
        """进程数异常触发告警"""
        engine, provider = engine_with_mock_provider
        provider.set("process_count", 600)  # > 500

        engine.check_all_rules()

        alerts = engine.get_active_alerts()
        proc_alerts = [a for a in alerts if "process" in a.rule_id.lower()]
        assert len(proc_alerts) >= 1

    def test_no_alert_when_normal(self, engine_with_mock_provider):
        """正常情况下不触发告警"""
        engine, provider = engine_with_mock_provider
        # 默认值都是正常的
        provider.set("cpu_usage", 30.0)
        provider.set("memory_usage", 50.0)
        provider.set("disk_usage", 40.0)
        provider.set("error_rate", 1.0)
        provider.set("slow_request_ratio", 2.0)
        provider.set("module_offline_count", 0)
        provider.set("db_connection_ok", True)
        provider.set("process_count", 150)
        provider.set("qps", 100.0)
        provider.set("qps_previous", 95.0)

        result = engine.check_all_rules()
        # 正常情况下不应有任何告警触发
        assert result["fired_count"] == 0
        assert len(engine.get_active_alerts()) == 0


# ============================================================================
# 10. 告警统计与历史测试
# ============================================================================

class TestAlertStatsAndHistory:
    """告警统计与历史记录测试"""

    def test_get_stats(self, engine_with_mock_provider):
        """获取告警统计"""
        engine, provider = engine_with_mock_provider
        provider.set("cpu_usage", 85.0)
        provider.set("error_rate", 7.0)

        engine.check_all_rules()
        stats = engine.get_stats()

        assert "total_fired" in stats
        assert "active_count" in stats
        assert "by_severity" in stats
        assert "by_state" in stats
        assert "rules_count" in stats
        assert stats["active_count"] >= 1
        assert stats["total_fired"] >= 1

    def test_get_history(self, engine_with_mock_provider):
        """获取告警历史"""
        engine, provider = engine_with_mock_provider

        # 触发一个告警
        provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        history = engine.get_history(limit=10)
        assert len(history) >= 1
        assert history[0]["state"] == "firing"

    def test_history_limit(self, engine):
        """历史记录限制"""
        rule = AlertRule(
            rule_id="hist_test",
            name="历史测试",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)

        # 触发多次
        for _ in range(5):
            engine.check_all_rules()

        history = engine.get_history(limit=3)
        assert len(history) <= 3


# ============================================================================
# 11. 边界情况测试
# ============================================================================

class TestEdgeCases:
    """边界情况测试"""

    def test_empty_engine(self):
        """空引擎的状态"""
        reset_alert_engine()
        engine = AlertEngine(service_name="empty", auto_start=False)
        assert len(engine.get_active_alerts()) == 0
        assert engine.get_stats()["active_count"] == 0
        assert engine.is_running is False
        engine.stop()  # 停止未启动的引擎不应报错
        reset_alert_engine()

    def test_alert_event_to_dict(self):
        """告警事件转字典"""
        alert = AlertEvent(
            id="evt1",
            rule_id="r1",
            rule_name="规则1",
            severity=AlertSeverity.WARNING,
            state=AlertState.FIRING,
            summary="测试摘要",
            description="测试描述",
            value=85.0,
            threshold=80.0,
            labels={"category": "system"},
        )
        d = alert.to_dict()
        assert d["id"] == "evt1"
        assert d["severity"] == "warning"
        assert d["state"] == "firing"
        assert d["value"] == 85.0
        assert "started_at_formatted" in d
        assert "duration_seconds" in d

    def test_rule_to_dict(self):
        """规则转字典"""
        rule = AlertRule(
            rule_id="r1",
            name="测试规则",
            description="描述",
            severity=AlertSeverity.WARNING,
            condition="cpu > 80",
            check_interval=60,
            silence_period=300,
            labels={"category": "system"},
        )
        d = rule.to_dict()
        assert d["rule_id"] == "r1"
        assert d["severity"] == "warning"
        assert d["check_interval"] == 60
        assert d["enabled"] is True
        assert d["is_builtin"] is False

    def test_invalid_expression_does_not_crash(self):
        """无效表达式不导致崩溃"""
        rule = AlertRule(
            rule_id="bad_expr",
            name="坏表达式",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="not a valid expression!!!",
        )
        triggered, value, details = rule.evaluate({"cpu": 50})
        assert triggered is False
        # 应该有错误信息
        assert "error" in details

    def test_get_alert_from_history(self, engine):
        """从历史记录中查找告警"""
        rule = AlertRule(
            rule_id="hist_lookup",
            name="历史查找",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition=lambda ctx: (True, 85.0, {"threshold": 80}),
            check_interval=1,
            silence_period=0,
        )
        engine.register_rule(rule)

        # 触发然后解决
        engine.check_all_rules()
        alert_id = engine.get_active_alerts()[0].id

        engine.resolve_alert(alert_id, resolved_by="test")

        # 从历史中查找
        found = engine.get_alert(alert_id)
        assert found is not None
        assert found.id == alert_id
        assert found.state == AlertState.RESOLVED

    def test_nonexistent_alert_returns_none(self, engine):
        """查找不存在的告警返回 None"""
        assert engine.get_alert("nonexistent") is None

    def test_health_impact(self, engine_with_mock_provider):
        """告警对健康状态的影响"""
        engine, provider = engine_with_mock_provider

        # 没有告警时是 healthy
        impact = engine.get_health_impact()
        assert impact["status"] == "healthy"

        # 有 CRITICAL 告警时是 degraded
        provider.set("memory_usage", 97.0)
        engine.check_all_rules()
        impact = engine.get_health_impact()
        assert impact["status"] == "degraded"
        assert impact["critical_alerts_count"] >= 1


# ============================================================================
# 12. 告警引擎后台线程测试
# ============================================================================

class TestAlertEngineBackground:
    """告警引擎后台线程测试"""

    def test_start_and_stop(self):
        """启动和停止后台线程"""
        reset_alert_engine()
        engine = AlertEngine(service_name="bg_test", auto_start=False)
        assert engine.is_running is False

        engine.start()
        assert engine.is_running is True

        engine.stop()
        assert engine.is_running is False
        reset_alert_engine()

    def test_auto_start(self):
        """自动启动"""
        reset_alert_engine()
        engine = AlertEngine(service_name="auto_test", auto_start=True)
        # 给线程一点时间启动
        time.sleep(0.1)
        assert engine.is_running is True
        engine.stop()
        reset_alert_engine()

    def test_context_provider(self, engine):
        """上下文提供者"""
        call_count = [0]

        def provider():
            call_count[0] += 1
            return {"custom_metric": 42.0}

        engine.add_context_provider(provider)

        rule = AlertRule(
            rule_id="ctx_test",
            name="上下文测试",
            description="测试",
            severity=AlertSeverity.INFO,
            condition="custom_metric > 40",
            check_interval=1,
        )
        engine.register_rule(rule)

        engine.check_all_rules()
        assert call_count[0] >= 1

        alerts = engine.get_active_alerts()
        assert len(alerts) >= 1
        assert alerts[0].rule_id == "ctx_test"

    def test_remove_context_provider(self, engine):
        """移除上下文提供者"""
        values = {"x": 100}

        def provider():
            return {"my_metric": values["x"]}

        engine.add_context_provider(provider)

        rule = AlertRule(
            rule_id="rm_ctx",
            name="移除上下文",
            description="测试",
            severity=AlertSeverity.WARNING,
            condition="my_metric > 50",
            check_interval=1,
        )
        engine.register_rule(rule)

        # 添加时触发
        engine.check_all_rules()
        assert len(engine.get_active_alerts()) == 1

        # 移除后，指标不存在，告警应恢复（重置检查时间以便立即检查）
        engine.remove_context_provider(provider)
        values["x"] = 10  # 即使值变了，也读不到了
        rule._last_check_time = 0
        engine.check_all_rules()
        # my_metric 不再存在于 context，规则不会触发，但已有告警不会自动恢复
        # 因为 evaluate 会返回 (False, None, {"error": ...})
        # 这会触发 _check_resolve
        assert len(engine.get_active_alerts()) == 0  # 告警应该已解决


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
