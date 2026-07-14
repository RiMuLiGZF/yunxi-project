"""Mock process generator for sandbox/testing."""

from __future__ import annotations

import random
import time
import re

from m10_system_guard.config import get_config
from m10_system_guard.models import ProcessSnapshot, ProcessTreeNode


class MockProcessGenerator:
    """模拟进程生成器.

    沙盒模式下使用，生成符合真实分布的模拟进程数据。
    包含系统进程、云汐进程、VS Code 进程等多种类型。
    """

    # 常见系统进程名称
    SYSTEM_PROCESSES = [
        ("System", "C:\\Windows\\System32\\ntoskrnl.exe"),
        ("svchost.exe", "C:\\Windows\\System32\\svchost.exe"),
        ("explorer.exe", "C:\\Windows\\explorer.exe"),
        ("dwm.exe", "C:\\Windows\\System32\\dwm.exe"),
        ("csrss.exe", "C:\\Windows\\System32\\csrss.exe"),
        ("wininit.exe", "C:\\Windows\\System32\\wininit.exe"),
        ("services.exe", "C:\\Windows\\System32\\services.exe"),
        ("lsass.exe", "C:\\Windows\\System32\\lsass.exe"),
        ("smss.exe", "C:\\Windows\\System32\\smss.exe"),
        ("chrome.exe", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"),
        ("firefox.exe", "C:\\Program Files\\Mozilla Firefox\\firefox.exe"),
        ("notepad.exe", "C:\\Windows\\System32\\notepad.exe"),
        ("calc.exe", "C:\\Windows\\System32\\calc.exe"),
        ("python.exe", "C:\\Python310\\python.exe"),
        ("node.exe", "C:\\Program Files\\nodejs\\node.exe"),
        ("java.exe", "C:\\Program Files\\Java\\jdk-17\\bin\\java.exe"),
        ("docker.exe", "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"),
        ("mysqld.exe", "C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysqld.exe"),
        ("nginx.exe", "C:\\nginx\\nginx.exe"),
        ("redis-server.exe", "C:\\Redis\\redis-server.exe"),
    ]

    # 云汐系统进程名称模板
    YUNXI_PROCESSES = [
        ("M1-agent-hub", "python -m M1_agent_hub.server", "M1"),
        ("m2-skills", "python -m m2_skills_cluster.server", "M2"),
        ("m3-edge-cloud", "python -m m3_edge_cloud.server", "M3"),
        ("m4-scene-engine", "python -m m4_scene_engine.server", "M4"),
        ("m5-tide-memory", "python -m m5_tide_memory.server", "M5"),
        ("m6-hardware", "python -m m6_hardware.server", "M6"),
        ("m7-workflow", "python -m m7_workflow.server", "M7"),
        ("m8-control-tower", "python -m m8_control_tower.server", "M8"),
        ("m9-mcp-bridge", "python -m m9_mcp_bridge.server", "M9"),
        ("m10-system-guard", "python -m m10_system_guard.server", "M10"),
        ("yunxi-agent-main", "python yunxi_agent.py", "M1"),
        ("trae-cli", "trae start", "M1"),
    ]

    # VS Code 进程名称
    VSCODE_PROCESSES = [
        ("Code.exe", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"),
        ("Code.exe", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe --renderer"),
        ("Code.exe", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe --extensionHost"),
        ("Code.exe", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe --utility"),
        ("code-helper", "C:\\Users\\User\\AppData\\Local\\Programs\\Microsoft VS Code\\code-helper.exe"),
    ]

    def __init__(self):
        """初始化模拟进程生成器."""
        config = get_config()
        self.process_cfg = config.process
        self.sandbox_cfg = config.sandbox
        self._total_memory_mb = 16384.0
        self._pid_counter = 1000
        self._processes: list[ProcessSnapshot] = []
        self._last_refresh = 0.0
        self._refresh_interval = 5.0  # 进程列表刷新间隔

    def _next_pid(self) -> int:
        """生成下一个 PID."""
        self._pid_counter += random.randint(1, 5)
        return self._pid_counter

    def generate_process_list(self, count: int | None = None) -> list[ProcessSnapshot]:
        """生成模拟进程列表.

        Args:
            count: 进程数量，None 则使用配置值

        Returns:
            进程快照列表
        """
        if count is None:
            count = self.sandbox_cfg.mock_process_count

        processes = []
        pid = 100  # 起始 PID

        # 1. 系统进程（约占 50%）
        sys_count = count // 2
        for i in range(sys_count):
            name, path = random.choice(self.SYSTEM_PROCESSES)
            proc = self._create_process(
                pid=pid + i,
                name=name,
                path=path,
                cpu_base=random.uniform(0.0, 5.0),
                mem_base=random.uniform(10.0, 200.0),
            )
            processes.append(proc)

        # 2. 云汐进程（所有 M1-M10 模块）
        start_pid = pid + sys_count
        for i, (name, cmdline, module) in enumerate(self.YUNXI_PROCESSES):
            proc = self._create_process(
                pid=start_pid + i,
                name=name,
                path=f"C:\\Yunxi\\{module.lower()}\\server.py",
                cmdline=cmdline,
                cpu_base=random.uniform(2.0, 15.0),
                mem_base=random.uniform(100.0, 500.0),
            )
            proc.is_yunxi_process = True
            proc.yunxi_module = module
            processes.append(proc)

        # 3. VS Code 进程（3-8个）
        vscode_count = random.randint(3, 8)
        start_pid = start_pid + len(self.YUNXI_PROCESSES)
        for i in range(vscode_count):
            name, path = random.choice(self.VSCODE_PROCESSES)
            proc = self._create_process(
                pid=start_pid + i,
                name=name,
                path=path,
                cpu_base=random.uniform(1.0, 12.0),
                mem_base=random.uniform(200.0, 800.0),
            )
            proc.is_vscode_process = True
            processes.append(proc)

        # 4. 其他用户进程（填充剩余数量）
        remaining = count - len(processes)
        if remaining > 0:
            start_pid = start_pid + vscode_count
            for i in range(remaining):
                name, path = random.choice(self.SYSTEM_PROCESSES)
                proc = self._create_process(
                    pid=start_pid + i,
                    name=f"{name}_user{i}",
                    path=path,
                    cpu_base=random.uniform(0.0, 8.0),
                    mem_base=random.uniform(20.0, 300.0),
                )
                processes.append(proc)

        # 设置父进程关系（模拟进程树）
        self._setup_ppid(processes)

        # 按 PID 排序
        processes.sort(key=lambda p: p.pid)

        return processes

    def _create_process(
        self,
        pid: int,
        name: str,
        path: str,
        cmdline: str = "",
        cpu_base: float = 0.0,
        mem_base: float = 0.0,
    ) -> ProcessSnapshot:
        """创建单个进程快照."""
        cpu = cpu_base + random.uniform(-cpu_base * 0.3, cpu_base * 0.3)
        cpu = max(0.0, min(100.0, cpu))

        memory = mem_base + random.uniform(-mem_base * 0.1, mem_base * 0.1)
        memory = max(1.0, memory)
        memory_percent = memory / self._total_memory_mb * 100.0

        statuses = ["running", "running", "running", "sleeping", "idle"]
        status = random.choice(statuses)

        return ProcessSnapshot(
            pid=pid,
            name=name,
            path=path,
            cmdline=cmdline or path,
            cpu_percent=round(cpu, 1),
            memory_mb=round(memory, 1),
            memory_percent=round(memory_percent, 2),
            status=status,
            username="yunxi-user",
            create_time=time.time() - random.randint(60, 86400),
            thread_count=random.randint(1, 50),
            ppid=0,
            is_yunxi_process=False,
            yunxi_module="",
            is_vscode_process=False,
        )

    def _setup_ppid(self, processes: list[ProcessSnapshot]):
        """设置父进程 ID，构建简单的进程树结构."""
        if not processes:
            return

        # 第一个进程作为根进程（PPID=0）
        root = processes[0]
        root.ppid = 0

        # 其余进程随机设置父进程（必须是列表中已有的 PID）
        for i in range(1, len(processes)):
            # 从前 i 个进程中随机选一个作为父进程
            parent_idx = random.randint(0, i - 1)
            processes[i].ppid = processes[parent_idx].pid
