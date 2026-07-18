"""
M10 系统卫士 - 启动安全检查单元测试

测试启动前安全检查、三级评估、历史记录等功能。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
from m10_system_guard.startup_check import (
    StartupChecker, get_startup_checker,
)
from m10_system_guard.models import (
    SecurityLevel, StartupCheckResult, TaskLevel,
)


class TestStartupChecker:
    """启动安全检查器测试类."""

    def setup_method(self):
        """每个测试用例前初始化."""
        StartupChecker._instance = None
        StartupChecker._initialized = False
        self.checker = StartupChecker()

    def test_singleton_pattern(self):
        """测试单例模式."""
        c1 = StartupChecker()
        c2 = StartupChecker()
        assert c1 is c2

    def test_get_startup_checker_function(self):
        """测试全局单例获取函数."""
        import m10_system_guard.startup_check as sc
        sc._startup_checker_instance = None
        instance = get_startup_checker()
        assert instance is not None
        assert isinstance(instance, StartupChecker)

    def test_check_before_start_returns_result(self):
        """测试启动检查返回正确类型."""
        result = self.checker.check_before_start(
            task_name="test_task",
            task_level="normal",
        )
        assert isinstance(result, StartupCheckResult)
        assert result.task_name == "test_task"
        assert result.check_id != ""

    def test_check_result_structure(self):
        """测试检查结果结构完整性."""
        result = self.checker.check_before_start(task_name="test")
        d = result.to_dict()
        assert "check_id" in d
        assert "overall_level" in d
        assert "memory_ok" in d
        assert "cpu_ok" in d
        assert "temperature_ok" in d
        assert "same_process_ok" in d
        assert "details" in d
        assert "recommended_action" in d
        assert "allowed_to_start" in d

    def test_overall_level_is_valid(self):
        """测试总体级别是有效值."""
        result = self.checker.check_before_start(task_name="test")
        assert isinstance(result.overall_level, SecurityLevel)
        assert result.overall_level in [
            SecurityLevel.SAFE, SecurityLevel.WARNING, SecurityLevel.DANGER
        ]

    def test_allowed_to_start_matches_level(self):
        """测试允许启动标志与级别匹配."""
        result = self.checker.check_before_start(task_name="test")
        if result.overall_level == SecurityLevel.DANGER:
            assert result.allowed_to_start is False
        else:
            assert result.allowed_to_start is True

    def test_light_task_check(self):
        """测试轻量级任务检查."""
        result = self.checker.check_before_start(
            task_name="light_task",
            task_level="light",
            estimated_cpu_percent=1.0,
            estimated_memory_mb=10.0,
        )
        # 轻量级任务应该更容易通过
        assert isinstance(result.overall_level, SecurityLevel)

    def test_heavy_task_check(self):
        """测试重型任务检查."""
        result = self.checker.check_before_start(
            task_name="heavy_task",
            task_level="heavy",
            estimated_cpu_percent=50.0,
            estimated_memory_mb=2000.0,
        )
        assert isinstance(result.overall_level, SecurityLevel)

    def test_super_heavy_task_check(self):
        """测试超重型任务检查."""
        result = self.checker.check_before_start(
            task_name="super_heavy_task",
            task_level="super_heavy",
            estimated_cpu_percent=80.0,
            estimated_memory_mb=8000.0,
        )
        assert isinstance(result.overall_level, SecurityLevel)

    def test_details_contain_all_checks(self):
        """测试详细信息包含所有检查项."""
        result = self.checker.check_before_start(task_name="test")
        assert "memory" in result.details
        assert "cpu" in result.details
        assert "temperature" in result.details
        assert "same_process" in result.details

    def test_memory_details_structure(self):
        """测试内存检查详情结构."""
        result = self.checker.check_before_start(task_name="test")
        mem_detail = result.details["memory"]
        assert "current_usage_percent" in mem_detail
        assert "status" in mem_detail
        assert "message" in mem_detail
        assert mem_detail["status"] in ["safe", "warning", "danger"]

    def test_cpu_details_structure(self):
        """测试 CPU 检查详情结构."""
        result = self.checker.check_before_start(task_name="test")
        cpu_detail = result.details["cpu"]
        assert "current_usage_percent" in cpu_detail
        assert "status" in cpu_detail
        assert cpu_detail["status"] in ["safe", "warning", "danger"]

    def test_recommendation_not_empty(self):
        """测试建议不为空."""
        result = self.checker.check_before_start(task_name="test")
        assert result.recommended_action != ""

    def test_check_history_records(self):
        """测试检查历史记录."""
        initial_count = len(self.checker._check_history)
        self.checker.check_before_start(task_name="test1")
        self.checker.check_before_start(task_name="test2")
        assert len(self.checker._check_history) == initial_count + 2

    def test_get_check_history(self):
        """测试获取检查历史."""
        self.checker.check_before_start(task_name="history_test")
        history = self.checker.get_check_history(limit=5)
        assert isinstance(history, list)
        assert len(history) >= 1
        assert isinstance(history[0], StartupCheckResult)

    def test_get_check_history_limit(self):
        """测试历史记录数量限制."""
        for i in range(10):
            self.checker.check_before_start(task_name=f"test_{i}")
        history = self.checker.get_check_history(limit=3)
        assert len(history) == 3

    def test_get_stats(self):
        """测试获取统计信息."""
        self.checker.check_before_start(task_name="stats_test")
        stats = self.checker.get_stats()
        assert "total_checks" in stats
        assert "safe_count" in stats
        assert "warning_count" in stats
        assert "danger_count" in stats
        assert "allowed_rate" in stats
        assert stats["total_checks"] >= 1
        assert 0 <= stats["allowed_rate"] <= 100

    def test_same_process_check(self):
        """测试同类进程检查."""
        result = self.checker.check_before_start(
            task_name="Code",
            same_process_name="Code",
        )
        assert "same_process" in result.details
        proc_detail = result.details["same_process"]
        assert "similar_process_count" in proc_detail
        assert "max_allowed" in proc_detail

    def test_security_level_values(self):
        """测试安全级别枚举值."""
        assert SecurityLevel.SAFE.value == "safe"
        assert SecurityLevel.WARNING.value == "warning"
        assert SecurityLevel.DANGER.value == "danger"

    def test_multiple_checks_consistency(self):
        """测试多次检查结果一致性（模拟数据下可能波动，但结构应一致）."""
        results = []
        for i in range(5):
            r = self.checker.check_before_start(task_name=f"consistency_test_{i}")
            results.append(r)

        # 所有结果都应该有有效的级别
        for r in results:
            assert r.overall_level in [SecurityLevel.SAFE, SecurityLevel.WARNING, SecurityLevel.DANGER]
