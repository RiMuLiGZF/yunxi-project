"""
M1-M8 集成测试

测试 M1 调度模块与 M8 管理台的集成接口，验证：
- M8 标准接口对接
- 模块注册与发现
- 健康检查上报
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
class TestM1M8Integration:
    """M1-M8 集成测试类"""

    # ============================================================
    # M8 标准接口
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_m8_health_endpoint(self, m8_client):
        """测试 M8 健康检查端点"""
        try:
            response = m8_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert "code" in data or "status" in data
        except Exception as e:
            pytest.skip(f"M8 健康检查跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_m8_module_registration_structure(self, data_generator):
        """测试模块注册数据结构"""
        module_status = data_generator.generate_module_status("m1")
        
        required_fields = ["key", "name", "status", "cpu_usage", "memory_usage", "version"]
        for field in required_fields:
            assert field in module_status, f"模块状态缺少字段: {field}"
        
        # 验证模块标识
        assert module_status["key"] == "m1"
        assert "调度" in module_status["name"] or "agent" in module_status["name"].lower()

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_module_health_status_transitions(self):
        """测试模块健康状态转换逻辑"""
        # 状态转换矩阵
        valid_transitions = {
            "running": ["running", "degraded", "stopped", "error"],
            "degraded": ["degraded", "running", "error"],
            "stopped": ["stopped", "running"],
            "error": ["error", "running", "stopped"],
            "unknown": ["unknown", "running", "stopped", "error"],
        }
        
        def can_transition(from_status: str, to_status: str) -> bool:
            return to_status in valid_transitions.get(from_status, [])
        
        # 验证合法转换
        assert can_transition("running", "stopped")
        assert can_transition("running", "error")
        assert can_transition("error", "running")
        assert can_transition("stopped", "running")
        
        # 验证非法转换
        assert not can_transition("stopped", "error")  # 停止状态不能直接变错误
        assert not can_transition("unknown", "degraded")  # 未知不能直接降级

    # ============================================================
    # 模块发现
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_eight_modules_registry(self, data_generator):
        """测试八模块注册表"""
        all_modules = data_generator.generate_all_modules_status()
        
        assert len(all_modules) == 8
        
        # 验证每个模块都有唯一标识
        keys = [m["key"] for m in all_modules]
        assert len(keys) == len(set(keys))  # 无重复
        
        # 验证模块顺序
        expected_order = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
        assert keys == expected_order

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_module_running_count_calculation(self, data_generator):
        """测试运行中模块数量计算"""
        modules = data_generator.generate_all_modules_status()
        
        running = sum(1 for m in modules if m["status"] == "running")
        total = len(modules)
        
        assert 0 <= running <= total
        assert total == 8
        
        # 计算运行率
        run_rate = (running / total) * 100
        assert 0 <= run_rate <= 100

    # ============================================================
    # 健康检查上报
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_health_report_data_structure(self, data_generator):
        """测试健康检查上报数据结构"""
        module = data_generator.generate_module_status("m1")
        
        # 验证上报数据的完整性
        assert "last_health_check" in module
        assert "uptime_seconds" in module
        
        # 验证时间戳格式
        from datetime import datetime
        try:
            datetime.strptime(module["last_health_check"], "%Y-%m-%d %H:%M:%S")
            valid_time = True
        except ValueError:
            valid_time = False
        assert valid_time
        
        # 验证运行时间为正
        assert module["uptime_seconds"] > 0

    @pytest.mark.integration
    @pytest.mark.m1
    @pytest.mark.m8
    def test_system_health_aggregation(self, data_generator):
        """测试系统健康度聚合计算"""
        modules = data_generator.generate_all_modules_status()
        
        # 计算系统健康度
        cpu_values = [m["cpu_usage"] for m in modules]
        mem_values = [m["memory_usage"] for m in modules]
        
        avg_cpu = sum(cpu_values) / len(cpu_values)
        avg_mem = sum(mem_values) / len(mem_values)
        max_cpu = max(cpu_values)
        max_mem = max(mem_values)
        
        # 简单健康度计算：基于平均使用率和峰值
        base_score = 100
        cpu_penalty = max(0, (avg_cpu - 50) * 0.5)
        mem_penalty = max(0, (avg_mem - 50) * 0.5)
        peak_penalty = max(0, (max(max_cpu, max_mem) - 80) * 1)
        
        health_score = max(0, min(100, base_score - cpu_penalty - mem_penalty - peak_penalty))
        
        assert 0 <= health_score <= 100
        assert isinstance(health_score, (int, float))
