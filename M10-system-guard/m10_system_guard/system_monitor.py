"""
M10 系统卫士 - 系统资源监控模块 (A1)

负责采集系统各项指标：CPU、内存、磁盘、网络、GPU、温度、电池。
沙盒模式优先：默认使用模拟数据生成器，不调用真实系统 API。
支持切换到真实模式的开关。
数据聚合：原始/分钟/小时/天 四级聚合。
"""

from __future__ import annotations

import random
import time
import threading
from collections import deque
from typing import Any

from .config import get_config
from .models import (
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
                from .models import GPUProcessInfo
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

            from .models import GPUDeviceInfo
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




class RealGPUCollector:
    """真实 GPU 数据采集器（基于 NVML）.

    使用 nvidia-ml-py (pynvml) 采集真实 GPU 数据。
    如果库未安装，所有方法返回空数据。
    """

    _initialized = False
    _nvml_available = False

    @classmethod
    def _ensure_init(cls):
        """确保 NVML 已初始化."""
        if cls._initialized:
            return cls._nvml_available
        cls._initialized = True
        try:
            import pynvml
            pynvml.nvmlInit()
            cls._nvml_available = True
            return True
        except ImportError:
            return False
        except Exception:
            return False

    @classmethod
    def is_available(cls) -> bool:
        """检测是否有可用的 GPU."""
        if not cls._ensure_init():
            return False
        try:
            import pynvml
            return pynvml.nvmlDeviceGetCount() > 0
        except Exception:
            return False

    @classmethod
    def get_gpu_count(cls) -> int:
        """获取 GPU 数量."""
        if not cls._ensure_init():
            return 0
        try:
            import pynvml
            return pynvml.nvmlDeviceGetCount()
        except Exception:
            return 0

    @classmethod
    def collect(cls) -> "GPUMetric":
        """采集所有 GPU 指标."""
        from .models import GPUMetric, GPUDeviceInfo, GPUProcessInfo

        if not cls._ensure_init():
            return GPUMetric(count=0)

        try:
            import pynvml
        except ImportError:
            return GPUMetric(count=0)

        try:
            count = pynvml.nvmlDeviceGetCount()
            devices = []
            all_processes = []
            total_usage = 0.0
            total_mem_total = 0.0
            total_mem_used = 0.0
            total_power = 0.0
            max_temp = 0.0

            # 驱动版本
            try:
                driver_ver = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver_ver, bytes):
                    driver_ver = driver_ver.decode("utf-8", errors="replace")
            except Exception:
                driver_ver = ""

            # CUDA 版本
            try:
                cuda_ver = pynvml.nvmlSystemGetCudaDriverVersion()
                cuda_major = cuda_ver // 1000
                cuda_minor = (cuda_ver % 1000) // 10
                cuda_version_str = f"{cuda_major}.{cuda_minor}"
            except Exception:
                cuda_version_str = ""

            for gpu_id in range(count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)

                    # GPU 名称
                    try:
                        name = pynvml.nvmlDeviceGetName(handle)
                        if isinstance(name, bytes):
                            name = name.decode("utf-8", errors="replace")
                    except Exception:
                        name = f"GPU {gpu_id}"

                    # UUID
                    try:
                        uuid = pynvml.nvmlDeviceGetUUID(handle)
                        if isinstance(uuid, bytes):
                            uuid = uuid.decode("utf-8", errors="replace")
                    except Exception:
                        uuid = f"GPU-{gpu_id}"

                    # 利用率
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        gpu_util = float(util.gpu)
                        mem_util = float(util.memory)
                    except Exception:
                        gpu_util = 0.0
                        mem_util = 0.0

                    # 显存
                    try:
                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        mem_total = mem_info.total / (1024 * 1024)  # MB
                        mem_used = mem_info.used / (1024 * 1024)
                        mem_free = mem_info.free / (1024 * 1024)
                        mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0
                    except Exception:
                        mem_total = 0.0
                        mem_used = 0.0
                        mem_free = 0.0
                        mem_percent = 0.0

                    # 温度
                    try:
                        temp = float(pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU
                        ))
                    except Exception:
                        temp = 0.0

                    # 功耗
                    try:
                        power = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0  # mW -> W
                    except Exception:
                        power = 0.0

                    # 功耗限制
                    try:
                        power_limit = float(pynvml.nvmlDeviceGetPowerManagementLimit(handle)) / 1000.0
                    except Exception:
                        power_limit = 0.0

                    # 风扇速度
                    try:
                        fan_speed = float(pynvml.nvmlDeviceGetFanSpeed(handle))
                    except Exception:
                        fan_speed = 0.0

                    # 显存时钟
                    try:
                        mem_clock = float(pynvml.nvmlDeviceGetClockInfo(
                            handle, pynvml.NVML_CLOCK_MEM
                        ))
                    except Exception:
                        mem_clock = 0.0

                    # 图形时钟
                    try:
                        gfx_clock = float(pynvml.nvmlDeviceGetClockInfo(
                            handle, pynvml.NVML_CLOCK_GRAPHICS
                        ))
                    except Exception:
                        gfx_clock = 0.0

                    # PCI 信息
                    try:
                        pci_info = pynvml.nvmlDeviceGetPciInfo(handle)
                        pci_bus_id = getattr(pci_info, "busId", "")
                        if isinstance(pci_bus_id, bytes):
                            pci_bus_id = pci_bus_id.decode("utf-8", errors="replace")
                    except Exception:
                        pci_bus_id = ""

                    # GPU 进程
                    processes = []
                    try:
                        proc_infos = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                        for pi in proc_infos:
                            proc_mem = pi.usedGpuMemory / (1024 * 1024) if pi.usedGpuMemory else 0.0
                            try:
                                proc_name = pynvml.nvmlSystemGetProcessName(pi.pid)
                                if isinstance(proc_name, bytes):
                                    proc_name = proc_name.decode("utf-8", errors="replace")
                            except Exception:
                                proc_name = f"pid_{pi.pid}"

                            processes.append(GPUProcessInfo(
                                pid=pi.pid,
                                process_name=proc_name,
                                memory_used_mb=proc_mem,
                                gpu_id=gpu_id,
                                sm_usage_percent=0.0,  # NVML 不直接提供单进程 SM 使用率
                                memory_usage_percent=proc_mem / mem_total * 100 if mem_total > 0 else 0,
                            ))
                    except Exception:
                        pass

                    device = GPUDeviceInfo(
                        gpu_id=gpu_id,
                        name=name,
                        uuid=uuid,
                        usage_percent=gpu_util,
                        memory_total_mb=mem_total,
                        memory_used_mb=mem_used,
                        memory_free_mb=mem_free,
                        memory_percent=mem_percent,
                        temperature_celsius=temp,
                        power_watt=power,
                        power_limit_watt=power_limit,
                        fan_speed_percent=fan_speed,
                        memory_clock_mhz=mem_clock,
                        graphics_clock_mhz=gfx_clock,
                        pci_bus_id=pci_bus_id,
                        processes=processes,
                    )
                    devices.append(device)
                    all_processes.extend(processes)

                    total_usage += gpu_util
                    total_mem_total += mem_total
                    total_mem_used += mem_used
                    total_power += power
                    if temp > max_temp:
                        max_temp = temp

                except Exception as e:
                    continue

            avg_usage = total_usage / count if count > 0 else 0
            avg_mem_percent = (total_mem_used / total_mem_total * 100) if total_mem_total > 0 else 0

            return GPUMetric(
                count=count,
                usage_percent=round(avg_usage, 1),
                memory_total_mb=round(total_mem_total, 1),
                memory_used_mb=round(total_mem_used, 1),
                memory_percent=round(avg_mem_percent, 1),
                temperature_celsius=round(max_temp, 1),
                power_watt=round(total_power, 1),
                driver_version=driver_ver,
                cuda_version=cuda_version_str,
                devices=devices,
                processes=all_processes,
            )

        except Exception:
            return GPUMetric(count=0)

