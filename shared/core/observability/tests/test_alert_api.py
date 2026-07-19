"""
告警管理 API 测试（OB-003 P1级）

测试覆盖：
- GET /api/alerts - 查询告警列表
- GET /api/alerts/{id} - 告警详情
- POST /api/alerts/{id}/acknowledge - 确认告警
- GET /api/alerts/rules - 告警规则列表
- POST /api/alerts/rules/{id}/toggle - 开关告警规则
- GET /api/alerts/status - 告警系统状态

所有测试使用 Mock 数据源，不依赖真实环境。
"""

import sys
import os
import pytest
from pathlib import Path

# 项目路径设置
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 在导入 shared 之前设置环境变量
os.environ.setdefault("YUNXI_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.core.observability import (
    AlertEngine,
    AlertSeverity,
    AlertState,
    create_alert_router,
    reset_alert_engine,
)
from shared.core.observability.alert_metrics_provider import (
    MockMetricsProvider,
    set_metrics_provider,
    reset_metrics_provider,
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
def alert_engine(mock_provider):
    """创建告警引擎"""
    reset_alert_engine()
    engine = AlertEngine(service_name="test_api", auto_start=False, history_limit=100)
    engine.add_context_provider(mock_provider.get_context)
    yield engine
    engine.stop()
    reset_alert_engine()


@pytest.fixture
def client(alert_engine):
    """创建 FastAPI 测试客户端"""
    app = FastAPI()
    router = create_alert_router(engine=alert_engine)
    app.include_router(router, prefix="/api")
    return TestClient(app)


# ============================================================================
# API 测试
# ============================================================================

class TestAlertsAPI:
    """告警列表 API 测试"""

    def test_get_alerts_empty(self, client):
        """获取空告警列表"""
        response = client.get("/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 0
        assert data["data"]["items"] == []

    def test_get_alerts_with_data(self, client, alert_engine, mock_provider):
        """获取有告警的列表"""
        # 触发一些告警
        mock_provider.set("cpu_usage", 95.0)
        mock_provider.set("memory_usage", 90.0)
        alert_engine.check_all_rules()

        response = client.get("/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 2
        assert len(data["data"]["items"]) >= 2

    def test_get_alerts_filter_by_severity(self, client, alert_engine, mock_provider):
        """按级别过滤告警"""
        mock_provider.set("cpu_usage", 95.0)  # WARNING + CRITICAL
        alert_engine.check_all_rules()

        # 只看 CRITICAL
        response = client.get("/api/alerts?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "critical"

        # 只看 WARNING
        response = client.get("/api/alerts?severity=warning")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "warning"

    def test_get_alerts_filter_by_category(self, client, alert_engine, mock_provider):
        """按类别过滤告警"""
        mock_provider.set("cpu_usage", 95.0)  # system 类
        alert_engine.check_all_rules()

        response = client.get("/api/alerts?category=system")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["labels"].get("category") == "system"

    def test_get_alerts_with_limit(self, client, alert_engine, mock_provider):
        """限制返回条数"""
        mock_provider.set("cpu_usage", 95.0)
        mock_provider.set("memory_usage", 97.0)
        mock_provider.set("disk_usage", 95.0)
        alert_engine.check_all_rules()

        response = client.get("/api/alerts?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        # total 是全部数量，items 是限制后的
        assert data["data"]["total"] >= 3
        assert len(data["data"]["items"]) == 2


class TestAlertDetailAPI:
    """告警详情 API 测试"""

    def test_get_alert_detail(self, client, alert_engine, mock_provider):
        """获取告警详情"""
        mock_provider.set("cpu_usage", 85.0)
        alert_engine.check_all_rules()

        active = alert_engine.get_active_alerts()
        alert_id = active[0].id

        response = client.get(f"/api/alerts/{alert_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["id"] == alert_id
        assert "rule_id" in data["data"]
        assert "severity" in data["data"]
        assert "state" in data["data"]
        assert "summary" in data["data"]
        assert "started_at" in data["data"]

    def test_get_alert_not_found(self, client):
        """获取不存在的告警返回 404"""
        response = client.get("/api/alerts/nonexistent-id")
        assert response.status_code == 404


class TestAlertAcknowledgeAPI:
    """告警确认 API 测试"""

    def test_acknowledge_alert(self, client, alert_engine, mock_provider):
        """确认告警"""
        mock_provider.set("cpu_usage", 85.0)
        alert_engine.check_all_rules()

        active = alert_engine.get_active_alerts()
        alert_id = active[0].id

        response = client.post(
            f"/api/alerts/{alert_id}/acknowledge",
            json={"acknowledged_by": "admin"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["state"] == "acknowledged"
        assert data["data"]["acknowledged_by"] == "admin"

    def test_acknowledge_alert_default_user(self, client, alert_engine, mock_provider):
        """确认告警不指定用户时使用默认值"""
        mock_provider.set("cpu_usage", 85.0)
        alert_engine.check_all_rules()

        active = alert_engine.get_active_alerts()
        alert_id = active[0].id

        response = client.post(
            f"/api/alerts/{alert_id}/acknowledge",
            json={},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["acknowledged_by"] == "system"

    def test_acknowledge_nonexistent_alert(self, client):
        """确认不存在的告警返回 404"""
        response = client.post(
            "/api/alerts/nonexistent-id/acknowledge",
            json={"acknowledged_by": "admin"},
        )
        assert response.status_code == 404


class TestAlertRulesAPI:
    """告警规则 API 测试"""

    def test_get_rules_list(self, client):
        """获取规则列表"""
        response = client.get("/api/alerts/rules")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0
        assert len(data["data"]["items"]) > 0

        # 验证规则字段
        first_rule = data["data"]["items"][0]
        assert "rule_id" in first_rule
        assert "name" in first_rule
        assert "severity" in first_rule
        assert "enabled" in first_rule
        assert "check_interval" in first_rule
        assert "silence_period" in first_rule

    def test_get_rules_filter_by_category(self, client):
        """按类别过滤规则"""
        response = client.get("/api/alerts/rules?category=system")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["labels"].get("category") == "system"

    def test_get_rules_filter_by_severity(self, client):
        """按级别过滤规则"""
        response = client.get("/api/alerts/rules?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "critical"

    def test_get_rules_enabled_only(self, client):
        """只返回启用的规则"""
        response = client.get("/api/alerts/rules?enabled_only=true")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["enabled"] is True

    def test_toggle_rule_disable(self, client, alert_engine):
        """开关规则 - 禁用"""
        rule_id = "system_cpu_high_warning"

        # 确认初始状态为启用
        rule = alert_engine.get_rule(rule_id)
        assert rule.enabled is True

        # 禁用
        response = client.post(f"/api/alerts/rules/{rule_id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["enabled"] is False
        assert data["data"]["rule_id"] == rule_id

        # 验证实际状态
        rule = alert_engine.get_rule(rule_id)
        assert rule.enabled is False

    def test_toggle_rule_enable(self, client, alert_engine):
        """开关规则 - 启用"""
        rule_id = "system_cpu_high_warning"

        # 先禁用
        alert_engine.disable_rule(rule_id)
        assert alert_engine.get_rule(rule_id).enabled is False

        # 再启用（toggle）
        response = client.post(f"/api/alerts/rules/{rule_id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["enabled"] is True

        # 验证实际状态
        rule = alert_engine.get_rule(rule_id)
        assert rule.enabled is True

    def test_toggle_nonexistent_rule(self, client):
        """开关不存在的规则返回 404"""
        response = client.post("/api/alerts/rules/nonexistent_rule/toggle")
        assert response.status_code == 404


class TestAlertStatusAPI:
    """告警系统状态 API 测试"""

    def test_get_status(self, client):
        """获取告警系统状态"""
        response = client.get("/api/alerts/status")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

        status = data["data"]
        assert "running" in status
        assert "service_name" in status
        assert "rules" in status
        assert "alerts" in status
        assert "channels" in status

        # 验证规则统计
        assert "total" in status["rules"]
        assert "enabled" in status["rules"]
        assert "disabled" in status["rules"]
        assert "by_category" in status["rules"]

        # 验证告警统计
        assert "active" in status["alerts"]
        assert "by_severity" in status["alerts"]
        assert "total_fired" in status["alerts"]
        assert "total_resolved" in status["alerts"]

        # 验证通知渠道
        assert "total" in status["channels"]
        assert "items" in status["channels"]

    def test_status_after_firing(self, client, alert_engine, mock_provider):
        """触发告警后状态更新"""
        # 初始状态
        response = client.get("/api/alerts/status")
        initial_active = response.json()["data"]["alerts"]["active"]

        # 触发告警
        mock_provider.set("cpu_usage", 95.0)
        alert_engine.check_all_rules()

        # 验证状态更新
        response = client.get("/api/alerts/status")
        data = response.json()
        assert data["data"]["alerts"]["active"] > initial_active
        assert data["data"]["alerts"]["total_fired"] > 0


class TestAlertHistoryAPI:
    """告警历史 API 测试"""

    def test_get_history(self, client, alert_engine, mock_provider):
        """获取告警历史"""
        # 触发再恢复，产生历史记录
        mock_provider.set("cpu_usage", 85.0)
        alert_engine.check_all_rules()

        mock_provider.set("cpu_usage", 30.0)
        rule = alert_engine.get_rule("system_cpu_high_warning")
        rule._last_check_time = 0
        alert_engine.check_all_rules()

        response = client.get("/api/alerts/history")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0

    def test_get_history_filter_by_severity(self, client, alert_engine, mock_provider):
        """按级别过滤历史记录"""
        mock_provider.set("cpu_usage", 95.0)
        alert_engine.check_all_rules()

        response = client.get("/api/alerts/history?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "critical"


class TestAlertChannelsAPI:
    """通知渠道 API 测试"""

    def test_get_channels(self, client):
        """获取通知渠道列表"""
        response = client.get("/api/alerts/channels")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 1  # 至少有 log 渠道
        assert len(data["data"]["items"]) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
