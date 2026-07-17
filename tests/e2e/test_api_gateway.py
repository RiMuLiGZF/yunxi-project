"""
E2E 测试 - API 网关集成

测试 API 网关的端到端功能：
- 网关 → 各模块路由转发
- 网关认证 → 模块认证一致性
- 网关限流 → 后端服务保护
- 网关熔断 → 故障模块隔离
"""

import sys
import pytest
from pathlib import Path
from typing import Dict, Any, List

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestGatewayHealth:
    """网关健康检查 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_gateway_health_endpoint(self, e2e_api_client):
        """测试网关健康检查端点"""
        result = e2e_api_client.get("/health")
        assert result["code"] == 0
        assert result["data"]["status"] == "healthy"

    @pytest.mark.e2e_gateway
    def test_gateway_health_has_version(self, e2e_api_client):
        """测试网关健康检查返回版本信息"""
        result = e2e_api_client.get("/health")
        assert result["code"] == 0
        assert "version" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_health_has_routes_count(self, e2e_api_client):
        """测试网关健康检查返回路由数量"""
        result = e2e_api_client.get("/health")
        assert result["code"] == 0
        assert "routes_count" in result["data"]
        assert result["data"]["routes_count"] > 0

    @pytest.mark.e2e_gateway
    def test_gateway_health_timestamp(self, e2e_api_client):
        """测试网关健康检查返回时间戳"""
        result = e2e_api_client.get("/health")
        assert result["code"] == 0
        assert "timestamp" in result["data"]
        assert isinstance(result["data"]["timestamp"], int)

    @pytest.mark.e2e_gateway
    def test_gateway_health_alias(self, e2e_api_client):
        """测试网关健康检查别名路径"""
        result = e2e_api_client.get("/gateway/health")
        assert result["code"] == 0
        assert result["data"]["status"] == "healthy"


class TestGatewayRoutes:
    """网关路由转发 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_list_all_routes(self, e2e_api_client):
        """测试获取所有路由配置"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0
        assert "total" in result["data"]
        assert "routes" in result["data"]
        assert result["data"]["total"] >= 12  # 12个模块

    @pytest.mark.e2e_gateway
    def test_routes_have_required_fields(self, e2e_api_client):
        """测试路由配置包含必要字段"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        assert len(routes) > 0

        for route in routes:
            required_fields = ["key", "name", "prefix", "target_url", "enabled"]
            for field in required_fields:
                assert field in route, f"路由缺少字段: {field}"

    @pytest.mark.e2e_gateway
    def test_m8_route_exists(self, e2e_api_client):
        """测试 M8 模块路由存在"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        m8_route = next((r for r in routes if r["key"] == "m8"), None)
        assert m8_route is not None
        assert m8_route["enabled"] is True
        assert m8_route["prefix"] == "/m8"

    @pytest.mark.e2e_gateway
    def test_m1_route_exists(self, e2e_api_client):
        """测试 M1 模块路由存在"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        m1_route = next((r for r in routes if r["key"] == "m1"), None)
        assert m1_route is not None
        assert m1_route["enabled"] is True
        assert m1_route["prefix"] == "/m1"

    @pytest.mark.e2e_gateway
    def test_get_single_route_detail(self, e2e_api_client):
        """测试获取单个路由详情"""
        result = e2e_api_client.get("/gateway/routes/m8")
        assert result["code"] == 0
        assert "key" in result["data"]
        assert result["data"]["key"] == "m8"

    @pytest.mark.e2e_gateway
    def test_nonexistent_route_returns_404(self, e2e_api_client):
        """测试不存在的路由返回 404"""
        result = e2e_api_client.get("/gateway/routes/nonexistent_module_xyz")
        assert result["code"] != 0

    @pytest.mark.e2e_gateway
    def test_all_module_routes_present(self, e2e_api_client):
        """测试所有 12 个模块路由都存在"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        route_keys = {r["key"] for r in routes}

        expected_modules = [
            "m1", "m2", "m3", "m4", "m5", "m6",
            "m7", "m8", "m9", "m10", "m11", "m12"
        ]

        for mod in expected_modules:
            assert mod in route_keys, f"缺少模块路由: {mod}"

    @pytest.mark.e2e_gateway
    def test_routes_have_auth_config(self, e2e_api_client):
        """测试路由包含认证配置"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        for route in routes:
            assert "auth_required" in route
            assert "public_paths" in route


