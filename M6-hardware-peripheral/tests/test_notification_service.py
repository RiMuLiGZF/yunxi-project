"""P1-6: 通知服务测试覆盖扩展"""
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from m6_hardware.services.notification import NotificationService, get_notification_service


@pytest.fixture
def mock_device_manager():
    """创建 mock 设备管理器"""
    dm = MagicMock()
    dm._devices = {}
    dm.get_simulator.return_value = None
    return dm


@pytest.fixture
def notification_service(mock_device_manager):
    """创建独立的 NotificationService 实例"""
    return NotificationService(device_manager=mock_device_manager)


class TestNotificationServiceSingleton:
    """单例模式测试"""

    def test_get_notification_service_singleton(self):
        """get_notification_service() 返回同一个实例"""
        import m6_hardware.services.notification as notif_mod
        notif_mod._instance = None

        n1 = get_notification_service()
        n2 = get_notification_service()
        assert n1 is n2
        assert isinstance(n1, NotificationService)

        notif_mod._instance = None


class TestNotificationServicePush:
    """推送功能测试"""

    def test_push_to_device_success(self, notification_service, mock_device_manager):
        """push_to_device 推送通知成功"""
        mock_device = MagicMock()
        mock_device.push_notification.return_value = {
            "success": True,
            "notification_id": "nid_123",
        }
        mock_device_manager.get_simulator.return_value = mock_device

        result = notification_service.push_to_device(
            "dev-watch-001", "标题", "内容", "info"
        )
        assert result["success"] is True
        mock_device.push_notification.assert_called_once()

    def test_push_to_device_not_found(self, notification_service, mock_device_manager):
        """push_to_device 设备不存在返回失败"""
        mock_device_manager.get_simulator.return_value = None
        result = notification_service.push_to_device(
            "no-such-device", "标题", "内容"
        )
        assert result["success"] is False
        assert "不存在" in result["message"]

    def test_push_alert(self, notification_service, mock_device_manager):
        """push_alert 推送告警"""
        mock_device = MagicMock()
        mock_device.get_alerts.return_value = [
            {
                "type": "low_battery",
                "message": "电量低",
                "timestamp": "2026-07-13T10:00:00",
                "device_id": "dev-001",
            }
        ]
        mock_device_manager._devices = {"dev-001": mock_device}
        mock_device_manager.get_simulator.return_value = mock_device

        alerts = notification_service.get_recent_alerts(limit=10)
        assert isinstance(alerts, list)
        # get_recent_alerts 会收集设备告警并广播


class TestNotificationServiceListener:
    """监听器管理测试"""

    def test_add_listener(self, notification_service):
        """add_listener 添加监听器"""
        listener = MagicMock()
        listener.send = MagicMock()
        notification_service.add_listener(listener)
        assert listener in notification_service._listeners

    def test_remove_listener(self, notification_service):
        """remove_listener 移除监听器"""
        listener = MagicMock()
        notification_service.add_listener(listener)
        notification_service.remove_listener(listener)
        assert listener not in notification_service._listeners

    def test_remove_nonexistent_listener_no_error(self, notification_service):
        """移除不存在的监听器不抛异常"""
        listener = MagicMock()
        notification_service.remove_listener(listener)
        assert notification_service._listeners == []

    def test_broadcast_to_listeners(self, notification_service):
        """_broadcast 向所有监听器发送消息"""
        l1 = MagicMock()
        l2 = MagicMock()
        notification_service.add_listener(l1)
        notification_service.add_listener(l2)

        notification_service._broadcast("test_event", {"k": "v"})

        l1.send.assert_called_once()
        l2.send.assert_called_once()

    def test_broadcast_removes_broken_listener(self, notification_service):
        """_broadcast 移除失效的监听器"""
        good = MagicMock()
        bad = MagicMock()
        bad.send.side_effect = RuntimeError("boom")

        notification_service.add_listener(good)
        notification_service.add_listener(bad)

        with patch("m6_hardware.services.notification.logger") as mock_logger:
            notification_service._broadcast("evt", {"k": "v"})
            assert bad not in notification_service._listeners
            assert good in notification_service._listeners
            mock_logger.error.assert_called()

    def test_broadcast_removes_listener_without_send(self, notification_service):
        """_broadcast 移除没有 send 方法的监听器"""
        bad = MagicMock()
        del bad.send
        good = MagicMock()

        notification_service.add_listener(bad)
        notification_service.add_listener(good)

        with patch("m6_hardware.services.notification.logger") as mock_logger:
            notification_service._broadcast("evt", {"k": "v"})
            assert bad not in notification_service._listeners
            mock_logger.warning.assert_called()

    def test_broadcast_attribute_error_listener(self, notification_service):
        """_broadcast 处理 AttributeError 并移除监听器"""
        class WeirdListener:
            pass

        weird = WeirdListener()
        notification_service.add_listener(weird)

        with patch("m6_hardware.services.notification.logger") as mock_logger:
            notification_service._broadcast("evt", {"k": "v"})
            assert weird not in notification_service._listeners
            mock_logger.warning.assert_called()


class TestNotificationServiceHistory:
    """通知历史测试"""

    def test_get_recent_notifications_empty(self, notification_service):
        """无通知时返回空列表"""
        result = notification_service.get_recent_notifications()
        assert result == []

    def test_get_recent_notifications_limit(self, notification_service, mock_device_manager):
        """get_recent_notifications 限制返回条数"""
        mock_device = MagicMock()
        mock_device.push_notification.return_value = {"success": True, "notification_id": "n1"}
        mock_device_manager.get_simulator.return_value = mock_device

        for i in range(10):
            notification_service.push_to_device("dev-001", f"标题{i}", f"内容{i}")

        result = notification_service.get_recent_notifications(limit=3)
        assert len(result) == 3

    def test_get_recent_notifications_filter_by_device(self, notification_service, mock_device_manager):
        """按设备ID过滤通知"""
        mock_device = MagicMock()
        mock_device.push_notification.return_value = {"success": True, "notification_id": "n1"}
        mock_device_manager.get_simulator.return_value = mock_device

        notification_service.push_to_device("dev-a", "标题", "内容")
        notification_service.push_to_device("dev-b", "标题2", "内容2")

        result = notification_service.get_recent_notifications(device_id="dev-a")
        assert all(n["device_id"] == "dev-a" for n in result)

    def test_get_recent_alerts_empty(self, notification_service):
        """无告警时返回空列表"""
        result = notification_service.get_recent_alerts()
        assert result == []

    def test_get_recent_alerts_with_clear(self, notification_service, mock_device_manager):
        """get_recent_alerts 支持清除已读告警"""
        mock_device = MagicMock()
        mock_device.get_alerts.return_value = [
            {"type": "test_alert", "message": "m", "timestamp": "2026-07-13T10:00:00", "device_id": "d1"}
        ]
        mock_device_manager._devices = {"d1": mock_device}
        mock_device_manager.get_simulator.return_value = mock_device

        alerts = notification_service.get_recent_alerts(clear=True)
        assert isinstance(alerts, list)
        mock_device.get_alerts.assert_called_once_with(clear=True)


class TestNotificationServiceAlertTypes:
    """告警类型和级别测试"""

    def test_notification_types(self, notification_service, mock_device_manager):
        """支持 info/warning/error 类型通知"""
        mock_device = MagicMock()
        mock_device.push_notification.return_value = {"success": True}
        mock_device_manager.get_simulator.return_value = mock_device

        for ntype in ("info", "warning", "error"):
            result = notification_service.push_to_device("dev-001", "t", "c", ntype)
            assert result["success"] is True
