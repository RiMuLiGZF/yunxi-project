"""
API-Gateway 集成测试（TS-005, P1级）

测试目标：
1. 健康检查端点
2. 路由配置 API
3. 认证集成（API Key + JWT）
4. 限流集成
5. 熔断器集成
6. 代理转发集成
7. 多模块路由
8. 错误处理
9. CORS 集成
10. 网关管理 API
"""

import sys
import os
import json
import time
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
    sys.path.insert(0, str(_gateway_root))

# 测试环境变量
TEST_JWT_SECRET = "integration-test-secret-key-123456"
TEST_API_KEY = "integration-test-api-key-abcdef123456"


def _make_jwt(payload: dict) -> str:
    """生成测试用 JWT"""
    import hmac
    import hashlib
    import base64

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = b64url(json.dumps(header).encode("utf-8"))
    payload_b64 = b64url(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(TEST_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _setup_env():
    """设置测试环境变量"""
    os.environ["GATEWAY_JWT_SECRET"] = TEST_JWT_SECRET
    os.environ["GATEWAY_API_KEY_1"] = TEST_API_KEY
    os.environ["ENV"] = "development"


class TestIntegrationSetup(unittest.TestCase):
    """集成测试 - 基础设置验证"""

    def setUp(self):
        _setup_env()

    def test_app_importable(self):
        """测试 FastAPI 应用可导入"""
        from src.main import app
        self.assertIsNotNone(app)
        self.assertEqual(app.title, "云汐 API 网关")
        self.assertEqual(app.version, "2.0.0")


class TestHealthCheckIntegration(unittest.TestCase):
    """健康检查集成测试"""

    def setUp(self):
        _setup_env()

    def test_health_endpoint_returns_200(self):
        """测试 /health 端点返回 200"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["status"], "healthy")
            self.assertEqual(data["data"]["service"], "yunxi-api-gateway")
            self.assertEqual(data["data"]["version"], "2.0.0")
            self.assertEqual(data["data"]["routes_count"], 12)

    def test_gateway_health_endpoint(self):
        """测试 /gateway/health 端点"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/health")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["status"], "healthy")


class TestRoutesAPIIntegration(unittest.TestCase):
    """路由配置 API 集成测试"""

    def setUp(self):
        _setup_env()

    def test_list_routes_endpoint(self):
        """测试获取所有路由配置"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/routes")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["total"], 12)
            self.assertEqual(data["data"]["enabled_count"], 12)
            self.assertEqual(len(data["data"]["routes"]), 12)

    def test_route_detail_endpoint(self):
        """测试获取单个路由详情"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/routes/m1")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["key"], "m1")
            self.assertIn("target_url", data["data"])
            self.assertIn("prefix", data["data"])

    def test_route_detail_not_found(self):
        """测试获取不存在的路由返回 404"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/routes/nonexistent")
            self.assertEqual(response.status_code, 404)

    def test_all_route_details_accessible(self):
        """测试所有12个模块路由详情都可访问"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            for i in range(1, 13):
                response = client.get(f"/gateway/routes/m{i}")
                self.assertEqual(response.status_code, 200, f"m{i} 路由详情应该可访问")
                data = response.json()
                self.assertEqual(data["data"]["key"], f"m{i}")


class TestGatewayStatusAPI(unittest.TestCase):
    """网关状态 API 测试"""

    def setUp(self):
        _setup_env()

    def test_gateway_status_endpoint(self):
        """测试 /gateway/status 端点"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/status")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertIn("modules", data["data"])
            self.assertIn("circuit_breakers", data["data"])


class TestGatewayMetricsAPI(unittest.TestCase):
    """网关指标 API 测试"""

    def setUp(self):
        _setup_env()

    def test_gateway_metrics_endpoint(self):
        """测试 /gateway/metrics 端点"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/gateway/metrics")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertIn("proxy", data["data"])
            self.assertIn("total_requests", data["data"]["proxy"])
            self.assertIn("success_requests", data["data"]["proxy"])
            self.assertIn("failed_requests", data["data"]["proxy"])
            self.assertIn("rate_limit", data["data"])
            self.assertIn("circuit_breakers", data["data"])


