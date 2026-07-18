"""
API-Gateway 认证鉴权测试（TS-005, P1级）

测试目标：
1. JWT Token 认证（有效/无效/过期/格式错误）
2. API Key 认证
3. 白名单路径跳过认证
4. 全局白名单路径
5. 模块级公开路径
6. 用户信息注入
7. 认证失败响应格式
8. Token 格式验证
"""

import sys
import os
import time
import json
import base64
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
# 将 API-Gateway 目录加入 path
_gateway_root = Path(__file__).resolve().parent.parent
if str(_gateway_root) not in sys.path:
# 测试用 JWT 密钥
TEST_JWT_SECRET = "test-secret-key-for-unit-testing-only"
TEST_JWT_ALGORITHM = "HS256"
TEST_JWT_ISSUER = "yunxi-test"


def _make_jwt_token(payload: dict, secret: str = TEST_JWT_SECRET, algorithm: str = TEST_JWT_ALGORITHM) -> str:
    """手动生成 JWT Token（用于测试）"""
    import hmac
    import hashlib

    def b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = {"alg": algorithm, "typ": "JWT"}
    header_b64 = b64url_encode(json.dumps(header).encode("utf-8"))
    payload_b64 = b64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    if algorithm == "HS256":
        signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    else:
        signature = b""

    sig_b64 = b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


class TestJWTHelper(unittest.TestCase):
    """JWT 验证辅助方法测试"""

    def setUp(self):
        os.environ["GATEWAY_JWT_SECRET"] = TEST_JWT_SECRET
        os.environ["GATEWAY_JWT_ALGORITHM"] = TEST_JWT_ALGORITHM
        os.environ["GATEWAY_JWT_ISSUER"] = TEST_JWT_ISSUER
        os.environ["ENV"] = "development"
        # 强制重新导入以使用测试环境变量
        if "src.middleware.auth" in sys.modules:
            del sys.modules["src.middleware.auth"]

    def test_valid_jwt_token(self):
        """测试有效 JWT Token 验证通过"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "user-123",
            "username": "testuser",
            "roles": ["user"],
            "scopes": ["read"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
            "jti": "test-jti-001",
        }
        token = _make_jwt_token(payload)
        result = middleware._validate_jwt(token)

        self.assertIsNotNone(result)
        self.assertEqual(result["user_id"], "user-123")
        self.assertEqual(result["username"], "testuser")
        self.assertEqual(result["auth_type"], "jwt")
        self.assertEqual(result["jti"], "test-jti-001")

    def test_invalid_signature_rejected(self):
        """测试签名无效的 Token 被拒绝"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "user-123",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
        }
        # 使用错误的密钥签名
        token = _make_jwt_token(payload, secret="wrong-secret")
        result = middleware._validate_jwt(token)
        self.assertIsNone(result)

    def test_expired_token_rejected(self):
        """测试过期 Token 被拒绝"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "user-123",
            "exp": int(time.time()) - 3600,  # 已过期1小时
            "iat": int(time.time()) - 7200,
            "type": "access",
        }
        token = _make_jwt_token(payload)
        result = middleware._validate_jwt(token)
        self.assertIsNone(result)

    def test_malformed_token_rejected(self):
        """测试格式错误的 Token 被拒绝"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        # 只有两段
        result = middleware._validate_jwt("header.payload")
        self.assertIsNone(result)

        # 空字符串
        result = middleware._validate_jwt("")
        self.assertIsNone(result)

        # 乱码
        result = middleware._validate_jwt("not.a.validtoken!!!")
        self.assertIsNone(result)

    def test_empty_token_rejected(self):
        """测试空 Token 被拒绝"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        result = middleware._validate_jwt("")
        self.assertIsNone(result)

    def test_wrong_token_type_rejected(self):
        """测试错误类型的 Token 被拒绝"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "user-123",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "refresh",  # refresh token 不能用于访问
        }
        token = _make_jwt_token(payload)
        result = middleware._validate_jwt(token)
        self.assertIsNone(result)

    def test_api_token_type_accepted(self):
        """测试 api 类型 Token 被接受"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "api-client",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "api",
        }
        token = _make_jwt_token(payload)
        result = middleware._validate_jwt(token)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "api")

    def test_roles_and_scopes_extracted(self):
        """测试角色和权限正确提取"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "admin-001",
            "username": "admin",
            "roles": ["admin", "moderator"],
            "scopes": ["read", "write", "delete"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
        }
        token = _make_jwt_token(payload)
        result = middleware._validate_jwt(token)

        self.assertIsNotNone(result)
        self.assertEqual(result["roles"], ["admin", "moderator"])
        self.assertEqual(result["scopes"], ["read", "write", "delete"])

    def tearDown(self):
        # 清理环境变量
        for key in ["GATEWAY_JWT_SECRET", "GATEWAY_JWT_ALGORITHM", "GATEWAY_JWT_ISSUER"]:
            if key in os.environ:
                del os.environ[key]


