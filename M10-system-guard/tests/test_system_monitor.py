"""
M10 系统卫士 - 系统监控单元测试

测试系统资源监控模块的模拟数据生成、数据聚合、模式切换等功能。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# 确保项目根目录在路径中
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from m10_system_guard.system_monitor import (
    SystemMonitor, MockDataGenerator, get_system_monitor,
)
from m10_system_guard.models import (
    AggregationLevel, MetricType, SystemMetric,
)
from m10_system_guard.config import get_config


class TestMockDataGenerator:
    """模拟数据生成器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        # 确保沙盒模式开启
        config = get_config()
        config.sandbox.enabled = True
        self.generator = MockDataGenerator()

    def test_generate_cpu(self):
        """测试 CPU 模拟数据生成."""
        cpu = self.generator.generate_cpu()
        assert cpu.usage_percent >= 0.0
        assert cpu.usage_percent <= 100.0
        assert cpu.core_count > 0
        assert len(cpu.per_core_usage) == cpu.core_count
        assert cpu.load_avg_1min >= 0.0

    def test_generate_memory(self):
        """测试内存模拟数据生成."""
        memory = self.generator.generate_memory()
        assert memory.total_mb > 0
        assert memory.used_mb >= 0
        assert memory.available_mb >= 0
        assert memory.usage_percent >= 0.0
        assert memory.usage_percent <= 100.0
        assert abs(memory.used_mb + memory.available_mb - memory.total_mb) < 1.0

    def test_generate_disk(self):
        """测试磁盘模拟数据生成."""
        disk = self.generator.generate_disk()
        assert disk.total_gb > 0
        assert disk.usage_percent >= 0.0
        assert disk.usage_percent <= 100.0
        assert disk.read_mb_per_sec >= 0.0
        assert disk.write_mb_per_sec >= 0.0

    def test_generate_network(self):
        """测试网络模拟数据生成."""
        network = self.generator.generate_network()
        assert network.send_mb_per_sec >= 0.0
        assert network.recv_mb_per_sec >= 0.0
        assert network.connection_count >= 0
        assert network.interface != ""

    def test_generate_gpu(self):
        """测试 GPU 模拟数据生成."""
        gpu = self.generator.generate_gpu()
        assert gpu.count >= 0
        assert gpu.usage_percent >= 0.0
        assert gpu.usage_percent <= 100.0
        assert gpu.memory_percent >= 0.0
        assert gpu.temperature_celsius >= 0.0

    def test_generate_temperature(self):
        """测试温度模拟数据生成."""
        temp = self.generator.generate_temperature()
        assert temp.cpu_temp_celsius > 0
        assert temp.gpu_temp_celsius > 0
        assert temp.highest_temp_celsius > 0
        assert temp.highest_temp_source in ["CPU", "GPU", "Motherboard"]
        # 最高温度应该等于三个中的最大值
        max_temp = max(temp.cpu_temp_celsius, temp.gpu_temp_celsius, temp.motherboard_temp_celsius)
        assert abs(temp.highest_temp_celsius - max_temp) < 0.1

    def test_generate_battery(self):
        """测试电池模拟数据生成."""
        battery = self.generator.generate_battery()
        assert battery.percent >= 0.0
        assert battery.percent <= 100.0
        assert isinstance(battery.is_charging, bool)
        assert isinstance(battery.power_plugged, bool)

    def test_generate_system_metric(self):
        """测试完整系统指标生成."""
        metric = self.generator.generate_system_metric()
        assert isinstance(metric, SystemMetric)
        assert metric.timestamp > 0
        assert metric.aggregation_level == AggregationLevel.RAW
        assert metric.cpu.usage_percent >= 0
        assert metric.memory.usage_percent >= 0
        assert metric.disk.usage_percent >= 0
        assert metric.temperature.highest_temp_celsius > 0

    def test_data_continuity(self):
        """测试数据连续性（不会剧烈跳变）."""
        # 连续采样多次，检查变化幅度
        prev_cpu = self.generator.generate_cpu().usage_percent
        large_jumps = 0

        for _ in range(20):
            curr = self.generator.generate_cpu().usage_percent
            if abs(curr - prev_cpu) > 10.0:
                large_jumps += 1
            prev_cpu = curr

        # 大部分采样变化应该在合理范围内
        assert large_jumps < 10

    def test_sandbox_mode_range(self):
        """测试模拟数据在配置范围内."""
        config = get_config()
        cpu_low, cpu_high = config.sandbox.mock_cpu_range

        # 多次采样，大部分值应该在范围内
        in_range = 0
        for _ in range(50):
            cpu = self.generator.generate_cpu().usage_percent
            # 允许一定的边界偏差
            if cpu_low - 5 <= cpu <= cpu_high + 5:
                in_range += 1

        assert in_range > 35  # 70% 以上在范围内


