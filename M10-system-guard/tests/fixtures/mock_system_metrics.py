"""Mock system metrics generator for sandbox/testing."""

from __future__ import annotations

import random
import time

from m10_system_guard.config import get_config
from m10_system_guard.models import (
    SystemMetric, CPUMetric, MemoryMetric, DiskMetric,
    NetworkMetric, GPUMetric, TemperatureMetric, BatteryMetric,
    AggregationLevel, MetricType,
)


class MockDataGenerator:
    """模拟数据生成器.

    沙盒模式下使用，生成符合真实分布的模拟系统指标数据。
    数据具有连续性（不会突变），接近真实系统行为。
    """

    def __init__(self):
        """初始化模拟数据生成器."""
        config = get_config()
        self.sandbox_cfg = config.sandbox

        # 当前值（用于生成连续变化的数据）
        self._current_cpu = 35.0
        self._current_memory = 50.0
        self._current_disk = 60.0
        self._current_gpu = 20.0
        self._current_temp = 55.0
        self._current_battery = 80.0
        self._current_net_send = 5.0
        self._current_net_recv = 10.0

        # 磁盘总量等固定值
        self._disk_total_gb = 512.0
        self._memory_total_mb = 16384.0
        self._gpu_memory_total_mb = 8192.0
        self._cpu_core_count = 8
        self._gpu_count = 1
        self._battery_design_mwh = 60000.0

    def _step_value(self, current: float, low: float, high: float, step: float = 2.0) -> float:
        """让数值在范围内连续变化（带微小随机步长）.

        Args:
            current: 当前值
            low: 范围下限
            high: 范围上限
            step: 最大步长

        Returns:
            变化后的值
        """
        change = random.uniform(-step, step)
        new_val = current + change
        # 限制在范围内
        new_val = max(low, min(high, new_val))
        return new_val

    def generate_cpu(self) -> CPUMetric:
        """生成 CPU 模拟数据."""
        cfg = self.sandbox_cfg
        self._current_cpu = self._step_value(
            self._current_cpu, cfg.mock_cpu_range[0], cfg.mock_cpu_range[1], step=3.0
        )

        per_core = []
        for i in range(self._cpu_core_count):
            core_usage = self._step_value(
                self._current_cpu + random.uniform(-15, 15), 0.0, 100.0, step=5.0
            )
            per_core.append(round(core_usage, 1))

        load_1 = self._current_cpu / 100.0 * self._cpu_core_count
        load_5 = load_1 * random.uniform(0.9, 1.1)
        load_15 = load_1 * random.uniform(0.8, 1.2)

        return CPUMetric(
            usage_percent=round(self._current_cpu, 1),
            core_count=self._cpu_core_count,
            per_core_usage=per_core,
            load_avg_1min=round(load_1, 2),
            load_avg_5min=round(load_5, 2),
            load_avg_15min=round(load_15, 2),
        )

    def generate_memory(self) -> MemoryMetric:
        """生成内存模拟数据."""
        cfg = self.sandbox_cfg
        self._current_memory = self._step_value(
            self._current_memory, cfg.mock_memory_range[0], cfg.mock_memory_range[1], step=1.5
        )

        used_mb = self._memory_total_mb * self._current_memory / 100.0
        available_mb = self._memory_total_mb - used_mb

        swap_total = 4096.0
        swap_percent = random.uniform(5.0, 30.0)
        swap_used = swap_total * swap_percent / 100.0

        return MemoryMetric(
            total_mb=self._memory_total_mb,
            used_mb=round(used_mb, 1),
            available_mb=round(available_mb, 1),
            usage_percent=round(self._current_memory, 1),
            swap_total_mb=swap_total,
            swap_used_mb=round(swap_used, 1),
            swap_percent=round(swap_percent, 1),
        )

    def generate_disk(self) -> DiskMetric:
        """生成磁盘模拟数据."""
        cfg = self.sandbox_cfg
        self._current_disk = self._step_value(
            self._current_disk, cfg.mock_disk_range[0], cfg.mock_disk_range[1], step=0.5
        )

        used_gb = self._disk_total_gb * self._current_disk / 100.0
        free_gb = self._disk_total_gb - used_gb

        read_speed = self._step_value(50.0, 0.1, 200.0, step=20.0)
        write_speed = self._step_value(30.0, 0.1, 150.0, step=15.0)
        io_wait = self._step_value(5.0, 0.0, 30.0, step=3.0)

        return DiskMetric(
            total_gb=self._disk_total_gb,
            used_gb=round(used_gb, 1),
            free_gb=round(free_gb, 1),
            usage_percent=round(self._current_disk, 1),
            read_mb_per_sec=round(read_speed, 2),
            write_mb_per_sec=round(write_speed, 2),
            io_wait_percent=round(io_wait, 1),
        )

    def generate_network(self) -> NetworkMetric:
        """生成网络模拟数据."""
        cfg = self.sandbox_cfg
        speed_range = cfg.mock_network_speed_range

        self._current_net_send = self._step_value(
            self._current_net_send, speed_range[0], speed_range[1], step=3.0
        )
        self._current_net_recv = self._step_value(
            self._current_net_recv, speed_range[0], speed_range[1], step=3.0
        )

        connections = random.randint(50, 200)

        return NetworkMetric(
            bytes_sent_mb=round(self._current_net_send * 60, 1),
            bytes_recv_mb=round(self._current_net_recv * 60, 1),
            send_mb_per_sec=round(self._current_net_send, 2),
            recv_mb_per_sec=round(self._current_net_recv, 2),
            connection_count=connections,
            interface="eth0",
        )

    def generate_gpu(self) -> "GPUMetric":
        """生成 GPU 模拟数据（支持多 GPU 设备详情）."""
        cfg = self.sandbox_cfg
        self._current_gpu = self._step_value(
            self._current_gpu, cfg.mock_gpu_range[0], cfg.mock_gpu_range[1], step=4.0
        )
        mem_used = self._gpu_memory_total_mb * (self._current_gpu / 100.0)

        # 模拟多 GPU 设备
        devices = []
        for gpu_id in range(self._gpu_count):
            gpu_usage = max(0, min(100, self._current_gpu + random.uniform(-10, 10)))
            gpu_mem_used = self._gpu_memory_total_mb * (gpu_usage / 100.0)
            gpu_temp = 55 + gpu_usage * 0.35
            gpu_power = 80 + gpu_usage * 1.8

            # 模拟 GPU 进程
            processes = []
            if gpu_usage > 30:
                from m10_system_guard.models import GPUProcessInfo
                processes = [
                    GPUProcessInfo(
                        pid=10000 + gpu_id * 10 + i,
                        process_name=f"worker_{gpu_id}_{i}",
                        memory_used_mb=gpu_mem_used * 0.4 / (i + 1),
                        gpu_id=gpu_id,
                        sm_usage_percent=gpu_usage * 0.5 / (i + 1),
                        memory_usage_percent=gpu_usage * 0.3 / (i + 1),
                    )
                    for i in range(min(3, int(gpu_usage / 20)))
                ]

            from m10_system_guard.models import GPUDeviceInfo
            devices.append(GPUDeviceInfo(
                gpu_id=gpu_id,
                name=f"NVIDIA RTX Mock {4090 - gpu_id}",
                uuid=f"GPU-{gpu_id:08x}-mock",
                usage_percent=gpu_usage,
                memory_total_mb=self._gpu_memory_total_mb,
                memory_used_mb=gpu_mem_used,
                memory_free_mb=self._gpu_memory_total_mb - gpu_mem_used,
                memory_percent=gpu_usage,
                temperature_celsius=gpu_temp,
                power_watt=gpu_power,
                power_limit_watt=450.0,
                fan_speed_percent=30 + gpu_usage * 0.5,
                memory_clock_mhz=18000,
                graphics_clock_mhz=2000 + gpu_usage * 5,
                pci_bus_id=f"0000:0{gpu_id}:00.0",
                processes=processes,
            ))

        # 模拟全部进程列表
        all_processes = []
        for dev in devices:
            all_processes.extend(dev.processes)

        return GPUMetric(
            count=self._gpu_count,
            usage_percent=self._current_gpu,
            memory_total_mb=self._gpu_memory_total_mb * self._gpu_count,
            memory_used_mb=mem_used * self._gpu_count,
            memory_percent=self._current_gpu,
            temperature_celsius=self._current_temp,
            power_watt=(100.0 + self._current_gpu * 1.5) * self._gpu_count,
            driver_version="535.104.05-mock",
            cuda_version="12.2",
            devices=devices,
            processes=all_processes,
        )

    def generate_temperature(self) -> TemperatureMetric:
        """生成温度模拟数据."""
        cfg = self.sandbox_cfg
        self._current_temp = self._step_value(
            self._current_temp, cfg.mock_temperature_range[0], cfg.mock_temperature_range[1], step=2.0
        )

        cpu_temp = self._current_temp
        gpu_temp = self._current_temp + random.uniform(3.0, 8.0)
        mb_temp = self._current_temp - random.uniform(5.0, 10.0)

        sources = {
            "CPU": cpu_temp,
            "GPU": gpu_temp,
            "Motherboard": mb_temp,
        }
        highest = max(sources.items(), key=lambda x: x[1])

        return TemperatureMetric(
            cpu_temp_celsius=round(cpu_temp, 1),
            gpu_temp_celsius=round(gpu_temp, 1),
            motherboard_temp_celsius=round(mb_temp, 1),
            highest_temp_celsius=round(highest[1], 1),
            highest_temp_source=highest[0],
        )

    def generate_battery(self) -> BatteryMetric:
        """生成电池模拟数据."""
        cfg = self.sandbox_cfg
        self._current_battery = self._step_value(
            self._current_battery, cfg.mock_battery_range[0], cfg.mock_battery_range[1], step=0.5
        )

        is_charging = random.random() < 0.3
        power_plugged = is_charging or random.random() < 0.2

        if is_charging:
            remaining = 0
        else:
            remaining = int(self._current_battery * 6.0)  # 假设满电约10小时

        current_capacity = self._battery_design_mwh * self._current_battery / 100.0

        return BatteryMetric(
            percent=round(self._current_battery, 1),
            is_charging=is_charging,
            remaining_minutes=remaining,
            power_plugged=power_plugged,
            design_capacity_mwh=self._battery_design_mwh,
            current_capacity_mwh=round(current_capacity, 1),
        )

    def generate_system_metric(self) -> SystemMetric:
        """生成完整的系统指标快照."""
        return SystemMetric(
            timestamp=time.time(),
            cpu=self.generate_cpu(),
            memory=self.generate_memory(),
            disk=self.generate_disk(),
            network=self.generate_network(),
            gpu=self.generate_gpu(),
            temperature=self.generate_temperature(),
            battery=self.generate_battery(),
            aggregation_level=AggregationLevel.RAW,
        )
