"""
告警 API 测试（基于 FastAPI 告警路由）

覆盖:
- GET /api/alerts - 查询告警列表
- GET /api/alerts/{id} - 告警详情
- POST /api/alerts/{id}/acknowledge - 确认告警
- GET /api/alerts/rules - 告警规则列表
- POST /api/alerts/rules/{id}/toggle - 开关告警规则
- GET /api/alerts/status - 告警系统状态
- 附加：历史记录、统计、创建/更新/删除规则

所有测试使用 Mock 数据源，不依赖真实环境。

运行: python -m pytest shared/tests/test_alert_api.py -v
"""
import os
import sys
import time
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# 设置路径
_shared_root = Path(__file__).resolve().parent.parent
if str(_shared_root) not in sys.path:
    sys.path.insert(0, str(_shared_root))
_project_root = _shared_root.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_app():
    """创建一个用于测试的 FastAPI 应用，仅包含告警路由"""
    from fastapi import FastAPI
    from shared.core.observability.alerting import (
        AlertEngine,
        create_alert_router,
        AlertSeverity,
        AlertRule,
        reset_alert_engine,
    )
    from shared.core.observability.alert_metrics_provider import (
        MockMetricsProvider,
        reset_metrics_provider,
    )

    # 重置全局状态
    reset_alert_engine()
    reset_metrics_provider()

    # 创建独立的告警引擎（不使用全局单例）
    engine = AlertEngine(service_name="test", history_limit=200, auto_start=False)

    # 创建 Mock 数据提供者并注册
    mock_provider = MockMetricsProvider()
    engine.add_context_provider(mock_provider.get_context)

    # 禁用所有通知渠道（避免测试输出干扰）
    for ch_info in engine.notifier_manager.list_channels():
        notifier = engine.notifier_manager.get(ch_info["name"])
        if notifier:
            notifier.enabled = False

    # 创建 FastAPI 应用
    app = FastAPI(title="Alert API Test")

    # 注册告警路由
    alert_router = create_alert_router(engine=engine)
    app.include_router(alert_router, prefix="/api")

    # 保存引擎引用，供测试使用
    app.state.alert_engine = engine
    app.state.mock_provider = mock_provider

    yield app

    # 清理
    engine.stop()
    reset_alert_engine()
    reset_metrics_provider()


@pytest.fixture
def client(test_app):
    """创建测试客户端"""
    from fastapi.testclient import TestClient
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def client_with_alerts(test_app):
    """创建有活跃告警的测试客户端"""
    from fastapi.testclient import TestClient

    engine = test_app.state.alert_engine
    provider = test_app.state.mock_provider

    # 设置指标触发多个告警
    provider.set_many({
        "cpu_usage": 85.0,      # WARNING
        "memory_usage": 96.0,   # CRITICAL
        "error_rate": 7.0,      # WARNING
    })

    # 触发告警
    engine.check_all_rules()

    with TestClient(test_app) as c:
        yield c


# ============================================================================
# 1. 查询告警列表
# ============================================================================