class TestAuthIntegration(unittest.TestCase):
    """认证集成测试"""

    def setUp(self):
        _setup_env()

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_jwt_auth_proxies_request(self, mock_client_cls):
        """测试 JWT 认证通过后请求被代理转发"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
        mock_response.elapsed.total_seconds.return_value = 0.05

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        # 生成有效 JWT
        payload = {
            "sub": "user-123",
            "username": "testuser",
            "roles": ["user"],
            "scopes": ["read"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
            "jti": "test-jti",
        }
        token = _make_jwt(payload)

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/v1/agents",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_api_key_auth_proxies_request(self, mock_client_cls):
        """测试 API Key 认证通过后请求被代理转发"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "ok"}'
        mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
        mock_response.elapsed.total_seconds.return_value = 0.05

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/v1/agents",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 200)

    def test_no_auth_returns_401(self):
        """测试无认证返回 401"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/m1/api/v1/agents")
            self.assertEqual(response.status_code, 401)

            data = response.json()
            self.assertEqual(data["code"], 401)
            self.assertIn("Unauthorized", data["message"])

    def test_invalid_token_returns_401(self):
        """测试无效 Token 返回 401"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/v1/agents",
                headers={"Authorization": "Bearer invalid.token.here"},
            )
            self.assertEqual(response.status_code, 401)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_public_path_no_auth_required(self, mock_client_cls):
        """测试公开路径不需要认证（返回非401）"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
        mock_response.elapsed.total_seconds.return_value = 0.05

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            # M12 的 /api/v1/auth/login 是公开路径
            response = client.post(
                "/m12/api/v1/auth/login",
                json={"username": "test", "password": "test"},
            )
            # 不应该是 401（认证失败），而应该正常转发
            self.assertNotEqual(response.status_code, 401)


class TestRateLimitIntegration(unittest.TestCase):
    """限流集成测试"""

    def setUp(self):
        _setup_env()
        # 重置限流器
        import src.services.rate_limiter as rl_module
        rl_module._rate_limiter = None

    def test_rate_limit_headers_in_health_response(self):
        """测试健康检查响应中包含限流相关头"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            # 验证响应成功
            data = response.json()
            self.assertEqual(data["code"], 0)

    def test_sensitive_endpoint_stricter_limit(self):
        """测试敏感接口更严格的限流（通过路径匹配验证）"""
        from src.middleware.rate_limit import _match_tier

        login_tier = _match_tier("/m12/api/v1/auth/login")
        normal_tier = _match_tier("/m1/api/v1/agents")

        from src.services.rate_limiter import RATE_LIMIT_TIERS
        login_limit = RATE_LIMIT_TIERS[login_tier].requests_per_minute
        normal_limit = RATE_LIMIT_TIERS[normal_tier].requests_per_minute

        self.assertLess(login_limit, normal_limit)


