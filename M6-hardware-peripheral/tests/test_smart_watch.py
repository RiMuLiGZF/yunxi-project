"""P1-6: 智能手表模拟器测试覆盖扩展"""
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from m6_hardware.devices.smart_watch import SmartWatchSimulator
from m6_hardware.models.device import Device, DeviceStatus, DeviceType
from m6_hardware.models.errors import M6Exception


@pytest.fixture
def mock_config():
    """创建 mock 配置"""
    config = MagicMock()
    config.battery_drain_base = 0.1
    config.battery_low_threshold = 20.0
    return config


@pytest.fixture
def watch_device():
    """创建手表设备模型"""
    return Device(
        device_id="dev-watch-test-001",
        name="测试手表",
        device_type=DeviceType.WATCH,
        status=DeviceStatus.ONLINE,
        battery=80.0,
        signal_strength=85,
    )


@pytest.fixture
def smart_watch(watch_device, mock_config):
    """创建智能手表模拟器"""
    return SmartWatchSimulator(watch_device)


class TestSmartWatchDefaults:
    """默认状态测试"""

    def test_default_heart_rate(self, smart_watch):
        """创建后默认心率约 72"""
        assert smart_watch._heart_rate == 72.0

    def test_default_steps(self, smart_watch):
        """创建后默认步数为 0"""
        assert smart_watch._steps == 0

    def test_default_calories(self, smart_watch):
        """创建后默认卡路里为 0"""
        assert smart_watch._calories == 0.0

    def test_default_sleep_score(self, smart_watch):
        """创建后默认睡眠分数约 85"""
        assert smart_watch._sleep_score == 85.0

    def test_default_blood_oxygen(self, smart_watch):
        """创建后默认血氧约 97"""
        assert smart_watch._blood_oxygen == 97.0

    def test_default_activity_state(self, smart_watch):
        """创建后默认活动状态为 rest"""
        assert smart_watch._activity_state == "rest"

    def test_device_type(self, smart_watch):
        """设备类型为 WATCH"""
        assert smart_watch.device_type == DeviceType.WATCH


class TestSmartWatchTick:
    """tick() 传感器数据生成测试"""

    def test_tick_generates_sensor_data(self, smart_watch):
        """tick() 生成传感器数据"""
        data = smart_watch.tick()
        readings = data.readings
        assert "heart_rate" in readings
        assert "steps" in readings
        assert "calories" in readings
        assert "sleep_score" in readings
        assert "blood_oxygen" in readings

    def test_tick_heart_rate_range(self, smart_watch):
        """心率在合理范围 50-200 内"""
        for _ in range(20):
            smart_watch.tick()
        hr = smart_watch._sensor_data.readings["heart_rate"].value
        assert 50 <= hr <= 200

    def test_tick_steps_range(self, smart_watch):
        """步数在 0-10000 范围内"""
        smart_watch._activity_state = "walking"
        for _ in range(20):
            smart_watch.tick()
        steps = smart_watch._sensor_data.readings["steps"].value
        assert 0 <= steps <= 10000

    def test_tick_blood_oxygen_range(self, smart_watch):
        """血氧在合理范围 92-100 内"""
        for _ in range(20):
            smart_watch.tick()
        spo2 = smart_watch._sensor_data.readings["blood_oxygen"].value
        assert 92 <= spo2 <= 100

    def test_tick_sleep_score_range(self, smart_watch):
        """睡眠分数在合理范围 70-95 内（睡眠状态下）"""
        smart_watch._activity_state = "sleeping"
        for _ in range(20):
            smart_watch.tick()
        score = smart_watch._sensor_data.readings["sleep_score"].value
        assert 70 <= score <= 95

    def test_tick_consumes_battery(self, smart_watch):
        """tick() 消耗电量"""
        import time
        smart_watch._last_tick_time = time.time() - 3600  # 模拟 1 小时间隔
        initial = smart_watch.device.battery
        smart_watch.tick()
        assert smart_watch.device.battery < initial

    def test_tick_running_consumes_more_battery(self, smart_watch):
        """运动模式下电量消耗更快"""
        import time
        smart_watch._activity_state = "rest"
        smart_watch._last_tick_time = time.time() - 3600
        smart_watch.tick()
        rest_battery = smart_watch.device.battery

        # 创建新手表，设置为 running
        watch2 = Device(
            device_id="w2", name="w2", device_type=DeviceType.WATCH,
            status=DeviceStatus.ONLINE, battery=80.0, signal_strength=85,
        )
        sw2 = SmartWatchSimulator(watch2)
        sw2._activity_state = "running"
        sw2._last_tick_time = time.time() - 3600
        sw2.tick()

        assert sw2.device.battery < rest_battery


