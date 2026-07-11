"""
M10 系统卫士 - 进程管理单元测试

测试进程监控、进程树、Top N 排行、云汐进程识别、VS Code 检测等功能。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from m10_system_guard.process_manager import (
    ProcessManager, MockProcessGenerator, get_process_manager,
)
from m10_system_guard.models import ProcessSnapshot, ProcessTreeNode


class TestMockProcessGenerator:
    """模拟进程生成器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        self.generator = MockProcessGenerator()

    def test_generate_process_list_count(self):
        """测试生成指定数量的进程."""
        count = 50
        processes = self.generator.generate_process_list(count=count)
        # 实际数量可能略多于 count（因为云汐和 VS Code 进程是固定数量的）
        assert len(processes) >= count
        assert all(isinstance(p, ProcessSnapshot) for p in processes)

    def test_process_has_required_fields(self):
        """测试进程快照包含所有必要字段."""
        processes = self.generator.generate_process_list(count=20)
        proc = processes[0]
        assert proc.pid > 0
        assert proc.name != ""
        assert proc.path != ""
        assert proc.cpu_percent >= 0.0
        assert proc.memory_mb > 0.0
        assert proc.status in ["running", "sleeping", "idle"]
        assert proc.thread_count >= 1

    def test_yunxi_processes_exist(self):
        """测试生成的进程中包含云汐进程."""
        processes = self.generator.generate_process_list(count=50)
        yunxi_procs = [p for p in processes if p.is_yunxi_process]
        assert len(yunxi_procs) > 0
        # 应该包含 M1-M10 各模块
        modules = set(p.yunxi_module for p in yunxi_procs)
        assert "M1" in modules
        assert "M10" in modules

    def test_vscode_processes_exist(self):
        """测试生成的进程中包含 VS Code 进程."""
        processes = self.generator.generate_process_list(count=50)
        vscode_procs = [p for p in processes if p.is_vscode_process]
        assert len(vscode_procs) > 0

    def test_ppid_relationship(self):
        """测试进程的父进程 ID 有效."""
        processes = self.generator.generate_process_list(count=30)
        pids = set(p.pid for p in processes)
        # 大部分进程的 PPID 应该在进程列表中（除了根进程）
        valid_ppid = sum(1 for p in processes if p.ppid == 0 or p.ppid in pids)
        assert valid_ppid > len(processes) * 0.8

    def test_process_to_dict(self):
        """测试进程快照转字典."""
        processes = self.generator.generate_process_list(count=10)
        d = processes[0].to_dict()
        assert isinstance(d, dict)
        assert "pid" in d
        assert "name" in d
        assert "cpu_percent" in d
        assert "memory_mb" in d
        assert "is_yunxi_process" in d
        assert "is_vscode_process" in d