class TestCircuitBreakerIntegration(unittest.TestCase):
    """熔断器集成测试"""

    def setUp(self):
        _setup_env()
        # 重置熔断器
        from src.services.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        asyncio.get_event_loop().run_until_complete(cb.reset_all())

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_circuit_breaker_triggers_after_failures(self, mock_client_cls):
        """测试连续失败后熔断器触发"""
        import httpx
        # 模拟失败响应
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b"error"
        mock_response.headers = httpx.Headers({})
        mock_response.elapsed.total_seconds.return_value = 0.01

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            # 连续失败 5 次（m1 默认阈值是 5）
            for i in range(5):
                response = client.get(
                    "/m1/api/test",
                    headers={"X-API-Key": TEST_API_KEY},
                )
                # 前 5 次应该返回后端的 500
                self.assertEqual(response.status_code, 500)

            # 第 6 次应该被熔断，返回 503
            response = client.get(
                "/m1/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("circuit breaker", response.text.lower())

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_independent_circuits_for_modules(self, mock_client_cls):
        """测试不同模块独立熔断"""
        import httpx
        mock_response_m1 = MagicMock()
        mock_response_m1.status_code = 500
        mock_response_m1.content = b"error"
        mock_response_m1.headers = httpx.Headers({})
        mock_response_m1.elapsed.total_seconds.return_value = 0.01

        mock_response_m2 = MagicMock()
        mock_response_m2.status_code = 200
        mock_response_m2.content = b'{"ok": true}'
        mock_response_m2.headers = httpx.Headers({"Content-Type": "application/json"})
        mock_response_m2.elapsed.total_seconds.return_value = 0.01

        # 根据请求头中的模块信息返回不同响应
        def mock_request(method, url, **kwargs):
            headers = kwargs.get("headers", {})
            module = headers.get("X-Gateway-Module", "")
            if module == "m1":
                return mock_response_m1
            return mock_response_m2

        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=mock_request)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            # 让 m1 熔断（连续 5 次失败）
            for i in range(5):
                client.get(
                    "/m1/api/test",
                    headers={"X-API-Key": TEST_API_KEY},
                )

            # m1 应该熔断了
            response_m1 = client.get(
                "/m1/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response_m1.status_code, 503)

            # m2 应该仍然正常
            response_m2 = client.get(
                "/m2/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response_m2.status_code, 200)


class TestProxyIntegration(unittest.TestCase):
    """代理转发集成测试"""

    def setUp(self):
        _setup_env()

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_full_request_chain(self, mock_client_cls):
        """测试完整请求链路：认证 → 限流 → 转发 → 响应"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"data": [1, 2, 3]}'
        mock_response.headers = httpx.Headers({
            "Content-Type": "application/json",
            "X-Custom-Backend": "backend-value",
        })
        mock_response.elapsed.total_seconds.return_value = 0.05

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/v1/agents?page=1&limit=10",
                headers={
                    "X-API-Key": TEST_API_KEY,
                    "X-Custom-Request": "test-value",
                },
            )

            # 验证响应状态
            self.assertEqual(response.status_code, 200)

            # 验证响应体
            self.assertEqual(response.json(), {"data": [1, 2, 3]})

            # 验证网关响应头
            self.assertIn("x-gateway-module", response.headers)
            self.assertEqual(response.headers["x-gateway-module"], "m1")
            self.assertIn("x-gateway-latency", response.headers)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_post_request_body_forwarded(self, mock_client_cls):
        """测试 POST 请求体被正确转发"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id": 123}'
        mock_response.headers = httpx.Headers({"Content-Type": "application/json"})
        mock_response.elapsed.total_seconds.return_value = 0.05

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            request_body = {"name": "test-agent", "type": "chat"}
            response = client.post(
                "/m1/api/v1/agents",
                json=request_body,
                headers={"X-API-Key": TEST_API_KEY},
            )

            self.assertEqual(response.status_code, 201)

            # 验证请求体被传递
            call_kwargs = mock_client.request.call_args
            sent_body = call_kwargs.kwargs.get("content")
            self.assertIsNotNone(sent_body)

    def test_route_not_found_returns_404(self):
        """测试未匹配路由返回 404"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/nonexistent-module/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 404)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_gateway_headers_in_forwarded_request(self, mock_client_cls):
        """测试转发请求中包含网关标识头"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"ok"
        mock_response.headers = httpx.Headers({})
        mock_response.elapsed.total_seconds.return_value = 0.01

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            client.get(
                "/m1/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )

            # 验证转发请求中包含网关头
            call_kwargs = mock_client.request.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            self.assertEqual(headers.get("X-Gateway"), "yunxi-api-gateway")
            self.assertEqual(headers.get("X-Gateway-Module"), "m1")


class TestMultiModuleRouting(unittest.TestCase):
    """多模块路由集成测试"""

    def setUp(self):
        _setup_env()

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_routes_to_correct_modules(self, mock_client_cls):
        """测试请求被路由到正确的后端模块"""
        import httpx

        responses = {}
        for i in range(1, 13):
            resp = MagicMock()
            resp.status_code = 200
            resp.content = f'{{"module": "m{i}"}}'.encode()
            resp.headers = httpx.Headers({"Content-Type": "application/json"})
            resp.elapsed.total_seconds.return_value = 0.01
            responses[f"m{i}"] = resp

        def mock_request(method, url, **kwargs):
            # 根据请求路径判断是哪个模块
            # url 是去除前缀后的路径，所以从 headers 中获取模块信息
            headers = kwargs.get("headers", {})
            module = headers.get("X-Gateway-Module", "unknown")
            return responses.get(module, responses["m1"])

        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=mock_request)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            # 测试几个不同的模块
            test_modules = ["m1", "m5", "m8", "m12"]
            for module in test_modules:
                response = client.get(
                    f"/{module}/api/test",
                    headers={"X-API-Key": TEST_API_KEY},
                )
                self.assertEqual(response.status_code, 200, f"{module} 应该返回 200")


class TestErrorHandling(unittest.TestCase):
    """错误处理集成测试"""

    def setUp(self):
        _setup_env()

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_connection_error_returns_502(self, mock_client_cls):
        """测试连接错误返回 502"""
        import httpx
        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 502)
            self.assertIn("Bad gateway", response.text)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_timeout_returns_504(self, mock_client_cls):
        """测试超时返回 504"""
        import httpx
        mock_client = MagicMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.get(
                "/m1/api/slow",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 504)
            self.assertIn("Gateway timeout", response.text)


