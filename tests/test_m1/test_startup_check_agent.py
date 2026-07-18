"""
启动检查 Agent 测试

测试系统启动快速检查 Agent 的功能，验证：
- 检查项数据结构
- 检查结果聚合
- 健康度计算
- 错误处理
"""

import sys
import pytest
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).parent.parent.parent
# ============================================================
# 模拟检查结果数据类
# ============================================================

@dataclass
class CheckItemResult:
    """单个检查项结果"""
    name: str
    status: str = "unknown"  # passed/warning/failed/unknown
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class StartupCheckResult:
    """启动检查整体结果"""
    check_id: str = ""
    overall_status: str = "unknown"  # healthy/degraded/unhealthy
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    duration_ms: int = 0
    checks: Dict[str, CheckItemResult] = field(default_factory=dict)
    error_summary: str = ""
    triggered_by: str = "system"

    def calculate_overall_status(self):
        """根据检查结果计算整体状态"""
        if not self.checks:
            self.overall_status = "unknown"
            return
        
        passed = 0
        warning = 0
        failed = 0
        
        for check in self.checks.values():
            if check.status == "passed":
                passed += 1
            elif check.status == "warning":
                warning += 1
            elif check.status == "failed":
                failed += 1
        
        self.total_checks = len(self.checks)
        self.passed_checks = passed
        self.failed_checks = failed
        
        if failed > 0:
            self.overall_status = "unhealthy"
        elif warning > 0:
            self.overall_status = "degraded"
        else:
            self.overall_status = "healthy"

    def get_health_score(self) -> float:
        """计算健康度评分 (0-100)"""
        if not self.checks:
            return 0.0
        
        total_weight = 0
        score = 0
        
        weights = {
            "passed": 100,
            "warning": 60,
            "failed": 0,
            "unknown": 50,
        }
        
        for check in self.checks.values():
            weight = 1.0  # 每个检查项权重相同
            total_weight += weight
            score += weights.get(check.status, 50) * weight
        
        return round(score / total_weight, 1) if total_weight > 0 else 0.0