class TestProcessManager:
    """进程管理器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        ProcessManager._instance = None
        ProcessManager._initialized = False
        self.pm = ProcessManager()

    def test_singleton_pattern(self):
        """测试单例模式."""
        pm1 = ProcessManager()
        pm2 = ProcessManager()
        assert pm1 is pm2

    def test_get_process_manager_function(self):
        """测试全局单例获取函数."""
        import m10_system_guard.process_manager as pm
        pm._process_manager_instance = None
        instance = get_process_manager()
        assert instance is not None
        assert isinstance(instance, ProcessManager)

    def test_get_all_processes(self):
        """测试获取全量进程."""
        processes = self.pm.get_all_processes()
        assert len(processes) > 0
        assert all(isinstance(p, ProcessSnapshot) for p in processes)

    def test_process_cache(self):
        """测试进程缓存机制."""
        # 第一次获取
        procs1 = self.pm.get_all_processes()
        cache_time = self.pm._cache_time

        # 第二次获取（应该用缓存）
        procs2 = self.pm.get_all_processes()
        assert procs1 is procs2  # 同一个列表对象（缓存）

        # 强制刷新
        procs3 = self.pm.get_all_processes(refresh=True)
        assert len(procs3) > 0

    def test_get_process_tree(self):
        """测试获取进程树."""
        trees = self.pm.get_process_tree()
        assert isinstance(trees, list)
        assert len(trees) > 0
        assert all(isinstance(t, ProcessTreeNode) for t in trees)

    def test_process_tree_structure(self):
        """测试进程树结构正确性."""
        trees = self.pm.get_process_tree()
        # 检查树节点结构
        for root in trees:
            assert hasattr(root, 'process')
            assert hasattr(root, 'children')
            assert isinstance(root.children, list)

    def test_get_top_by_cpu(self):
        """测试 CPU Top N 排行."""
        top5 = self.pm.get_top_by_cpu(5)
        assert len(top5) == 5
        # 验证降序排列
        for i in range(len(top5) - 1):
            assert top5[i].cpu_percent >= top5[i + 1].cpu_percent

    def test_get_top_by_memory(self):
        """测试内存 Top N 排行."""
        top10 = self.pm.get_top_by_memory(10)
        assert len(top10) == 10
        # 验证降序排列
        for i in range(len(top10) - 1):
            assert top10[i].memory_mb >= top10[i + 1].memory_mb

    def test_get_yunxi_processes(self):
        """测试获取云汐进程."""
        yunxi = self.pm.get_yunxi_processes()
        assert len(yunxi) > 0
        assert all(p.is_yunxi_process for p in yunxi)

    def test_get_yunxi_processes_by_module(self):
        """测试按模块分组获取云汐进程."""
        by_module = self.pm.get_yunxi_processes_by_module()
        assert isinstance(by_module, dict)
        assert len(by_module) > 0
        # M1 和 M10 应该都在
        assert "M1" in by_module
        assert "M10" in by_module

    def test_get_vscode_processes(self):
        """测试获取 VS Code 进程."""
        vscode = self.pm.get_vscode_processes()
        assert len(vscode) > 0
        assert all(p.is_vscode_process for p in vscode)

    def test_get_vscode_instance_count(self):
        """测试 VS Code 实例数量估算."""
        count = self.pm.get_vscode_instance_count()
        assert count >= 1

    def test_check_vscode_limit(self):
        """测试 VS Code 限制检查."""
        result = self.pm.check_vscode_limit()
        assert "vscode_process_count" in result
        assert "estimated_instances" in result
        assert "max_instances" in result
        assert "exceeded" in result
        assert "level" in result
        assert "message" in result
        assert isinstance(result["exceeded"], bool)

    def test_get_process_by_pid(self):
        """测试按 PID 获取进程."""
        procs = self.pm.get_all_processes()
        target_pid = procs[0].pid
        proc = self.pm.get_process_by_pid(target_pid)
        assert proc is not None
        assert proc.pid == target_pid

    def test_get_process_by_pid_not_found(self):
        """测试获取不存在的 PID."""
        proc = self.pm.get_process_by_pid(999999)
        assert proc is None

    def test_search_processes(self):
        """测试搜索进程."""
        # 搜索云汐进程
        results = self.pm.search_processes("yunxi")
        assert len(results) > 0

        # 搜索 VS Code
        results = self.pm.search_processes("Code")
        assert len(results) > 0

    def test_search_processes_empty(self):
        """测试搜索无结果."""
        results = self.pm.search_processes("nonexistent_process_xyz")
        assert len(results) == 0

    def test_get_process_stats(self):
        """测试获取进程统计信息."""
        stats = self.pm.get_process_stats()
        assert "total_processes" in stats
        assert "yunxi_processes" in stats
        assert "vscode_processes" in stats
        assert "vscode_instances" in stats
        assert "total_cpu_percent" in stats
        assert "total_memory_mb" in stats
        assert "sandbox_mode" in stats
        assert stats["total_processes"] > 0

    def test_set_sandbox_mode(self):
        """测试设置沙盒模式."""
        self.pm.set_sandbox_mode(False)
        assert self.pm.sandbox_mode is False
        self.pm.set_sandbox_mode(True)
        assert self.pm.sandbox_mode is True