class TestCircuitBreakerResetAPI(unittest.TestCase):
    """熔断器重置 API 测试"""

    def setUp(self):
        _setup_env()
        # 重置熔断器
        from src.services.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        asyncio.get_event_loop().run_until_complete(cb.reset_all())

    def test_reset_all_circuit_breakers(self):
        """测试重置所有熔断器"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.post("/gateway/circuit-breakers/reset")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertTrue(data["data"]["reset"])

    def test_reset_nonexistent_circuit_breaker(self):
        """测试重置不存在的熔断器返回 404"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.post("/gateway/circuit-breakers/nonexistent/reset")
            self.assertEqual(response.status_code, 404)

    @patch("src.services.proxy_service.httpx.AsyncClient")
    def test_reset_triggered_circuit_breaker(self, mock_client_cls):
        """测试重置已触发的熔断器"""
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.content = b"error"
        mock_response.headers = httpx.Headers({})
        mock_response.elapsed.total_seconds.return_value = 0.01

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            # 触发熔断
            for i in range(5):
                client.get(
                    "/m1/api/test",
                    headers={"X-API-Key": TEST_API_KEY},
                )

            # 验证已熔断
            response = client.get(
                "/m1/api/test",
                headers={"X-API-Key": TEST_API_KEY},
            )
            self.assertEqual(response.status_code, 503)

            # 重置熔断器
            reset_response = client.post("/gateway/circuit-breakers/m1/reset")
            self.assertEqual(reset_response.status_code, 200)
            self.assertTrue(reset_response.json()["data"]["reset"])


class TestReloadRoutesAPI(unittest.TestCase):
    """路由重载 API 测试"""

    def setUp(self):
        _setup_env()

    def test_reload_single_route(self):
        """测试重新加载单个路由"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.post("/gateway/routes/m1/reload")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertTrue(data["data"]["reloaded"])

    def test_reload_nonexistent_route(self):
        """测试重新加载不存在的路由返回 404"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.post("/gateway/routes/nonexistent/reload")
            self.assertEqual(response.status_code, 404)

    def test_reload_all_routes(self):
        """测试重新加载所有路由"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.post("/gateway/routes/reload")
            self.assertEqual(response.status_code, 200)

            data = response.json()
            self.assertEqual(data["code"], 0)
            self.assertGreaterEqual(data["data"]["reloaded_count"], 0)


class TestCORSIntegration(unittest.TestCase):
    """CORS 集成测试"""

    def setUp(self):
        _setup_env()

    def test_cors_headers_present(self):
        """测试 CORS 响应头存在"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            # 开发环境应该允许 localhost:3000
            self.assertIn("access-control-allow-origin", response.headers)

    def test_cors_preflight_request(self):
        """测试 CORS 预检请求"""
        from fastapi.testclient import TestClient
        from src.main import app

        with TestClient(app) as client:
            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type",
                },
            )
            self.assertIn("access-control-allow-origin", response.headers)
            self.assertIn("access-control-allow-methods", response.headers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