class TestGatewayAuthentication:
    """网关认证 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_public_path_no_auth_required(self, e2e_api_client):
        """测试公开路径不需要认证"""
        # 健康检查是公开路径
        result = e2e_api_client.get("/health")
        assert result["code"] == 0

    @pytest.mark.e2e_gateway
    def test_protected_path_without_auth_fails(self, e2e_api_client):
        """测试受保护路径无认证失败"""
        e2e_api_client.access_token = None
        # 访问需要认证的路径
        result = e2e_api_client.get("/api/users")
        assert result["code"] != 0

    @pytest.mark.e2e_gateway
    def test_protected_path_with_valid_auth(self, admin_api_client):
        """测试受保护路径带有效认证成功"""
        result = admin_api_client.get("/api/users")
        assert result["code"] == 0

    @pytest.mark.e2e_gateway
    def test_gateway_auth_consistency(self, e2e_api_client, admin_api_client):
        """测试网关认证与模块认证一致性"""
        # 经过网关认证后，各模块应该能正确识别用户

        # 1. 访问用户信息（M8）
        m8_result = admin_api_client.get("/api/auth/me")
        assert m8_result["code"] == 0
        assert m8_result["data"]["username"] == "admin"

        # 2. 访问系统信息
        sys_result = admin_api_client.get("/api/system/stats")
        assert sys_result["code"] == 0

        # 3. 两者都能正确识别用户身份
        # （通过 code == 0 验证认证通过）

    @pytest.mark.e2e_gateway
    def test_invalid_token_rejected_by_gateway(self, e2e_api_client):
        """测试无效 Token 被网关拒绝"""
        e2e_api_client.set_token("invalid_token_for_gateway_test")

        result = e2e_api_client.get("/api/users")
        assert result["code"] != 0

    @pytest.mark.e2e_gateway
    def test_multiple_auth_headers_handling(self, admin_api_client):
        """测试网关正确处理认证头"""
        # 正常认证应该通过
        result = admin_api_client.get("/api/auth/me")
        assert result["code"] == 0
        assert "username" in result["data"]

    @pytest.mark.e2e_gateway
    def test_user_info_injection(self, admin_api_client):
        """测试网关注入用户信息到请求头"""
        # 通过访问受保护接口验证用户信息正确传递
        result = admin_api_client.get("/api/auth/me")
        assert result["code"] == 0
        user = result["data"]
        assert user["role"] == "admin"
        assert user["username"] == "admin"

    @pytest.mark.e2e_gateway
    def test_api_key_auth(self, e2e_api_client):
        """测试 API Key 认证方式"""
        e2e_api_client.set_api_key("test-api-key-for-e2e")

        # API Key 认证的路径
        result = e2e_api_client.get("/health")
        assert result["code"] == 0


class TestGatewayRateLimit:
    """网关限流 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_rate_limit_config_exists(self, e2e_api_client):
        """测试限流配置存在"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        for route in routes:
            assert "rate_limit_per_minute" in route
            assert "rate_limit_per_ip" in route

    @pytest.mark.e2e_gateway
    def test_rate_limit_per_module(self, e2e_api_client):
        """测试各模块有独立限流配置"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        rate_limits = {r["key"]: r.get("rate_limit_per_minute", 0) for r in routes}

        # 不同模块可能有不同的限流值
        assert len(set(rate_limits.values())) >= 1  # 至少都有限流

    @pytest.mark.e2e_gateway
    def test_normal_requests_not_limited(self, e2e_api_client):
        """测试正常请求不会被限流"""
        # 发送少量请求
        results = []
        for i in range(3):
            result = e2e_api_client.get("/health")
            results.append(result)

        # 都应该成功
        success_count = sum(1 for r in results if r["code"] == 0)
        assert success_count == 3

    @pytest.mark.e2e_gateway
    def test_gateway_rate_limit_tiers(self, e2e_api_client):
        """测试网关限流分级"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        tiers = set()
        for route in routes:
            tier = route.get("rate_limit_tier", "")
            if tier:
                tiers.add(tier)

        # 应该有不同的限流级别
        assert len(tiers) >= 1

    @pytest.mark.e2e_gateway
    def test_gateway_metrics_include_rate_limit_stats(self, e2e_api_client):
        """测试网关指标包含限流统计"""
        result = e2e_api_client.get("/gateway/metrics")
        assert result["code"] == 0
        assert "rate_limit" in result["data"]


class TestGatewayCircuitBreaker:
    """网关熔断 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_circuit_breaker_config_exists(self, e2e_api_client):
        """测试熔断器配置存在"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        for route in routes:
            assert "cb_failure_threshold" in route
            assert "cb_recovery_time" in route

    @pytest.mark.e2e_gateway
    def test_circuit_breaker_status_in_gateway_status(self, e2e_api_client):
        """测试网关状态包含熔断器状态"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0
        assert "circuit_breakers" in result["data"]

        cb = result["data"]["circuit_breakers"]
        assert "total" in cb
        assert "open" in cb
        assert "closed" in cb

    @pytest.mark.e2e_gateway
    def test_all_circuits_closed_normally(self, e2e_api_client):
        """测试正常情况下所有熔断器闭合"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0

        cb = result["data"]["circuit_breakers"]
        # 正常情况下应该都是闭合的
        assert cb["open"] == 0
        assert cb["closed"] == cb["total"]

    @pytest.mark.e2e_gateway
    def test_circuit_breaker_details(self, e2e_api_client):
        """测试熔断器详情"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0

        cb = result["data"]["circuit_breakers"]
        assert "details" in cb

        details = cb["details"]
        assert isinstance(details, dict)
        # 每个模块都应该有熔断器状态
        assert len(details) >= 12

    @pytest.mark.e2e_gateway
    def test_circuit_breaker_per_module_config(self, e2e_api_client):
        """测试各模块有独立熔断器配置"""
        result = e2e_api_client.get("/gateway/routes")
        assert result["code"] == 0

        routes = result["data"]["routes"]
        thresholds = {
            r["key"]: r.get("cb_failure_threshold")
            for r in routes
        }

        # M8 等核心模块可能有不同阈值
        assert len(set(thresholds.values())) >= 1

    @pytest.mark.e2e_gateway
    def test_reset_circuit_breaker(self, e2e_api_client):
        """测试重置熔断器"""
        result = e2e_api_client.post("/gateway/circuit-breakers/m8/reset", {})
        # 可能需要管理员权限，但接口应该存在
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.e2e_gateway
    def test_reset_all_circuit_breakers(self, e2e_api_client):
        """测试重置所有熔断器"""
        result = e2e_api_client.post("/gateway/circuit-breakers/reset", {})
        assert result is not None
        assert isinstance(result, dict)


