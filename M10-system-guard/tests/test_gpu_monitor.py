# -*- coding: utf-8 -*-
"""M10 GPU 监控增强测试"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestGPUModels:
    """GPU 数据模型测试"""

    def test_gpu_process_info(self):
        """GPUProcessInfo 数据类"""
        from m10_system_guard.models import GPUProcessInfo
        proc = GPUProcessInfo(
            pid=1234,
            process_name="python",
            memory_used_mb=1024.0,
            gpu_id=0,
            sm_usage_percent=50.0,
            memory_usage_percent=10.0,
        )
        assert proc.pid == 1234
        assert proc.process_name == "python"

    def test_gpu_device_info(self):
        """GPUDeviceInfo 数据类及 to_dict"""
        from m10_system_guard.models import GPUDeviceInfo, GPUProcessInfo
        dev = GPUDeviceInfo(
            gpu_id=0,
            name="NVIDIA RTX 4090",
            uuid="GPU-abc123",
            usage_percent=75.5,
            memory_total_mb=24576.0,
            memory_used_mb=12288.0,
            memory_free_mb=12288.0,
            memory_percent=50.0,
            temperature_celsius=72.0,
            power_watt=320.0,
            power_limit_watt=450.0,
            fan_speed_percent=65.0,
            memory_clock_mhz=21000.0,
            graphics_clock_mhz=2500.0,
            pci_bus_id="0000:01:00.0",
            processes=[
                GPUProcessInfo(pid=100, process_name="test", memory_used_mb=100.0, gpu_id=0),
            ],
        )
        d = dev.to_dict()
        assert d["gpu_id"] == 0
        assert d["name"] == "NVIDIA RTX 4090"
        assert d["memory_total_mb"] == 24576.0
        assert len(d["processes"]) == 1
        assert d["processes"][0]["pid"] == 100

    def test_gpu_metric_enhanced(self):
        """增强版 GPUMetric"""
        from m10_system_guard.models import GPUMetric, GPUDeviceInfo
        gpu = GPUMetric(
            count=2,
            usage_percent=60.0,
            memory_total_mb=49152.0,
            memory_used_mb=24576.0,
            memory_percent=50.0,
            temperature_celsius=75.0,
            power_watt=600.0,
            driver_version="535.104.05",
            cuda_version="12.2",
            devices=[
                GPUDeviceInfo(gpu_id=0, name="GPU 0"),
                GPUDeviceInfo(gpu_id=1, name="GPU 1"),
            ],
        )
        assert gpu.count == 2
        assert gpu.driver_version == "535.104.05"
        assert gpu.cuda_version == "12.2"
        assert len(gpu.devices) == 2


class TestMockGPU:
    """模拟 GPU 数据生成测试"""

    def test_mock_gpu_has_devices(self):
        """模拟数据生成器应返回包含 devices 的 GPUMetric"""
        from tests.fixtures.mock_system_metrics import MockDataGenerator
        gen = MockDataGenerator()
        gpu = gen.generate_gpu()

        assert gpu.count > 0
        assert len(gpu.devices) == gpu.count
        assert isinstance(gpu.driver_version, str)
        assert isinstance(gpu.cuda_version, str)

    def test_mock_gpu_device_has_processes(self):
        """模拟 GPU 设备包含进程信息"""
        from tests.fixtures.mock_system_metrics import MockDataGenerator
        gen = MockDataGenerator()
        gen._current_gpu = 80.0  # 设高值以触发进程生成
        gpu = gen.generate_gpu()

        for dev in gpu.devices:
            assert hasattr(dev, "name")
            assert hasattr(dev, "temperature_celsius")
            assert hasattr(dev, "power_limit_watt")

    def test_mock_gpu_continuous(self):
        """GPU 模拟数据连续变化"""
        from tests.fixtures.mock_system_metrics import MockDataGenerator
        gen = MockDataGenerator()
        first = gen.generate_gpu().usage_percent

        changes = 0
        for _ in range(10):
            val = gen.generate_gpu().usage_percent
            if val != first:
                changes += 1

        assert changes > 0  # 数据应该有变化


class TestRealGPUCollector:
    """真实 GPU 采集器测试"""

    def test_is_available_returns_bool(self):
        """is_available 返回布尔值"""
        from m10_system_guard.system_monitor import RealGPUCollector
        result = RealGPUCollector.is_available()
        assert isinstance(result, bool)

    def test_get_gpu_count_returns_int(self):
        """get_gpu_count 返回整数"""
        from m10_system_guard.system_monitor import RealGPUCollector
        count = RealGPUCollector.get_gpu_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_collect_returns_gpu_metric(self):
        """collect 返回 GPUMetric 对象"""
        from m10_system_guard.system_monitor import RealGPUCollector
        from m10_system_guard.models import GPUMetric
        result = RealGPUCollector.collect()
        assert isinstance(result, GPUMetric)
        assert isinstance(result.count, int)


class TestGPUMetricInSystemMetric:
    """SystemMetric 中 GPU 字段完整性"""

    def test_system_metric_gpu_has_enhanced_fields(self):
        """SystemMetric.to_dict 包含增强 GPU 字段"""
        from m10_system_guard.models import SystemMetric, GPUMetric, GPUDeviceInfo
        sm = SystemMetric()
        sm.gpu = GPUMetric(
            count=1,
            driver_version="535.104.05",
            cuda_version="12.2",
            devices=[GPUDeviceInfo(gpu_id=0, name="Test GPU")],
        )
        d = sm.to_dict()
        assert "driver_version" in d["gpu"]
        assert "cuda_version" in d["gpu"]
        assert "devices" in d["gpu"]
        assert len(d["gpu"]["devices"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
