"""
M10 系统卫士 - 进程监控与管控模块 (A2)

负责全量进程快照、进程树结构、Top N 资源排行、
云汐进程识别、VS Code 单实例锁等功能。
沙盒模式优先：默认使用模拟进程数据，不调用真实系统 API。
"""

from __future__ import annotations

import random
import time
import re
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .models import ProcessSnapshot, ProcessTreeNode


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
        ("m1-agent-cluster", "python -m m1_agent_cluster.server", "M1"),
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


class ProcessManager:
    """进程管理器.

    负责进程监控、进程树构建、Top N 排行、
    云汐进程识别、VS Code 实例检测等。
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
        self._init_manager()

    def _init_manager(self):
        """初始化进程管理器."""
        config = get_config()
        self.config = config
        self.process_cfg = config.process
        self.sandbox_mode = config.sandbox.enabled

        # 模拟数据生成器
        self.mock_generator = MockProcessGenerator()

        # 缓存
        self._cached_processes: list[ProcessSnapshot] = []
        self._cache_time = 0.0
        self._cache_ttl = 2.0  # 缓存有效期（秒）

        # VS Code 告警状态
        self._vscode_alert_triggered = False

    def get_all_processes(self, refresh: bool = False) -> list[ProcessSnapshot]:
        """获取全量进程快照.

        Args:
            refresh: 是否强制刷新

        Returns:
            进程快照列表
        """
        now = time.time()
        if not refresh and self._cached_processes and (now - self._cache_time < self._cache_ttl):
            return self._cached_processes

        if self.sandbox_mode:
            processes = self.mock_generator.generate_process_list()
        else:
            # 真实模式（沙盒模式下不执行）
            processes = self.mock_generator.generate_process_list()

        self._cached_processes = processes
        self._cache_time = now
        return processes

    def get_process_tree(self) -> list[ProcessTreeNode]:
        """获取进程树结构.

        Returns:
            进程树根节点列表
        """
        processes = self.get_all_processes()

        # 构建 PID -> 节点映射
        nodes: dict[int, ProcessTreeNode] = {}
        for proc in processes:
            nodes[proc.pid] = ProcessTreeNode(process=proc)

        # 构建父子关系
        roots: list[ProcessTreeNode] = []
        for pid, node in nodes.items():
            ppid = node.process.ppid
            if ppid in nodes:
                nodes[ppid].children.append(node)
            else:
                roots.append(node)

        return roots

    def get_top_by_cpu(self, n: int | None = None) -> list[ProcessSnapshot]:
        """获取 CPU 使用率 Top N 进程.

        Args:
            n: 返回数量，默认使用配置值

        Returns:
            按 CPU 降序排列的进程列表
        """
        if n is None:
            n = self.process_cfg.top_n_default
        processes = self.get_all_processes()
        return sorted(processes, key=lambda p: p.cpu_percent, reverse=True)[:n]

    def get_top_by_memory(self, n: int | None = None) -> list[ProcessSnapshot]:
        """获取内存使用 Top N 进程.

        Args:
            n: 返回数量，默认使用配置值

        Returns:
            按内存降序排列的进程列表
        """
        if n is None:
            n = self.process_cfg.top_n_default
        processes = self.get_all_processes()
        return sorted(processes, key=lambda p: p.memory_mb, reverse=True)[:n]

    def get_yunxi_processes(self) -> list[ProcessSnapshot]:
        """获取云汐系统进程.

        Returns:
            云汐进程列表
        """
        processes = self.get_all_processes()
        return [p for p in processes if p.is_yunxi_process]

    def get_yunxi_processes_by_module(self) -> dict[str, list[ProcessSnapshot]]:
        """按模块分组获取云汐进程.

        Returns:
            模块名 -> 进程列表 的字典
        """
        result: dict[str, list[ProcessSnapshot]] = {}
        for proc in self.get_yunxi_processes():
            module = proc.yunxi_module or "unknown"
            if module not in result:
                result[module] = []
            result[module].append(proc)
        return result

    def get_vscode_processes(self) -> list[ProcessSnapshot]:
        """获取 VS Code 进程.

        Returns:
            VS Code 进程列表
        """
        processes = self.get_all_processes()
        return [p for p in processes if p.is_vscode_process]

    def get_vscode_instance_count(self) -> int:
        """获取 VS Code 实例数量.

        Returns:
            VS Code 主进程数量（去重估算）
        """
        vscode_procs = self.get_vscode_processes()
        # 简单估算：VS Code 主进程数（假设 Code.exe 是主进程）
        main_procs = [p for p in vscode_procs if "Code.exe" in p.name and "renderer" not in p.cmdline]
        count = len(main_procs) if main_procs else len(vscode_procs) // 3
        return max(1, count)

    def check_vscode_limit(self) -> dict[str, Any]:
        """检查 VS Code 进程是否超过限制.

        Returns:
            检查结果字典
        """
        instance_count = self.get_vscode_instance_count()
        max_instances = self.process_cfg.vscode_max_instances
        exceeded = instance_count > max_instances

        result = {
            "vscode_process_count": len(self.get_vscode_processes()),
            "estimated_instances": instance_count,
            "max_instances": max_instances,
            "exceeded": exceeded,
            "level": "normal",
            "message": "",
        }

        if exceeded:
            result["level"] = "warning"
            result["message"] = (
                f"VS Code 实例数 ({instance_count}) 超过限制 ({max_instances})，"
                f"建议关闭多余的 VS Code 窗口以节省资源"
            )
            self._vscode_alert_triggered = True
        else:
            self._vscode_alert_triggered = False

        return result

    def get_process_by_pid(self, pid: int) -> ProcessSnapshot | None:
        """根据 PID 获取进程.

        Args:
            pid: 进程 ID

        Returns:
            进程快照，不存在返回 None
        """
        for proc in self.get_all_processes():
            if proc.pid == pid:
                return proc
        return None

    def search_processes(self, keyword: str) -> list[ProcessSnapshot]:
        """搜索进程（按名称或路径）.

        Args:
            keyword: 搜索关键词

        Returns:
            匹配的进程列表
        """
        keyword_lower = keyword.lower()
        processes = self.get_all_processes()
        return [
            p for p in processes
            if keyword_lower in p.name.lower() or keyword_lower in p.path.lower()
        ]

    def get_process_stats(self) -> dict[str, Any]:
        """获取进程统计信息.

        Returns:
            统计信息字典
        """
        processes = self.get_all_processes()
        total_cpu = sum(p.cpu_percent for p in processes)
        total_memory = sum(p.memory_mb for p in processes)

        vscode_check = self.check_vscode_limit()

        return {
            "total_processes": len(processes),
            "running_processes": sum(1 for p in processes if p.status == "running"),
            "sleeping_processes": sum(1 for p in processes if p.status == "sleeping"),
            "yunxi_processes": len(self.get_yunxi_processes()),
            "vscode_processes": len(self.get_vscode_processes()),
            "vscode_instances": self.get_vscode_instance_count(),
            "vscode_limit_exceeded": vscode_check["exceeded"],
            "total_cpu_percent": round(total_cpu, 1),
            "total_memory_mb": round(total_memory, 1),
            "sandbox_mode": self.sandbox_mode,
        }

    def set_sandbox_mode(self, enabled: bool):
        """设置沙盒模式.

        Args:
            enabled: 是否启用沙盒模式
        """
        self.sandbox_mode = enabled
        # 清除缓存以强制刷新
        self._cached_processes = []
        self._cache_time = 0.0


# 全局单例获取函数
_process_manager_instance = None


def get_process_manager() -> ProcessManager:
    """获取进程管理器单例."""
    global _process_manager_instance
    if _process_manager_instance is None:
        _process_manager_instance = ProcessManager()
    return _process_manager_instance