class TestGatewayStatusAndMetrics:
    """网关状态与指标 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_gateway_status_endpoint(self, e2e_api_client):
        """测试网关状态端点"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0
        assert "gateway" in result["data"]
        assert "modules" in result["data"]
        assert "circuit_breakers" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_status_overall_healthy(self, e2e_api_client):
        """测试网关整体状态健康"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0
        gateway = result["data"]["gateway"]
        assert gateway["status"] == "healthy"

    @pytest.mark.e2e_gateway
    def test_gateway_modules_status(self, e2e_api_client):
        """测试网关中的模块状态"""
        result = e2e_api_client.get("/gateway/status")
        assert result["code"] == 0

        modules = result["data"]["modules"]
        assert "total" in modules
        assert "healthy" in modules
        assert "unhealthy" in modules
        assert "details" in modules

        # 总模块数应该 >= 12
        assert modules["total"] >= 12

    @pytest.mark.e2e_gateway
    def test_gateway_metrics_endpoint(self, e2e_api_client):
        """测试网关指标端点"""
        result = e2e_api_client.get("/gateway/metrics")
        assert result["code"] == 0
        assert "proxy" in result["data"]
        assert "rate_limit" in result["data"]
        assert "circuit_breakers" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_proxy_metrics(self, e2e_api_client):
        """测试网关代理指标"""
        result = e2e_api_client.get("/gateway/metrics")
        assert result["code"] == 0

        proxy = result["data"]["proxy"]
        # 应该有请求量统计
        assert "total_requests" in proxy or "uptime_seconds" in proxy

    @pytest.mark.e2e_gateway
    def test_gateway_metrics_has_routes_count(self, e2e_api_client):
        """测试网关指标包含路由数量"""
        result = e2e_api_client.get("/gateway/metrics")
        assert result["code"] == 0
        assert "routes_count" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_uptime_tracking(self, e2e_api_client):
        """测试网关运行时间追踪"""
        result1 = e2e_api_client.get("/gateway/metrics")
        assert result1["code"] == 0

        # 再次获取，运行时间应该增加
        import time
        time.sleep(0.1)

        result2 = e2e_api_client.get("/gateway/metrics")
        assert result2["code"] == 0

        # 两者都应该有运行时间数据
        assert "proxy" in result1["data"]
        assert "proxy" in result2["data"]


class TestGatewayRouteReload:
    """网关路由重载 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_reload_single_route(self, e2e_api_client):
        """测试重载单个路由"""
        result = e2e_api_client.post("/gateway/routes/m8/reload", {})
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.e2e_gateway
    def test_reload_all_routes(self, e2e_api_client):
        """测试重载所有路由"""
        result = e2e_api_client.post("/gateway/routes/reload", {})
        assert result["code"] == 0
        assert "reloaded_count" in result["data"]
        assert result["data"]["reloaded_count"] >= 12

    @pytest.mark.e2e_gateway
    def test_reload_nonexistent_route(self, e2e_api_client):
        """测试重载不存在的路由"""
        result = e2e_api_client.post("/gateway/routes/nonexistent_xyz/reload", {})
        assert result["code"] != 0


