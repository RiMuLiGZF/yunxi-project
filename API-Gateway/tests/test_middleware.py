"""
API-Gateway 中间件测试（TS-005, P1级）

测试目标：
1. 限流中间件 - 路径匹配限速级别
2. 限流中间件 - 请求处理流程
3. 限流中间件 - 客户端IP获取
4. 认证中间件 - （已在 test_auth.py 中详细测试）
5. CORS 中间件配置
6. 请求ID生成和传递（通过代理服务测试）
"""

import sys
import os
import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
class TestRateLimitMiddlewareTierMatching(unittest.TestCase):
    """限流中间件 - 路径匹配限速级别测试"""

    def test_login_path_is_sensitive(self):
        """测试登录路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/auth/login")
        self.assertEqual(tier, "sensitive")

    def test_register_path_is_sensitive(self):
        """测试注册路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/auth/register")
        self.assertEqual(tier, "sensitive")

    def test_password_reset_path_is_sensitive(self):
        """测试密码重置路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/auth/password/forgot")
        self.assertEqual(tier, "sensitive")

    def test_captcha_path_is_sensitive(self):
        """测试验证码路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/captcha")
        self.assertEqual(tier, "sensitive")

    def test_sms_path_is_sensitive(self):
        """测试短信路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/sms/send")
        self.assertEqual(tier, "sensitive")

    def test_verify_path_is_sensitive(self):
        """测试验证路径匹配 sensitive 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m12/api/v1/verify/email")
        self.assertEqual(tier, "sensitive")

    def test_admin_path_is_admin_tier(self):
        """测试管理员路径匹配 admin 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m8/api/v1/admin/users")
        self.assertEqual(tier, "admin")

    def test_api_keys_path_is_strict(self):
        """测试 API Key 管理路径匹配 strict 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m8/api/v1/api-keys")
        self.assertEqual(tier, "strict")

    def test_security_settings_path_is_strict(self):
        """测试安全设置路径匹配 strict 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m8/api/v1/settings/security")
        self.assertEqual(tier, "strict")

    def test_mcp_path_is_mcp_tier(self):
        """测试 MCP 路径匹配 mcp 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m11/api/v1/mcp/call")
        self.assertEqual(tier, "mcp")

    def test_tools_path_is_mcp_tier(self):
        """测试工具路径匹配 mcp 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m11/api/v1/tools/list")
        self.assertEqual(tier, "mcp")

    def test_generic_path_is_public(self):
        """测试普通路径匹配 public 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m1/api/v1/agents/list")
        self.assertEqual(tier, "public")

    def test_health_path_is_public(self):
        """测试健康检查路径匹配 public 级别"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/m1/health")
        self.assertEqual(tier, "public")

    def test_case_insensitive_matching(self):
        """测试路径匹配不区分大小写"""
        from src.middleware.rate_limit import _match_tier
        tier = _match_tier("/M12/API/V1/AUTH/LOGIN")
        self.assertEqual(tier, "sensitive")


class TestRateLimitMiddlewareIPExtraction(unittest.TestCase):
    """限流中间件 - 客户端IP获取测试"""

    def setUp(self):
        from src.middleware.rate_limit import RateLimitMiddleware
        self.middleware = RateLimitMiddleware(MagicMock())

    def test_x_forwarded_for_header(self):
        """测试从 X-Forwarded-For 获取 IP"""
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"x-forwarded-for", b"192.168.1.100, 10.0.0.1"),
            ],
        }
        request = Request(scope)
        ip = self.middleware._get_client_ip(request)
        self.assertEqual(ip, "192.168.1.100")

    def test_x_real_ip_header(self):
        """测试从 X-Real-IP 获取 IP"""
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"x-real-ip", b"10.0.0.50"),
            ],
        }
        request = Request(scope)
        ip = self.middleware._get_client_ip(request)
        self.assertEqual(ip, "10.0.0.50")

    def test_x_forwarded_for_takes_priority(self):
        """测试 X-Forwarded-For 优先级高于 X-Real-IP"""
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [
                (b"x-forwarded-for", b"192.168.1.100"),
                (b"x-real-ip", b"10.0.0.50"),
            ],
        }
        request = Request(scope)
        ip = self.middleware._get_client_ip(request)
        self.assertEqual(ip, "192.168.1.100")

    def test_no_headers_uses_client_ip(self):
        """测试没有IP头时使用连接IP"""
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "client": ("127.0.0.1", 50000),
        }
        request = Request(scope)
        ip = self.middleware._get_client_ip(request)
        self.assertEqual(ip, "127.0.0.1")

    def test_no_client_and_no_headers(self):
        """测试没有客户端信息和IP头时返回 unknown"""
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
        }
        request = Request(scope)
        ip = self.middleware._get_client_ip(request)
        self.assertEqual(ip, "unknown")


class TestRateLimitMiddlewareDispatch(unittest.TestCase):
    """限流中间件 dispatch 测试"""

    def setUp(self):
        # 重置限流器
        from src.services.rate_limiter import _rate_limiter, _rate_limiter_lock
        global _rate_limiter, _rate_limiter_lock
        import src.services.rate_limiter as rl_module
        rl_module._rate_limiter = None

    def test_normal_request_passes(self):
        """测试正常请求通过限流中间件"""
        from src.middleware.rate_limit import RateLimitMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/test",
            "headers": [
                (b"x-forwarded-for", b"192.168.200.1"),
            ],
        }

        async def call_next(request):
            return Response(status_code=200, content=b"ok")

        middleware = RateLimitMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)

        asyncio.get_event_loop().run_until_complete(test())

    def test_rate_limit_headers_added(self):
        """测试限流响应头被添加"""
        from src.middleware.rate_limit import RateLimitMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/test",
            "headers": [
                (b"x-forwarded-for", b"192.168.200.2"),
            ],
        }

        async def call_next(request):
            return Response(status_code=200, content=b"ok")

        middleware = RateLimitMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            # 检查响应头
            headers_lower = {k.lower(): v for k, v in response.headers.items()}
            self.assertIn("x-ratelimit-limit", headers_lower)
            self.assertIn("x-ratelimit-remaining", headers_lower)
            self.assertIn("x-ratelimit-tier", headers_lower)

        asyncio.get_event_loop().run_until_complete(test())

    def test_rate_exceeded_returns_429(self):
        """测试超限返回 429"""
        from src.middleware.rate_limit import RateLimitMiddleware
        from src.services.rate_limiter import RateLimiter
        from starlette.requests import Request
        from starlette.responses import Response

        # 使用严格的限制便于测试
        with patch("src.middleware.rate_limit.get_rate_limiter") as mock_get:
            mock_rl = RateLimiter(total_limit=1000, per_ip_limit=2)
            mock_get.return_value = mock_rl

            scope = {
                "type": "http",
                "method": "GET",
                "path": "/m1/api/v1/test",
                "headers": [
                    (b"x-forwarded-for", b"192.168.200.99"),
                ],
            }

            async def call_next(request):
                return Response(status_code=200, content=b"ok")

            middleware = RateLimitMiddleware(call_next)

            async def test():
                # 前2次通过
                for i in range(2):
                    request = Request(scope)
                    response = await middleware.dispatch(request, call_next)
                    self.assertEqual(response.status_code, 200, f"第 {i+1} 次应该通过")

                # 第3次被限流
                request = Request(scope)
                response = await middleware.dispatch(request, call_next)
                self.assertEqual(response.status_code, 429)

                # 检查响应体
                import json
                body = json.loads(response.body)
                self.assertEqual(body["code"], 429)
                self.assertIn("message", body)
                self.assertEqual(body["data"]["reason"], "ip_rate_limit_exceeded")

                # 检查响应头
                self.assertIn("Retry-After", response.headers)

            asyncio.get_event_loop().run_until_complete(test())

    def test_sensitive_tier_rate_limit(self):
        """测试敏感接口更严格的限流"""
        from src.middleware.rate_limit import RateLimitMiddleware
        from src.services.rate_limiter import RateLimiter
        from starlette.requests import Request
        from starlette.responses import Response

        with patch("src.middleware.rate_limit.get_rate_limiter") as mock_get:
            # 使用大的IP限制，确保触发的是分级限流
            mock_rl = RateLimiter(total_limit=1000, per_ip_limit=1000)
            mock_get.return_value = mock_rl

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/m12/api/v1/auth/login",
                "headers": [
                    (b"x-forwarded-for", b"192.168.200.100"),
                ],
            }

            async def call_next(request):
                return Response(status_code=200, content=b"ok")

            middleware = RateLimitMiddleware(call_next)

            async def test():
                # sensitive 级别是 10次/分钟
                for i in range(10):
                    request = Request(scope)
                    response = await middleware.dispatch(request, call_next)
                    self.assertEqual(response.status_code, 200, f"第 {i+1} 次应该通过")

                # 第11次被限流
                request = Request(scope)
                response = await middleware.dispatch(request, call_next)
                self.assertEqual(response.status_code, 429)

                import json
                body = json.loads(response.body)
                self.assertEqual(body["data"]["reason"], "tier_rate_limit_exceeded")
                self.assertEqual(body["data"]["tier"], "sensitive")

            asyncio.get_event_loop().run_until_complete(test())


class TestCORSMiddlewareConfig(unittest.TestCase):
    """CORS 中间件配置测试"""

    def test_cors_origins_resolution_dev(self):
        """测试开发环境 CORS 配置解析"""
        # 测试开发环境通配符自动替换为 localhost 列表
        os.environ["ENV"] = "development"

        # 重新导入以应用环境变量
        if "src.config" in sys.modules:
            # 重置单例以便测试
            import src.config as cfg
            if cfg._gateway_config is not None:
                cfg._gateway_config.cors_origins = "*"

        from src.main import _resolve_cors_origins
        origins = _resolve_cors_origins()
        self.assertIsInstance(origins, list)
        self.assertGreater(len(origins), 0)
        # 应该包含 localhost 常见端口
        self.assertTrue(any("localhost:3000" in o for o in origins))
        self.assertTrue(any("localhost:5173" in o for o in origins))
        self.assertTrue(any("localhost:8080" in o for o in origins))
        # 不应该包含通配符
        self.assertNotIn("*", origins)

    def test_cors_origins_resolution_custom(self):
        """测试自定义 CORS 来源配置"""
        # 保存原值
        from src.config import get_gateway_config
        cfg = get_gateway_config()
        original = cfg.cors_origins

        try:
            cfg.cors_origins = "https://example.com,https://app.example.com"
            from src.main import _resolve_cors_origins
            origins = _resolve_cors_origins()
            self.assertEqual(len(origins), 2)
            self.assertIn("https://example.com", origins)
            self.assertIn("https://app.example.com", origins)
        finally:
            cfg.cors_origins = original


class TestSecurityHeaders(unittest.TestCase):
    """安全响应头中间件测试"""

    def test_security_headers_module_available(self):
        """测试安全响应头中间件模块可导入"""
        try:
            from shared.core.middleware.security_headers import SecurityHeadersMiddleware
            self.assertIsNotNone(SecurityHeadersMiddleware)
        except ImportError:
            self.skipTest("SecurityHeadersMiddleware not available")


class TestMainAppMiddleware(unittest.TestCase):
    """主应用中间件注册测试"""

    def test_app_has_cors_middleware(self):
        """测试应用有 CORS 中间件"""
        # 检查 main.py 中是否注册了 CORSMiddleware
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CORSMiddleware", content)
        self.assertIn("add_middleware", content)

    def test_app_has_rate_limit_middleware(self):
        """测试应用有限流中间件"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("RateLimitMiddleware", content)

    def test_app_has_auth_middleware(self):
        """测试应用有认证中间件"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("AuthMiddleware", content)

    def test_middleware_order(self):
        """测试中间件注册顺序"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 查找各中间件 add_middleware 调用所在的行号
        def find_middleware_line(name: str) -> int:
            for i, line in enumerate(lines):
                # 匹配 add_middleware(...name 或 add_middleware(name
                if "add_middleware" in line and name in line:
                    return i
                # 多行情况：上一行有 add_middleware(，当前行有 name
                if i > 0 and "add_middleware" in lines[i - 1] and name in line:
                    return i
            return -1

        cors_line = find_middleware_line("CORSMiddleware")
        rate_limit_line = find_middleware_line("RateLimitMiddleware")
        auth_line = find_middleware_line("AuthMiddleware")

        self.assertGreater(cors_line, 0, "CORSMiddleware 应该被注册")
        self.assertGreater(rate_limit_line, 0, "RateLimitMiddleware 应该被注册")
        self.assertGreater(auth_line, 0, "AuthMiddleware 应该被注册")

        # CORS 在限流之前注册（内层）
        self.assertLess(cors_line, rate_limit_line, "CORS 应该在限流之前注册")
        # 限流在认证之前注册（内层）
        self.assertLess(rate_limit_line, auth_line, "限流应该在认证之前注册")


