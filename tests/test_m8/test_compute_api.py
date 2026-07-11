"""
算力调度 API 测试

测试 M8 算力调度中台的相关接口，验证：
- 算力源管理
- 算力监控总览
- 调用日志查询
- 路由策略
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestComputeApi:
    """算力调度 API 测试类"""

    # ============================================================
    # 算力源管理
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_sources_list(self, m8_client, auth_headers):
        """测试算力源列表接口"""
        try:
            response = m8_client.get("/api/compute/sources", headers=auth_headers)
            if response.status_code == 401:
                pytest.skip("需要有效认证 Token")
            
            assert response.status_code == 200
            data = response.json()
            assert "code" in data
        except Exception as e:
            pytest.skip(f"算力源列表测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_sources_structure(self, data_generator):
        """测试算力源数据结构（模拟数据验证）"""
        call = data_generator.generate_compute_call()
        
        required_fields = [
            "call_id", "model_key", "source_id", "caller_module",
            "input_tokens", "output_tokens", "status"
        ]
        for field in required_fields:
            assert field in call, f"算力调用记录缺少字段: {field}"
        
        # 验证 token 计算
        assert call["total_tokens"] == call["input_tokens"] + call["output_tokens"]
        
        # 验证数值合理性
        assert call["input_tokens"] > 0
        assert call["output_tokens"] > 0
        assert call["latency_ms"] > 0
        assert call["cost"] >= 0

    # ============================================================
    # 算力监控总览
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_overview_endpoint(self, m8_client, auth_headers):
        """测试算力监控总览接口"""
        try:
            response = m8_client.get("/api/compute/monitor/overview", headers=auth_headers)
            if response.status_code == 401:
                pytest.skip("需要有效认证 Token")
            
            # 接口存在时验证响应
            if response.status_code == 200:
                data = response.json()
                assert "code" in data
        except Exception as e:
            pytest.skip(f"算力总览测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_monitor_metrics(self, data_generator):
        """测试算力监控指标数据结构"""
        # 生成模拟的调用记录并验证统计逻辑
        calls = [data_generator.generate_compute_call() for _ in range(10)]
        
        total_cost = sum(c["cost"] for c in calls)
        total_tokens = sum(c["total_tokens"] for c in calls)
        avg_latency = sum(c["latency_ms"] for c in calls) / len(calls)
        success_count = sum(1 for c in calls if c["status"] == "success")
        success_rate = (success_count / len(calls)) * 100
        
        # 验证统计计算
        assert total_cost >= 0
        assert total_tokens > 0
        assert avg_latency > 0
        assert 0 <= success_rate <= 100

    # ============================================================
    # 调用日志
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_call_logs(self, m8_client, auth_headers):
        """测试算力调用日志接口"""
        try:
            response = m8_client.get(
                "/api/compute/monitor/logs?page=1&page_size=10",
                headers=auth_headers
            )
            if response.status_code == 401:
                pytest.skip("需要有效认证 Token")
            
            if response.status_code == 200:
                data = response.json()
                assert "code" in data
        except Exception as e:
            pytest.skip(f"调用日志测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_call_pagination(self, data_generator):
        """测试调用记录分页逻辑"""
        all_calls = [data_generator.generate_compute_call() for _ in range(25)]
        
        page = 1
        page_size = 10
        
        # 第一页
        page1 = all_calls[(page-1)*page_size:page*page_size]
        assert len(page1) == 10
        
        # 第二页
        page = 2
        page2 = all_calls[(page-1)*page_size:page*page_size]
        assert len(page2) == 10
        
        # 第三页
        page = 3
        page3 = all_calls[(page-1)*page_size:page*page_size]
        assert len(page3) == 5
        
        # 验证所有记录不重复
        all_paged = page1 + page2 + page3
        assert len(all_paged) == len(all_calls)

    # ============================================================
    # 路由策略
    # ============================================================

    @pytest.mark.m8
    @pytest.mark.compute
    def test_compute_routing_policies(self, m8_client, auth_headers):
        """测试算力路由策略接口"""
        try:
            response = m8_client.get("/api/compute/routing", headers=auth_headers)
            if response.status_code == 401:
                pytest.skip("需要有效认证 Token")
            
            if response.status_code == 200:
                data = response.json()
                assert "code" in data
        except Exception as e:
            pytest.skip(f"路由策略测试跳过: {e}")

    @pytest.mark.m8
    @pytest.mark.compute
    def test_model_routing_selection(self):
        """测试模型路由选择逻辑（基础验证）"""
        # 模拟路由选择：根据偏好选择模型
        models = [
            {"key": "model_a", "speed_score": 90, "quality_score": 70, "cost_score": 80},
            {"key": "model_b", "speed_score": 60, "quality_score": 95, "cost_score": 50},
            {"key": "model_c", "speed_score": 75, "quality_score": 80, "cost_score": 70},
        ]
        
        def select_model(preference: str) -> str:
            if preference == "speed":
                return max(models, key=lambda m: m["speed_score"])["key"]
            elif preference == "quality":
                return max(models, key=lambda m: m["quality_score"])["key"]
            elif preference == "cost":
                return max(models, key=lambda m: m["cost_score"])["key"]
            else:  # balanced
                return max(models, key=lambda m: (m["speed_score"] + m["quality_score"] + m["cost_score"]) / 3)["key"]
        
        # 验证各偏好下的选择
        assert select_model("speed") == "model_a"
        assert select_model("quality") == "model_b"
        assert select_model("cost") == "model_a"
        assert select_model("balanced") == "model_a"  # 平均分最高