class SystemMonitor:
    """系统资源监控器.

    负责采集、存储和聚合系统指标数据。
    沙盒模式优先：默认使用模拟数据。
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_monitor()

    def _init_monitor(self):
        """初始化监控器."""
        config = get_config()
        self.config = config
        self.sandbox_mode = config.sandbox.enabled
        self.sample_interval = config.sandbox.sample_interval_seconds

        # 模拟数据生成器
        self.mock_generator = MockDataGenerator()

        # 数据存储（各级聚合）
        self._raw_data = deque(maxlen=config.data_aggregation.raw_retention_minutes * 60)
        # 数据库持久化（延迟启用）
        self._db_enabled = False
        self._minute_data = deque(maxlen=config.data_aggregation.minute_retention_hours * 60)
        self._hour_data = deque(maxlen=config.data_aggregation.hour_retention_days * 24)
        self._day_data = deque(maxlen=config.data_aggregation.day_retention_days)

        # 运行状态
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # 最新指标
        self._latest_metric = None

        # 生成一些初始数据
        self._prepopulate_data()

    def _prepopulate_data(self):
        """预填充一些历史数据."""
        # 生成一些分钟级数据
        for i in range(30):
            metric = self.mock_generator.generate_system_metric()
            metric.timestamp = time.time() - (30 - i) * 60
            metric.aggregation_level = AggregationLevel.MINUTE
            self._minute_data.append(metric)

        # 生成一些小时级数据
        for i in range(12):
            metric = self.mock_generator.generate_system_metric()
            metric.timestamp = time.time() - (12 - i) * 3600
            metric.aggregation_level = AggregationLevel.HOUR
            self._hour_data.append(metric)

    def enable_db_persistence(self) -> None:
        """启用指标数据库持久化."""
        self._db_enabled = True

    def start(self):
        """启动监控采样."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._sampling_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止监控采样."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _sampling_loop(self):
        """采样循环（后台线程）."""
        while self._running:
            try:
                metric = self._sample_once()
                with self._lock:
                    self._latest_metric = metric
                    self._raw_data.append(metric)
                    # 持久化到数据库（异步，不阻塞采集循环）
                    if self._db_enabled:
                        try:
                            from .repositories.metric_repository import MetricRepository
                            MetricRepository.add_metric(
                                metric_type='system',
                                value=metric.to_dict(),
                                aggregation_level='raw',
                                timestamp=metric.timestamp,
                            )
                        except Exception:
                            pass
                    self._check_aggregation(metric)
            except Exception:
                pass
            time.sleep(self.sample_interval)

    def _sample_once(self) -> SystemMetric:
        """执行一次采样.

        沙盒模式下使用模拟数据，真实模式下调用 psutil。
        """
        if self.sandbox_mode:
            return self.mock_generator.generate_system_metric()
        else:
            # 真实模式：调用 psutil（此处为占位，沙盒模式优先）
            return self._sample_real()

    def _sample_real(self) -> SystemMetric:
        """真实模式采样 - 使用 psutil 采集真实系统指标.

        P2-27: 实现真实 API 调用，沙盒模式关闭时采集真实系统数据。
        如果 psutil 不可用或采集失败，自动回退到模拟数据。
        """
        try:
            import psutil
            import time

            # ---- CPU ----
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count(logical=True) or 1
            per_core = psutil.cpu_percent(interval=None, percpu=True) or [cpu_percent] * cpu_count
            try:
                load_1, load_5, load_15 = psutil.getloadavg()
            except (AttributeError, OSError):
                load_1 = cpu_percent / 100.0 * cpu_count
                load_5 = load_1 * 0.95
                load_15 = load_1 * 0.9

            cpu_metric = CPUMetric(
                usage_percent=round(cpu_percent, 1),
                core_count=cpu_count,
                per_core_usage=[round(v, 1) for v in per_core],
                load_avg_1min=round(load_1, 2),
                load_avg_5min=round(load_5, 2),
                load_avg_15min=round(load_15, 2),
            )

            # ---- 内存 ----
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            mem_metric = MemoryMetric(
                total_mb=round(mem.total / (1024 * 1024), 1),
                used_mb=round(mem.used / (1024 * 1024), 1),
                available_mb=round(mem.available / (1024 * 1024), 1),
                usage_percent=round(mem.percent, 1),
                swap_total_mb=round(swap.total / (1024 * 1024), 1),
                swap_used_mb=round(swap.used / (1024 * 1024), 1),
                swap_percent=round(swap.percent, 1),
            )

            # ---- 磁盘 ----
            disk_usage = psutil.disk_usage("/")
            try:
                disk_io = psutil.disk_io_counters()
                # 计算速度需要前后采样，这里用累计值做近似
                read_mb = disk_io.read_bytes / (1024 * 1024) if disk_io else 0
                write_mb = disk_io.write_bytes / (1024 * 1024) if disk_io else 0
                read_speed = round(read_mb * 0.01, 2)  # 近似值
                write_speed = round(write_mb * 0.01, 2)
            except (AttributeError, OSError):
                read_speed = 0.0
                write_speed = 0.0

            disk_metric = DiskMetric(
                total_gb=round(disk_usage.total / (1024 ** 3), 1),
                used_gb=round(disk_usage.used / (1024 ** 3), 1),
                free_gb=round(disk_usage.free / (1024 ** 3), 1),
                usage_percent=round(disk_usage.percent, 1),
                read_mb_per_sec=read_speed,
                write_mb_per_sec=write_speed,
                io_wait_percent=0.0,
            )

            # ---- 网络 ----
            try:
                net_io = psutil.net_io_counters()
                bytes_sent = net_io.bytes_sent / (1024 * 1024)
                bytes_recv = net_io.bytes_recv / (1024 * 1024)
                # 近似速度
                send_speed = round(bytes_sent * 0.001, 2)
                recv_speed = round(bytes_recv * 0.001, 2)
            except (AttributeError, OSError):
                bytes_sent = 0.0
                bytes_recv = 0.0
                send_speed = 0.0
                recv_speed = 0.0

            try:
                connections = len(psutil.net_connections())
            except (AttributeError, OSError, psutil.AccessDenied):
                connections = 0

            net_metric = NetworkMetric(
                bytes_sent_mb=round(bytes_sent, 1),
                bytes_recv_mb=round(bytes_recv, 1),
                send_mb_per_sec=send_speed,
                recv_mb_per_sec=recv_speed,
                connection_count=connections,
                interface="default",
            )

            # ---- GPU (可选，尝试 pynvml) ----
            gpu_metric = self._sample_gpu_real()

            # ---- 温度 ----
            temp_metric = self._sample_temperature_real()

            # ---- 电池 ----
            battery_metric = self._sample_battery_real()

            return SystemMetric(
                timestamp=time.time(),
                cpu=cpu_metric,
                memory=mem_metric,
                disk=disk_metric,
                network=net_metric,
                gpu=gpu_metric,
                temperature=temp_metric,
                battery=battery_metric,
                aggregation_level=AggregationLevel.RAW,
            )

        except Exception as e:
            # 真实采集失败，回退到模拟数据
            print(f"[SystemMonitor] 真实采集失败，回退到模拟数据: {e}")
            return self.mock_generator.generate_system_metric()

    def _sample_gpu_real(self) -> GPUMetric:
        """真实 GPU 采样 - 尝试使用 pynvml，失败回退 mock."""
        try:
            try:
                import pynvml
                pynvml.nvmlInit()
                gpu_count = pynvml.nvmlDeviceGetCount()
                if gpu_count > 0:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                    pynvml.nvmlShutdown()

                    return GPUMetric(
                        count=gpu_count,
                        usage_percent=round(util.gpu, 1),
                        memory_total_mb=round(mem.total / (1024 * 1024), 1),
                        memory_used_mb=round(mem.used / (1024 * 1024), 1),
                        memory_percent=round(util.memory, 1),
                        temperature_celsius=round(float(temp), 1),
                        power_watt=round(power, 1),
                    )
            except (ImportError, Exception):
                pass

            # 尝试用 psutil 的相关信息做近似
            import psutil
            gpu_count = 0
            try:
                # Windows 上尝试 WMI
                if hasattr(psutil, "WINDOWS") and psutil.WINDOWS:
                    pass  # 留待后续扩展
            except Exception:
                pass
            return self.mock_generator.generate_gpu()

        except Exception:
            return self.mock_generator.generate_gpu()

    def _sample_temperature_real(self) -> TemperatureMetric:
        """真实温度采样 - 尝试 psutil.sensors_temperatures，失败回退 mock."""
        try:
            import psutil
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    cpu_temp = 0.0
                    gpu_temp = 0.0
                    mb_temp = 0.0
                    highest = 0.0
                    highest_src = "unknown"

                    for name, entries in temps.items():
                        if entries:
                            current = entries[0].current
                            if "core" in name.lower() or "cpu" in name.lower():
                                cpu_temp = max(cpu_temp, current)
                            elif "gpu" in name.lower():
                                gpu_temp = max(gpu_temp, current)
                            else:
                                mb_temp = max(mb_temp, current)
                            if current > highest:
                                highest = current
                                highest_src = name

                    return TemperatureMetric(
                        cpu_temp_celsius=round(cpu_temp, 1),
                        gpu_temp_celsius=round(gpu_temp, 1),
                        motherboard_temp_celsius=round(mb_temp, 1),
                        highest_temp_celsius=round(highest, 1),
                        highest_temp_source=highest_src,
                    )
        except Exception:
            pass
        return self.mock_generator.generate_temperature()

    def _sample_battery_real(self) -> BatteryMetric:
        """真实电池采样 - 使用 psutil.sensors_battery，失败回退 mock."""
        try:
            import psutil
            if hasattr(psutil, "sensors_battery"):
                battery = psutil.sensors_battery()
                if battery:
                    design_cap = 60000.0  # 设计容量近似值
                    current_cap = design_cap * battery.percent / 100.0
                    return BatteryMetric(
                        percent=round(battery.percent, 1),
                        is_charging=battery.power_plugged,
                        remaining_minutes=int(battery.secs_left / 60) if battery.secs_left and battery.secs_left > 0 else 0,
                        power_plugged=battery.power_plugged,
                        design_capacity_mwh=design_cap,
                        current_capacity_mwh=round(current_cap, 1),
                    )
        except Exception:
            pass
        return self.mock_generator.generate_battery()

    def _check_aggregation(self, metric: SystemMetric):
        """检查是否需要进行数据聚合."""
        now = metric.timestamp

        # 检查是否需要生成分钟级聚合
        if not self._minute_data or now - self._minute_data[-1].timestamp >= 60:
            self._aggregate_minute()

        # 检查是否需要生成小时级聚合
        if not self._hour_data or now - self._hour_data[-1].timestamp >= 3600:
            self._aggregate_hour()

        # 检查是否需要生成天级聚合
        if not self._day_data or now - self._day_data[-1].timestamp >= 86400:
            self._aggregate_day()

    def _aggregate_metrics(self, metrics: list, level: AggregationLevel) -> SystemMetric:
        """将一组指标聚合成一个指标（取平均值）."""
        if not metrics:
            return SystemMetric(aggregation_level=level)

        n = len(metrics)
        avg_cpu = sum(m.cpu.usage_percent for m in metrics) / n
        avg_mem = sum(m.memory.usage_percent for m in metrics) / n
        avg_disk = sum(m.disk.usage_percent for m in metrics) / n
        avg_gpu = sum(m.gpu.usage_percent for m in metrics) / n
        avg_temp = sum(m.temperature.highest_temp_celsius for m in metrics) / n
        avg_battery = sum(m.battery.percent for m in metrics) / n

        peak_cpu = max(m.cpu.usage_percent for m in metrics)
        peak_mem = max(m.memory.usage_percent for m in metrics)

        aggregated = SystemMetric(
            timestamp=metrics[-1].timestamp,
            aggregation_level=level,
        )
        aggregated.cpu.usage_percent = round(avg_cpu, 1)
        aggregated.memory.usage_percent = round(avg_mem, 1)
        aggregated.disk.usage_percent = round(avg_disk, 1)
        aggregated.gpu.usage_percent = round(avg_gpu, 1)
        aggregated.temperature.highest_temp_celsius = round(avg_temp, 1)
        aggregated.battery.percent = round(avg_battery, 1)

        return aggregated

    def _aggregate_minute(self):
        """生成分钟级聚合."""
        if len(self._raw_data) < 10:
            return
        raw_list = list(self._raw_data)[-60:]
        if raw_list:
            aggregated = self._aggregate_metrics(raw_list, AggregationLevel.MINUTE)
            self._minute_data.append(aggregated)
            if self._db_enabled:
                try:
                    from .repositories.metric_repository import MetricRepository
                    MetricRepository.add_metric(
                        metric_type='system',
                        value=aggregated.to_dict(),
                        aggregation_level='minute',
                        timestamp=aggregated.timestamp,
                    )
                except Exception:
                    pass

    def _aggregate_hour(self):
        """生成小时级聚合."""
        if len(self._minute_data) < 30:
            return
        minute_list = list(self._minute_data)[-60:]
        if minute_list:
            aggregated = self._aggregate_metrics(minute_list, AggregationLevel.HOUR)
            self._hour_data.append(aggregated)

    def _aggregate_day(self):
        """生成天级聚合."""
        if len(self._hour_data) < 12:
            return
        hour_list = list(self._hour_data)[-24:]
        if hour_list:
            aggregated = self._aggregate_metrics(hour_list, AggregationLevel.DAY)
            self._day_data.append(aggregated)

    def get_latest(self) -> SystemMetric:
        """获取最新的系统指标."""
        if self._latest_metric:
            return self._latest_metric
        # 如果没有运行，生成一个即时快照
        return self._sample_once()

    def get_metric_value(self, metric_type: MetricType) -> float:
        """获取指定类型的指标值.

        Args:
            metric_type: 指标类型

        Returns:
            指标值（百分比或数值）
        """
        latest = self.get_latest()
        mapping = {
            MetricType.CPU: latest.cpu.usage_percent,
            MetricType.MEMORY: latest.memory.usage_percent,
            MetricType.DISK: latest.disk.usage_percent,
            MetricType.NETWORK: max(latest.network.send_mb_per_sec, latest.network.recv_mb_per_sec),
            MetricType.GPU: latest.gpu.usage_percent,
            MetricType.TEMPERATURE: latest.temperature.highest_temp_celsius,
            MetricType.BATTERY: latest.battery.percent,
        }
        return mapping.get(metric_type, 0.0)

    def get_history(self, level: AggregationLevel = AggregationLevel.RAW, limit: int = 60) -> list:
        """获取历史数据.

        Args:
            level: 聚合级别
            limit: 返回数据条数

        Returns:
            系统指标列表
        """
        with self._lock:
            data_map = {
                AggregationLevel.RAW: self._raw_data,
                AggregationLevel.MINUTE: self._minute_data,
                AggregationLevel.HOUR: self._hour_data,
                AggregationLevel.DAY: self._day_data,
            }
            data = data_map.get(level, deque())
            return list(data)[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """获取系统状态摘要."""
        latest = self.get_latest()
        return {
            "sandbox_mode": self.sandbox_mode,
            "sample_interval": self.sample_interval,
            "raw_data_count": len(self._raw_data),
            "minute_data_count": len(self._minute_data),
            "hour_data_count": len(self._hour_data),
            "day_data_count": len(self._day_data),
            "latest": latest.to_dict(),
        }

    def set_sandbox_mode(self, enabled: bool):
        """设置沙盒模式.

        Args:
            enabled: 是否启用沙盒模式
        """
        self.sandbox_mode = enabled

    def is_running(self) -> bool:
        """检查监控是否在运行."""
        return self._running


# 全局单例获取函数
_system_monitor_instance = None


def get_system_monitor() -> SystemMonitor:
    """获取系统监控器单例."""
    global _system_monitor_instance
    if _system_monitor_instance is None:
        _system_monitor_instance = SystemMonitor()
    return _system_monitor_instance