class TestStartupCheckAgent:
    """启动检查 Agent 测试类"""

    # ============================================================
    # 检查结果数据结构
    # ============================================================

    @pytest.mark.m1
    @pytest.mark.health
    def test_check_item_result_creation(self):
        """测试检查项结果创建"""
        result = CheckItemResult(
            name="database_connection",
            status="passed",
            message="数据库连接正常",
            details={"latency_ms": 5, "version": "3.45.1"},
            duration_ms=5
        )
        
        assert result.name == "database_connection"
        assert result.status == "passed"
        assert result.message == "数据库连接正常"
        assert result.details["latency_ms"] == 5
        assert result.duration_ms == 5

    @pytest.mark.m1
    @pytest.mark.health
    def test_check_item_default_values(self):
        """测试检查项默认值"""
        result = CheckItemResult(name="test_check")
        
        assert result.status == "unknown"
        assert result.message == ""
        assert result.details == {}
        assert result.duration_ms == 0

    # ============================================================
    # 整体检查结果
    # ============================================================

    @pytest.mark.smoke
    @pytest.mark.m1
    @pytest.mark.health
    def test_all_checks_passed(self):
        """测试所有检查通过的情况"""
        result = StartupCheckResult()
        result.checks = {
            "database": CheckItemResult("database", "passed", "数据库正常"),
            "modules": CheckItemResult("modules", "passed", "模块正常"),
            "ollama": CheckItemResult("ollama", "passed", "Ollama 服务正常"),
            "compute": CheckItemResult("compute", "passed", "算力平台正常"),
            "disk": CheckItemResult("disk", "passed", "磁盘空间充足"),
        }
        result.calculate_overall_status()
        
        assert result.overall_status == "healthy"
        assert result.total_checks == 5
        assert result.passed_checks == 5
        assert result.failed_checks == 0
        assert result.get_health_score() == 100.0

    @pytest.mark.m1
    @pytest.mark.health
    def test_some_checks_failed(self):
        """测试部分检查失败的情况"""
        result = StartupCheckResult()
        result.checks = {
            "database": CheckItemResult("database", "passed", "数据库正常"),
            "modules": CheckItemResult("modules", "passed", "模块正常"),
            "ollama": CheckItemResult("ollama", "failed", "Ollama 服务未启动"),
            "compute": CheckItemResult("compute", "passed", "算力平台正常"),
            "disk": CheckItemResult("disk", "passed", "磁盘空间充足"),
        }
        result.calculate_overall_status()
        
        assert result.overall_status == "unhealthy"
        assert result.failed_checks == 1
        assert result.get_health_score() == 80.0  # 4 passed, 1 failed = (4*100+0)/5 = 80

    @pytest.mark.m1
    @pytest.mark.health
    def test_warning_status(self):
        """测试警告状态"""
        result = StartupCheckResult()
        result.checks = {
            "database": CheckItemResult("database", "passed", "数据库正常"),
            "modules": CheckItemResult("modules", "passed", "模块正常"),
            "disk": CheckItemResult("disk", "warning", "磁盘使用率 85%"),
        }
        result.calculate_overall_status()
        
        assert result.overall_status == "degraded"
        assert result.failed_checks == 0
        assert 60 < result.get_health_score() < 100

    @pytest.mark.m1
    @pytest.mark.health
    def test_no_checks_unknown_status(self):
        """测试无检查项时的状态"""
        result = StartupCheckResult()
        result.calculate_overall_status()
        
        assert result.overall_status == "unknown"
        assert result.total_checks == 0
        assert result.get_health_score() == 0.0

    # ============================================================
    # 健康度评分
    # ============================================================

    @pytest.mark.m1
    @pytest.mark.health
    def test_health_score_range(self):
        """测试健康度评分范围"""
        result = StartupCheckResult()
        
        # 全部通过
        for i in range(10):
            result.checks[f"check_{i}"] = CheckItemResult(f"check_{i}", "passed")
        assert result.get_health_score() == 100.0
        
        # 全部失败
        result.checks.clear()
        for i in range(10):
            result.checks[f"check_{i}"] = CheckItemResult(f"check_{i}", "failed")
        assert result.get_health_score() == 0.0

    @pytest.mark.m1
    @pytest.mark.health
    def test_health_score_mixed(self):
        """测试混合状态下的健康度评分"""
        result = StartupCheckResult()
        result.checks = {
            "check1": CheckItemResult("check1", "passed"),   # 100
            "check2": CheckItemResult("check2", "passed"),   # 100
            "check3": CheckItemResult("check3", "warning"),  # 60
            "check4": CheckItemResult("check4", "failed"),   # 0
        }
        score = result.get_health_score()
        expected = (100 + 100 + 60 + 0) / 4  # 65.0
        assert abs(score - expected) < 0.1

    # ============================================================
    # 八模块检查
    # ============================================================

    @pytest.mark.m1
    @pytest.mark.health
    def test_eight_modules_health_check(self, data_generator):
        """测试八大模块健康检查"""
        modules = data_generator.generate_all_modules_status()
        
        assert len(modules) == 8
        
        module_keys = [m["key"] for m in modules]
        expected_keys = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
        assert module_keys == expected_keys
        
        # 验证每个模块都有状态字段
        for mod in modules:
            assert "status" in mod
            assert "cpu_usage" in mod
            assert "memory_usage" in mod
            assert 0 <= mod["cpu_usage"] <= 100
            assert 0 <= mod["memory_usage"] <= 100

    @pytest.mark.m1
    @pytest.mark.health
    def test_module_status_classification(self):
        """测试模块状态分类"""
        def classify_module_status(cpu: int, mem: int) -> str:
            if cpu > 90 or mem > 90:
                return "critical"
            elif cpu > 70 or mem > 70:
                return "warning"
            else:
                return "normal"
        
        assert classify_module_status(30, 40) == "normal"
        assert classify_module_status(75, 50) == "warning"
        assert classify_module_status(50, 75) == "warning"
        assert classify_module_status(95, 50) == "critical"
        assert classify_module_status(50, 95) == "critical"
        assert classify_module_status(95, 95) == "critical"
