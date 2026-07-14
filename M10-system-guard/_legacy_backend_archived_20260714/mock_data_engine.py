"""
云汐 M10 系统卫士 - 模拟数据生成引擎
在沙盒模式下生成逼真的系统监控数据，完全不调用真实系统API
"""

import random
import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

# 兼容相对导入和直接运行
try:
    from .config import get_settings
except ImportError:
    from config import get_settings


class MockDataEngine:
    """
    模拟数据生成引擎
    生成具有真实波动感的系统监控数据，支持CPU/内存/磁盘/网络/GPU/电池等多维度
    """

    def __init__(self):
        """初始化模拟数据引擎"""
        self.settings = get_settings()
        self._last_metrics = None
        self._process_cache = None
        self._process_cache_time = 0
        self._uptime_start = datetime.now() - timedelta(hours=random.randint(2, 8))
        self._boot_time = self._uptime_start
        # 用于生成平滑波动的种子值
        self._cpu_seed = random.uniform(30, 50)
        self._mem_seed = random.uniform(55, 70)
        self._disk_io_seed = random.uniform(10, 30)
        self._net_seed = random.uniform(50, 200)
        self._gpu_seed = random.uniform(15, 35)
        self._battery_seed = random.uniform(75, 100)
        self._temp_seed = random.uniform(45, 65)
        # 进程事件缓存
        self._process_events = []
        self._event_counter = 0
        self._init_process_events()

    def _random_walk(self, current: float, min_val: float, max_val: float,
                     step: float = 2.0) -> float:
        """
        随机游走算法，生成平滑波动的数据

        Args:
            current: 当前值
            min_val: 最小值
            max_val: 最大值
            step: 最大步长

        Returns:
            波动后的新值
        """
        change = random.uniform(-step, step)
        new_val = current + change
        # 边界反弹
        if new_val < min_val:
            new_val = min_val + abs(change) * 0.5
        elif new_val > max_val:
            new_val = max_val - abs(change) * 0.5
        return round(new_val, 2)

    def generate_system_metrics(self) -> dict:
        """
        生成逼真的系统监控数据

        Returns:
            包含CPU/内存/磁盘/网络/GPU/电池等维度的系统指标字典
        """
        # 使用随机游走生成平滑波动
        self._cpu_seed = self._random_walk(self._cpu_seed, 15, 75, 3.0)
        self._mem_seed = self._random_walk(self._mem_seed, 50, 78, 1.0)
        self._disk_io_seed = self._random_walk(self._disk_io_seed, 5, 80, 5.0)
        self._net_seed = self._random_walk(self._net_seed, 20, 800, 50.0)
        self._gpu_seed = self._random_walk(self._gpu_seed, 5, 60, 4.0)
        self._battery_seed = self._random_walk(self._battery_seed, 20, 100, 0.5)
        self._temp_seed = self._random_walk(self._temp_seed, 40, 80, 1.5)

        cpu_percent = self._cpu_seed
        mem_percent = self._mem_seed
        mem_total = self.settings.mock_total_memory_gb
        mem_used = round(mem_total * mem_percent / 100, 2)
        mem_available = round(mem_total - mem_used, 2)

        # 计算运行时间
        uptime_seconds = int((datetime.now() - self._uptime_start).total_seconds())

        # 各核心CPU使用率（围绕整体值波动）
        cpu_cores = self.settings.mock_cpu_logical
        cpu_per_core = []
        for i in range(cpu_cores):
            core_val = self._random_walk(cpu_percent + random.uniform(-15, 15), 0, 100, 0)
            cpu_per_core.append(round(core_val, 1))

        # CPU负载均值
        cpu_load_1 = round(cpu_percent / 100 * cpu_cores * 0.8, 2)
        cpu_load_5 = round(cpu_percent / 100 * cpu_cores * 0.7, 2)
        cpu_load_15 = round(cpu_percent / 100 * cpu_cores * 0.6, 2)

        # 磁盘数据
        disk_read_speed = round(self._disk_io_seed * random.uniform(0.5, 1.5), 2)
        disk_write_speed = round(self._disk_io_seed * random.uniform(0.3, 1.0), 2)
        disk_busy = round(min(100, self._disk_io_seed + random.uniform(-10, 10)), 1)

        # 磁盘分区使用情况
        total_disk = self.settings.mock_total_disk_gb
        disk_usage = {
            "C:": {
                "total_gb": round(total_disk * 0.4, 1),
                "used_gb": round(total_disk * 0.4 * 0.65, 1),
                "free_gb": round(total_disk * 0.4 * 0.35, 1),
                "percent": 65.0,
                "mountpoint": "C:\\",
                "fstype": "NTFS",
            },
            "D:": {
                "total_gb": round(total_disk * 0.6, 1),
                "used_gb": round(total_disk * 0.6 * 0.45, 1),
                "free_gb": round(total_disk * 0.6 * 0.55, 1),
                "percent": 45.0,
                "mountpoint": "D:\\",
                "fstype": "NTFS",
            },
        }

        # 网络数据
        net_up = round(self._net_seed * random.uniform(0.2, 0.8), 2)
        net_down = round(self._net_seed * random.uniform(1.0, 3.0), 2)
        net_latency = round(random.uniform(5, 50), 1)
        net_packet_loss = round(random.uniform(0, 2), 2)
        net_connections = random.randint(80, 200)

        # GPU数据
        gpu_mem_total = self.settings.mock_gpu_memory_gb
        gpu_mem_percent = self._gpu_seed
        gpu_mem_used = round(gpu_mem_total * gpu_mem_percent / 100, 2)

        # 电池数据
        battery_percent = self._battery_seed
        power_plugged = battery_percent > 95 or random.random() > 0.3
        battery_secs_left = int(battery_percent * 360) if not power_plugged else 0
        battery_health = round(random.uniform(85, 100), 1)
        battery_cycles = random.randint(100, 500)

        # 进程数
        process_count = random.randint(120, 180)

        metrics = {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": cpu_percent,
                "percent_per_core": cpu_per_core,
                "load_avg": [cpu_load_1, cpu_load_5, cpu_load_15],
                "freq_current": round(2800 + cpu_percent * 10, 0),
                "freq_min": 800.0,
                "freq_max": 4500.0,
                "temp": round(self._temp_seed, 1),
                "fan_speed": round(1500 + self._temp_seed * 30, 0),
                "count_physical": self.settings.mock_cpu_cores,
                "count_logical": cpu_cores,
            },
            "memory": {
                "total_gb": mem_total,
                "available_gb": mem_available,
                "used_gb": mem_used,
                "percent": mem_percent,
                "swap_total_gb": round(mem_total * 1.5, 1),
                "swap_used_gb": round(mem_total * 0.15, 2),
                "swap_percent": round(10.0 + random.uniform(-2, 2), 1),
                "cache_gb": round(mem_used * 0.2, 2),
            },
            "disk": {
                "read_speed_mb": disk_read_speed,
                "write_speed_mb": disk_write_speed,
                "read_count": random.randint(100000, 500000),
                "write_count": random.randint(80000, 400000),
                "busy_percent": disk_busy,
                "usage": disk_usage,
                "partitions": list(disk_usage.keys()),
            },
            "network": {
                "up_speed_kb": net_up,
                "down_speed_kb": net_down,
                "total_sent_mb": round(random.uniform(500, 2000), 1),
                "total_recv_mb": round(random.uniform(2000, 8000), 1),
                "connection_count": net_connections,
                "latency_ms": net_latency,
                "packet_loss": net_packet_loss,
                "interfaces": ["以太网", "Wi-Fi", "蓝牙网络连接"],
            },
            "gpu": {
                "count": 1,
                "name": "NVIDIA GeForce RTX 3070 Laptop GPU",
                "percent": gpu_mem_percent,
                "mem_total_gb": gpu_mem_total,
                "mem_used_gb": gpu_mem_used,
                "mem_percent": gpu_mem_percent,
                "temp": round(self._temp_seed + 5, 1),
                "power_watt": round(30 + gpu_mem_percent * 0.8, 1),
                "driver_version": "537.42",
            },
            "battery": {
                "percent": round(battery_percent, 1),
                "power_plugged": power_plugged,
                "secs_left": battery_secs_left,
                "health_percent": battery_health,
                "cycle_count": battery_cycles,
            },
            "system": {
                "uptime_seconds": uptime_seconds,
                "process_count": process_count,
                "boot_time": self._boot_time.isoformat(),
            },
        }

        self._last_metrics = metrics
        return metrics

    def _init_process_events(self):
        """初始化进程事件历史"""
        now = datetime.now()
        event_templates = [
            ("chrome.exe", "start", "browser"),
            ("Code.exe", "start", "yunxi_m9"),
            ("python.exe", "start", "yunxi_m8"),
            ("notepad.exe", "start", "system"),
            ("chrome.exe", "exit", "browser"),
            ("python.exe", "exit", "yunxi_m4"),
        ]
        for i in range(20):
            name, action, category = random.choice(event_templates)
            event_time = now - timedelta(minutes=random.randint(1, 60))
            self._process_events.append({
                "id": i + 1,
                "pid": random.randint(1000, 50000),
                "name": name,
                "action": action,
                "category": category,
                "timestamp": event_time.isoformat(),
                "ppid": random.randint(100, 1000),
                "duration_seconds": random.randint(10, 3600) if action == "exit" else None,
                "exit_code": random.choice([0, 0, 0, -1]) if action == "exit" else None,
            })
        self._event_counter = 20

    def generate_process_list(self, count: int = 50) -> List[dict]:
        """
        生成模拟进程列表

        Args:
            count: 进程数量

        Returns:
            进程信息列表
        """
        # 缓存2秒内的结果
        now = time.time()
        if self._process_cache and (now - self._process_cache_time) < 2:
            return self._process_cache[:count]

        processes = []
        pid_counter = 1000

        # ===== 系统核心进程 =====
        system_processes = [
            ("System", 4, 0, "system", 0.1, 0.5, 8, "system"),
            ("Registry", 120, 4, "system", 0.05, 20.0, 4, "system"),
            ("smss.exe", 384, 4, "system", 0.01, 0.3, 2, "system"),
            ("csrss.exe", 548, 544, "system", 0.02, 5.0, 3, "system"),
            ("wininit.exe", 820, 672, "system", 0.01, 2.0, 1, "system"),
            ("services.exe", 704, 672, "system", 0.05, 8.0, 6, "system"),
            ("lsass.exe", 812, 672, "system", 0.03, 15.0, 8, "system"),
            ("svchost.exe", 1200, 704, "system", 0.5, 30.0, 25, "system"),
            ("svchost.exe", 1350, 704, "system", 0.3, 25.0, 20, "system"),
            ("svchost.exe", 1420, 704, "system", 0.2, 20.0, 15, "system"),
            ("svchost.exe", 1580, 704, "system", 0.4, 35.0, 30, "system"),
            ("explorer.exe", 2048, 1800, "system", 1.2, 120.0, 45, "system"),
            ("ShellExperienceHost.exe", 2200, 2048, "system", 0.5, 50.0, 12, "system"),
            ("SearchUI.exe", 2300, 2048, "system", 0.3, 40.0, 10, "system"),
            ("RuntimeBroker.exe", 2500, 704, "system", 0.1, 15.0, 5, "system"),
            ("dwm.exe", 1080, 904, "system", 1.5, 80.0, 8, "system"),
            ("WmiPrvSE.exe", 2800, 704, "system", 0.2, 10.0, 4, "system"),
            ("spoolsv.exe", 3000, 704, "system", 0.05, 5.0, 3, "system"),
            ("fontdrvhost.exe", 1500, 820, "system", 0.02, 3.0, 2, "system"),
            ("winlogon.exe", 600, 544, "system", 0.01, 2.0, 1, "system"),
        ]

        for name, pid, ppid, username, cpu, mem, threads, _ in system_processes:
            processes.append({
                "pid": pid,
                "ppid": ppid,
                "name": name,
                "exe_path": f"C:\\Windows\\System32\\{name}",
                "cmdline": name,
                "username": username,
                "cpu_percent": round(cpu + random.uniform(-0.1, 0.5), 2),
                "cpu_time_user": round(random.uniform(10, 1000), 2),
                "cpu_time_system": round(random.uniform(5, 500), 2),
                "mem_rss_mb": round(mem + random.uniform(-5, 10), 2),
                "mem_vms_mb": round(mem * 1.5, 2),
                "mem_percent": round(mem / self.settings.mock_total_memory_gb / 1024 * 100, 4),
                "num_threads": threads + random.randint(-2, 5),
                "num_handles": random.randint(100, 2000),
                "status": "running",
                "create_time": (datetime.now() - timedelta(hours=random.randint(2, 8))).isoformat(),
                "io_read_mb": round(random.uniform(10, 500), 2),
                "io_write_mb": round(random.uniform(5, 200), 2),
                "net_connections": random.randint(0, 10),
                "category": "system",
                "is_yunxi": False,
                "yunxi_module": "",
            })

        # ===== 云汐系统进程 =====
        yunxi_processes = [
            ("M1 调度中心", "M1-agent-hub", 5),
            ("M2 技能集群", "M2-skill-cluster", 4),
            ("M4 场景引擎", "M4-scene-engine", 6),
            ("M5 潮汐记忆", "M5-tide-memory", 3),
            ("M8 管理台", "M8-control-tower", 2),
            ("M9 开发者工坊", "M9-dev-workshop", 1),
        ]

        pid_counter = 10000
        for display_name, module, worker_count in yunxi_processes:
            # 主进程
            main_pid = pid_counter
            pid_counter += 1
            processes.append({
                "pid": main_pid,
                "ppid": 2048,
                "name": "python.exe",
                "exe_path": f"C:\\云汐\\工作台\\yunxi-project\\{module}\\backend\\main.py",
                "cmdline": f"python main.py --module {module}",
                "username": "yunxi",
                "cpu_percent": round(random.uniform(2, 8), 2),
                "cpu_time_user": round(random.uniform(100, 5000), 2),
                "cpu_time_system": round(random.uniform(50, 2000), 2),
                "mem_rss_mb": round(random.uniform(150, 400), 2),
                "mem_vms_mb": round(random.uniform(300, 800), 2),
                "mem_percent": 0.0,
                "num_threads": random.randint(10, 30),
                "num_handles": random.randint(200, 800),
                "status": "running",
                "create_time": (datetime.now() - timedelta(hours=random.randint(1, 4))).isoformat(),
                "io_read_mb": round(random.uniform(50, 500), 2),
                "io_write_mb": round(random.uniform(20, 200), 2),
                "net_connections": random.randint(5, 30),
                "category": "yunxi",
                "is_yunxi": True,
                "yunxi_module": module,
                "display_name": display_name,
            })
            # 工作进程
            for i in range(worker_count):
                pid_counter += 1
                processes.append({
                    "pid": pid_counter,
                    "ppid": main_pid,
                    "name": "python.exe",
                    "exe_path": f"C:\\云汐\\工作台\\yunxi-project\\{module}\\backend\\worker.py",
                    "cmdline": f"python worker.py --module {module} --worker-id {i+1}",
                    "username": "yunxi",
                    "cpu_percent": round(random.uniform(0.5, 5), 2),
                    "cpu_time_user": round(random.uniform(50, 2000), 2),
                    "cpu_time_system": round(random.uniform(20, 800), 2),
                    "mem_rss_mb": round(random.uniform(80, 250), 2),
                    "mem_vms_mb": round(random.uniform(150, 500), 2),
                    "mem_percent": 0.0,
                    "num_threads": random.randint(5, 15),
                    "num_handles": random.randint(100, 400),
                    "status": "running",
                    "create_time": (datetime.now() - timedelta(hours=random.randint(1, 4))).isoformat(),
                    "io_read_mb": round(random.uniform(20, 200), 2),
                    "io_write_mb": round(random.uniform(10, 100), 2),
                    "net_connections": random.randint(2, 15),
                    "category": "yunxi",
                    "is_yunxi": True,
                    "yunxi_module": module,
                    "display_name": f"{display_name} - Worker-{i+1}",
                })

        # VS Code 进程（M9相关）
        vscode_pid = 20000
        processes.append({
            "pid": vscode_pid,
            "ppid": 2048,
            "name": "Code.exe",
            "exe_path": "C:\\Users\\XiZho\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
            "cmdline": "Code.exe --goto",
            "username": "XiZho",
            "cpu_percent": round(random.uniform(3, 12), 2),
            "cpu_time_user": round(random.uniform(500, 3000), 2),
            "cpu_time_system": round(random.uniform(200, 1000), 2),
            "mem_rss_mb": round(random.uniform(400, 800), 2),
            "mem_vms_mb": round(random.uniform(800, 1500), 2),
            "mem_percent": 0.0,
            "num_threads": random.randint(20, 40),
            "num_handles": random.randint(500, 2000),
            "status": "running",
            "create_time": (datetime.now() - timedelta(hours=random.randint(1, 6))).isoformat(),
            "io_read_mb": round(random.uniform(100, 1000), 2),
            "io_write_mb": round(random.uniform(50, 500), 2),
            "net_connections": random.randint(10, 30),
            "category": "yunxi",
            "is_yunxi": True,
            "yunxi_module": "M9-dev-workshop",
            "display_name": "VS Code - 云汐项目",
        })
        # VS Code 子进程
        for i in range(6):
            pid = 20100 + i
            processes.append({
                "pid": pid,
                "ppid": vscode_pid,
                "name": "Code.exe",
                "exe_path": "C:\\Users\\XiZho\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
                "cmdline": f"Code.exe --type=renderer --ms-enable-electron-run-as-node",
                "username": "XiZho",
                "cpu_percent": round(random.uniform(0.5, 5), 2),
                "cpu_time_user": round(random.uniform(100, 1500), 2),
                "cpu_time_system": round(random.uniform(50, 500), 2),
                "mem_rss_mb": round(random.uniform(100, 350), 2),
                "mem_vms_mb": round(random.uniform(200, 600), 2),
                "mem_percent": 0.0,
                "num_threads": random.randint(10, 25),
                "num_handles": random.randint(200, 800),
                "status": "running",
                "create_time": (datetime.now() - timedelta(hours=random.randint(1, 6))).isoformat(),
                "io_read_mb": round(random.uniform(50, 300), 2),
                "io_write_mb": round(random.uniform(20, 150), 2),
                "net_connections": random.randint(5, 20),
                "category": "yunxi",
                "is_yunxi": True,
                "yunxi_module": "M9-dev-workshop",
                "display_name": f"VS Code 渲染进程-{i+1}",
            })

        # Ollama 进程
        ollama_pid = 25000
        processes.append({
            "pid": ollama_pid,
            "ppid": 2048,
            "name": "ollama.exe",
            "exe_path": "C:\\Users\\XiZho\\AppData\\Local\\Programs\\Ollama\\ollama.exe",
            "cmdline": "ollama serve",
            "username": "XiZho",
            "cpu_percent": round(random.uniform(5, 20), 2),
            "cpu_time_user": round(random.uniform(1000, 5000), 2),
            "cpu_time_system": round(random.uniform(500, 2000), 2),
            "mem_rss_mb": round(random.uniform(2000, 4000), 2),
            "mem_vms_mb": round(random.uniform(3000, 6000), 2),
            "mem_percent": 0.0,
            "num_threads": random.randint(15, 30),
            "num_handles": random.randint(300, 800),
            "status": "running",
            "create_time": (datetime.now() - timedelta(hours=random.randint(2, 5))).isoformat(),
            "io_read_mb": round(random.uniform(200, 1000), 2),
            "io_write_mb": round(random.uniform(100, 500), 2),
            "net_connections": random.randint(5, 15),
            "category": "yunxi",
            "is_yunxi": True,
            "yunxi_module": "Ollama",
            "display_name": "Ollama 大模型服务",
        })

        # ===== 第三方应用进程 =====
        third_party = [
            ("chrome.exe", "browser", 12, 2048, 15.0, 300.0),
            ("msedge.exe", "browser", 5, 2048, 5.0, 200.0),
            ("WeChat.exe", "communication", 2, 2048, 2.0, 150.0),
            ("QQ.exe", "communication", 1, 2048, 1.0, 100.0),
            ("DingTalk.exe", "communication", 2, 2048, 1.5, 200.0),
            ("WPS.exe", "office", 1, 2048, 3.0, 250.0),
            ("wpscloudsvr.exe", "office", 1, 2048, 0.5, 30.0),
            ("idea64.exe", "development", 1, 2048, 8.0, 1500.0),
            ("navicat.exe", "development", 1, 2048, 2.0, 200.0),
            ("postman.exe", "development", 1, 2048, 1.5, 150.0),
            ("OneDrive.exe", "utility", 1, 2048, 0.5, 50.0),
            ("Everything.exe", "utility", 1, 2048, 0.3, 20.0),
            ("TrafficMonitor.exe", "utility", 1, 2048, 0.8, 30.0),
            ("DiskGenius.exe", "utility", 1, 2048, 1.0, 80.0),
            ("PotPlayerMini.exe", "media", 1, 2048, 3.0, 100.0),
            ("cloudmusic.exe", "media", 1, 2048, 2.0, 120.0),
        ]

        pid_counter = 30000
        for name, category, instance_count, ppid, base_cpu, base_mem in third_party:
            main_pid = pid_counter
            for i in range(instance_count):
                pid = pid_counter + i
                is_main = i == 0
                processes.append({
                    "pid": pid,
                    "ppid": main_pid if not is_main else ppid,
                    "name": name,
                    "exe_path": f"C:\\Program Files\\{name}\\{name}.exe",
                    "cmdline": name,
                    "username": "XiZho",
                    "cpu_percent": round(base_cpu * (0.3 if not is_main else 1.0) * random.uniform(0.5, 1.5), 2),
                    "cpu_time_user": round(random.uniform(100, 3000), 2),
                    "cpu_time_system": round(random.uniform(50, 1000), 2),
                    "mem_rss_mb": round(base_mem * (0.4 if not is_main else 1.0) * random.uniform(0.8, 1.2), 2),
                    "mem_vms_mb": round(base_mem * 1.8, 2),
                    "mem_percent": 0.0,
                    "num_threads": random.randint(5, 30),
                    "num_handles": random.randint(100, 1000),
                    "status": "running",
                    "create_time": (datetime.now() - timedelta(hours=random.randint(1, 8))).isoformat(),
                    "io_read_mb": round(random.uniform(50, 500), 2),
                    "io_write_mb": round(random.uniform(20, 200), 2),
                    "net_connections": random.randint(2, 30),
                    "category": category,
                    "is_yunxi": False,
                    "yunxi_module": "",
                })
            pid_counter += instance_count

        # 计算内存占比
        total_mem_kb = self.settings.mock_total_memory_gb * 1024
        for p in processes:
            p["mem_percent"] = round(p["mem_rss_mb"] / total_mem_kb * 100, 4)

        # 按CPU使用率排序
        processes.sort(key=lambda x: x["cpu_percent"], reverse=True)

        self._process_cache = processes
        self._process_cache_time = time.time()

        return processes[:count]

    def generate_health_score(self, metrics: dict = None) -> dict:
        """
        根据模拟数据计算健康评分

        Args:
            metrics: 系统指标数据，为空则自动生成

        Returns:
            健康评分结果字典
        """
        if metrics is None:
            metrics = self.generate_system_metrics()

        cpu = metrics["cpu"]
        mem = metrics["memory"]
        disk = metrics["disk"]
        net = metrics["network"]
        gpu = metrics["gpu"]
        battery = metrics["battery"]

        # ===== 各维度评分 =====
        # CPU健康（20%权重）：使用率越低分越高，温度越低分越高
        cpu_score_usage = max(0, 100 - cpu["percent"] * 1.2)
        cpu_score_temp = max(0, 100 - max(0, cpu["temp"] - 40) * 2)
        cpu_score = round(cpu_score_usage * 0.6 + cpu_score_temp * 0.4, 1)

        # 内存健康（25%权重）：可用内存越多分越高，Swap使用率越低分越高
        mem_score_usage = max(0, 100 - mem["percent"] * 1.1)
        mem_score_swap = max(0, 100 - mem["swap_percent"] * 3)
        mem_score = round(mem_score_usage * 0.7 + mem_score_swap * 0.3, 1)

        # 磁盘健康（15%权重）：剩余空间越多分越高，繁忙度越低分越高
        c_usage = disk["usage"].get("C:", {}).get("percent", 50)
        disk_score_space = max(0, 100 - c_usage * 1.0)
        disk_score_busy = max(0, 100 - disk["busy_percent"] * 1.0)
        disk_score = round(disk_score_space * 0.6 + disk_score_busy * 0.4, 1)

        # 网络健康（10%权重）：延迟越低分越高，丢包越少分越高
        net_score_latency = max(0, 100 - net["latency_ms"] * 1.5)
        net_score_loss = max(0, 100 - net["packet_loss"] * 20)
        net_score = round(net_score_latency * 0.6 + net_score_loss * 0.4, 1)

        # 温度健康（15%权重）：CPU/GPU温度
        temp_score_cpu = max(0, 100 - max(0, cpu["temp"] - 40) * 2)
        temp_score_gpu = max(0, 100 - max(0, gpu["temp"] - 40) * 2)
        temp_score = round(temp_score_cpu * 0.6 + temp_score_gpu * 0.4, 1)

        # 电池健康（10%权重）：电量越高分越高
        if battery["power_plugged"]:
            battery_score = min(100, battery["percent"] + 10)
        else:
            battery_score = battery["percent"]
        battery_score = round(battery_score, 1)

        # 进程健康（5%权重）
        proc_score = round(random.uniform(80, 98), 1)

        # 综合评分（加权）
        total_score = round(
            cpu_score * 0.20 +
            mem_score * 0.25 +
            disk_score * 0.15 +
            net_score * 0.10 +
            temp_score * 0.15 +
            battery_score * 0.10 +
            proc_score * 0.05,
            1
        )

        # 等级判定
        if total_score >= 90:
            level = "excellent"
            level_text = "优秀"
            description = "系统状态极佳，资源充裕"
        elif total_score >= 70:
            level = "good"
            level_text = "良好"
            description = "系统状态正常，运行平稳"
        elif total_score >= 50:
            level = "fair"
            level_text = "一般"
            description = "资源偏紧，建议关注"
        else:
            level = "poor"
            level_text = "较差"
            description = "系统压力大，需要干预"

        return {
            "total_score": total_score,
            "level": level,
            "level_text": level_text,
            "description": description,
            "dimensions": {
                "cpu": {"score": cpu_score, "weight": 20, "name": "CPU健康"},
                "memory": {"score": mem_score, "weight": 25, "name": "内存健康"},
                "disk": {"score": disk_score, "weight": 15, "name": "磁盘健康"},
                "network": {"score": net_score, "weight": 10, "name": "网络健康"},
                "temperature": {"score": temp_score, "weight": 15, "name": "温度健康"},
                "battery": {"score": battery_score, "weight": 10, "name": "电池健康"},
                "process": {"score": proc_score, "weight": 5, "name": "进程健康"},
            },
            "timestamp": datetime.now().isoformat(),
        }

    def generate_alerts(self, metrics: dict = None) -> List[dict]:
        """
        根据阈值生成模拟告警

        Args:
            metrics: 系统指标数据，为空则自动生成

        Returns:
            告警列表
        """
        if metrics is None:
            metrics = self.generate_system_metrics()

        alerts = []
        alert_id = 1
        now = datetime.now()

        cpu = metrics["cpu"]
        mem = metrics["memory"]
        disk = metrics["disk"]
        battery = metrics["battery"]
        gpu = metrics["gpu"]

        # 高内存使用率告警
        if mem["percent"] > self.settings.memory_warning_threshold:
            level = "critical" if mem["percent"] > self.settings.memory_danger_threshold else "warning"
            alerts.append({
                "id": alert_id,
                "alert_type": "high_memory",
                "level": level,
                "title": "高内存使用率",
                "message": f"当前内存使用率 {mem['percent']}%，已超过警告阈值 {self.settings.memory_warning_threshold}%",
                "metric_name": "mem_percent",
                "metric_value": mem["percent"],
                "threshold": self.settings.memory_warning_threshold,
                "created_at": (now - timedelta(minutes=random.randint(0, 5))).isoformat(),
                "acknowledged": False,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        # 高CPU使用率告警
        if cpu["percent"] > self.settings.cpu_warning_threshold:
            level = "critical" if cpu["percent"] > self.settings.cpu_danger_threshold else "warning"
            alerts.append({
                "id": alert_id,
                "alert_type": "high_cpu",
                "level": level,
                "title": "高CPU使用率",
                "message": f"当前CPU使用率 {cpu['percent']}%，已超过警告阈值 {self.settings.cpu_warning_threshold}%",
                "metric_name": "cpu_percent",
                "metric_value": cpu["percent"],
                "threshold": self.settings.cpu_warning_threshold,
                "created_at": (now - timedelta(minutes=random.randint(0, 3))).isoformat(),
                "acknowledged": False,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        # CPU温度过高告警
        if cpu["temp"] > 85:
            alerts.append({
                "id": alert_id,
                "alert_type": "high_cpu_temp",
                "level": "critical" if cpu["temp"] > 90 else "warning",
                "title": "CPU温度过高",
                "message": f"当前CPU温度 {cpu['temp']}°C，建议检查散热",
                "metric_name": "cpu_temp",
                "metric_value": cpu["temp"],
                "threshold": 85.0,
                "created_at": (now - timedelta(minutes=random.randint(0, 2))).isoformat(),
                "acknowledged": False,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        # GPU温度过高告警
        if gpu["temp"] > 85:
            alerts.append({
                "id": alert_id,
                "alert_type": "high_gpu_temp",
                "level": "warning",
                "title": "GPU温度过高",
                "message": f"当前GPU温度 {gpu['temp']}°C，建议降低GPU负载",
                "metric_name": "gpu_temp",
                "metric_value": gpu["temp"],
                "threshold": 85.0,
                "created_at": (now - timedelta(minutes=random.randint(0, 2))).isoformat(),
                "acknowledged": False,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        # 磁盘空间不足告警
        c_free = disk["usage"].get("C:", {}).get("free_gb", 0)
        if c_free < self.settings.disk_warning_gb:
            alerts.append({
                "id": alert_id,
                "alert_type": "low_disk_space",
                "level": "warning",
                "title": "磁盘空间不足",
                "message": f"C盘剩余空间 {c_free}GB，已低于警告阈值 {self.settings.disk_warning_gb}GB",
                "metric_name": "disk_free_gb",
                "metric_value": c_free,
                "threshold": self.settings.disk_warning_gb,
                "created_at": (now - timedelta(hours=random.randint(1, 6))).isoformat(),
                "acknowledged": True,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        # 低电量告警
        if not battery["power_plugged"] and battery["percent"] < self.settings.battery_warning_percent:
            level = "critical" if battery["percent"] < self.settings.battery_critical_percent else "warning"
            alerts.append({
                "id": alert_id,
                "alert_type": "low_battery",
                "level": level,
                "title": "电量不足",
                "message": f"当前电量 {battery['percent']}%，请及时充电",
                "metric_name": "battery_percent",
                "metric_value": battery["percent"],
                "threshold": self.settings.battery_warning_percent,
                "created_at": (now - timedelta(minutes=random.randint(0, 10))).isoformat(),
                "acknowledged": False,
                "resolved": False,
                "source": "system_monitor",
            })
            alert_id += 1

        return alerts

    def generate_startup_check_result(
        self,
        module: str = "m9",
        task_type: str = "vscode-instance",
        expected_memory_mb: int = 500,
        expected_cpu_percent: float = 5.0,
        instance_count: int = 1,
        priority: str = "normal",
    ) -> dict:
        """
        生成启动安全检查模拟结果

        Args:
            module: 调用模块标识
            task_type: 任务类型
            expected_memory_mb: 预期新增内存(MB)
            expected_cpu_percent: 预期新增CPU(%)
            instance_count: 启动实例数量
            priority: 优先级

        Returns:
            启动安全检查结果字典
        """
        metrics = self.generate_system_metrics()
        mem = metrics["memory"]
        cpu = metrics["cpu"]
        disk = metrics["disk"]

        # 同类进程数（模拟）
        similar_process_count = random.randint(1, 6)
        yunxi_process_count = random.randint(15, 25)

        # 计算启动后的预测值
        total_expected_mem_mb = expected_memory_mb * instance_count
        total_expected_cpu = expected_cpu_percent * instance_count
        after_mem_percent = round(mem["percent"] + total_expected_mem_mb / (mem["total_gb"] * 1024) * 100, 1)
        after_mem_available = round(mem["available_gb"] - total_expected_mem_mb / 1024, 2)
        after_cpu_percent = round(min(100, cpu["percent"] + total_expected_cpu), 1)

        # ===== 评分计算 =====
        # 内存维度（40%权重）
        if after_mem_percent < 60:
            mem_score = 100
        elif after_mem_percent < 70:
            mem_score = 85
        elif after_mem_percent < 80:
            mem_score = 65
        elif after_mem_percent < 90:
            mem_score = 40
        else:
            mem_score = 20

        # CPU维度（25%权重）
        if after_cpu_percent < 50:
            cpu_score = 100
        elif after_cpu_percent < 60:
            cpu_score = 85
        elif after_cpu_percent < 75:
            cpu_score = 65
        elif after_cpu_percent < 90:
            cpu_score = 40
        else:
            cpu_score = 20

        # 同类进程数维度（15%权重）
        max_vscode = 8
        similar_score = max(0, 100 - (similar_process_count / max_vscode) * 100)
        similar_score = max(20, min(100, similar_score))

        # 磁盘维度（10%权重）
        c_free = disk["usage"].get("C:", {}).get("free_gb", 100)
        if c_free > 50:
            disk_score = 100
        elif c_free > 20:
            disk_score = 80
        elif c_free > 10:
            disk_score = 60
        else:
            disk_score = 30

        # 趋势维度（10%权重）
        # 模拟一个趋势分数
        trend_score = round(random.uniform(60, 95), 1)

        # 综合评分
        total_score = round(
            mem_score * 0.40 +
            cpu_score * 0.25 +
            similar_score * 0.15 +
            disk_score * 0.10 +
            trend_score * 0.10,
            1
        )

        # 等级判定
        if total_score >= 80:
            level = "safe"
            can_start = True
            recommendation = "可以正常启动"
        elif total_score >= 50:
            level = "warning"
            can_start = priority == "high"
            recommendation = "建议谨慎启动，注意资源占用"
        else:
            level = "danger"
            can_start = False
            recommendation = "不建议启动，当前资源紧张"

        # 智能建议生成
        suggestions = []
        if after_mem_percent > 70:
            suggestions.append("内存使用率偏高，建议关闭闲置程序释放内存")
            suggestions.append("可考虑合并VS Code窗口，减少内存占用")
        if after_cpu_percent > 70:
            suggestions.append("CPU负载较高，建议降低并发任务数")
            suggestions.append("可关闭后台更新和不必要的服务")
        if similar_process_count > 4:
            suggestions.append(f"同类进程已达 {similar_process_count} 个，建议合并实例")
        if c_free < 30:
            suggestions.append("磁盘空间不足，建议清理临时文件和日志")
        if not suggestions:
            suggestions.append("当前资源充足，可以安全启动")
            suggestions.append(f"启动后预计内存使用率 {after_mem_percent}%")

        # 最大推荐实例数
        available_mem_gb = mem["available_gb"]
        max_instances_by_mem = max(1, int(available_mem_gb * 1024 / expected_memory_mb)) if expected_memory_mb > 0 else 10
        max_recommended = min(max_instances_by_mem, 10)

        return {
            "level": level,
            "score": total_score,
            "can_start": can_start,
            "recommendation": recommendation,
            "current_state": {
                "memory_percent": mem["percent"],
                "memory_available_gb": mem["available_gb"],
                "cpu_percent": cpu["percent"],
                "disk_available_gb": c_free,
                "similar_process_count": similar_process_count,
                "yunxi_process_count": yunxi_process_count,
            },
            "after_projection": {
                "memory_percent": after_mem_percent,
                "memory_available_gb": after_mem_available,
                "cpu_percent": after_cpu_percent,
                "risk_level": "low" if level == "safe" else ("medium" if level == "warning" else "high"),
            },
            "suggestions": suggestions,
            "limits": {
                "max_recommended_instances": max_recommended,
                "warning_threshold_memory": self.settings.memory_warning_threshold,
                "danger_threshold_memory": self.settings.memory_danger_threshold,
            },
            "score_detail": {
                "memory": {"score": mem_score, "weight": 40},
                "cpu": {"score": cpu_score, "weight": 25},
                "similar_process": {"score": round(similar_score, 1), "weight": 15},
                "disk": {"score": disk_score, "weight": 10},
                "trend": {"score": trend_score, "weight": 10},
            },
            "timestamp": datetime.now().isoformat(),
        }

    def generate_health_trend(self, minutes: int = 30) -> List[dict]:
        """
        生成健康趋势数据

        Args:
            minutes: 趋势时长（分钟）

        Returns:
            趋势数据点列表
        """
        trend = []
        now = datetime.now()
        base_score = random.uniform(70, 90)

        for i in range(minutes, -1, -1):
            timestamp = now - timedelta(minutes=i)
            # 模拟波动
            score = base_score + math.sin(i / 5) * 5 + random.uniform(-3, 3)
            score = max(50, min(98, score))

            mem_percent = 60 + math.sin(i / 7) * 10 + random.uniform(-2, 2)
            cpu_percent = 35 + math.sin(i / 4) * 15 + random.uniform(-3, 3)

            trend.append({
                "timestamp": timestamp.isoformat(),
                "health_score": round(score, 1),
                "memory_percent": round(mem_percent, 1),
                "cpu_percent": round(cpu_percent, 1),
            })

        return trend

    def generate_risk_prediction(self) -> dict:
        """
        生成风险预测数据（未来10分钟）

        Returns:
            风险预测结果字典
        """
        metrics = self.generate_system_metrics()
        cpu = metrics["cpu"]
        mem = metrics["memory"]
        battery = metrics["battery"]

        # 简单线性预测（加随机波动）
        mem_trend = random.uniform(-2, 3)  # 每分钟变化率
        cpu_trend = random.uniform(-3, 4)

        predicted_mem_10min = round(min(100, mem["percent"] + mem_trend * 10), 1)
        predicted_cpu_10min = round(min(100, cpu["percent"] + cpu_trend * 10), 1)
        predicted_temp_10min = round(cpu["temp"] + random.uniform(-2, 3), 1)

        # 风险预警
        warnings = []
        if predicted_mem_10min > 90:
            warnings.append({
                "type": "memory_exhaustion",
                "level": "critical",
                "message": f"预测10分钟内内存使用率将达到 {predicted_mem_10min}%",
                "time_estimate_minutes": 10,
            })
        elif predicted_mem_10min > 80:
            warnings.append({
                "type": "high_memory_trend",
                "level": "warning",
                "message": f"内存呈上升趋势，预计10分钟后达到 {predicted_mem_10min}%",
                "time_estimate_minutes": 10,
            })

        if predicted_cpu_10min > 85 and cpu_trend > 0:
            warnings.append({
                "type": "high_cpu_load",
                "level": "warning",
                "message": f"CPU持续高负载且呈上升趋势",
                "time_estimate_minutes": 0,
            })

        if predicted_temp_10min > 85:
            warnings.append({
                "type": "overheat_risk",
                "level": "warning",
                "message": f"温度有上升风险，预计达到 {predicted_temp_10min}°C",
                "time_estimate_minutes": 5,
            })

        if not battery["power_plugged"] and battery["percent"] < 30:
            warnings.append({
                "type": "low_battery",
                "level": "warning",
                "message": f"电量较低且未充电，请及时连接电源",
                "time_estimate_minutes": int(battery["percent"] * 3),
            })

        # 磁盘空间预测（按日消耗估算）
        daily_disk_usage_gb = random.uniform(0.5, 2.0)
        c_free = metrics["disk"]["usage"].get("C:", {}).get("free_gb", 100)
        days_until_full = round(c_free / daily_disk_usage_gb, 1) if daily_disk_usage_gb > 0 else 999

        if days_until_full < 7:
            warnings.append({
                "type": "disk_space_warning",
                "level": "warning",
                "message": f"按当前使用速率，预计 {days_until_full} 天后磁盘空间耗尽",
                "time_estimate_days": days_until_full,
            })

        overall_risk = "low"
        if any(w["level"] == "critical" for w in warnings):
            overall_risk = "high"
        elif len(warnings) >= 2:
            overall_risk = "medium"
        elif warnings:
            overall_risk = "low"

        return {
            "prediction_window_minutes": 10,
            "predicted_metrics": {
                "memory_percent_10min": predicted_mem_10min,
                "cpu_percent_10min": predicted_cpu_10min,
                "cpu_temp_10min": predicted_temp_10min,
                "disk_days_until_full": days_until_full,
            },
            "trends": {
                "memory_trend_percent_per_min": round(mem_trend, 2),
                "cpu_trend_percent_per_min": round(cpu_trend, 2),
            },
            "warnings": warnings,
            "overall_risk_level": overall_risk,
            "timestamp": datetime.now().isoformat(),
        }

    def get_process_events(self, limit: int = 50) -> List[dict]:
        """
        获取进程事件历史

        Args:
            limit: 返回数量限制

        Returns:
            进程事件列表
        """
        # 偶尔添加新事件
        if random.random() < 0.3:
            self._event_counter += 1
            event_templates = [
                ("chrome.exe", "start", "browser"),
                ("Code.exe", "start", "yunxi_m9"),
                ("python.exe", "start", "yunxi_m8"),
                ("notepad.exe", "start", "system"),
                ("chrome.exe", "exit", "browser"),
            ]
            name, action, category = random.choice(event_templates)
            self._process_events.insert(0, {
                "id": self._event_counter,
                "pid": random.randint(1000, 50000),
                "name": name,
                "action": action,
                "category": category,
                "timestamp": datetime.now().isoformat(),
                "ppid": random.randint(100, 1000),
                "duration_seconds": random.randint(10, 3600) if action == "exit" else None,
                "exit_code": random.choice([0, 0, 0, -1]) if action == "exit" else None,
            })
            # 只保留最近100条
            self._process_events = self._process_events[:100]

        return self._process_events[:limit]

    def get_system_info(self) -> dict:
        """
        获取系统基本信息（模拟）

        Returns:
            系统信息字典
        """
        return {
            "os": {
                "name": "Windows 11 Pro",
                "version": "23H2",
                "build": "22631.3880",
                "arch": "x64",
                "hostname": "YUNXI-LAPTOP",
                "username": "XiZho",
            },
            "cpu": {
                "name": "12th Gen Intel(R) Core(TM) i7-12700H",
                "physical_cores": self.settings.mock_cpu_cores,
                "logical_cores": self.settings.mock_cpu_logical,
                "base_freq_mhz": 2300.0,
                "max_freq_mhz": 4700.0,
            },
            "memory": {
                "total_gb": self.settings.mock_total_memory_gb,
                "type": "DDR5",
                "speed_mhz": 4800.0,
                "modules": 2,
            },
            "gpu": [
                {
                    "name": "NVIDIA GeForce RTX 3070 Laptop GPU",
                    "memory_gb": self.settings.mock_gpu_memory_gb,
                    "driver_version": "537.42",
                },
                {
                    "name": "Intel(R) Iris(R) Xe Graphics",
                    "memory_gb": 2.0,
                    "driver_version": "31.0.101.4502",
                },
            ],
            "disks": [
                {
                    "name": "NVMe Samsung SSD 980",
                    "total_gb": 512.0,
                    "type": "NVMe SSD",
                    "interface": "PCIe 3.0 x4",
                },
                {
                    "name": "WD Blue SN570",
                    "total_gb": 512.0,
                    "type": "NVMe SSD",
                    "interface": "PCIe 3.0 x4",
                },
            ],
            "battery": {
                "design_capacity_wh": 80.0,
                "full_charge_capacity_wh": 75.0,
                "health_percent": 93.75,
                "cycle_count": 320,
            },
            "boot_time": self._boot_time.isoformat(),
            "uptime_seconds": int((datetime.now() - self._boot_time).total_seconds()),
        }


# 全局单例
_mock_engine: Optional[MockDataEngine] = None


def get_mock_engine() -> MockDataEngine:
    """获取模拟数据引擎单例"""
    global _mock_engine
    if _mock_engine is None:
        _mock_engine = MockDataEngine()
    return _mock_engine


# 兼容直接运行测试
if __name__ == "__main__":
    engine = get_mock_engine()

    print("=== 模拟系统指标 ===")
    metrics = engine.generate_system_metrics()
    print(f"CPU使用率: {metrics['cpu']['percent']}%")
    print(f"内存使用率: {metrics['memory']['percent']}%")
    print(f"CPU温度: {metrics['cpu']['temp']}°C")

    print("\n=== 模拟进程列表（前5个） ===")
    processes = engine.generate_process_list(5)
    for p in processes[:5]:
        print(f"  PID {p['pid']}: {p['name']} - CPU {p['cpu_percent']}%, MEM {p['mem_rss_mb']}MB")

    print("\n=== 健康评分 ===")
    health = engine.generate_health_score()
    print(f"综合评分: {health['total_score']} ({health['level_text']})")

    print("\n=== 启动安全检查 ===")
    check = engine.generate_startup_check_result(module="m9", task_type="vscode-instance")
    print(f"评分: {check['score']}, 等级: {check['level']}, 可启动: {check['can_start']}")
