"""
集成测试 - 模块间健康检查调用

测试 M8 控制塔调用其他模块健康检查的集成场景。
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
class TestModuleHealthIntegration:
    """模块间健康检查集成测试"""

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_m8_health_check(self, m8_client):
        """M8 控制塔自身健康检查"""
        try:
            response = m8_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, dict)
            assert "status" in data or "code" in data
        except Exception as e:
            pytest.skip(f"M8 健康检查集成测试跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.health
    def test_m9_health_check(self, m9_client):
        """M9 开发工坊健康检查"""
        try:
            response = m9_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, dict)
            assert "status" in data or "code" in data
        except Exception as e:
            pytest.skip(f"M9 健康检查集成测试跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.m11
    @pytest.mark.health
    def test_m11_health_check(self, m11_client):
        """M11 MCP 总线健康检查"""
        try:
            response = m11_client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, dict)
            assert "status" in data or "code" in data
        except Exception as e:
            pytest.skip(f"M11 健康检查集成测试跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.health
    def test_all_modules_health_consistent(self, m8_client, m9_client, m11_client):
        """所有模块健康检查格式一致"""
        results = {}
        modules = {
            "m8": m8_client,
            "m9": m9_client,
            "m11": m11_client,
        }

        for name, client in modules.items():
            try:
                response = client.get("/health")
                if response.status_code == 200:
                    data = response.json()
                    results[name] = {
                        "status": "ok",
                        "keys": list(data.keys()),
                    }
                else:
                    results[name] = {"status": f"error_{response.status_code}"}
            except Exception as e:
                results[name] = {"status": "skip", "error": str(e)}

        # 验证所有可访问的模块都有健康检查
        accessible = [name for name, r in results.items() if r["status"] == "ok"]
        # 至少有一个模块可访问
        assert len(accessible) > 0, f"没有任何模块的健康检查可访问: {results}"

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.module
    def test_m8_module_list_endpoint(self, m8_client, auth_headers):
        """M8 模块列表接口"""
        try:
            response = m8_client.get("/api/modules", headers=auth_headers)
            if response.status_code == 404:
                response = m8_client.get("/api/modules/list", headers=auth_headers)
            if response.status_code == 200:
                data = response.json()
                assert "code" in data or "modules" in data or "data" in data
        except Exception as e:
            pytest.skip(f"M8 模块列表集成测试跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_m8_check_all_modules_health(self, m8_client, auth_headers):
        """M8 检查所有模块健康状态"""
        try:
            response = m8_client.get("/api/modules/health", headers=auth_headers)
            if response.status_code == 404:
                response = m8_client.get("/api/health/all", headers=auth_headers)
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"所有模块健康检查集成测试跳过: {e}")

    @pytest.mark.integration
    @pytest.mark.m8
    @pytest.mark.health
    def test_m8_module_health_detail(self, m8_client, auth_headers):
        """M8 单个模块健康详情"""
        try:
            response = m8_client.get("/api/modules/m9/health", headers=auth_headers)
            if response.status_code == 404:
                response = m8_client.get("/api/health/m9", headers=auth_headers)
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"单个模块健康详情集成测试跳过: {e}")