class TestSystemMonitor:
    """系统监控器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        # 重置单例以确保测试隔离
        SystemMonitor._instance = None
        SystemMonitor._initialized = False
        self.monitor = SystemMonitor()

    def teardown_method(self):
        """每个测试用例后清理."""
        if self.monitor.is_running():
            self.monitor.stop()

    def test_singleton_pattern(self):
        """测试单例模式."""
        m1 = SystemMonitor()
        m2 = SystemMonitor()
        assert m1 is m2

    def test_get_system_monitor_function(self):
        """测试全局单例获取函数."""
        # 重置
        import m10_system_guard.system_monitor as sm
        sm._system_monitor_instance = None
        monitor = get_system_monitor()
        assert monitor is not None
        assert isinstance(monitor, SystemMonitor)

    def test_sandbox_mode_default(self):
        """测试默认沙盒模式开启."""
        assert self.monitor.sandbox_mode is True

    def test_get_latest_metric(self):
        """测试获取最新指标."""
        metric = self.monitor.get_latest()
        assert isinstance(metric, SystemMetric)
        assert metric.timestamp > 0

    def test_get_metric_value_cpu(self):
        """测试获取 CPU 指标值."""
        value = self.monitor.get_metric_value(MetricType.CPU)
        assert isinstance(value, float)
        assert 0 <= value <= 100

    def test_get_metric_value_memory(self):
        """测试获取内存指标值."""
        value = self.monitor.get_metric_value(MetricType.MEMORY)
        assert isinstance(value, float)
        assert 0 <= value <= 100

    def test_get_metric_value_temperature(self):
        """测试获取温度指标值."""
        value = self.monitor.get_metric_value(MetricType.TEMPERATURE)
        assert isinstance(value, float)
        assert value > 0

    def test_get_metric_value_all_types(self):
        """测试所有指标类型都能获取值."""
        for mtype in MetricType:
            value = self.monitor.get_metric_value(mtype)
            assert isinstance(value, float)
            assert value >= 0

    def test_get_history_raw(self):
        """测试获取原始历史数据."""
        history = self.monitor.get_history(AggregationLevel.RAW, limit=10)
        assert isinstance(history, list)

    def test_get_history_minute(self):
        """测试获取分钟级历史数据."""
        history = self.monitor.get_history(AggregationLevel.MINUTE, limit=10)
        assert isinstance(history, list)
        # 预填充了数据
        assert len(history) > 0

    def test_get_history_hour(self):
        """测试获取小时级历史数据."""
        history = self.monitor.get_history(AggregationLevel.HOUR, limit=10)
        assert isinstance(history, list)
        assert len(history) > 0

    def test_get_summary(self):
        """测试获取状态摘要."""
        summary = self.monitor.get_summary()
        assert "sandbox_mode" in summary
        assert "sample_interval" in summary
        assert "raw_data_count" in summary
        assert "minute_data_count" in summary
        assert "hour_data_count" in summary
        assert "day_data_count" in summary
        assert "latest" in summary
        assert summary["sandbox_mode"] is True

    def test_set_sandbox_mode(self):
        """测试设置沙盒模式."""
        self.monitor.set_sandbox_mode(False)
        assert self.monitor.sandbox_mode is False
        self.monitor.set_sandbox_mode(True)
        assert self.monitor.sandbox_mode is True

    def test_start_stop(self):
        """测试启动和停止监控."""
        assert self.monitor.is_running() is False
        self.monitor.start()
        time.sleep(0.1)
        assert self.monitor.is_running() is True
        self.monitor.stop()
        assert self.monitor.is_running() is False

    def test_metric_to_dict(self):
        """测试指标转字典."""
        metric = self.monitor.get_latest()
        d = metric.to_dict()
        assert isinstance(d, dict)
        assert "timestamp" in d
        assert "cpu" in d
        assert "memory" in d
        assert "disk" in d
        assert "gpu" in d
        assert "temperature" in d
        assert "battery" in d
        assert "network" in d