class TestAPIKeyAuth(unittest.TestCase):
    """API Key 认证测试"""

    def setUp(self):
        os.environ["ENV"] = "development"
        # 清理可能存在的 API Key 环境变量
        for i in range(1, 20):
            key = f"GATEWAY_API_KEY_{i}"
            if key in os.environ:
                del os.environ[key]
        if "GATEWAY_ENABLE_DEV_KEY" in os.environ:
            del os.environ["GATEWAY_ENABLE_DEV_KEY"]
        if "GATEWAY_DEV_API_KEY" in os.environ:
            del os.environ["GATEWAY_DEV_API_KEY"]

    def test_no_api_keys_configured_rejects(self):
        """测试未配置 API Key 时认证失败"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("any-key")
        self.assertFalse(result)

    def test_valid_api_key_accepted(self):
        """测试有效 API Key 认证通过"""
        os.environ["GATEWAY_API_KEY_1"] = "abcdefghijklmnop1234567890"  # >=16 字符
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("abcdefghijklmnop1234567890")
        self.assertTrue(result)

    def test_invalid_api_key_rejected(self):
        """测试无效 API Key 被拒绝"""
        os.environ["GATEWAY_API_KEY_1"] = "abcdefghijklmnop1234567890"
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("wrong-key-value")
        self.assertFalse(result)

    def test_short_api_key_ignored(self):
        """测试短于16字符的 API Key 被忽略（安全长度校验）"""
        os.environ["GATEWAY_API_KEY_1"] = "short"  # 不足16字符
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("short")
        self.assertFalse(result)

    def test_multiple_api_keys(self):
        """测试多个 API Key 配置"""
        os.environ["GATEWAY_API_KEY_1"] = "first-valid-api-key-12345"
        os.environ["GATEWAY_API_KEY_2"] = "second-valid-api-key-67890"
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        self.assertTrue(middleware._validate_api_key("first-valid-api-key-12345"))
        self.assertTrue(middleware._validate_api_key("second-valid-api-key-67890"))
        self.assertFalse(middleware._validate_api_key("invalid-key"))

    def test_dev_api_key_disabled_by_default(self):
        """测试开发环境默认不启用开发 API Key"""
        os.environ["GATEWAY_DEV_API_KEY"] = "dev-key-1234567890abcdef"
        # 不设置 GATEWAY_ENABLE_DEV_KEY
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("dev-key-1234567890abcdef")
        self.assertFalse(result)

    def test_dev_api_key_enabled(self):
        """测试启用开发 API Key"""
        os.environ["GATEWAY_ENABLE_DEV_KEY"] = "true"
        os.environ["GATEWAY_DEV_API_KEY"] = "dev-key-1234567890abcdef"
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        result = middleware._validate_api_key("dev-key-1234567890abcdef")
        self.assertTrue(result)

    def tearDown(self):
        # 清理环境变量
        for i in range(1, 20):
            key = f"GATEWAY_API_KEY_{i}"
            if key in os.environ:
                del os.environ[key]
        for key in ["GATEWAY_ENABLE_DEV_KEY", "GATEWAY_DEV_API_KEY", "ENV"]:
            if key in os.environ:
                del os.environ[key]


class TestWhiteListPaths(unittest.TestCase):
    """白名单路径测试"""

    def setUp(self):
        os.environ["ENV"] = "development"
        if "src.middleware.auth" in sys.modules:
            del sys.modules["src.middleware.auth"]

    def test_global_whitelist_health(self):
        """测试 /health 是全局白名单路径"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        self.assertTrue(middleware._is_global_white_list("/health"))

    def test_global_whitelist_gateway(self):
        """测试 /gateway 前缀路径是全局白名单"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        self.assertTrue(middleware._is_global_white_list("/gateway/routes"))
        self.assertTrue(middleware._is_global_white_list("/gateway/health"))
        self.assertTrue(middleware._is_global_white_list("/gateway/status"))

    def test_global_whitelist_docs(self):
        """测试 /docs 和 /openapi.json 是全局白名单"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        self.assertTrue(middleware._is_global_white_list("/docs"))
        self.assertTrue(middleware._is_global_white_list("/openapi.json"))
        self.assertTrue(middleware._is_global_white_list("/redoc"))

    def test_global_whitelist_favicon(self):
        """测试 /favicon.ico 是全局白名单"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        self.assertTrue(middleware._is_global_white_list("/favicon.ico"))

    def test_non_whitelist_path_rejected(self):
        """测试非白名单路径返回 False"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())
        self.assertFalse(middleware._is_global_white_list("/api/v1/users"))
        self.assertFalse(middleware._is_global_white_list("/m1/agents"))

    def test_module_public_path_m12_login(self):
        """测试 M12 登录路径是公开路径"""
        from src.middleware.auth import AuthMiddleware
        from src.config import settings
        middleware = AuthMiddleware(MagicMock())

        # 找到 M12 路由
        m12_route = None
        for r in settings.routes:
            if r.key == "m12":
                m12_route = r
                break

        self.assertIsNotNone(m12_route)
        self.assertTrue(
            middleware._is_module_public_path("/m12/api/v1/auth/login", m12_route)
        )

    def test_module_public_path_m12_register(self):
        """测试 M12 注册路径是公开路径"""
        from src.middleware.auth import AuthMiddleware
        from src.config import settings
        middleware = AuthMiddleware(MagicMock())

        m12_route = None
        for r in settings.routes:
            if r.key == "m12":
                m12_route = r
                break

        self.assertIsNotNone(m12_route)
        self.assertTrue(
            middleware._is_module_public_path("/m12/api/v1/auth/register", m12_route)
        )

    def test_module_public_path_health(self):
        """测试各模块的 /health 是公开路径"""
        from src.middleware.auth import AuthMiddleware
        from src.config import settings
        middleware = AuthMiddleware(MagicMock())

        for route in settings.routes:
            if "/health" in route.public_paths:
                result = middleware._is_module_public_path(
                    f"{route.prefix}/health", route
                )
                self.assertTrue(
                    result,
                    f"{route.key} 的 /health 应该是公开路径"
                )

    def test_module_private_path(self):
        """测试模块私有路径不在白名单中"""
        from src.middleware.auth import AuthMiddleware
        from src.config import settings
        middleware = AuthMiddleware(MagicMock())

        m12_route = None
        for r in settings.routes:
            if r.key == "m12":
                m12_route = r
                break

        self.assertIsNotNone(m12_route)
        self.assertFalse(
            middleware._is_module_public_path("/m12/api/v1/users/profile", m12_route)
        )

    def test_public_path_prefix_match(self):
        """测试公开路径前缀匹配"""
        from src.middleware.auth import AuthMiddleware
        from src.config import settings
        middleware = AuthMiddleware(MagicMock())

        m12_route = None
        for r in settings.routes:
            if r.key == "m12":
                m12_route = r
                break

        self.assertIsNotNone(m12_route)
        # /api/v1/auth/password/forgot 应该匹配 /api/v1/auth/password 前缀
        self.assertTrue(
            middleware._is_module_public_path(
                "/m12/api/v1/auth/password/forgot", m12_route
            )
        )

    def tearDown(self):
        if "ENV" in os.environ:
            del os.environ["ENV"]


