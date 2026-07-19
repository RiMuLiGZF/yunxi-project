"""
告警引擎单元测试（OB-003 P1级）

测试覆盖：
- 告警规则触发（系统资源类、接口性能类、业务健康类）
- 告警去重静默机制
- 告警级别判断
- 多渠道通知
- 告警确认
- 规则开关
- 边界情况
- Mock 数据源集成

所有测试使用 MockMetricsProvider，不依赖真实环境。
"""

import sys
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 项目路径设置
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 在导入 shared 之前设置环境变量
os.environ.setdefault("YUNXI_ENV", "test")

from shared.core.observability import (
    AlertEngine,
    AlertSeverity,
    AlertState,
    AlertRule,
    AlertEvent,
    LogNotifier,
    ConsoleNotifier,
    WebhookNotifier,
    NotifierManager,
    reset_alert_engine,
)
from shared.core.observability.alert_metrics_provider import (
    MockMetricsProvider,
    reset_metrics_provider,
    set_metrics_provider,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_provider():
    """创建 Mock 指标提供者"""
    provider = MockMetricsProvider()
    set_metrics_provider(provider)
    yield provider
    reset_metrics_provider()


@pytest.fixture
def engine(mock_provider):
    """创建告警引擎实例，使用 Mock 数据源"""
    reset_alert_engine()
    eng = AlertEngine(service_name="test", auto_start=False, history_limit=100)
    # 注册 mock 数据源
    eng.add_context_provider(mock_provider.get_context)
    yield eng
    eng.stop()
    reset_alert_engine()


@pytest.fixture
def engine_with_notifiers(engine):
    """创建带通知渠道的告警引擎"""
    # 清理默认通知器，使用 mock
    engine.notifier_manager = NotifierManager()
    return engine


# ============================================================================
# 1. 告警规则触发测试
# ============================================================================

class TestAlertRuleFiring:
    """告警规则触发测试"""

    def test_cpu_high_warning_triggers(self, engine, mock_provider):
        """CPU 使用率 > 80% 触发 WARNING 告警"""
        mock_provider.set("cpu_usage", 85.0)
        result = engine.check_all_rules()

        assert result["fired_count"] >= 1
        active = engine.get_active_alerts()
        cpu_alerts = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_alerts) == 1
        assert cpu_alerts[0].severity == AlertSeverity.WARNING
        assert cpu_alerts[0].state == AlertState.FIRING

    def test_cpu_high_critical_triggers(self, engine, mock_provider):
        """CPU 使用率 > 90% 同时触发 WARNING 和 CRITICAL"""
        mock_provider.set("cpu_usage", 95.0)
        result = engine.check_all_rules()

        assert result["fired_count"] >= 2
        active = engine.get_active_alerts()
        warning_alerts = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        critical_alerts = [a for a in active if a.rule_id == "system_cpu_high_critical"]
        assert len(warning_alerts) == 1
        assert len(critical_alerts) == 1
        assert critical_alerts[0].severity == AlertSeverity.CRITICAL

    def test_memory_high_warning_triggers(self, engine, mock_provider):
        """内存使用率 > 85% 触发 WARNING"""
        mock_provider.set("memory_usage", 90.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        mem_alerts = [a for a in active if a.rule_id == "system_memory_high_warning"]
        assert len(mem_alerts) == 1
        assert mem_alerts[0].severity == AlertSeverity.WARNING

    def test_memory_high_critical_triggers(self, engine, mock_provider):
        """内存使用率 > 95% 触发 CRITICAL"""
        mock_provider.set("memory_usage", 97.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        mem_critical = [a for a in active if a.rule_id == "system_memory_high_critical"]
        assert len(mem_critical) == 1
        assert mem_critical[0].severity == AlertSeverity.CRITICAL

    def test_disk_high_warning_triggers(self, engine, mock_provider):
        """磁盘使用率 > 80% 触发 WARNING"""
        mock_provider.set("disk_usage", 85.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        disk_alerts = [a for a in active if a.rule_id == "system_disk_high_warning"]
        assert len(disk_alerts) == 1

    def test_disk_free_percent_critical_triggers(self, engine, mock_provider):
        """磁盘剩余空间 < 10% 触发 CRITICAL"""
        mock_provider.set("disk_usage", 92.0)  # 剩余 8%
        engine.check_all_rules()

        active = engine.get_active_alerts()
        disk_free_alerts = [a for a in active if a.rule_id == "system_disk_free_percent_critical"]
        assert len(disk_free_alerts) == 1
        assert disk_free_alerts[0].severity == AlertSeverity.CRITICAL

    def test_process_count_warning_triggers(self, engine, mock_provider):
        """进程数量超过阈值触发 WARNING"""
        mock_provider.set("process_count", 600)  # 默认阈值 500
        engine.check_all_rules()

        active = engine.get_active_alerts()
        proc_alerts = [a for a in active if a.rule_id == "system_process_count_warning"]
        assert len(proc_alerts) == 1
        assert proc_alerts[0].severity == AlertSeverity.WARNING

    def test_error_rate_warning_triggers(self, engine, mock_provider):
        """错误率 > 5% 触发 WARNING"""
        mock_provider.set("error_rate", 7.5)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        err_alerts = [a for a in active if a.rule_id == "api_error_rate_warning"]
        assert len(err_alerts) == 1
        assert err_alerts[0].severity == AlertSeverity.WARNING

    def test_error_rate_critical_triggers(self, engine, mock_provider):
        """错误率 > 10% 触发 CRITICAL"""
        mock_provider.set("error_rate", 15.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        err_critical = [a for a in active if a.rule_id == "api_error_rate_critical"]
        assert len(err_critical) == 1
        assert err_critical[0].severity == AlertSeverity.CRITICAL

    def test_slow_request_ratio_warning_triggers(self, engine, mock_provider):
        """慢请求占比 > 10% 触发 WARNING"""
        mock_provider.set("slow_request_ratio", 15.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        slow_alerts = [a for a in active if a.rule_id == "api_slow_request_ratio_warning"]
        assert len(slow_alerts) == 1

    def test_qps_drop_warning_triggers(self, engine, mock_provider):
        """QPS 环比下降 > 50% 触发 WARNING"""
        mock_provider.set("qps", 40.0)
        mock_provider.set("qps_previous", 100.0)  # 下降 60%
        engine.check_all_rules()

        active = engine.get_active_alerts()
        qps_alerts = [a for a in active if a.rule_id == "api_qps_drop_warning"]
        assert len(qps_alerts) == 1

    def test_module_offline_critical_triggers(self, engine, mock_provider):
        """模块离线触发 CRITICAL"""
        mock_provider.set("module_offline_count", 2)
        mock_provider.set("module_total", 8)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        offline_alerts = [a for a in active if a.rule_id == "service_module_offline_critical"]
        assert len(offline_alerts) == 1
        assert offline_alerts[0].severity == AlertSeverity.CRITICAL

    def test_db_connection_critical_triggers(self, engine, mock_provider):
        """数据库连接失败触发 CRITICAL"""
        mock_provider.set("db_connection_ok", False)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        db_alerts = [a for a in active if a.rule_id == "service_db_connection_critical"]
        assert len(db_alerts) == 1
        assert db_alerts[0].severity == AlertSeverity.CRITICAL

    def test_no_alert_when_normal(self, engine, mock_provider):
        """正常情况下不触发任何告警"""
        # Mock 默认值都是正常的
        result = engine.check_all_rules()

        assert result["fired_count"] == 0
        active = engine.get_active_alerts()
        assert len(active) == 0


# ============================================================================
# 2. 告警去重静默测试
# ============================================================================

class TestAlertDeduplicationSilence:
    """告警去重静默机制测试"""

    def test_same_rule_deduplication(self, engine, mock_provider):
        """同一规则多次检查不重复创建告警"""
        mock_provider.set("cpu_usage", 85.0)

        # 第一次检查触发告警
        result1 = engine.check_all_rules()
        assert result1["fired_count"] >= 1

        # 第二次检查（在静默期内）
        result2 = engine.check_all_rules()
        # 由于 check_interval 的存在，可能不会立即重新检查
        # 手动重置检查时间来测试去重
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        rule._last_fire_time = time.time()  # 设置为刚触发过

        result3 = engine.check_all_rules()
        # 静默期内，fired_count 应该为 0（没有新告警）
        assert result3["fired_count"] == 0

        # 活跃告警数不变
        active = engine.get_active_alerts()
        cpu_alerts = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_alerts) == 1

    def test_silence_period_prevents_duplicate_notifications(self, engine, mock_provider):
        """静默期内不重复发送通知"""
        mock_provider.set("cpu_usage", 85.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule.silence_period = 60  # 60 秒静默期
        rule.check_interval = 0  # 每次都检查

        # Mock 通知器
        mock_notifier = MagicMock()
        mock_notifier.name = "mock"
        mock_notifier.enabled = True
        mock_notifier.min_severity = AlertSeverity.INFO
        mock_notifier.should_notify.return_value = True
        mock_notifier.notify.return_value = True
        engine.notifier_manager.register(mock_notifier)
        engine.notifier_manager.set_default_channels(["mock"])

        # 第一次触发
        engine.check_all_rules()
        first_call_count = mock_notifier.notify.call_count

        # 手动重置检查时间，模拟立即再次检查
        rule._last_check_time = 0
        rule._last_fire_time = time.time() - 10  # 10秒前触发，仍在静默期

        # 第二次检查（静默期内）
        engine.check_all_rules()
        second_call_count = mock_notifier.notify.call_count

        # 静默期内不应增加通知次数
        assert second_call_count == first_call_count

    def test_silence_period_expired_resends(self, engine, mock_provider):
        """静默期过后重新发送通知"""
        mock_provider.set("cpu_usage", 85.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule.silence_period = 1  # 1 秒静默期（很短，便于测试）
        rule.check_interval = 1  # 1 秒检查间隔

        # Mock 通知器
        mock_notifier = MagicMock()
        mock_notifier.name = "mock"
        mock_notifier.enabled = True
        mock_notifier.min_severity = AlertSeverity.INFO
        mock_notifier.should_notify.return_value = True
        mock_notifier.notify.return_value = True
        engine.notifier_manager.register(mock_notifier)
        engine.notifier_manager.set_default_channels(["mock"])

        # 第一次触发
        rule._last_check_time = 0
        engine.check_all_rules()
        first_count = mock_notifier.notify.call_count
        assert first_count >= 1

        # 设置静默期已过
        rule._last_check_time = 0
        rule._last_fire_time = time.time() - 2  # 2秒前触发，静默期已过

        # 第二次检查
        engine.check_all_rules()
        second_count = mock_notifier.notify.call_count

        # 静默期已过，应重新发送通知
        assert second_count > first_count

    def test_firing_count_increments(self, engine, mock_provider):
        """firing_count 随重复触发递增"""
        mock_provider.set("cpu_usage", 85.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule.check_interval = 1  # 1 秒检查间隔
        rule.silence_period = 0  # 无静默，每次都通知

        # 多次触发
        for i in range(5):
            rule._last_check_time = 0
            rule._last_fire_time = 0  # 重置，确保每次都过静默期
            engine.check_all_rules()

        active = engine.get_active_alerts()
        cpu_alerts = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_alerts) == 1
        assert cpu_alerts[0].firing_count >= 5


# ============================================================================
# 3. 告警级别判断测试
# ============================================================================

class TestAlertSeverityLevels:
    """告警级别判断测试"""

    def test_severity_comparison(self):
        """告警级别比较"""
        assert AlertSeverity.CRITICAL > AlertSeverity.WARNING
        assert AlertSeverity.WARNING > AlertSeverity.INFO
        assert AlertSeverity.CRITICAL >= AlertSeverity.CRITICAL
        assert AlertSeverity.INFO < AlertSeverity.WARNING
        assert AlertSeverity.WARNING <= AlertSeverity.WARNING

    def test_severity_from_str(self):
        """从字符串解析告警级别"""
        assert AlertSeverity.from_str("info") == AlertSeverity.INFO
        assert AlertSeverity.from_str("INFO") == AlertSeverity.INFO
        assert AlertSeverity.from_str("warning") == AlertSeverity.WARNING
        assert AlertSeverity.from_str("warn") == AlertSeverity.WARNING
        assert AlertSeverity.from_str("critical") == AlertSeverity.CRITICAL
        assert AlertSeverity.from_str("fatal") == AlertSeverity.CRITICAL
        assert AlertSeverity.from_str("unknown") == AlertSeverity.WARNING  # 默认

    def test_numeric_level(self):
        """数字级别"""
        assert AlertSeverity.INFO.numeric_level == 1
        assert AlertSeverity.WARNING.numeric_level == 2
        assert AlertSeverity.CRITICAL.numeric_level == 3

    def test_filter_by_severity(self, engine, mock_provider):
        """按级别过滤活跃告警"""
        # 触发多个不同级别的告警
        mock_provider.set("cpu_usage", 95.0)  # WARNING + CRITICAL
        mock_provider.set("memory_usage", 50.0)  # 不触发
        engine.check_all_rules()

        # 所有告警
        all_alerts = engine.get_active_alerts()
        assert len(all_alerts) >= 2

        # 仅 CRITICAL
        critical_alerts = engine.get_active_alerts(severity=AlertSeverity.CRITICAL)
        assert len(critical_alerts) >= 1
        for a in critical_alerts:
            assert a.severity == AlertSeverity.CRITICAL

        # 仅 WARNING
        warning_alerts = engine.get_active_alerts(severity=AlertSeverity.WARNING)
        assert len(warning_alerts) >= 1
        for a in warning_alerts:
            assert a.severity == AlertSeverity.WARNING


# ============================================================================
# 4. 多渠道通知测试
# ============================================================================

class TestNotificationChannels:
    """多渠道通知测试"""

    def test_log_notifier_creation(self):
        """LogNotifier 创建"""
        notifier = LogNotifier(name="test_log", min_severity=AlertSeverity.INFO)
        assert notifier.name == "test_log"
        assert notifier.min_severity == AlertSeverity.INFO
        assert notifier.enabled is True

    def test_console_notifier_creation(self):
        """ConsoleNotifier 创建"""
        notifier = ConsoleNotifier(name="test_console", min_severity=AlertSeverity.WARNING)
        assert notifier.name == "test_console"
        assert notifier.min_severity == AlertSeverity.WARNING

    def test_webhook_notifier_no_url_returns_false(self):
        """WebhookNotifier 无 URL 时返回 False"""
        notifier = WebhookNotifier(name="test_webhook", url="")
        alert = AlertEvent(
            id="test-1",
            rule_id="test",
            rule_name="Test",
            severity=AlertSeverity.WARNING,
            state=AlertState.FIRING,
            summary="Test alert",
        )
        assert notifier.notify(alert) is False

    def test_webhook_notifier_with_url(self):
        """WebhookNotifier 配置 URL 后尝试发送"""
        notifier = WebhookNotifier(
            name="test_webhook",
            url="http://localhost:9999/test-webhook",
            timeout=1.0,
        )
        alert = AlertEvent(
            id="test-1",
            rule_id="test",
            rule_name="Test",
            severity=AlertSeverity.CRITICAL,
            state=AlertState.FIRING,
            summary="Test alert",
        )
        # 因为没有真实服务器，应该返回 False（连接失败）
        result = notifier.notify(alert)
        assert result is False  # 连接失败但不抛出异常

    def test_notifier_manager_register_and_get(self):
        """通知管理器注册和获取"""
        manager = NotifierManager()
        notifier = ConsoleNotifier(name="console_test")
        manager.register(notifier)

        retrieved = manager.get("console_test")
        assert retrieved is not None
        assert retrieved.name == "console_test"

    def test_notifier_manager_unregister(self):
        """通知管理器注销"""
        manager = NotifierManager()
        notifier = ConsoleNotifier(name="to_remove")
        manager.register(notifier)
        assert manager.get("to_remove") is not None

        manager.unregister("to_remove")
        assert manager.get("to_remove") is None

    def test_notifier_min_severity_filter(self):
        """通知器按最低级别过滤"""
        notifier = ConsoleNotifier(name="test", min_severity=AlertSeverity.WARNING)

        # INFO 级别不应通知
        info_alert = AlertEvent(
            id="test-info", rule_id="test", rule_name="Test",
            severity=AlertSeverity.INFO, state=AlertState.FIRING,
            summary="Info alert",
        )
        assert notifier.should_notify(AlertSeverity.INFO) is False

        # WARNING 级别应该通知
        warning_alert = AlertEvent(
            id="test-warning", rule_id="test", rule_name="Test",
            severity=AlertSeverity.WARNING, state=AlertState.FIRING,
            summary="Warning alert",
        )
        assert notifier.should_notify(AlertSeverity.WARNING) is True

        # CRITICAL 级别应该通知
        assert notifier.should_notify(AlertSeverity.CRITICAL) is True

    def test_disabled_notifier_does_not_send(self):
        """禁用的通知器不发送"""
        notifier = ConsoleNotifier(name="test")
        notifier.enabled = False

        alert = AlertEvent(
            id="test-1", rule_id="test", rule_name="Test",
            severity=AlertSeverity.CRITICAL, state=AlertState.FIRING,
            summary="Test alert",
        )
        assert notifier.notify(alert) is False

    def test_default_channels_config(self, engine):
        """默认通知渠道配置"""
        channels = engine.notifier_manager.list_channels()
        # 至少有 log 渠道
        channel_names = [c["name"] for c in channels]
        assert "log" in channel_names


# ============================================================================
# 5. 告警确认测试
# ============================================================================

class TestAlertAcknowledgement:
    """告警确认测试"""

    def test_acknowledge_alert(self, engine, mock_provider):
        """确认告警"""
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        assert len(active) > 0
        alert = active[0]
        assert alert.state == AlertState.FIRING

        # 确认告警
        success = engine.acknowledge_alert(alert.id, acknowledged_by="admin")
        assert success is True

        # 验证状态变更
        updated = engine.get_alert(alert.id)
        assert updated is not None
        assert updated.state == AlertState.ACKNOWLEDGED
        assert updated.acknowledged_by == "admin"
        assert updated.acknowledged_at is not None

    def test_acknowledge_nonexistent_alert(self, engine):
        """确认不存在的告警返回 False"""
        success = engine.acknowledge_alert("nonexistent-id", acknowledged_by="admin")
        assert success is False

    def test_resolve_alert(self, engine, mock_provider):
        """手动解决告警"""
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        alert = active[0]

        success = engine.resolve_alert(alert.id, resolved_by="admin", reason="manual fix")
        assert success is True

        # 验证已从活跃告警中移除
        active_after = engine.get_active_alerts()
        assert all(a.id != alert.id for a in active_after)

        # 验证在历史记录中（resolved 状态）
        history = engine.get_history(limit=10)
        resolved = [h for h in history if h["id"] == alert.id and h["state"] == "resolved"]
        assert len(resolved) >= 1
        assert resolved[0]["state"] == "resolved"

    def test_silence_alert(self, engine, mock_provider):
        """静默告警"""
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        alert = active[0]

        success = engine.silence_alert(
            alert.id,
            duration_seconds=3600,
            silenced_by="admin",
            reason="investigating",
        )
        assert success is True

        updated = engine.get_alert(alert.id)
        assert updated.state == AlertState.SILENCED
        assert updated.silenced_by == "admin"
        assert updated.silence_reason == "investigating"
        assert updated.silenced_until is not None


# ============================================================================
# 6. 规则开关测试
# ============================================================================

class TestRuleToggle:
    """规则开关测试"""

    def test_disable_rule(self, engine, mock_provider):
        """禁用规则后不再触发"""
        mock_provider.set("cpu_usage", 85.0)

        # 先确认规则存在且启用
        rule = engine.get_rule("system_cpu_high_warning")
        assert rule is not None
        assert rule.enabled is True

        # 禁用规则
        success = engine.disable_rule("system_cpu_high_warning")
        assert success is True
        assert rule.enabled is False

        # 检查不应触发
        result = engine.check_all_rules()
        active = engine.get_active_alerts()
        cpu_alerts = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_alerts) == 0

    def test_enable_rule(self, engine, mock_provider):
        """启用规则后可以触发"""
        # 先禁用
        engine.disable_rule("system_cpu_high_warning")

        mock_provider.set("cpu_usage", 85.0)
        result_before = engine.check_all_rules()
        active_before = engine.get_active_alerts()
        assert all(a.rule_id != "system_cpu_high_warning" for a in active_before)

        # 启用规则
        success = engine.enable_rule("system_cpu_high_warning")
        assert success is True

        # 重置检查时间，立即检查
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0

        result_after = engine.check_all_rules()
        active_after = engine.get_active_alerts()
        cpu_alerts = [a for a in active_after if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_alerts) == 1

    def test_disable_rule_resolves_alerts(self, engine, mock_provider):
        """禁用规则时自动解决该规则的活跃告警"""
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        active_before = engine.get_active_alerts()
        assert any(a.rule_id == "system_cpu_high_warning" for a in active_before)

        engine.disable_rule("system_cpu_high_warning")

        active_after = engine.get_active_alerts()
        assert all(a.rule_id != "system_cpu_high_warning" for a in active_after)

    def test_toggle_nonexistent_rule(self, engine):
        """操作不存在的规则返回 False"""
        assert engine.enable_rule("nonexistent_rule") is False
        assert engine.disable_rule("nonexistent_rule") is False

    def test_list_rules_filter_by_enabled(self, engine):
        """按启用状态过滤规则列表"""
        all_rules = engine.list_rules()
        enabled_rules = engine.list_rules(enabled_only=True)
        assert len(enabled_rules) <= len(all_rules)
        for r in enabled_rules:
            assert r.enabled is True

    def test_list_rules_filter_by_severity(self, engine):
        """按级别过滤规则列表"""
        critical_rules = engine.list_rules(severity=AlertSeverity.CRITICAL)
        for r in critical_rules:
            assert r.severity == AlertSeverity.CRITICAL

        warning_rules = engine.list_rules(severity=AlertSeverity.WARNING)
        for r in warning_rules:
            assert r.severity == AlertSeverity.WARNING

    def test_list_rules_filter_by_category(self, engine):
        """按类别过滤规则列表"""
        system_rules = engine.list_rules(category="system")
        for r in system_rules:
            assert r.labels.get("category") == "system"

        perf_rules = engine.list_rules(category="performance")
        for r in perf_rules:
            assert r.labels.get("category") == "performance"


# ============================================================================
# 7. 告警恢复测试
# ============================================================================

class TestAlertResolution:
    """告警恢复测试"""

    def test_alert_resolves_when_condition_clears(self, engine, mock_provider):
        """条件恢复后告警自动解决"""
        # 先触发
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        active_before = engine.get_active_alerts()
        assert any(a.rule_id == "system_cpu_high_warning" for a in active_before)

        # 条件恢复
        mock_provider.set("cpu_usage", 50.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        result = engine.check_all_rules()

        assert result["resolved_count"] >= 1
        active_after = engine.get_active_alerts()
        assert all(a.rule_id != "system_cpu_high_warning" for a in active_after)

    def test_resolved_alert_in_history(self, engine, mock_provider):
        """恢复的告警出现在历史记录中"""
        # 触发再恢复
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        mock_provider.set("cpu_usage", 30.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        engine.check_all_rules()

        history = engine.get_history(limit=20)
        resolved_cpu = [
            h for h in history
            if h["rule_id"] == "system_cpu_high_warning" and h["state"] == "resolved"
        ]
        assert len(resolved_cpu) >= 1

    def test_total_resolved_counter(self, engine, mock_provider):
        """解决计数器正确累加"""
        initial_resolved = engine._total_resolved

        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()

        mock_provider.set("cpu_usage", 30.0)
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        engine.check_all_rules()

        assert engine._total_resolved > initial_resolved


# ============================================================================
# 8. 边界情况测试
# ============================================================================

class TestEdgeCases:
    """边界情况测试"""

    def test_threshold_exact_value(self, engine, mock_provider):
        """恰好等于阈值时不触发（严格大于）"""
        # CPU WARNING 阈值 80，恰好 80 不触发
        mock_provider.set("cpu_usage", 80.0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        cpu_warnings = [a for a in active if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_warnings) == 0

        # 超过一点点则触发
        mock_provider.set("cpu_usage", 80.1)
        rule = engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        engine.check_all_rules()

        active2 = engine.get_active_alerts()
        cpu_warnings2 = [a for a in active2 if a.rule_id == "system_cpu_high_warning"]
        assert len(cpu_warnings2) == 1

    def test_qps_drop_no_previous_traffic(self, engine, mock_provider):
        """上一周期无流量时 QPS 突降告警不触发"""
        mock_provider.set("qps", 0.0)
        mock_provider.set("qps_previous", 0.5)  # 低于 1.0 的阈值
        engine.check_all_rules()

        active = engine.get_active_alerts()
        qps_alerts = [a for a in active if a.rule_id == "api_qps_drop_warning"]
        assert len(qps_alerts) == 0

    def test_zero_process_count(self, engine, mock_provider):
        """进程数为 0 时不触发告警"""
        mock_provider.set("process_count", 0)
        engine.check_all_rules()

        active = engine.get_active_alerts()
        proc_alerts = [a for a in active if a.rule_id == "system_process_count_warning"]
        assert len(proc_alerts) == 0

    def test_custom_threshold_via_context(self, engine, mock_provider):
        """通过 context 覆盖进程数阈值"""
        mock_provider.set("process_count", 50)
        mock_provider.set("process_count_threshold", 40)  # 降低阈值
        engine.check_all_rules()

        active = engine.get_active_alerts()
        proc_alerts = [a for a in active if a.rule_id == "system_process_count_warning"]
        # 50 > 40，应该触发
        assert len(proc_alerts) == 1

    def test_alert_event_to_dict(self):
        """告警事件序列化"""
        alert = AlertEvent(
            id="test-123",
            rule_id="test_rule",
            rule_name="Test Rule",
            severity=AlertSeverity.WARNING,
            state=AlertState.FIRING,
            summary="Test alert",
            description="Test description",
            labels={"category": "test", "env": "test"},
            value=85.0,
            threshold=80.0,
        )
        d = alert.to_dict()
        assert d["id"] == "test-123"
        assert d["severity"] == "warning"
        assert d["state"] == "firing"
        assert d["value"] == 85.0
        assert d["threshold"] == 80.0
        assert d["labels"]["category"] == "test"
        assert "started_at_formatted" in d

    def test_alert_rule_to_dict(self, engine):
        """规则序列化"""
        rule = engine.get_rule("system_cpu_high_warning")
        d = rule.to_dict()
        assert d["rule_id"] == "system_cpu_high_warning"
        assert d["severity"] == "warning"
        assert d["enabled"] is True
        assert d["check_interval"] > 0
        assert d["silence_period"] > 0

    def test_get_stats(self, engine, mock_provider):
        """告警统计信息"""
        stats = engine.get_stats()
        assert "total_fired" in stats
        assert "total_resolved" in stats
        assert "active_count" in stats
        assert "by_severity" in stats
        assert "by_state" in stats
        assert "rules_count" in stats

    def test_health_impact(self, engine, mock_provider):
        """告警对健康检查的影响"""
        # 无告警时 healthy
        impact = engine.get_health_impact()
        assert impact["status"] == "healthy"

        # 有 WARNING 告警时 degraded
        mock_provider.set("cpu_usage", 85.0)
        engine.check_all_rules()
        impact = engine.get_health_impact()
        assert impact["status"] == "degraded"
        assert impact["warning_alerts_count"] >= 1

    def test_empty_context_provider(self, engine):
        """空上下文提供者不影响评估"""
        # 已经有 mock provider，再添加一个返回空 dict 的
        engine.add_context_provider(lambda: {})
        result = engine.check_all_rules()
        # 不应抛出异常
        assert "fired_count" in result

    def test_error_in_context_provider(self, engine):
        """上下文提供者出错不影响告警引擎"""
        def bad_provider():
            raise RuntimeError("context provider failed")

        engine.add_context_provider(bad_provider)
        # 不应抛出异常
        result = engine.check_all_rules()
        assert "fired_count" in result


# ============================================================================
# 9. Mock 数据源测试
# ============================================================================

class TestMockMetricsProvider:
    """Mock 指标提供者测试"""

    def test_default_values(self):
        """Mock 默认值都在正常范围内"""
        provider = MockMetricsProvider()
        data = provider.get_context()

        assert data["cpu_usage"] < 80
        assert data["memory_usage"] < 85
        assert data["disk_usage"] < 80
        assert data["error_rate"] < 5
        assert data["module_offline_count"] == 0
        assert data["db_connection_ok"] is True

    def test_set_and_get(self):
        """设置和获取指标值"""
        provider = MockMetricsProvider()
        provider.set("cpu_usage", 99.0)
        assert provider.get("cpu_usage") == 99.0

    def test_set_many(self):
        """批量设置指标值"""
        provider = MockMetricsProvider()
        provider.set_many({
            "cpu_usage": 95.0,
            "memory_usage": 90.0,
            "error_rate": 15.0,
        })
        assert provider.get("cpu_usage") == 95.0
        assert provider.get("memory_usage") == 90.0
        assert provider.get("error_rate") == 15.0

    def test_get_system_metrics(self):
        """获取系统指标子集"""
        provider = MockMetricsProvider()
        sys_metrics = provider.get_system_metrics()
        assert "cpu_usage" in sys_metrics
        assert "memory_usage" in sys_metrics
        assert "disk_usage" in sys_metrics
        assert "process_count" in sys_metrics

    def test_get_api_metrics(self):
        """获取接口指标子集"""
        provider = MockMetricsProvider()
        api_metrics = provider.get_api_metrics()
        assert "error_rate" in api_metrics
        assert "qps" in api_metrics
        assert "slow_request_ratio" in api_metrics
        assert "avg_latency_ms" in api_metrics

    def test_get_health_metrics(self):
        """获取健康指标子集"""
        provider = MockMetricsProvider()
        health_metrics = provider.get_health_metrics()
        assert "module_offline_count" in health_metrics
        assert "db_connection_ok" in health_metrics

    def test_reset(self):
        """重置为默认值"""
        provider = MockMetricsProvider()
        provider.set("cpu_usage", 100.0)
        assert provider.get("cpu_usage") == 100.0

        provider.reset()
        assert provider.get("cpu_usage") == 30.0  # 默认值

    def test_get_default_value(self):
        """获取不存在的指标返回默认值"""
        provider = MockMetricsProvider()
        assert provider.get("nonexistent_metric", 42) == 42
        assert provider.get("nonexistent_metric") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
