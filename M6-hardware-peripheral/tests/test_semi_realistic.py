"""
P2 半真实化改造测试

覆盖：
- 智能台灯状态机（开关、亮度、色温、使用时长）
- 温湿度传感器（波动、校准、数据质量）
- 智能插座（功率、过载保护、用电量）
- 窗帘电机（慢速设备、行程、过热保护）
- 延迟模拟（有延迟/无延迟配置）
- 故障模拟（设备离线、传感器异常）
- 状态持久化（保存和加载）
- 设备注册接口（注册、发现、移除）
- 传感器波动测试（读数在合理范围内）
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from m6_hardware.models.device import Device, DeviceStatus, DeviceType
from m6_hardware.devices.smart_lamp import SmartLampSimulator
from m6_hardware.devices.temp_humidity_sensor import TempHumiditySensorSimulator
from m6_hardware.devices.smart_plug import SmartPlugSimulator
from m6_hardware.devices.curtain_motor import CurtainMotorSimulator
from m6_hardware.services.simulation_core import DelaySimulator, FaultSimulator
from m6_hardware.services.state_persistence import StatePersistence


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def mock_config():
    """mock 配置"""
    config = MagicMock()
    config.battery_drain_base = 0.1
    config.battery_low_threshold = 20.0
    return config


@pytest.fixture
def lamp_device():
    """智能台灯设备模型"""
    return Device(
        device_id="test-lamp-001",
        name="测试台灯",
        device_type=DeviceType.SMART_LAMP,
        status=DeviceStatus.ONLINE,
        battery=None,
        signal_strength=90,
    )


@pytest.fixture
def lamp_sim(lamp_device, mock_config):
    """智能台灯模拟器"""
    return SmartLampSimulator(lamp_device, config=mock_config)


@pytest.fixture
def temp_sensor_device():
    """温湿度传感器设备模型"""
    return Device(
        device_id="test-temp-001",
        name="测试温湿度传感器",
        device_type=DeviceType.TEMP_HUMIDITY,
        status=DeviceStatus.ONLINE,
        battery=90.0,
        signal_strength=80,
    )


@pytest.fixture
def temp_sim(temp_sensor_device, mock_config):
    """温湿度传感器模拟器"""
    return TempHumiditySensorSimulator(temp_sensor_device, config=mock_config)


@pytest.fixture
def plug_device():
    """智能插座设备模型"""
    return Device(
        device_id="test-plug-001",
        name="测试智能插座",
        device_type=DeviceType.SMART_PLUG,
        status=DeviceStatus.ONLINE,
        battery=None,
        signal_strength=95,
    )


@pytest.fixture
def plug_sim(plug_device, mock_config):
    """智能插座模拟器"""
    return SmartPlugSimulator(plug_device, config=mock_config)


@pytest.fixture
def curtain_device():
    """窗帘电机设备模型"""
    return Device(
        device_id="test-curtain-001",
        name="测试窗帘电机",
        device_type=DeviceType.CURTAIN_MOTOR,
        status=DeviceStatus.ONLINE,
        battery=None,
        signal_strength=75,
    )


@pytest.fixture
def curtain_sim(curtain_device, mock_config):
    """窗帘电机模拟器"""
    return CurtainMotorSimulator(curtain_device, config=mock_config)


@pytest.fixture
def temp_state_file(tmp_path):
    """临时状态文件路径"""
    return str(tmp_path / "device_states.json")


@pytest.fixture
def state_persistence(temp_state_file):
    """状态持久化管理器"""
    return StatePersistence(temp_state_file)


# =========================================================================
# 测试一：智能台灯状态机
# =========================================================================

class TestSmartLampStateMachine:
    """智能台灯状态机测试"""

    def test_initial_state(self, lamp_sim):
        """初始状态：默认开灯，亮度 80%，自然光色温"""
        assert lamp_sim._is_on is True
        assert lamp_sim._brightness == 80.0
        assert lamp_sim._color_temp == "natural"
        assert lamp_sim._usage_hours == 0.0

    def test_turn_on_off(self, lamp_sim):
        """开关灯操作"""
        result = lamp_sim.execute_action("turn_off")
        assert result["success"] is True
        assert lamp_sim._is_on is False

        result = lamp_sim.execute_action("turn_on")
        assert result["success"] is True
        assert lamp_sim._is_on is True

    def test_toggle(self, lamp_sim):
        """切换开关"""
        initial = lamp_sim._is_on
        result = lamp_sim.execute_action("toggle")
        assert result["success"] is True
        assert lamp_sim._is_on is not initial

    def test_set_brightness(self, lamp_sim):
        """设置亮度"""
        result = lamp_sim.execute_action("set_brightness", {"brightness": 50})
        assert result["success"] is True
        assert lamp_sim._brightness == 50.0

    def test_set_brightness_clamping(self, lamp_sim):
        """亮度边界限制"""
        lamp_sim.execute_action("set_brightness", {"brightness": 150})
        assert lamp_sim._brightness == 100.0

        lamp_sim.execute_action("set_brightness", {"brightness": -10})
        assert lamp_sim._brightness == 0.0

    def test_brightness_zero_turns_off(self, lamp_sim):
        """亮度设为 0 自动关灯"""
        lamp_sim.execute_action("set_brightness", {"brightness": 0})
        assert lamp_sim._is_on is False

    def test_set_color_temp(self, lamp_sim):
        """设置色温"""
        result = lamp_sim.execute_action("set_color_temp", {"mode": "warm"})
        assert result["success"] is True
        assert lamp_sim._color_temp == "warm"

    def test_set_color_temp_invalid(self, lamp_sim):
        """无效色温模式"""
        result = lamp_sim.execute_action("set_color_temp", {"mode": "invalid"})
        assert result["success"] is False
        assert result["error_code"] == "INVALID_PARAMS"

    def test_usage_hours_accumulate(self, lamp_sim):
        """使用时长累计（开灯时才计时）"""
        lamp_sim._is_on = True
        initial = lamp_sim._usage_hours
        # 模拟 1 小时
        lamp_sim._generate_sensor_data(3600.0)
        lamp_sim._update_device_state(3600.0)
        assert lamp_sim._usage_hours > initial

    def test_power_related_to_brightness(self, lamp_sim):
        """功率与亮度成正比"""
        lamp_sim._is_on = True

        lamp_sim._brightness = 100.0
        lamp_sim._generate_sensor_data(1.0)
        power_full = lamp_sim._power

        lamp_sim._brightness = 50.0
        lamp_sim._generate_sensor_data(1.0)
        power_half = lamp_sim._power

        assert power_half < power_full

    def test_get_state_vars(self, lamp_sim):
        """获取状态变量"""
        state = lamp_sim.get_state_vars()
        assert "is_on" in state
        assert "brightness" in state
        assert "color_temp" in state
        assert "usage_hours" in state

    def test_restore_state_vars(self, lamp_sim):
        """恢复状态变量"""
        new_state = {
            "is_on": False,
            "brightness": 30.0,
            "color_temp": "warm",
            "usage_hours": 100.5,
        }
        lamp_sim.restore_state_vars(new_state)
        assert lamp_sim._is_on is False
        assert lamp_sim._brightness == 30.0
        assert lamp_sim._color_temp == "warm"
        assert lamp_sim._usage_hours == 100.5


# =========================================================================
# 测试二：温湿度传感器
# =========================================================================

class TestTempHumiditySensor:
    """温湿度传感器测试"""

    def test_initial_temperature(self, temp_sim):
        """初始温度在合理范围内"""
        assert 10 <= temp_sim._temperature <= 40

    def test_temperature_fluctuation(self, temp_sim):
        """温度随机漫步波动在合理范围内"""
        temps = []
        for _ in range(100):
            temp_sim._generate_sensor_data(1.0)
            temps.append(temp_sim._temperature)
        # 温度应在合理范围内波动
        assert all(10 <= t <= 40 for t in temps)
        # 温度应该有变化（不是固定值）
        assert len(set(round(t, 1) for t in temps)) > 1

    def test_humidity_fluctuation(self, temp_sim):
        """湿度随机漫步波动在合理范围内"""
        humidities = []
        for _ in range(100):
            temp_sim._generate_sensor_data(1.0)
            humidities.append(temp_sim._humidity)
        assert all(20 <= h <= 90 for h in humidities)

    def test_calibrate_action(self, temp_sim):
        """校准操作"""
        temp_sim._calibration_status = "needs_calibration"
        result = temp_sim.execute_action("calibrate")
        assert result["success"] is True
        assert temp_sim._calibration_status == "calibrated"
        assert temp_sim._data_quality == 100

    def test_data_quality_with_low_battery(self, temp_sim, temp_sensor_device):
        """低电量降低数据质量"""
        temp_sensor_device.battery = 5.0
        temp_sim._update_data_quality()
        assert temp_sim._data_quality < 100

    def test_force_reading(self, temp_sim):
        """强制读取传感器数据"""
        result = temp_sim.execute_action("force_reading")
        assert result["success"] is True
        assert "temperature" in result
        assert "humidity" in result


# =========================================================================
# 测试三：智能插座
# =========================================================================

class TestSmartPlug:
    """智能插座测试"""

    def test_initial_state(self, plug_sim):
        """初始状态：默认开启"""
        assert plug_sim._is_on is True

    def test_turn_on_off(self, plug_sim):
        """开关操作"""
        result = plug_sim.execute_action("turn_off")
        assert result["success"] is True
        assert plug_sim._is_on is False
        assert plug_sim._power == 0.0

    def test_voltage_fluctuation(self, plug_sim):
        """电压在正常范围内波动（220V ± 5%）"""
        voltages = []
        for _ in range(50):
            plug_sim._generate_sensor_data(1.0)
            voltages.append(plug_sim._voltage)
        assert all(209 <= v <= 231 for v in voltages)

    def test_energy_accumulation(self, plug_sim):
        """用电量累计"""
        plug_sim._is_on = True
        initial = plug_sim._energy_total
        plug_sim._generate_sensor_data(3600.0)  # 1 小时
        assert plug_sim._energy_total > initial

    def test_overload_protection(self, plug_sim):
        """过载保护触发"""
        plug_sim._overload_threshold = 100.0  # 设低阈值便于测试
        plug_sim._load_base_power = 200.0
        plug_sim._load_type = "stable"
        plug_sim._is_on = True
        plug_sim._power = 150.0  # 超过阈值

        plug_sim._check_overload()
        assert plug_sim._overload_protected is True
        assert plug_sim._is_on is False

    def test_overload_prevents_turn_on(self, plug_sim):
        """过载保护状态下无法开启"""
        plug_sim._overload_protected = True
        plug_sim._is_on = False
        result = plug_sim.execute_action("turn_on")
        assert result["success"] is False
        assert result["error_code"] == "OVERLOAD_PROTECTED"

    def test_reset_energy(self, plug_sim):
        """重置用电量"""
        plug_sim._energy_total = 10.5
        result = plug_sim.execute_action("reset_energy")
        assert result["success"] is True
        assert plug_sim._energy_total == 0.0

    def test_set_overload_threshold(self, plug_sim):
        """设置过载阈值"""
        result = plug_sim.execute_action("set_overload_threshold", {"threshold": 1500})
        assert result["success"] is True
        assert plug_sim._overload_threshold == 1500.0


# =========================================================================
# 测试四：窗帘电机（慢速设备）
# =========================================================================

class TestCurtainMotor:
    """窗帘电机测试"""

    def test_initial_position(self, curtain_sim):
        """初始位置在 50%"""
        assert curtain_sim._position == 50.0

    def test_open_curtain(self, curtain_sim):
        """打开窗帘"""
        result = curtain_sim.execute_action("open")
        assert result["success"] is True
        assert curtain_sim._running_state == "opening"
        assert curtain_sim._is_moving is True

    def test_close_curtain(self, curtain_sim):
        """关闭窗帘"""
        curtain_sim._position = 0.0
        result = curtain_sim.execute_action("close")
        assert result["success"] is True
        assert curtain_sim._running_state == "closing"

    def test_stop_curtain(self, curtain_sim):
        """停止窗帘"""
        curtain_sim._start_moving(100.0)
        assert curtain_sim._is_moving is True
        result = curtain_sim.execute_action("stop")
        assert result["success"] is True
        assert curtain_sim._is_moving is False

    def test_set_position(self, curtain_sim):
        """设置窗帘位置"""
        curtain_sim._position = 0.0
        result = curtain_sim.execute_action("set_position", {"position": 70})
        assert result["success"] is True
        assert curtain_sim._target_position == 70.0

    def test_position_update_over_time(self, curtain_sim):
        """窗帘位置随时间变化"""
        curtain_sim._position = 0.0
        curtain_sim._start_moving(100.0)
        initial = curtain_sim._position
        # 模拟 10 秒运行（中速 2%/秒，应移动约 20%）
        curtain_sim._update_device_state(10.0)
        assert curtain_sim._position > initial

    def test_travel_time_calculation(self, curtain_sim):
        """行程时间计算"""
        curtain_sim._position = 0.0
        curtain_sim._speed_level = "medium"  # 2% 每秒
        travel_time = curtain_sim.get_travel_time(100.0)
        # 100% 距离 / 2%每秒 = 50 秒
        assert abs(travel_time - 50.0) < 0.1

    def test_motor_temp_rise_when_running(self, curtain_sim):
        """运行时电机温度上升"""
        curtain_sim._position = 0.0
        curtain_sim._motor_temp = 25.0
        curtain_sim._start_moving(100.0)
        curtain_sim._update_device_state(10.0)
        assert curtain_sim._motor_temp > 25.0

    def test_overheat_protection(self, curtain_sim):
        """过热保护"""
        curtain_sim._motor_temp = 75.0  # 超过 70 度过热阈值
        curtain_sim._start_moving(100.0)
        # 模拟一段时间后触发过热保护
        curtain_sim._motor_temp = 72.0
        curtain_sim._update_device_state(0.0)
        # 过热状态下启动会停止
        curtain_sim._motor_temp = 75.0
        curtain_sim._start_moving(50.0)
        curtain_sim._update_device_state(0.0)
        assert curtain_sim._is_moving is False

    def test_set_speed(self, curtain_sim):
        """设置速度"""
        result = curtain_sim.execute_action("set_speed", {"speed": "high"})
        assert result["success"] is True
        assert curtain_sim._speed_level == "high"

    def test_limit_status(self, curtain_sim):
        """限位状态检测"""
        curtain_sim._position = 0.0
        curtain_sim._generate_sensor_data(1.0)
        assert curtain_sim._limit_status == "top_limit"

        curtain_sim._position = 100.0
        curtain_sim._generate_sensor_data(1.0)
        assert curtain_sim._limit_status == "bottom_limit"


# =========================================================================
# 测试五：延迟模拟
# =========================================================================

class TestDelaySimulator:
    """延迟模拟器测试"""

    def test_delay_enabled_default(self):
        """默认启用延迟（环境变量控制）"""
        delay = DelaySimulator(enabled=True)
        assert delay.enabled is True

    @pytest.mark.asyncio
    async def test_delay_disabled(self):
        """关闭延迟后不产生延迟"""
        delay = DelaySimulator(enabled=False)
        start = time.time()
        await delay.simulate_read_delay()
        elapsed = time.time() - start
        assert elapsed < 0.01  # 几乎立即返回

    @pytest.mark.asyncio
    async def test_read_delay_range(self):
        """读取延迟在 50-200ms 范围内"""
        delay = DelaySimulator(enabled=True)
        delays = []
        for _ in range(10):
            start = time.time()
            await delay.simulate_read_delay()
            elapsed = (time.time() - start) * 1000
            delays.append(elapsed)
        # 至少有一些延迟 > 50ms
        assert any(d > 40 for d in delays)

    @pytest.mark.asyncio
    async def test_write_delay_longer_than_read(self):
        """写入延迟比读取延迟长"""
        delay = DelaySimulator(enabled=True)

        read_delays = []
        write_delays = []
        for _ in range(5):
            start = time.time()
            await delay.simulate_read_delay()
            read_delays.append((time.time() - start) * 1000)

            start = time.time()
            await delay.simulate_write_delay()
            write_delays.append((time.time() - start) * 1000)

        # 平均写入延迟应大于读取延迟
        assert sum(write_delays) / len(write_delays) > sum(read_delays) / len(read_delays)

    @pytest.mark.asyncio
    async def test_slow_device_delay_proportional(self):
        """慢速设备延迟与行程距离成正比"""
        delay = DelaySimulator(enabled=True)

        start = time.time()
        await delay.simulate_slow_device_delay(distance_ratio=0.1)
        short_time = time.time() - start

        start = time.time()
        await delay.simulate_slow_device_delay(distance_ratio=1.0)
        long_time = time.time() - start

        assert long_time > short_time

    def test_set_enabled(self):
        """动态开关延迟"""
        delay = DelaySimulator(enabled=True)
        assert delay.enabled is True
        delay.set_enabled(False)
        assert delay.enabled is False


# =========================================================================
# 测试六：故障模拟
# =========================================================================

class TestFaultSimulator:
    """故障模拟器测试"""

    def test_fault_enabled_default(self):
        """默认启用故障模拟"""
        fault = FaultSimulator(enabled=True)
        assert fault.enabled is True

    def test_fault_disabled_no_offline(self):
        """关闭故障模拟后不会触发离线"""
        fault = FaultSimulator(enabled=False)
        # 测试 100 次都不应返回离线
        results = [fault.check_offline() for _ in range(100)]
        assert not any(results)

    def test_offline_probability(self):
        """离线概率在合理范围内"""
        fault = FaultSimulator(enabled=True)
        # 测试大量样本，验证概率在合理范围
        count = 1000
        offline_count = sum(1 for _ in range(count) if fault.check_offline())
        # 允许较大误差范围，避免偶发失败
        assert 0 <= offline_count < count * 0.15  # 不超过 15%

    def test_sensor_fault_probability(self):
        """传感器故障概率较低"""
        fault = FaultSimulator(enabled=True)
        count = 1000
        fault_count = sum(1 for _ in range(count) if fault.check_sensor_fault())
        # 传感器故障概率应该很低
        assert fault_count < count * 0.05  # 不超过 5%

    def test_abnormal_reading_spike(self):
        """异常读数尖峰类型"""
        fault = FaultSimulator(enabled=True)
        normal = 100.0
        abnormal = fault.generate_abnormal_reading(normal, fault_type="spike")
        assert abnormal > normal * 2.5  # 尖峰至少是正常值的 2.5 倍

    def test_abnormal_reading_drop(self):
        """异常读数骤降类型"""
        fault = FaultSimulator(enabled=True)
        normal = 100.0
        abnormal = fault.generate_abnormal_reading(normal, fault_type="drop")
        assert abnormal < normal * 0.2  # 骤降到正常值的 20% 以下

    def test_overload_detection(self):
        """过载检测"""
        fault = FaultSimulator(enabled=True)
        assert fault.check_overload(3000, 2500) is True
        assert fault.check_overload(2000, 2500) is False

    def test_overload_disabled(self):
        """故障模拟关闭时过载检测也关闭"""
        fault = FaultSimulator(enabled=False)
        assert fault.check_overload(9999, 100) is False

    def test_low_battery_check(self):
        """低电量检测"""
        fault = FaultSimulator(enabled=True)
        assert fault.check_low_battery(15.0, 20.0) is True
        assert fault.check_low_battery(50.0, 20.0) is False
        assert fault.check_low_battery(None, 20.0) is False  # 有线供电


# =========================================================================
# 测试七：状态持久化
# =========================================================================

class TestStatePersistence:
    """状态持久化测试"""

    def test_save_and_load_device(self, state_persistence):
        """保存和加载设备状态"""
        state = {"is_on": True, "brightness": 75}
        state_persistence.save_device_state("dev-1", state)

        loaded = state_persistence.get_device_state("dev-1")
        assert loaded is not None
        assert loaded["is_on"] is True
        assert loaded["brightness"] == 75

    def test_persist_to_file(self, state_persistence, temp_state_file):
        """状态持久化到文件"""
        state = {"power": 100.0}
        state_persistence.save_device_state("dev-1", state)

        # 直接读取文件验证
        with open(temp_state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "devices" in data
        assert "dev-1" in data["devices"]

    def test_load_from_existing_file(self, temp_state_file):
        """从已有的状态文件加载"""
        # 先创建一个状态文件
        data = {
            "version": 1,
            "saved_at": "2024-01-01T00:00:00",
            "devices": {
                "dev-test": {
                    "is_on": False,
                    "brightness": 30,
                }
            }
        }
        with open(temp_state_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # 加载
        sp = StatePersistence(temp_state_file)
        loaded = sp.load()
        assert "dev-test" in loaded
        assert loaded["dev-test"]["brightness"] == 30

    def test_remove_device_state(self, state_persistence):
        """删除设备状态"""
        state_persistence.save_device_state("dev-1", {"a": 1})
        assert state_persistence.get_device_state("dev-1") is not None

        state_persistence.remove_device_state("dev-1")
        assert state_persistence.get_device_state("dev-1") is None

    def test_clear_all(self, state_persistence):
        """清空所有状态"""
        state_persistence.save_device_state("dev-1", {"a": 1})
        state_persistence.save_device_state("dev-2", {"b": 2})
        state_persistence.clear_all()
        assert len(state_persistence.load()) == 0

    def test_nonexistent_device(self, state_persistence):
        """获取不存在的设备状态返回 None"""
        assert state_persistence.get_device_state("nonexistent") is None

    def test_save_all(self, state_persistence):
        """批量保存所有设备状态"""
        devices = {
            "dev-1": {"status": "online"},
            "dev-2": {"status": "offline"},
        }
        state_persistence.save_all(devices)

        loaded = state_persistence.load()
        assert len(loaded) == 2
        assert loaded["dev-1"]["status"] == "online"


# =========================================================================
# 测试八：传感器波动验证
# =========================================================================

class TestSensorFluctuation:
    """传感器波动范围测试"""

    def test_temperature_stable_range(self, temp_sim):
        """温度在多次 tick 后仍在合理范围内"""
        for _ in range(1000):
            temp_sim._generate_sensor_data(1.0)
            assert 10 <= temp_sim._temperature <= 40

    def test_humidity_stable_range(self, temp_sim):
        """湿度在多次 tick 后仍在合理范围内"""
        for _ in range(1000):
            temp_sim._generate_sensor_data(1.0)
            assert 20 <= temp_sim._humidity <= 90

    def test_lamp_power_stable(self, lamp_sim):
        """台灯功率在合理范围内"""
        lamp_sim._is_on = True
        lamp_sim._brightness = 100.0
        for _ in range(100):
            lamp_sim._generate_sensor_data(1.0)
            # 最大功率 12W * 1.2 上限 = 14.4W
            assert lamp_sim._power <= 14.4
            assert lamp_sim._power >= 0

    def test_random_walk_within_bounds(self, lamp_sim):
        """随机游走方法始终在边界内"""
        for _ in range(1000):
            val = lamp_sim._random_walk(50.0, 0.0, 100.0, 10.0)
            assert 0.0 <= val <= 100.0


# =========================================================================
# 测试九：设备注册/发现/移除
# =========================================================================

class TestDeviceRegistration:
    """设备注册接口测试（通过 DeviceManager）"""

    @pytest.fixture
    def dm(self, mock_config, temp_state_file):
        """带临时持久化的设备管理器"""
        from m6_hardware.services.device_manager import DeviceManager
        from m6_hardware.services.state_persistence import StatePersistence
        sp = StatePersistence(temp_state_file)
        return DeviceManager(config=mock_config, state_persistence=sp)

    def test_register_new_device(self, dm):
        """注册新设备"""
        result = dm.register_device({
            "name": "新台灯",
            "device_type": "smart_lamp",
        })
        assert result["success"] is True
        assert result["device_type"] == "smart_lamp"

    def test_register_duplicate_id(self, dm):
        """重复 ID 注册失败"""
        dm.register_device({
            "device_id": "unique-id",
            "name": "设备1",
            "device_type": "smart_lamp",
        })
        result = dm.register_device({
            "device_id": "unique-id",
            "name": "设备2",
            "device_type": "smart_plug",
        })
        assert result["success"] is False
        assert result["error_code"] == "DEVICE_ALREADY_EXISTS"

    def test_register_unsupported_type(self, dm):
        """注册不支持的设备类型"""
        result = dm.register_device({
            "name": "未知设备",
            "device_type": "unknown_type",
        })
        assert result["success"] is False
        assert result["error_code"] == "UNSUPPORTED_DEVICE_TYPE"

    def test_discover_devices(self, dm):
        """发现设备"""
        discovered = dm.discover_devices()
        assert isinstance(discovered, list)
        assert len(discovered) >= 2  # 至少发现 2 个新设备

    def test_remove_device(self, dm):
        """移除设备"""
        # 先注册一个
        result = dm.register_device({
            "device_id": "to-remove",
            "name": "待删除",
            "device_type": "smart_lamp",
        })
        assert result["success"] is True

        # 再删除
        result = dm.remove_device("to-remove")
        assert result["success"] is True

        # 确认已删除
        assert dm.get_device("to-remove") is None

    def test_remove_nonexistent(self, dm):
        """删除不存在的设备"""
        result = dm.remove_device("nonexistent")
        assert result["success"] is False
        assert result["error_code"] == "DEVICE_NOT_FOUND"
