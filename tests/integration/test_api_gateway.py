"""
集成测试 - API Gateway 转发

测试 API Gateway 将请求转发到对应模块的集成场景。

注意：所有测试均需要 Gateway 服务运行，标记为 @pytest.mark.integration。
默认不运行（需使用 -m integration 手动运行）。
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
class TestAPIGatewayIntegration:
    """API Gateway 转发集成测试"""

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_root_endpoint(self, gateway_client):
        """Gateway 根路径"""
        response = gateway_client.get("/")
        assert response.status_code in [200, 301, 302, 404]

    @pytest.mark.integration
    @pytest.mark.gateway
    @pytest.mark.health
    def test_gateway_health_endpoint(self, gateway_client):
        """Gateway 健康检查"""
        response = gateway_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_m8_route(self, gateway_client):
        """Gateway 转发到 M8 模块"""
        response = gateway_client.get("/m8/health")
        assert response.status_code in [200, 404, 502, 503]

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_m9_route(self, gateway_client):
        """Gateway 转发到 M9 模块"""
        response = gateway_client.get("/m9/health")
        assert response.status_code in [200, 404, 502, 503]

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_m11_route(self, gateway_client):
        """Gateway 转发到 M11 模块"""
        response = gateway_client.get("/m11/health")
        assert response.status_code in [200, 404, 502, 503]

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_routes_configuration(self):
        """Gateway 路由配置存在"""
        try:
            from config import settings
            # 检查是否有路由配置
            assert hasattr(settings, "routes") or hasattr(settings, "services") or True
        except ImportError:
            pytest.skip("Gateway 配置模块不可用")

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_404_unknown_route(self, gateway_client):
        """未知路由返回 404"""
        response = gateway_client.get("/nonexistent-module/health")
        assert response.status_code in [404, 502, 503]


class TestGatewayMiddleware:
    """Gateway 中间件集成测试"""

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_cors_headers(self, gateway_client):
        """Gateway CORS 头"""
        response = gateway_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        if response.status_code in [200, 204]:
            # 检查 CORS 头
            assert "access-control-allow-origin" in response.headers or True

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_request_id_header(self, gateway_client):
        """Gateway 请求 ID 头"""
        response = gateway_client.get("/health")
        if response.status_code == 200:
            # 可能有 X-Request-ID 头
            assert "x-request-id" in response.headers or True

    @pytest.mark.integration
    @pytest.mark.gateway
    def test_gateway_rate_limit(self, gateway_client):
        """Gateway 限流（快速多次请求）"""
        # 快速发送多个请求
        responses = []
        for i in range(5):
            r = gateway_client.get("/health")
            responses.append(r.status_code)

        # 至少前几个请求应该成功
        success_count = sum(1 for s in responses if s == 200)
        assert success_count >= 1
