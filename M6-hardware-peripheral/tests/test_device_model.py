"""P2-11: 设备模型测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from m6_hardware.models.device import Device, DeviceStatus, DeviceType


class TestDeviceType:
    def test_device_type_values(self):
        assert DeviceType.WATCH.value == "watch"
        assert DeviceType.RING.value == "ring"
        assert DeviceType.AR.value == "ar"
        assert DeviceType.DRONE.value == "drone"
        assert DeviceType.DESKTOP.value == "desktop"
        assert DeviceType.LAPTOP.value == "laptop"


class TestDeviceStatus:
    def test_device_status_values(self):
        assert DeviceStatus.ONLINE.value == "online"
        assert DeviceStatus.OFFLINE.value == "offline"
        assert DeviceStatus.WARNING.value == "warning"
        assert DeviceStatus.CHARGING.value == "charging"


class TestDeviceModel:
    def test_create_device(self):
        dev = Device(
            device_id="test-001",
            name="测试手表",
            device_type=DeviceType.WATCH,
            status=DeviceStatus.ONLINE,
        )
        assert dev.device_id == "test-001"
        assert dev.name == "测试手表"
        assert dev.device_type == DeviceType.WATCH
        assert dev.status == DeviceStatus.ONLINE

    def test_device_default_status(self):
        dev = Device(device_id="test-002", name="测试设备", device_type=DeviceType.RING)
        assert dev.status == DeviceStatus.ONLINE

    def test_device_default_battery_none(self):
        dev = Device(device_id="test-003", name="测试", device_type=DeviceType.DESKTOP)
        assert dev.battery is None

    def test_device_battery_bounds(self):
        dev = Device(device_id="t1", name="t", device_type=DeviceType.WATCH, battery=50.0)
        assert dev.battery == 50.0

    def test_device_signal_default(self):
        dev = Device(device_id="t1", name="t", device_type=DeviceType.WATCH)
        assert dev.signal_strength == 85

    def test_device_to_dict(self):
        dev = Device(
            device_id="test-004",
            name="测试眼镜",
            device_type=DeviceType.AR,
            status=DeviceStatus.ONLINE,
        )
        d = dev.to_dict()
        assert d["device_id"] == "test-004"
        assert d["name"] == "测试眼镜"
        assert d["device_type"] == "ar"
        assert d["status"] == "online"
        assert "last_seen" in d

    def test_device_capabilities_list(self):
        dev = Device(
            device_id="t1",
            name="t",
            device_type=DeviceType.WATCH,
            capabilities=["heart_rate", "steps"],
        )
        assert "heart_rate" in dev.capabilities
        assert len(dev.capabilities) == 2
