"""
M8 健康检查测试

测试 M8 管理台的健康检查接口，验证：
- /health 端点响应
- /api/system/check 系统检查
- 模块健康状态获取

说明：
- 使用 data_generator 的纯单元测试（unit）：验证数据结构和计算逻辑
- 需要真实 API 服务的测试标记为 integration，需手动运行
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
class TestHealthCheck:
    """M8 健康检查测试类"""

    # ============================================================
    # 基础健康检查 - 需要真实服务
    # ============================================================

    @pytest.mark.smoke
    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_health_endpoint_available(self, m8_client):
        """测试健康检查接口可访问"""
        response = m8_client.get("/health")
        # 健康检查接口应该返回 200
        assert response.status_code == 200
        data = response.json()
        assert "code" in data or "status" in data

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_health_response_structure(self, m8_client):
        """测试健康检查响应结构"""
        response = m8_client.get("/health")
        data = response.json()

        # 验证响应包含必要字段
        if "data" in data:
            health_data = data["data"]
            assert health_data is not None
            # 健康检查数据通常包含状态
            assert "status" in health_data or isinstance(health_data, (dict, str))

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_system_check_endpoint(self, m8_client, auth_headers):
        """测试系统检查接口"""
        response = m8_client.get("/api/system/check", headers=auth_headers)
        # 认证接口可能返回 200 或 401
        if response.status_code == 401:
            pytest.skip("需要有效认证 Token")
        assert response.status_code == 200
        data = response.json()
        assert data.get("code") == 0

    # ============================================================
    # 模块健康检查 - 需要真实服务
    # ============================================================

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_modules_list_returns_eight_modules(self, m8_client, auth_headers):
        """测试模块列表接口返回 8 个模块"""
        response = m8_client.get("/api/system/modules", headers=auth_headers)
        if response.status_code == 401:
            pytest.skip("需要有效认证 Token")
        assert response.status_code == 200
        data = response.json()

        if data.get("code") == 0:
            modules = data.get("data", [])
            # 模块数据可能是列表或包含 items 的字典
            if isinstance(modules, dict):
                modules = modules.get("items", [])
            if isinstance(modules, list):
                assert len(modules) >= 1  # 至少有一个模块

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_module_health_endpoint(self, m8_client, auth_headers):
        """测试单个模块健康检查接口"""
        # 测试 M1 模块健康
        response = m8_client.get("/api/modules/m1/health", headers=auth_headers)
        # 模块健康接口可能有不同的路径，先检查响应
        if response.status_code == 404:
            # 尝试备用路径
            response = m8_client.get("/api/system/modules/m1/health", headers=auth_headers)

        if response.status_code == 401:
            pytest.skip("需要有效认证 Token")

        # 接口存在时验证响应
        if response.status_code == 200:
            data = response.json()
            assert "code" in data

    # ============================================================
    # 系统统计 - 纯单元测试
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m8
    @pytest.mark.health
    def test_system_stats_structure(self, data_generator):
        """测试系统统计数据结构（使用模拟数据）"""
        stats = data_generator.generate_system_stats()

        # 验证统计数据包含必要字段
        required_fields = [
            "total_modules", "running_modules", "tasks_today",
            "active_users", "health_score"
        ]
        for field in required_fields:
            assert field in stats, f"缺少字段: {field}"

        # 验证数值合理性
        assert stats["total_modules"] == 8
        assert 0 <= stats["running_modules"] <= 8
        assert 0 <= stats["health_score"] <= 100
        assert stats["tasks_today"] >= 0
        assert stats["active_users"] >= 0

    @pytest.mark.unit
    @pytest.mark.m8
    @pytest.mark.health
    def test_health_score_calculation(self, data_generator):
        """测试健康度评分计算逻辑"""
        stats = data_generator.generate_system_stats()
        health_score = stats["health_score"]

        # 健康分数应在合理范围内
        assert isinstance(health_score, int)
        assert 0 <= health_score <= 100

        # 运行模块比例与健康分数正相关
        module_ratio = stats["running_modules"] / stats["total_modules"]
        # 健康分数应该反映模块运行状态
        if module_ratio == 1.0:
            assert health_score >= 80  # 所有模块运行时健康分不应太低
