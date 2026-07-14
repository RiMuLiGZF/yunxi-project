"""
M10 系统卫士 - 进程监控与管控模块 (A2)

负责全量进程快照、进程树结构、Top N 资源排行、
云汐进程识别、VS Code 单实例锁等功能。
沙盒模式优先：默认使用模拟进程数据，不调用真实系统 API。
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from typing import Any

from .config import get_config
from .models import ProcessSnapshot, ProcessTreeNode


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

        # 模拟数据生成器（仅在沙盒模式下创建）
        if self.sandbox_mode:
            from tests.fixtures.mock_processes import MockProcessGenerator
            self.mock_generator = MockProcessGenerator()
        else:
            self.mock_generator = None

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

        if self.sandbox_mode and self.mock_generator:
            processes = self.mock_generator.generate_process_list()
        else:
            processes = self._collect_real_processes()

        self._cached_processes = processes
        self._cache_time = now
        return processes

    def _collect_real_processes(self) -> list[ProcessSnapshot]:
        """使用 psutil 采集真实进程列表.

        Returns:
            进程快照列表，psutil 不可用时返回空列表
        """
        try:
            import psutil
        except ImportError:
            return []

        processes: list[ProcessSnapshot] = []
        yunxi_patterns = self.process_cfg.yunxi_process_patterns
        vscode_patterns = self.process_cfg.vscode_process_patterns

        try:
            for proc in psutil.process_iter(
                ['pid', 'name', 'exe', 'cpu_percent', 'memory_percent', 'status', 'username', 'create_time', 'num_threads', 'ppid']
            ):
                try:
                    info = proc.info
                    pid = info.get('pid') or 0
                    name = info.get('name') or ''
                    exe = info.get('exe') or ''
                    cmdline = ''
                    try:
                        cmdline = ' '.join(proc.cmdline())
                    except Exception:
                        cmdline = exe

                    # 识别云汐进程
                    is_yunxi = False
                    for pattern in yunxi_patterns:
                        if re.search(pattern, name, re.IGNORECASE) or re.search(pattern, cmdline, re.IGNORECASE):
                            is_yunxi = True
                            break

                    # 识别 VS Code 进程
                    is_vscode = False
                    for pattern in vscode_patterns:
                        if re.search(pattern, name, re.IGNORECASE):
                            is_vscode = True
                            break

                    cpu_pct = info.get('cpu_percent') or 0.0
                    mem_pct = info.get('memory_percent') or 0.0

                    snapshot = ProcessSnapshot(
                        pid=pid,
                        name=name,
                        path=exe,
                        cmdline=cmdline,
                        cpu_percent=round(cpu_pct, 1),
                        memory_mb=round(mem_pct * 16.384, 1),
                        memory_percent=round(mem_pct, 2),
                        status=str(info.get('status') or 'running'),
                        username=str(info.get('username') or ''),
                        create_time=float(info.get('create_time') or 0.0),
                        thread_count=int(info.get('num_threads') or 0),
                        ppid=int(info.get('ppid') or 0),
                        is_yunxi_process=is_yunxi,
                        yunxi_module='',
                        is_vscode_process=is_vscode,
                    )
                    processes.append(snapshot)
                except Exception:
                    continue
        except Exception:
            return []

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