class TestFindRouteByPath(unittest.TestCase):
    """路径查找路由测试"""

    def test_find_m1_route(self):
        """测试根据路径找到 M1 路由"""
        from src.middleware.auth import _find_route_by_path
        route = _find_route_by_path("/m1/api/v1/agents")
        self.assertIsNotNone(route)
        self.assertEqual(route.key, "m1")

    def test_find_m8_route(self):
        """测试根据路径找到 M8 路由"""
        from src.middleware.auth import _find_route_by_path
        route = _find_route_by_path("/m8/api/v1/users")
        self.assertIsNotNone(route)
        self.assertEqual(route.key, "m8")

    def test_find_m12_route(self):
        """测试根据路径找到 M12 路由"""
        from src.middleware.auth import _find_route_by_path
        route = _find_route_by_path("/m12/api/v1/auth/login")
        self.assertIsNotNone(route)
        self.assertEqual(route.key, "m12")

    def test_find_no_route(self):
        """测试找不到路由的情况"""
        from src.middleware.auth import _find_route_by_path
        route = _find_route_by_path("/nonexistent/path")
        self.assertIsNone(route)

    def test_all_routes_findaable(self):
        """测试所有12个模块路由都能通过路径找到"""
        from src.middleware.auth import _find_route_by_path
        for i in range(1, 13):
            route = _find_route_by_path(f"/m{i}/health")
            self.assertIsNotNone(route, f"模块 m{i} 应该能通过路径找到")
            self.assertEqual(route.key, f"m{i}")


