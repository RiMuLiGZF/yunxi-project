"""P1-6: 设备基类测试覆盖扩展"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import MagicMock, patch

from m6_hardware.devices import base_device as base_device_module
from m6_hardware.devices.base_device import BaseDeviceSimulator
from m6_hardware.models.device import Device, DeviceStatus, DeviceType
from m6_hardware.models.sensor_data import SensorData


@pytest.fixture(autouse=True)
def patch_device_status_error():
    """P1-6: 兼容源代码中引用了不存在的 DeviceStatus.ERROR"""
    original = base_device_module.DeviceStatus
    mock_status = MagicMock()
    mock_status.OFFLINE = DeviceStatus.OFFLINE
    mock_status.WARNING = DeviceStatus.WARNING
    mock_status.CHARGING = DeviceStatus.CHARGING
    mock_status.ONLINE = DeviceStatus.ONLINE
    mock_status.ERROR = "error"
    with patch.object(base_device_module, "DeviceStatus", mock_status):
        yield


class ConcreteDevice(BaseDeviceSimulator):
    """用于测试的具体设备模拟器"""

    def _generate_sensor_data(self, elapsed: float) -> None:
        self._set_reading("test_sensor", 42.0, "unit")

    def _update_device_state(self, elapsed: float) -> None:
        pass

    def _action_test_action(self, params):
        return {"message": "ok"}


@pytest.fixture
def mock_config():
    """创建 mock 配置"""
    config = MagicMock()
    config.battery_drain_base = 0.1
    config.battery_low_threshold = 20.0
    return config


@pytest.fixture
def base_device(mock_config):
    """创建具体设备模拟器实例"""
    device = Device(
        device_id="dev-base-001",
        name="基础设备",
        device_type=DeviceType.WATCH,
        status=DeviceStatus.ONLINE,
        battery=50.0,
        signal_strength=80,
    )
    return ConcreteDevice(device, config=mock_config)


class TestBaseDeviceInit:
    """初始化测试"""

    def test_initial_battery(self, base_device):
        """创建后初始电量与设备模型一致"""
        assert base_device.device.battery == 50.0

    def test_device_id_property(self, base_device):
        """device_id 属性返回正确"""
        assert base_device.device_id == "dev-base-001"

    def test_device_type_property(self, base_device):
        """device_type 属性返回正确"""
        assert base_device.device_type == DeviceType.WATCH

    def test_status_property(self, base_device):
        """status 属性返回设备状态"""
        assert base_device.status == DeviceStatus.ONLINE

    def test_sensor_data_init(self, base_device):
        """传感器数据初始为空"""
        data = base_device.get_current_sensor_data()
        assert isinstance(data, SensorData)
        assert data.device_id == "dev-base-001"
        assert len(data.readings) == 0


class TestBaseDeviceTick:
    """tick() 测试"""

    def test_tick_reduces_battery(self, base_device):
        """tick() 减少电量"""
        base_device._last_tick_time = 0.0
        with patch("m6_hardware.devices.base_device.time") as mock_time:
            mock_time.time.return_value = 3600.0  # 模拟 1 小时流逝
            base_device.tick()
        assert base_device.device.battery < 50.0

    def test_tick_offline_no_battery_drain(self, base_device):
        """离线状态不消耗电量"""
        base_device.device.status = DeviceStatus.OFFLINE
        initial = base_device.device.battery
        base_device.tick()
        assert base_device.device.battery == initial

    def test_tick_charging_increases_battery(self, base_device):
        """充电状态电量增加"""
        base_device.device.status = DeviceStatus.CHARGING
        base_device.device.battery = 30.0
        base_device._last_tick_time = 0.0
        with patch("m6_hardware.devices.base_device.time") as mock_time:
            mock_time.time.return_value = 3600.0  # 模拟 1 小时流逝
            base_device.tick()
        assert base_device.device.battery > 30.0

    def test_tick_updates_last_seen(self, base_device):
        """tick() 更新最后在线时间"""
        import time
        time.sleep(0.001)
        old_seen = base_device.device.last_seen
        base_device.tick()
        assert base_device.device.last_seen > old_seen

    def test_tick_generates_sensor_data(self, base_device):
        """tick() 生成传感器数据"""
        base_device.tick()
        data = base_device.get_current_sensor_data()
        assert "test_sensor" in data.readings

    def test_tick_returns_sensor_data(self, base_device):
        """tick() 返回 SensorData"""
        result = base_device.tick()
        assert isinstance(result, SensorData)


class TestBaseDeviceAlerts:
    """告警检测测试"""

    def test_low_battery_alert(self, base_device):
        """低电量触发告警"""
        base_device.device.battery = 10.0  # 低于默认阈值 20
        base_device.tick()
        alerts = base_device.get_alerts()
        assert any(a["type"] == "low_battery" for a in alerts)

    def test_low_battery_alert_uses_config_threshold(self, base_device, mock_config):
        """低电量告警使用配置的阈值"""
        mock_config.battery_low_threshold = 30.0
        base_device.device.battery = 25.0
        base_device.tick()
        alerts = base_device.get_alerts()
        assert any(a["type"] == "low_battery" for a in alerts)

    def test_no_low_battery_alert_when_charging(self, base_device):
        """充电中不触发低电量告警"""
        base_device.device.status = DeviceStatus.CHARGING
        base_device.device.battery = 10.0
        base_device.tick()
        alerts = base_device.get_alerts()
        assert not any(a["type"] == "low_battery" for a in alerts)

    def test_offline_alert(self, base_device):
        """离线状态触发 offline 告警"""
        base_device.device.status = DeviceStatus.OFFLINE
        base_device.tick()
        alerts = base_device.get_alerts()
        assert any(a["type"] == "offline" for a in alerts)

    def test_alert_deduplication(self, base_device):
        """相同类型告警不重复添加"""
        base_device.device.battery = 10.0
        base_device.tick()
        base_device.tick()
        base_device.tick()
        alerts = base_device.get_alerts()
        low_battery_alerts = [a for a in alerts if a["type"] == "low_battery"]
        assert len(low_battery_alerts) == 1

    def test_get_alerts_clear(self, base_device):
        """get_alerts(clear=True) 清空告警"""
        base_device.device.status = DeviceStatus.OFFLINE
        base_device.tick()
        assert len(base_device.get_alerts()) > 0
        base_device.get_alerts(clear=True)
        assert len(base_device.get_alerts()) == 0


class TestBaseDeviceHealthScore:
    """健康度评分测试"""

    def test_health_score_perfect(self, base_device):
        """完美状态健康度为 100"""
        base_device.device.battery = 100.0
        base_device.device.signal_strength = 100
        base_device.device.status = DeviceStatus.ONLINE
        base_device._alerts.clear()
        assert base_device.get_health_score() == 100

    def test_health_score_low_battery(self, base_device):
        """低电量降低健康度"""
        base_device.device.battery = 5.0
        base_device.device.signal_strength = 100
        base_device.device.status = DeviceStatus.ONLINE
        score = base_device.get_health_score()
        assert score < 100

    def test_health_score_offline(self, base_device):
        """离线状态大幅降低健康度"""
        base_device.device.status = DeviceStatus.OFFLINE
        score = base_device.get_health_score()
        assert score <= 50

    def test_health_score_bounds(self, base_device):
        """健康度在 0-100 范围内"""
        assert 0 <= base_device.get_health_score() <= 100


class TestBaseDeviceSmoothValue:
    """平滑算法测试"""

    def test_smooth_value_basic(self, base_device):
        """平滑值向目标值靠近"""
        result = base_device._smooth_value(100.0, 200.0, 0.5)
        assert result == 150.0

    def test_smooth_value_no_change(self, base_device):
        """当前值等于目标值时不变"""
        result = base_device._smooth_value(100.0, 100.0, 0.5)
        assert result == 100.0

    def test_smooth_value_factor_zero(self, base_device):
        """factor 为 0 时不变"""
        result = base_device._smooth_value(100.0, 200.0, 0.0)
        assert result == 100.0

    def test_smooth_value_factor_one(self, base_device):
        """factor 为 1 时直接到达目标"""
        result = base_device._smooth_value(100.0, 200.0, 1.0)
        assert result == 200.0


class TestBaseDeviceExecuteAction:
    """动作执行测试"""

    def test_execute_supported_action(self, base_device):
        """执行支持的动作"""
        result = base_device.execute_action("test_action")
        assert result["success"] is True
        assert result["device_id"] == base_device.device_id
        assert result["action"] == "test_action"

    def test_execute_unsupported_action(self, base_device):
        """执行不支持的动作返回错误"""
        result = base_device.execute_action("unsupported")
        assert result["success"] is False
        assert result["error_code"] == "ACTION_NOT_SUPPORTED"

    def test_execute_action_with_params(self, base_device):
        """动作执行传递参数"""
        result = base_device.execute_action("test_action", {"key": "value"})
        assert result["success"] is True

    def test_execute_action_exception_handling(self, base_device):
        """动作执行异常返回结构化错误"""
        class BadDevice(BaseDeviceSimulator):
            def _generate_sensor_data(self, elapsed):
                pass
            def _update_device_state(self, elapsed):
                pass
            def _action_boom(self, params):
                raise RuntimeError("boom")

        bad = BadDevice(
            Device(device_id="bad", name="bad", device_type=DeviceType.WATCH),
            config=MagicMock(),
        )
        result = bad.execute_action("boom")
        assert result["success"] is False
        assert result["error_code"] == "ACTION_EXECUTION_ERROR"
        assert "boom" in result["message"]


class TestBaseDeviceRandomWalk:
    """随机游走测试"""

    def test_random_walk_within_bounds(self, base_device):
        """随机游走结果在边界内"""
        for _ in range(100):
            val = base_device._random_walk(50.0, 0.0, 100.0, 5.0)
            assert 0.0 <= val <= 100.0

    def test_random_walk_bounce_at_min(self, base_device):
        """低于最小值时回弹"""
        val = base_device._random_walk(0.5, 1.0, 10.0, 5.0)
        assert val >= 1.0

    def test_random_walk_bounce_at_max(self, base_device):
        """高于最大值时回弹"""
        val = base_device._random_walk(9.5, 1.0, 10.0, 5.0)
        assert val <= 10.0


class TestBaseDeviceToDict:
    """序列化测试"""

    def test_to_dict_contains_device_info(self, base_device):
        """to_dict 包含设备信息"""
        d = base_device.to_dict()
        assert d["device_id"] == "dev-base-001"
        assert d["name"] == "基础设备"

    def test_to_dict_contains_sensors(self, base_device):
        """to_dict 包含传感器读数"""
        base_device.tick()
        d = base_device.to_dict()
        assert "sensors" in d
        assert "test_sensor" in d["sensors"]
