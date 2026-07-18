"""设备管理增强测试.

覆盖：
- 设备注册/注销
- 设备信息（型号/系统/版本/性能）
- 设备状态（在线/离线/忙碌）
- 设备分组
- 设备信任等级
- 设备健康监测（心跳/指标/异常/评分）
"""

from __future__ import annotations

import asyncio
import time

import pytest

from edge_cloud_kernel.services.device_manager import (
    DeviceHealthRecord,
    DeviceHealthScore,
    DeviceHealthStatus,
    DeviceInfo,
    DeviceManager,
    DeviceOperationalStatus,
    DeviceTrustLevel,
    HealthMetric,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def device_manager():
    """创建设备管理器测试实例."""
    manager = DeviceManager(heartbeat_timeout=120)
    yield manager


# ============================================================
# 枚举值测试
# ============================================================

class TestEnums:
    """枚举值测试."""

    def test_trust_level_values(self):
        """测试信任等级枚举值."""
        assert DeviceTrustLevel.UNTRUSTED == "untrusted"
        assert DeviceTrustLevel.LOW == "low"
        assert DeviceTrustLevel.MEDIUM == "medium"
        assert DeviceTrustLevel.HIGH == "high"
        assert DeviceTrustLevel.TRUSTED == "trusted"

    def test_health_status_values(self):
        """测试健康状态枚举值."""
        assert DeviceHealthStatus.HEALTHY == "healthy"
        assert DeviceHealthStatus.WARNING == "warning"
        assert DeviceHealthStatus.DEGRADED == "degraded"
        assert DeviceHealthStatus.UNHEALTHY == "unhealthy"
        assert DeviceHealthStatus.UNKNOWN == "unknown"

    def test_operational_status_values(self):
        """测试运行状态枚举值."""
        assert DeviceOperationalStatus.ONLINE == "online"
        assert DeviceOperationalStatus.OFFLINE == "offline"
        assert DeviceOperationalStatus.BUSY == "busy"
        assert DeviceOperationalStatus.IDLE == "idle"
        assert DeviceOperationalStatus.ERROR == "error"
        assert DeviceOperationalStatus.MAINTENANCE == "maintenance"


# ============================================================
# 设备注册测试
# ============================================================

class TestDeviceRegistration:
    """设备注册测试."""

    def test_register_device(self, device_manager):
        """测试注册设备."""
        device = device_manager.register_device(
            device_id="dev-001",
            name="Test Device",
            device_type="phone",
        )
        assert device is not None
        assert isinstance(device, DeviceInfo)
        assert device.device_id == "dev-001"
        assert device.name == "Test Device"

    def test_register_device_with_details(self, device_manager):
        """测试注册带详细信息的设备."""
        device = device_manager.register_device(
            device_id="dev-002",
            name="Detailed Device",
            device_type="tablet",
            model="Model X",
            manufacturer="TestCorp",
            os_name="Android",
            os_version="14.0",
            app_version="2.1.0",
            cpu_cores=8,
            total_memory_gb=8.0,
            total_storage_gb=256.0,
            has_gpu=True,
        )
        assert device.model == "Model X"
        assert device.manufacturer == "TestCorp"
        assert device.os_name == "Android"
        assert device.cpu_cores == 8
        assert device.total_memory_gb == 8.0
        assert device.has_gpu is True

    def test_register_duplicate_device(self, device_manager):
        """测试重复注册设备（应更新）."""
        device_manager.register_device(
            device_id="dev-003",
            name="Original Name",
        )
        updated = device_manager.register_device(
            device_id="dev-003",
            name="Updated Name",
        )
        assert updated.name == "Updated Name"
        # 设备数应为 1
        devices = device_manager.list_devices()
        assert len([d for d in devices if d.device_id == "dev-003"]) == 1

    def test_unregister_device(self, device_manager):
        """测试注销设备."""
        device_manager.register_device(device_id="dev-unreg", name="To Remove")
        result = device_manager.unregister_device("dev-unreg")
        assert result is True
        assert device_manager.get_device("dev-unreg") is None

    def test_unregister_nonexistent(self, device_manager):
        """测试注销不存在的设备."""
        result = device_manager.unregister_device("nonexistent")
        assert result is False

    def test_get_device(self, device_manager):
        """测试获取设备."""
        device_manager.register_device(device_id="dev-get", name="Get Me")
        device = device_manager.get_device("dev-get")
        assert device is not None
        assert device.device_id == "dev-get"

    def test_get_nonexistent_device(self, device_manager):
        """测试获取不存在的设备."""
        device = device_manager.get_device("nonexistent")
        assert device is None

    def test_list_devices(self, device_manager):
        """测试列出设备."""
        for i in range(5):
            device_manager.register_device(
                device_id=f"dev-list-{i}",
                name=f"Device {i}",
            )
        devices = device_manager.list_devices()
        assert len(devices) >= 5
        assert all(isinstance(d, DeviceInfo) for d in devices)


# ============================================================
# 设备状态测试
# ============================================================

class TestDeviceStatus:
    """设备状态测试."""

    def test_update_device_status_online(self, device_manager):
        """测试设置设备在线."""
        device_manager.register_device(
            device_id="status-test",
            name="Status Test",
            device_type="phone",
        )
        result = device_manager.update_device_status(
            "status-test", DeviceOperationalStatus.ONLINE)
        assert result is True
        device = device_manager.get_device("status-test")
        assert device is not None
        assert device.status == DeviceOperationalStatus.ONLINE

    def test_update_device_status_offline(self, device_manager):
        """测试设置设备离线."""
        device_manager.register_device(device_id="offline-test", name="Offline")
        device_manager.update_device_status(
            "offline-test", DeviceOperationalStatus.OFFLINE)
        device = device_manager.get_device("offline-test")
        assert device.status == DeviceOperationalStatus.OFFLINE

    def test_update_device_status_busy(self, device_manager):
        """测试设置设备忙碌."""
        device_manager.register_device(device_id="busy-test", name="Busy")
        device_manager.update_device_status(
            "busy-test", DeviceOperationalStatus.BUSY)
        device = device_manager.get_device("busy-test")
        assert device.status == DeviceOperationalStatus.BUSY

    def test_update_status_nonexistent(self, device_manager):
        """测试更新不存在设备的状态."""
        result = device_manager.update_device_status(
            "no-device", DeviceOperationalStatus.ONLINE)
        assert result is False

    def test_initial_status_online(self, device_manager):
        """测试新注册设备初始状态为在线."""
        device = device_manager.register_device(
            device_id="initial-status", name="Initial")
        assert device.status == DeviceOperationalStatus.ONLINE


# ============================================================
# 设备分组测试
# ============================================================

class TestDeviceGrouping:
    """设备分组测试."""

    def test_create_group(self, device_manager):
        """测试创建分组."""
        result = device_manager.create_group("mobile-devices")
        assert result is True

    def test_delete_group(self, device_manager):
        """测试删除分组."""
        device_manager.create_group("temp-group")
        result = device_manager.delete_group("temp-group")
        assert result is True

    def test_add_to_group(self, device_manager):
        """测试添加设备到分组."""
        device_manager.register_device(device_id="grp-dev-1", name="Group Dev 1")
        device_manager.create_group("test-group")
        result = device_manager.add_to_group("grp-dev-1", "test-group")
        assert result is True

    def test_remove_from_group(self, device_manager):
        """测试从分组移除设备."""
        device_manager.register_device(device_id="grp-dev-2", name="Group Dev 2")
        device_manager.create_group("test-group2")
        device_manager.add_to_group("grp-dev-2", "test-group2")
        result = device_manager.remove_from_group("grp-dev-2", "test-group2")
        assert result is True

    def test_list_groups(self, device_manager):
        """测试列出分组."""
        device_manager.create_group("group-a")
        device_manager.create_group("group-b")
        groups = device_manager.list_groups()
        assert "group-a" in groups
        assert "group-b" in groups

    def test_get_group_devices(self, device_manager):
        """测试获取分组设备."""
        device_manager.register_device(device_id="gd1", name="GD1")
        device_manager.register_device(device_id="gd2", name="GD2")
        device_manager.create_group("my-group")
        device_manager.add_to_group("gd1", "my-group")
        device_manager.add_to_group("gd2", "my-group")
        devices = device_manager.get_group_devices("my-group")
        assert len(devices) == 2

    def test_add_to_nonexistent_group(self, device_manager):
        """测试添加到不存在的分组（自动创建分组）."""
        device_manager.register_device(device_id="gd3", name="GD3")
        # add_to_group 会自动创建不存在的分组
        result = device_manager.add_to_group("gd3", "auto-created-group")
        assert result is True
        # 验证分组已被创建
        assert "auto-created-group" in device_manager.list_groups()


# ============================================================
# 设备信任等级测试
# ============================================================

class TestDeviceTrust:
    """设备信任等级测试."""

    def test_set_trust_level(self, device_manager):
        """测试设置信任等级."""
        device_manager.register_device(device_id="trust-dev", name="Trust Dev")
        result = device_manager.set_trust_level(
            "trust-dev", DeviceTrustLevel.HIGH)
        assert result is True

    def test_get_trust_level(self, device_manager):
        """测试获取信任等级."""
        device_manager.register_device(device_id="trust-dev2", name="Trust Dev 2")
        device_manager.set_trust_level("trust-dev2", DeviceTrustLevel.TRUSTED)
        level = device_manager.get_trust_level("trust-dev2")
        assert level == DeviceTrustLevel.TRUSTED

    def test_initial_trust_level(self, device_manager):
        """测试新设备初始信任等级."""
        device = device_manager.register_device(
            device_id="new-trust", name="New Trust Device")
        assert device.trust_level == DeviceTrustLevel.UNTRUSTED

    def test_get_trust_level_nonexistent(self, device_manager):
        """测试获取不存在设备的信任等级."""
        level = device_manager.get_trust_level("no-device")
        assert level is None


# ============================================================
# 设备健康监测测试
# ============================================================

class TestDeviceHealth:
    """设备健康监测测试."""

    def test_record_heartbeat(self, device_manager):
        """测试记录心跳."""
        device_manager.register_device(device_id="heartbeat-dev", name="Heartbeat")
        result = device_manager.record_heartbeat(
            device_id="heartbeat-dev",
            cpu_usage=30.0,
            memory_usage=50.0,
            battery_level=80.0,
        )
        # record_heartbeat 返回 DeviceHealthScore
        assert result is not None
        assert isinstance(result, DeviceHealthScore)
        assert 0 <= result.overall_score <= 100

    def test_heartbeat_updates_last_seen(self, device_manager):
        """测试心跳更新最后活跃时间."""
        device_manager.register_device(device_id="last-seen", name="Last Seen")
        time.sleep(0.1)
        device_manager.record_heartbeat(
            device_id="last-seen", cpu_usage=10.0, memory_usage=20.0)
        device = device_manager.get_device("last-seen")
        assert device.last_seen > device.registered_at

    def test_get_health_score(self, device_manager):
        """测试获取健康评分."""
        device_manager.register_device(device_id="health-score", name="Health Score")
        device_manager.record_heartbeat(
            device_id="health-score",
            cpu_usage=25.0,
            memory_usage=40.0,
            battery_level=90.0,
        )
        score = device_manager.get_health_score("health-score")
        assert score is not None
        assert isinstance(score, DeviceHealthScore)
        assert 0 <= score.overall_score <= 100

    def test_get_health_records(self, device_manager):
        """测试获取健康记录."""
        device_manager.register_device(device_id="health-records", name="Health Records")
        for i in range(3):
            device_manager.record_heartbeat(
                device_id="health-records",
                cpu_usage=20.0 + i * 10,
                memory_usage=40.0 + i * 5,
            )
        records = device_manager.get_health_records("health-records", limit=10)
        assert len(records) >= 3
        assert all(isinstance(r, DeviceHealthRecord) for r in records)

    def test_check_offline_devices(self, device_manager):
        """测试检查离线设备."""
        # 使用很短的超时
        manager = DeviceManager(heartbeat_timeout=1)
        manager.register_device(device_id="offline-check", name="Offline Check")
        time.sleep(1.1)
        offline = manager.check_offline_devices()
        assert "offline-check" in offline

    def test_health_metric_creation(self):
        """测试健康指标创建."""
        metric = HealthMetric(
            metric_name="cpu_usage",
            value=45.5,
            unit="percent",
        )
        assert metric.metric_name == "cpu_usage"
        assert metric.value == 45.5
        assert metric.unit == "percent"
        assert metric.status == "normal"

    def test_health_metric_with_thresholds(self):
        """测试带阈值的健康指标."""
        metric = HealthMetric(
            metric_name="temperature",
            value=85.0,
            unit="celsius",
            threshold_warning=70.0,
            threshold_critical=90.0,
            status="warning",
        )
        assert metric.threshold_warning == 70.0
        assert metric.status == "warning"


# ============================================================
# 设备通知测试
# ============================================================

class TestDeviceNotification:
    """设备通知测试."""

    def test_send_notification(self, device_manager):
        """测试发送通知."""
        device_manager.register_device(device_id="notify-dev", name="Notify Dev")
        result = asyncio.run(device_manager.send_notification(
            device_id="notify-dev",
            title="Test Notification",
            body="This is a test",
            notification_type="info",
        ))
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "notification_id" in result


# ============================================================
# 异常检测测试
# ============================================================

class TestAnomalyDetection:
    """异常检测测试."""

    def test_register_anomaly_callback(self, device_manager):
        """测试注册异常回调."""
        anomalies = []

        def on_anomaly(device_id, metric, value):
            anomalies.append((device_id, metric, value))

        device_manager.register_anomaly_callback(on_anomaly)
        # 注册不应报错

    def test_high_cpu_anomaly(self, device_manager):
        """测试高 CPU 异常检测."""
        device_manager.register_device(device_id="high-cpu", name="High CPU")
        # 高 CPU 使用率
        device_manager.record_heartbeat(
            device_id="high-cpu",
            cpu_usage=95.0,
            memory_usage=50.0,
            battery_level=80.0,
        )
        score = device_manager.get_health_score("high-cpu")
        assert score is not None
        # 高 CPU 应降低健康评分
        assert score.cpu_score < 100.0


# ============================================================
# 统计测试
# ============================================================

class TestDeviceStats:
    """设备统计测试."""

    def test_get_stats(self, device_manager):
        """测试获取统计信息."""
        for i in range(3):
            device_manager.register_device(device_id=f"stat-{i}", name=f"Stat {i}")
        stats = device_manager.get_stats()
        assert isinstance(stats, dict)
        assert "total_devices" in stats
        assert stats["total_devices"] >= 3


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures:
    """数据结构测试."""

    def test_device_info_defaults(self):
        """测试 DeviceInfo 默认值."""
        info = DeviceInfo(device_id="test")
        assert info.device_id == "test"
        assert info.status == DeviceOperationalStatus.ONLINE
        assert info.trust_level == DeviceTrustLevel.UNTRUSTED
        assert info.groups == []
        assert info.cpu_cores == 0

    def test_health_score_defaults(self):
        """测试 DeviceHealthScore 默认值."""
        score = DeviceHealthScore()
        assert score.overall_score == 100.0
        assert score.cpu_score == 100.0
        assert score.memory_score == 100.0
        assert score.status == DeviceHealthStatus.HEALTHY
        assert score.recommendations == []

    def test_health_record_fields(self):
        """测试 DeviceHealthRecord 字段."""
        record = DeviceHealthRecord(
            record_id="rec-1",
            device_id="dev-1",
            timestamp=time.time(),
            cpu_usage=50.0,
            memory_usage=60.0,
            battery_level=70.0,
        )
        assert record.device_id == "dev-1"
        assert record.cpu_usage == 50.0
        assert record.memory_usage == 60.0