class TestAuthMiddlewareDispatch(unittest.TestCase):
    """认证中间件 dispatch 集成测试"""

    def setUp(self):
        os.environ["ENV"] = "development"
        os.environ["GATEWAY_JWT_SECRET"] = TEST_JWT_SECRET
        os.environ["GATEWAY_JWT_ALGORITHM"] = TEST_JWT_ALGORITHM
        os.environ["GATEWAY_API_KEY_1"] = "test-api-key-1234567890abcdef"
        if "src.middleware.auth" in sys.modules:
            del sys.modules["src.middleware.auth"]

    def test_whitelist_path_passes(self):
        """测试白名单路径直接通过"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        # 创建模拟请求
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",
            "headers": [],
        }

        async def call_next(request):
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_no_auth_returns_401(self):
        """测试无认证信息返回 401"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/agents",
            "headers": [],
        }

        async def call_next(request):
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 401)

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_valid_jwt_passes(self):
        """测试有效 JWT Token 通过认证"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        payload = {
            "sub": "user-123",
            "username": "testuser",
            "roles": ["user"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
        }
        token = _make_jwt_token(payload)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }

        captured_state = {}

        async def call_next(request):
            captured_state["authenticated"] = request.state.authenticated
            captured_state["user"] = request.state.user
            captured_state["auth_method"] = request.state.auth_method
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(captured_state["authenticated"])
            self.assertEqual(captured_state["auth_method"], "jwt")
            self.assertEqual(captured_state["user"]["user_id"], "user-123")

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_valid_api_key_passes(self):
        """测试有效 API Key 通过认证"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/agents",
            "headers": [(b"x-api-key", b"test-api-key-1234567890abcdef")],
        }

        captured_state = {}

        async def call_next(request):
            captured_state["authenticated"] = request.state.authenticated
            captured_state["user"] = request.state.user
            captured_state["auth_method"] = request.state.auth_method
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(captured_state["authenticated"])
            self.assertEqual(captured_state["auth_method"], "api_key")
            self.assertEqual(captured_state["user"]["user_id"], "api-client")

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_invalid_jwt_returns_401(self):
        """测试无效 JWT 返回 401"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/agents",
            "headers": [(b"authorization", b"Bearer invalid.token.here")],
        }

        async def call_next(request):
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 401)

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_unauthorized_response_format(self):
        """测试未认证响应格式"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m1/api/v1/test",
            "headers": [],
        }

        async def call_next(request):
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 401)

            # 检查响应头
            self.assertIn("www-authenticate", [k.lower() for k in response.headers.keys()])
            self.assertIn("x-gateway-module", [k.lower() for k in response.headers.keys()])

            # 检查响应体
            import json
            body = json.loads(response.body)
            self.assertEqual(body["code"], 401)
            self.assertIn("Unauthorized", body["message"])
            self.assertIn("data", body)
            self.assertIn("auth_methods", body["data"])
            self.assertIn("api_key", body["data"]["auth_methods"])
            self.assertIn("bearer_token", body["data"]["auth_methods"])

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_module_public_path_skips_auth(self):
        """测试模块公开路径跳过认证"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/m12/api/v1/auth/login",  # 公开路径
            "headers": [],  # 无认证信息
        }

        async def call_next(request):
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            response = await middleware.dispatch(request, call_next)
            # 公开路径应该直接通过
            self.assertEqual(response.status_code, 200)

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def test_request_state_initialized(self):
        """测试请求状态被正确初始化"""
        from src.middleware.auth import AuthMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/health",  # 白名单
            "headers": [],
        }

        captured_state = {}

        async def call_next(request):
            captured_state["authenticated"] = request.state.authenticated
            captured_state["auth_method"] = request.state.auth_method
            captured_state["user"] = request.state.user
            captured_state["token"] = request.state.token
            return Response(status_code=200)

        middleware = AuthMiddleware(call_next)

        async def test():
            request = Request(scope)
            await middleware.dispatch(request, call_next)
            self.assertFalse(captured_state["authenticated"])
            self.assertIsNone(captured_state["auth_method"])
            self.assertIsNone(captured_state["user"])
            self.assertIsNone(captured_state["token"])

        import asyncio
        asyncio.get_event_loop().run_until_complete(test())

    def tearDown(self):
        for key in [
            "ENV", "GATEWAY_JWT_SECRET", "GATEWAY_JWT_ALGORITHM",
            "GATEWAY_JWT_ISSUER", "GATEWAY_API_KEY_1"
        ]:
            if key in os.environ:
                del os.environ[key]


class TestTokenInfo(unittest.TestCase):
    """Token 信息获取测试"""

    def setUp(self):
        os.environ["ENV"] = "development"
        os.environ["GATEWAY_JWT_SECRET"] = TEST_JWT_SECRET
        os.environ["GATEWAY_JWT_ALGORITHM"] = TEST_JWT_ALGORITHM
        if "src.middleware.auth" in sys.modules:
            del sys.modules["src.middleware.auth"]

    def test_get_token_info_valid(self):
        """测试获取有效 Token 信息"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        payload = {
            "sub": "user-456",
            "username": "testuser2",
            "roles": ["admin"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "type": "access",
            "jti": "jti-789",
        }
        token = _make_jwt_token(payload)
        info = middleware.get_token_info(token)

        self.assertIsNotNone(info)
        self.assertEqual(info["user_id"], "user-456")
        self.assertEqual(info["username"], "testuser2")
        self.assertEqual(info["jti"], "jti-789")

    def test_get_token_info_invalid(self):
        """测试获取无效 Token 信息返回 None"""
        from src.middleware.auth import AuthMiddleware
        middleware = AuthMiddleware(MagicMock())

        info = middleware.get_token_info("invalid.token.value")
        self.assertIsNone(info)

    def tearDown(self):
        for key in ["ENV", "GATEWAY_JWT_SECRET", "GATEWAY_JWT_ALGORITHM"]:
            if key in os.environ:
                del os.environ[key]


if __name__ == "__main__":
    unittest.main(verbosity=2)