class TestHealthEndpoint(unittest.TestCase):
    """健康检查端点测试"""

    def test_health_endpoint_exists(self):
        """测试健康检查端点存在"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/health", content)
        self.assertIn("health_check", content)

    def test_gateway_health_endpoint(self):
        """测试网关健康检查端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/health", content)

    def test_gateway_routes_endpoint(self):
        """测试网关路由列表端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/routes", content)

    def test_gateway_status_endpoint(self):
        """测试网关状态端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/status", content)

    def test_gateway_metrics_endpoint(self):
        """测试网关指标端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/metrics", content)


class TestGatewayManagementAPI(unittest.TestCase):
    """网关管理 API 测试"""

    def test_reload_route_endpoint(self):
        """测试路由重载端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/routes/{route_key}/reload", content)

    def test_reload_all_routes_endpoint(self):
        """测试全部路由重载端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/routes/reload", content)

    def test_reset_circuit_breaker_endpoint(self):
        """测试熔断器重置端点"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/gateway/circuit-breakers/{route_key}/reset", content)
        self.assertIn("/gateway/circuit-breakers/reset", content)


class TestClientIPExtraction(unittest.TestCase):
    """客户端 IP 提取测试（main.py 中的函数）"""

    def test_get_client_ip_function_exists(self):
        """测试 _get_client_ip 函数存在"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_get_client_ip", content)
        self.assertIn("X-Forwarded-For", content)
        self.assertIn("X-Real-IP", content)


class TestSSERequestDetection(unittest.TestCase):
    """SSE 请求检测测试（main.py 中的函数）"""

    def test_is_sse_request_function_exists(self):
        """测试 _is_sse_request 函数存在"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_is_sse_request", content)
        self.assertIn("text/event-stream", content)

    def test_sse_patterns(self):
        """测试 SSE 路径模式"""
        with open(os.path.join(_gateway_root, "src", "main.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("/sse", content)
        self.assertIn("/stream", content)
        self.assertIn("/events", content)
        self.assertIn("/watch", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