class TestGetAlerts:
    """GET /api/alerts - 查询告警列表"""

    def test_get_empty_alerts(self, client):
        """获取空告警列表"""
        response = client.get("/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 0
        assert data["data"]["items"] == []

    def test_get_active_alerts(self, client_with_alerts):
        """获取活跃告警列表"""
        response = client_with_alerts.get("/api/alerts")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 1
        assert len(data["data"]["items"]) >= 1

        # 验证告警字段
        alert = data["data"]["items"][0]
        assert "id" in alert
        assert "rule_id" in alert
        assert "severity" in alert
        assert "state" in alert
        assert "summary" in alert

    def test_filter_by_severity_warning(self, client_with_alerts):
        """按 WARNING 级别过滤"""
        response = client_with_alerts.get("/api/alerts?severity=warning")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "warning"

    def test_filter_by_severity_critical(self, client_with_alerts):
        """按 CRITICAL 级别过滤"""
        response = client_with_alerts.get("/api/alerts?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["severity"] == "critical"

    def test_filter_by_category(self, client_with_alerts):
        """按类别过滤"""
        response = client_with_alerts.get("/api/alerts?category=system")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for item in data["data"]["items"]:
            assert item["labels"].get("category") == "system"

    def test_limit_param(self, client_with_alerts):
        """limit 参数限制返回数量"""
        response = client_with_alerts.get("/api/alerts?limit=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["items"]) <= 1


# ============================================================================
# 2. 告警详情
# ============================================================================

class TestGetAlertDetail:
    """GET /api/alerts/{id} - 告警详情"""

    def test_get_alert_detail(self, client_with_alerts):
        """获取告警详情"""
        # 先获取列表
        list_resp = client_with_alerts.get("/api/alerts")
        alerts = list_resp.json()["data"]["items"]
        assert len(alerts) > 0

        alert_id = alerts[0]["id"]
        detail_resp = client_with_alerts.get(f"/api/alerts/{alert_id}")
        assert detail_resp.status_code == 200

        detail = detail_resp.json()["data"]
        assert detail["id"] == alert_id
        assert "rule_id" in detail
        assert "description" in detail
        assert "started_at_formatted" in detail
        assert "duration_seconds" in detail

    def test_get_nonexistent_alert(self, client):
        """获取不存在的告警返回 404"""
        response = client.get("/api/alerts/nonexistent-id")
        assert response.status_code == 404


# ============================================================================
# 3. 确认告警
# ============================================================================

class TestAcknowledgeAlert:
    """POST /api/alerts/{id}/acknowledge - 确认告警"""

    def test_acknowledge_alert(self, client_with_alerts):
        """确认告警"""
        # 获取一个告警
        list_resp = client_with_alerts.get("/api/alerts")
        alerts = list_resp.json()["data"]["items"]
        assert len(alerts) > 0
        alert_id = alerts[0]["id"]

        # 确认告警
        response = client_with_alerts.post(
            f"/api/alerts/{alert_id}/acknowledge",
            json={"acknowledged_by": "test_user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["state"] == "acknowledged"
        assert data["data"]["acknowledged_by"] == "test_user"
        assert data["data"]["acknowledged_at"] is not None

    def test_acknowledge_nonexistent_alert(self, client):
        """确认不存在的告警返回 404"""
        response = client.post(
            "/api/alerts/nonexistent/acknowledge",
            json={"acknowledged_by": "test"},
        )
        assert response.status_code == 404

    def test_acknowledge_default_user(self, client_with_alerts):
        """确认告警时使用默认确认人"""
        list_resp = client_with_alerts.get("/api/alerts")
        alerts = list_resp.json()["data"]["items"]
        alert_id = alerts[0]["id"]

        response = client_with_alerts.post(
            f"/api/alerts/{alert_id}/acknowledge",
            json={},
        )
        assert response.status_code == 200
        assert response.json()["data"]["acknowledged_by"] == "system"


# ============================================================================
# 4. 告警规则列表
# ============================================================================

class TestGetAlertRules:
    """GET /api/alerts/rules - 告警规则列表"""

    def test_get_all_rules(self, client):
        """获取所有规则"""
        response = client.get("/api/alerts/rules")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0
        assert len(data["data"]["items"]) > 0

        # 验证规则字段
        rule = data["data"]["items"][0]
        assert "rule_id" in rule
        assert "name" in rule
        assert "severity" in rule
        assert "enabled" in rule
        assert "is_builtin" in rule

    def test_filter_by_category(self, client):
        """按类别过滤规则"""
        response = client.get("/api/alerts/rules?category=system")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for rule in data["data"]["items"]:
            assert rule["labels"].get("category") == "system"

    def test_filter_by_severity(self, client):
        """按级别过滤规则"""
        response = client.get("/api/alerts/rules?severity=critical")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for rule in data["data"]["items"]:
            assert rule["severity"] == "critical"

    def test_enabled_only(self, client):
        """只返回启用的规则"""
        response = client.get("/api/alerts/rules?enabled_only=true")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        for rule in data["data"]["items"]:
            assert rule["enabled"] is True


# ============================================================================
# 5. 开关告警规则
# ============================================================================

class TestToggleAlertRule:
    """POST /api/alerts/rules/{id}/toggle - 开关告警规则"""

    def test_toggle_enable_to_disable(self, client):
        """从启用切换到禁用"""
        # 先获取一个启用的规则
        rules_resp = client.get("/api/alerts/rules?enabled_only=true")
        rules = rules_resp.json()["data"]["items"]
        assert len(rules) > 0
        rule_id = rules[0]["rule_id"]
        assert rules[0]["enabled"] is True

        # 切换（启用 -> 禁用）
        response = client.post(f"/api/alerts/rules/{rule_id}/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["enabled"] is False

        # 验证状态
        detail_resp = client.get("/api/alerts/rules")
        all_rules = detail_resp.json()["data"]["items"]
        toggled = [r for r in all_rules if r["rule_id"] == rule_id][0]
        assert toggled["enabled"] is False

    def test_toggle_disable_to_enable(self, client):
        """从禁用切换到启用"""
        # 先禁用一个规则
        rules_resp = client.get("/api/alerts/rules?enabled_only=true")
        rules = rules_resp.json()["data"]["items"]
        rule_id = rules[0]["rule_id"]

        # 第一次切换：禁用
        client.post(f"/api/alerts/rules/{rule_id}/toggle")

        # 第二次切换：启用
        response = client.post(f"/api/alerts/rules/{rule_id}/toggle")
        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is True

    def test_toggle_nonexistent_rule(self, client):
        """切换不存在的规则返回 404"""
        response = client.post("/api/alerts/rules/nonexistent_rule/toggle")
        assert response.status_code == 404


# ============================================================================
# 6. 告警系统状态
# ============================================================================

class TestAlertSystemStatus:
    """GET /api/alerts/status - 告警系统状态"""

    def test_status_endpoint(self, client):
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

    def test_status_rules_breakdown(self, client):
        """状态中的规则统计"""
        response = client.get("/api/alerts/status")
        rules_data = response.json()["data"]["rules"]

        assert "total" in rules_data
        assert "enabled" in rules_data
        assert "disabled" in rules_data
        assert "by_category" in rules_data
        assert rules_data["total"] == rules_data["enabled"] + rules_data["disabled"]

    def test_status_with_active_alerts(self, client_with_alerts):
        """有活跃告警时的状态"""
        response = client_with_alerts.get("/api/alerts/status")
        alerts_data = response.json()["data"]["alerts"]

        assert alerts_data["active"] >= 1
        assert "firing" in alerts_data
        assert "by_severity" in alerts_data
        assert "total_fired" in alerts_data

    def test_status_channels(self, client):
        """状态中的通知渠道信息"""
        response = client.get("/api/alerts/status")
        channels_data = response.json()["data"]["channels"]

        assert "total" in channels_data
        assert "items" in channels_data
        assert channels_data["total"] >= 1  # 至少有 log 渠道


# ============================================================================
# 7. 附加：告警历史与统计
# ============================================================================

class TestAlertHistoryAndStats:
    """告警历史和统计端点测试"""

    def test_alert_history(self, client_with_alerts):
        """获取告警历史"""
        response = client_with_alerts.get("/api/alerts/history")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 1

    def test_alert_stats(self, client_with_alerts):
        """获取告警统计"""
        response = client_with_alerts.get("/api/alerts/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "total_fired" in data["data"]
        assert "active_count" in data["data"]
        assert "by_severity" in data["data"]

    def test_notification_channels(self, client):
        """获取通知渠道列表"""
        response = client.get("/api/alerts/channels")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] >= 1


# ============================================================================
# 8. 附加：规则 CRUD
# ============================================================================

class TestAlertRuleCRUD:
    """告警规则创建/更新/删除测试"""

    def test_create_custom_rule(self, client):
        """创建自定义规则"""
        response = client.post(
            "/api/alerts/rules",
            json={
                "rule_id": "custom_test_rule",
                "name": "自定义测试规则",
                "description": "用于测试的自定义规则",
                "severity": "warning",
                "condition": "custom_metric > 100",
                "check_interval": 120,
                "silence_period": 600,
                "labels": {"category": "custom", "type": "test"},
                "enabled": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["rule_id"] == "custom_test_rule"
        assert data["data"]["is_builtin"] is False

    def test_create_duplicate_rule(self, client):
        """创建重复 ID 的规则返回错误"""
        # 先创建一个
        client.post(
            "/api/alerts/rules",
            json={
                "rule_id": "dup_rule",
                "name": "重复规则",
                "severity": "info",
                "condition": "x > 0",
            },
        )

        # 再创建同名的
        response = client.post(
            "/api/alerts/rules",
            json={
                "rule_id": "dup_rule",
                "name": "重复规则2",
                "severity": "warning",
                "condition": "x > 1",
            },
        )
        assert response.status_code == 400

    def test_update_rule(self, client):
        """更新规则"""
        # 先创建
        client.post(
            "/api/alerts/rules",
            json={
                "rule_id": "update_test_rule",
                "name": "原始名称",
                "description": "原始描述",
                "severity": "info",
                "condition": "x > 0",
            },
        )

        # 再更新
        response = client.put(
            "/api/alerts/rules/update_test_rule",
            json={
                "name": "新名称",
                "description": "新描述",
                "severity": "critical",
                "check_interval": 300,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["name"] == "新名称"
        assert data["data"]["severity"] == "critical"
        assert data["data"]["check_interval"] == 300

    def test_delete_custom_rule(self, client):
        """删除自定义规则"""
        # 先创建
        client.post(
            "/api/alerts/rules",
            json={
                "rule_id": "delete_test_rule",
                "name": "待删除",
                "severity": "info",
                "condition": "x > 0",
            },
        )

        # 再删除
        response = client.delete("/api/alerts/rules/delete_test_rule")
        assert response.status_code == 200
        assert response.json()["code"] == 0

        # 验证已删除
        rules_resp = client.get("/api/alerts/rules")
        rule_ids = [r["rule_id"] for r in rules_resp.json()["data"]["items"]]
        assert "delete_test_rule" not in rule_ids

    def test_cannot_delete_builtin_rule(self, client):
        """不能删除内置规则"""
        # 获取一个内置规则
        rules_resp = client.get("/api/alerts/rules")
        builtin_rules = [r for r in rules_resp.json()["data"]["items"] if r["is_builtin"]]
        assert len(builtin_rules) > 0

        response = client.delete(f"/api/alerts/rules/{builtin_rules[0]['rule_id']}")
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
