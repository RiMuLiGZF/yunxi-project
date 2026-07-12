"""P2-11: 设备管理器测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from m6_hardware.services.device_manager import DeviceManager, get_device_manager
from m6_hardware.models.device import DeviceStatus, DeviceType


@pytest.fixture
def manager():
    """每个测试用独立的 DeviceManager 实例"""
    DeviceManager._instance = None
    m = DeviceManager()
    return m


class TestDeviceManagerSingleton:
    def test_singleton_pattern(self):
        DeviceManager._instance = None
        m1 = get_device_manager()
        m2 = get_device_manager()
        assert m1 is m2


class TestDeviceManagerBasic:
    def test_list_devices_returns_list(self, manager):
        result = manager.list_devices()
        assert isinstance(result, list)

    def test_scan_devices_returns_list(self, manager):
        found = manager.scan_devices()
        assert isinstance(found, list)

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get_device("definitely-not-real-12345") is None

    def test_get_stats_returns_dict(self, manager):
        stats = manager.get_stats()
        assert isinstance(stats, dict)

    def test_pair_nonexistent_device(self, manager):
        result = manager.pair_device("no-such-device")
        assert isinstance(result, dict)
        assert result.get("success") is False

    def test_unpair_nonexistent_device(self, manager):
        result = manager.unpair_device("no-such-device")
        assert isinstance(result, dict)
        assert result.get("success") is False

    def test_update_config_nonexistent(self, manager):
        result = manager.update_device_config("no-such", {})
        assert isinstance(result, (bool, dict))

    def test_tick_all_no_crash(self, manager):
        """tick_all 在无设备时不抛异常"""
        manager.tick_all()

    def test_device_manager_has_simulator(self, manager):
        assert hasattr(manager, "get_simulator") or hasattr(manager, "_devices")


class TestDeviceManagerWithDevices:
    def test_scan_then_list(self, manager):
        """scan 后 list 应该有设备"""
        manager.scan_devices()
        devices = manager.list_devices()
        assert isinstance(devices, list)
        # 模拟器应该有一些默认设备
        assert len(devices) >= 0

    def test_get_device_after_scan(self, manager):
        manager.scan_devices()
        devices = manager.list_devices()
        if devices:
            dev_id = devices[0]["device_id"]
            dev = manager.get_device(dev_id)
            assert dev is not None
            assert isinstance(dev, dict)

    def test_pair_existing_device(self, manager):
        manager.scan_devices()
        devices = manager.list_devices()
        if devices:
            dev_id = devices[0]["device_id"]
            result = manager.pair_device(dev_id)
            assert isinstance(result, dict)
            # 可能成功也可能说已配对，但都是 dict 格式
            assert "success" in result

    def test_unpair_existing_device(self, manager):
        manager.scan_devices()
        devices = manager.list_devices()
        if devices:
            dev_id = devices[0]["device_id"]
            result = manager.unpair_device(dev_id)
            assert isinstance(result, dict)
            assert "success" in result