class TestSmartWatchActions:
    """动作执行测试"""

    def test_action_start_exercise(self, smart_watch):
        """start_exercise 开始运动"""
        result = smart_watch.execute_action("start_exercise", {"type": "run"})
        assert result["success"] is True
        assert smart_watch._activity_state == "running"
        assert "exercise_id" in result

    def test_action_start_exercise_walking(self, smart_watch):
        """start_exercise 非 run 类型为 walking"""
        result = smart_watch.execute_action("start_exercise", {"type": "walk"})
        assert result["success"] is True
        assert smart_watch._activity_state == "walking"

    def test_action_stop_exercise(self, smart_watch):
        """stop_exercise 停止运动"""
        smart_watch._activity_state = "running"
        result = smart_watch.execute_action("stop_exercise")
        assert result["success"] is True
        assert smart_watch._activity_state == "rest"
        assert "summary" in result

    def test_action_find_device(self, smart_watch):
        """find_device 响铃震动"""
        result = smart_watch.execute_action("find_device")
        assert result["success"] is True
        assert "响铃" in result["message"]

    def test_action_unsupported(self, smart_watch):
        """不支持的动作返回错误信息"""
        result = smart_watch.execute_action("fly_to_moon")
        assert result["success"] is False
        assert result["error_code"] == "ACTION_NOT_SUPPORTED"
        assert result["device_id"] == smart_watch.device_id


class TestSmartWatchSensorRanges:
    """传感器数据合理性测试"""

    def test_sensor_readings_have_units(self, smart_watch):
        """传感器读数带有单位"""
        smart_watch.tick()
        r = smart_watch._sensor_data.readings
        assert r["heart_rate"].unit == "bpm"
        assert r["steps"].unit == "步"
        assert r["calories"].unit == "kcal"
        assert r["sleep_score"].unit == "分"
        assert r["blood_oxygen"].unit == "%"

    def test_calories_increases_over_time(self, smart_watch):
        """卡路里随时间增加"""
        import time
        smart_watch._activity_state = "running"
        smart_watch._state_change_time = time.time()
        smart_watch._last_tick_time = time.time() - 3600  # 模拟 1 小时间隔
        initial = smart_watch._calories
        smart_watch.tick()
        assert smart_watch._calories > initial

    def test_steps_increase_when_walking(self, smart_watch):
        """走路时步数增加"""
        import time
        smart_watch._activity_state = "walking"
        smart_watch._state_change_time = time.time()
        smart_watch._last_tick_time = time.time() - 60  # 模拟 60 秒间隔
        initial = smart_watch._steps
        smart_watch.tick()
        assert smart_watch._steps > initial

    def test_steps_static_when_rest(self, smart_watch):
        """静止时步数不增加"""
        smart_watch._activity_state = "rest"
        initial = smart_watch._steps
        for _ in range(10):
            smart_watch.tick()
        assert smart_watch._steps == initial

    def test_signal_strength_in_range(self, smart_watch):
        """信号强度在 0-100 范围内"""
        for _ in range(50):
            smart_watch.tick()
        assert 0 <= smart_watch.device.signal_strength <= 100