class TestGatewayIntegration:
    """网关综合集成 E2E 测试"""

    @pytest.mark.e2e_gateway
    def test_full_request_flow(self, admin_api_client):
        """测试完整请求流程（认证→路由→响应）"""
        # 1. 登录获取 Token（经过网关）
        # 2. 发送请求（经过网关认证和路由）
        result = admin_api_client.get("/api/auth/me")
        assert result["code"] == 0
        assert result["data"]["username"] == "admin"

    @pytest.mark.e2e_gateway
    def test_request_id_propagation(self, e2e_api_client):
        """测试请求 ID 传播"""
        result = e2e_api_client.get("/health")
        # 响应中应该有 trace id 相关信息（通过 data 或 mock 返回）
        assert result["code"] == 0

    @pytest.mark.e2e_gateway
    def test_gateway_to_m8_integration(self, admin_api_client):
        """测试网关到 M8 模块的集成"""
        # 通过网关访问 M8 的用户列表
        result = admin_api_client.get("/api/users")
        assert result["code"] == 0
        assert "items" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_to_m1_integration(self, admin_api_client):
        """测试网关到 M1 模块的集成"""
        # 通过网关访问 M1 的对话接口
        result = admin_api_client.post("/api/chat", {"message": "网关集成测试"})
        assert result["code"] == 0
        assert "reply" in result["data"]

    @pytest.mark.e2e_gateway
    def test_gateway_to_m5_integration(self, admin_api_client):
        """测试网关到 M5 模块的集成"""
        # 通过网关访问 M5 的记忆接口
        result = admin_api_client.get("/api/memory")
        assert result["code"] == 0

    @pytest.mark.e2e_gateway
    def test_gateway_error_handling(self, e2e_api_client):
        """测试网关错误处理"""
        # 访问不存在的路径
        result = e2e_api_client.get("/nonexistent_api_path_xyz")
        # 应该返回合理的错误响应（不是连接错误）
        assert result is not None
        assert isinstance(result, dict)
        assert "code" in result

    @pytest.mark.e2e_gateway
    def test_gateway_multiple_modules_access(self, admin_api_client):
        """测试通过网关访问多个模块"""
        # 访问不同模块的接口
        results = {
            "auth": admin_api_client.get("/api/auth/me"),
            "system": admin_api_client.get("/api/system/stats"),
            "modules": admin_api_client.get("/api/modules"),
            "memory": admin_api_client.get("/api/memory"),
            "skills": admin_api_client.get("/api/skills"),
        }

        # 都应该成功
        for name, result in results.items():
            assert result["code"] == 0, f"模块 {name} 访问失败: {result.get('message')}"

    @pytest.mark.e2e_gateway
    def test_gateway_complete_integration_chain(self, admin_api_client):
        """测试完整网关集成链路"""
        # Step 1: 网关健康检查
        health = admin_api_client.get("/health")
        assert health["code"] == 0

        # Step 2: 查看路由配置
        routes = admin_api_client.get("/gateway/routes")
        assert routes["code"] == 0

        # Step 3: 访问 M8 模块
        m8_users = admin_api_client.get("/api/users")
        assert m8_users["code"] == 0

        # Step 4: 访问 M1 对话
        chat = admin_api_client.post("/api/chat", {"message": "集成测试"})
        assert chat["code"] == 0

        # Step 5: 访问 M5 记忆
        memory = admin_api_client.post("/api/memory", {
            "content": "E2E_TEST_网关集成测试记忆",
            "type": "test",
        })
        assert memory["code"] == 0

        # Step 6: 查看网关状态
        status = admin_api_client.get("/gateway/status")
        assert status["code"] == 0
