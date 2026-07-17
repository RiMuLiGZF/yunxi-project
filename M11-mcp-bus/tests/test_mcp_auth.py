"""M11 MCP Bus - MCP 端点鉴权测试.

测试 /mcp 端点的 API Key 鉴权功能，包括：
- 无 API Key 的请求被拒绝（401）
- 错误 API Key 的请求被拒绝（401）
- 正确 API Key 的请求可以通过
- 多种 API Key 传递方式（header / bearer / query）
- SSE 连接也经过认证
- 生产环境安全校验
"""

import hashlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# 辅助函数
# ============================================================

def _hash_key(key: str) -> str:
    """计算 key 的 SHA256 哈希."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _create_mock_request(
    method: str = "POST",
    path: str = "/mcp",
    headers: dict | None = None,
    query_params: dict | None = None,
    client_host: str = "127.0.0.1",
) -> MagicMock:
    """创建一个模拟的 FastAPI Request 对象."""
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.headers = headers or {}
    request.query_params = query_params or {}
    request.client = MagicMock()
    request.client.host = client_host
    return request


# ============================================================
# API Key 提取测试
# ============================================================

class TestExtractApiKey(unittest.TestCase):
    """测试 _extract_api_key 函数从请求中提取 API Key."""

    def setUp(self) -> None:
        """每个测试前导入被测函数."""
        from src.routers.mcp import _extract_api_key
        self._extract_api_key = _extract_api_key

    def test_extract_from_x_api_key_header(self) -> None:
        """测试从 X-API-Key header 提取."""
        request = _create_mock_request(headers={"x-api-key": "test-key-123"})
        result = self._extract_api_key(request)
        self.assertEqual(result, "test-key-123")

    def test_extract_from_authorization_bearer(self) -> None:
        """测试从 Authorization: Bearer header 提取."""
        request = _create_mock_request(headers={"authorization": "Bearer my-bearer-token"})
        result = self._extract_api_key(request)
        self.assertEqual(result, "my-bearer-token")

    def test_extract_from_authorization_bearer_lowercase(self) -> None:
        """测试小写 bearer 也能正确提取."""
        request = _create_mock_request(headers={"authorization": "bearer lowercase-token"})
        result = self._extract_api_key(request)
        self.assertEqual(result, "lowercase-token")

    def test_extract_from_query_param(self) -> None:
        """测试从 api_key 查询参数提取."""
        request = _create_mock_request(query_params={"api_key": "query-key-456"})
        result = self._extract_api_key(request)
        self.assertEqual(result, "query-key-456")

    def test_x_api_key_priority_over_bearer(self) -> None:
        """测试 X-API-Key 优先级高于 Authorization: Bearer."""
        request = _create_mock_request(
            headers={
                "x-api-key": "from-x-api-key",
                "authorization": "Bearer from-bearer",
            }
        )
        result = self._extract_api_key(request)
        self.assertEqual(result, "from-x-api-key")

    def test_bearer_priority_over_query(self) -> None:
        """测试 Authorization: Bearer 优先级高于 query 参数."""
        request = _create_mock_request(
            headers={"authorization": "Bearer from-bearer"},
            query_params={"api_key": "from-query"},
        )
        result = self._extract_api_key(request)
        self.assertEqual(result, "from-bearer")

    def test_no_key_returns_none(self) -> None:
        """测试没有 API Key 时返回 None."""
        request = _create_mock_request()
        result = self._extract_api_key(request)
        self.assertIsNone(result)

    def test_empty_bearer_returns_none(self) -> None:
        """测试 Authorization 不是 Bearer 格式时不提取."""
        request = _create_mock_request(headers={"authorization": "Basic dXNlcjpwYXNz"})
        result = self._extract_api_key(request)
        self.assertIsNone(result)


# ============================================================
# MCP 鉴权检查测试（默认 API Key 方式）
# ============================================================

class TestCheckMcpAuthDefaultKey(unittest.TestCase):
    """测试 _check_mcp_auth 使用默认 API Key 的场景."""

    def setUp(self) -> None:
        """每个测试前设置 mock 配置."""
        # 创建设置 mock
        self.settings_patch = patch("src.routers.mcp.get_settings")
        mock_get_settings = self.settings_patch.start()
        self.mock_settings = MagicMock()
        self.mock_settings.mcp_require_auth = True
        self.mock_settings.mcp_default_api_key = "test-default-key-abc123"
        mock_get_settings.return_value = self.mock_settings

        # mock 数据库查询（返回 None，让它走默认 key 路径）
        self.db_patch = patch("src.routers.mcp._validate_api_key_in_db")
        self.mock_validate_db = self.db_patch.start()
        self.mock_validate_db.return_value = None

        from src.routers.mcp import _check_mcp_auth
        self._check_mcp_auth = _check_mcp_auth

    def tearDown(self) -> None:
        """清理 mock."""
        self.settings_patch.stop()
        self.db_patch.stop()

    def test_valid_default_key_via_header(self) -> None:
        """测试通过 X-API-Key header 传递正确的默认 key."""
        request = _create_mock_request(headers={"x-api-key": "test-default-key-abc123"})
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "default-mcp-key")
        self.assertEqual(result.id, -1)

    def test_valid_default_key_via_bearer(self) -> None:
        """测试通过 Authorization: Bearer 传递正确的默认 key."""
        request = _create_mock_request(
            headers={"authorization": "Bearer test-default-key-abc123"}
        )
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "default-mcp-key")

    def test_valid_default_key_via_query(self) -> None:
        """测试通过 query 参数传递正确的默认 key."""
        request = _create_mock_request(query_params={"api_key": "test-default-key-abc123"})
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "default-mcp-key")

    def test_wrong_key_returns_none(self) -> None:
        """测试错误的 API Key 返回 None."""
        request = _create_mock_request(headers={"x-api-key": "wrong-key"})
        result = self._check_mcp_auth(request)
        self.assertIsNone(result)

    def test_no_key_returns_none(self) -> None:
        """测试没有 API Key 返回 None."""
        request = _create_mock_request()
        result = self._check_mcp_auth(request)
        self.assertIsNone(result)

    def test_auth_disabled_returns_anonymous(self) -> None:
        """测试鉴权关闭时返回 anonymous key."""
        self.mock_settings.mcp_require_auth = False
        request = _create_mock_request()
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "anonymous")
        self.assertEqual(result.id, 0)

    def test_default_key_permissions(self) -> None:
        """测试默认 key 拥有 mcp:read 和 mcp:call 权限."""
        request = _create_mock_request(headers={"x-api-key": "test-default-key-abc123"})
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertIn("mcp:read", result.permissions)
        self.assertIn("mcp:call", result.permissions)


# ============================================================
# MCP 鉴权检查测试（数据库 API Key 方式）
# ============================================================

class TestCheckMcpAuthDbKey(unittest.TestCase):
    """测试 _check_mcp_auth 使用数据库 API Key 的场景."""

    def setUp(self) -> None:
        """每个测试前设置 mock 配置."""
        # 创建设置 mock
        self.settings_patch = patch("src.routers.mcp.get_settings")
        mock_get_settings = self.settings_patch.start()
        self.mock_settings = MagicMock()
        self.mock_settings.mcp_require_auth = True
        self.mock_settings.mcp_default_api_key = ""  # 空默认 key，只测数据库
        mock_get_settings.return_value = self.mock_settings

        # mock 数据库验证函数
        self.db_patch = patch("src.routers.mcp._validate_api_key_in_db")
        self.mock_validate_db = self.db_patch.start()

        from src.routers.mcp import _check_mcp_auth
        from src.models_db import ApiKey
        self._check_mcp_auth = _check_mcp_auth
        self._ApiKey = ApiKey

    def tearDown(self) -> None:
        """清理 mock."""
        self.settings_patch.stop()
        self.db_patch.stop()

    def test_db_key_validation_success(self) -> None:
        """测试数据库中的 API Key 验证成功."""
        mock_key = MagicMock()
        mock_key.id = 42
        mock_key.name = "test-db-key"
        mock_key.permissions = ["mcp:read", "mcp:call"]
        mock_key.rate_limit = 100

        self.mock_validate_db.return_value = mock_key

        request = _create_mock_request(headers={"x-api-key": "valid-db-key"})
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 42)
        self.assertEqual(result.name, "test-db-key")
        self.mock_validate_db.assert_called_once_with("valid-db-key")

    def test_db_key_validation_failed(self) -> None:
        """测试数据库中不存在的 API Key 返回 None."""
        self.mock_validate_db.return_value = None

        request = _create_mock_request(headers={"x-api-key": "invalid-key"})
        result = self._check_mcp_auth(request)
        self.assertIsNone(result)

    def test_db_key_takes_priority_over_default(self) -> None:
        """测试数据库 key 优先级高于默认 key."""
        # 设置一个默认 key
        self.mock_settings.mcp_default_api_key = "same-key"

        # 数据库也返回一个 key（不同的 id）
        mock_key = MagicMock()
        mock_key.id = 99
        mock_key.name = "db-key"
        mock_key.permissions = ["*"]
        mock_key.rate_limit = 500

        self.mock_validate_db.return_value = mock_key

        request = _create_mock_request(headers={"x-api-key": "same-key"})
        result = self._check_mcp_auth(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 99)  # 应该是数据库的 key
        self.assertEqual(result.name, "db-key")


# ============================================================
# 配置安全校验测试
# ============================================================

class TestConfigSecurityValidation(unittest.TestCase):
    """测试配置中的安全校验逻辑."""

    def setUp(self) -> None:
        """每个测试前清除缓存."""
        from src.config import reload_settings
        self._reload_settings = reload_settings

    def tearDown(self) -> None:
        """每个测试后恢复环境并清除缓存."""
        # 强制恢复为开发环境配置，避免生产环境测试失败影响后续测试
        os.environ["M11_ENV"] = "development"
        os.environ["M11_MCP_REQUIRE_AUTH"] = "true"
        os.environ["M11_MCP_DEFAULT_API_KEY"] = "test-teardown-key"

        # 清除缓存并重新加载（忽略可能的错误）
        try:
            self._reload_settings()
        except RuntimeError:
            pass

        # 清除所有测试相关的环境变量
        for key in ["M11_ENV", "M11_MCP_REQUIRE_AUTH", "M11_MCP_DEFAULT_API_KEY"]:
            if key in os.environ:
                del os.environ[key]

        # 最后再清除一次缓存，恢复默认状态
        try:
            self._reload_settings()
        except RuntimeError:
            pass

    def test_production_env_requires_auth(self) -> None:
        """测试生产环境必须启用 MCP 鉴权."""
        os.environ["M11_ENV"] = "production"
        os.environ["M11_MCP_REQUIRE_AUTH"] = "false"
        os.environ["M11_MCP_DEFAULT_API_KEY"] = "prod-key-123"

        # reload_settings 内部会调用 get_settings()，预期抛出 RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            self._reload_settings()
        self.assertIn("生产环境下 MCP 鉴权必须启用", str(ctx.exception))

    def test_production_env_requires_custom_key(self) -> None:
        """测试生产环境不能使用默认 API Key."""
        os.environ["M11_ENV"] = "production"
        os.environ["M11_MCP_REQUIRE_AUTH"] = "true"
        # 不设置 MCP_DEFAULT_API_KEY，使用默认值

        # reload_settings 内部会调用 get_settings()，预期抛出 RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            self._reload_settings()
        self.assertIn("生产环境下必须显式配置 MCP API Key", str(ctx.exception))

    def test_production_with_valid_config_starts_ok(self) -> None:
        """测试生产环境配置正确时正常启动."""
        os.environ["M11_ENV"] = "production"
        os.environ["M11_MCP_REQUIRE_AUTH"] = "true"
        os.environ["M11_MCP_DEFAULT_API_KEY"] = "strong-prod-key-xyz789"

        self._reload_settings()

        from src.config import get_settings
        settings = get_settings()
        self.assertTrue(settings.mcp_require_auth)
        self.assertEqual(settings.mcp_default_api_key, "strong-prod-key-xyz789")
        self.assertTrue(settings.is_production)

    def test_development_default_key_warning(self) -> None:
        """测试开发环境使用默认 key 时不报错（但有警告日志）."""
        os.environ["M11_ENV"] = "development"
        if "M11_MCP_DEFAULT_API_KEY" in os.environ:
            del os.environ["M11_MCP_DEFAULT_API_KEY"]

        self._reload_settings()

        from src.config import get_settings
        settings = get_settings()
        self.assertTrue(settings.is_development)
        self.assertTrue(settings.mcp_require_auth)
        # 默认 key 不应该为空
        self.assertTrue(len(settings.mcp_default_api_key) > 0)

    def test_development_with_custom_key(self) -> None:
        """测试开发环境配置自定义 key 正常."""
        os.environ["M11_ENV"] = "development"
        os.environ["M11_MCP_DEFAULT_API_KEY"] = "my-dev-key-123"

        self._reload_settings()

        from src.config import get_settings
        settings = get_settings()
        self.assertEqual(settings.mcp_default_api_key, "my-dev-key-123")


# ============================================================
# DEFAULT_PUBLIC_PATHS 测试
# ============================================================

class TestPublicPathsExcludesMcp(unittest.TestCase):
    """测试 /mcp 不再出现在默认公开路径中."""

    def test_mcp_not_in_default_public_paths(self) -> None:
        """测试 /mcp 已从默认公开路径移除."""
        from src.middleware.auth import DEFAULT_PUBLIC_PATHS
        self.assertNotIn("/mcp", DEFAULT_PUBLIC_PATHS)

    def test_health_still_public(self) -> None:
        """测试 /health 仍然是公开路径."""
        from src.middleware.auth import DEFAULT_PUBLIC_PATHS
        self.assertIn("/health", DEFAULT_PUBLIC_PATHS)

    def test_mcp_sse_not_in_public_paths(self) -> None:
        """测试 /mcp/sse 不在公开路径中."""
        from src.middleware.auth import _is_public_path
        self.assertFalse(_is_public_path("/mcp/sse"))
        self.assertFalse(_is_public_path("/mcp/sse/session123"))


# ============================================================
# 端到端：MCP 端点鉴权集成测试
# ============================================================

class TestMcpEndpointAuthIntegration(unittest.TestCase):
    """MCP 端点鉴权集成测试（使用 TestClient）."""

    @classmethod
    def setUpClass(cls) -> None:
        """设置测试环境和测试用 API Key."""
        # 设置开发环境和测试用 key
        os.environ["M11_ENV"] = "development"
        os.environ["M11_MCP_DEFAULT_API_KEY"] = "test-mcp-key-integration"
        os.environ["M11_DB_PATH"] = "/tmp/m11_test_mcp_auth.db"
        # 清除配置缓存
        from src.config import reload_settings
        reload_settings()

    @classmethod
    def tearDownClass(cls) -> None:
        """清理测试环境."""
        for key in ["M11_ENV", "M11_MCP_DEFAULT_API_KEY", "M11_DB_PATH"]:
            if key in os.environ:
                del os.environ[key]
        # 清理测试数据库
        db_path = os.path.expanduser("/tmp/m11_test_mcp_auth.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        from src.config import reload_settings
        reload_settings()

    def setUp(self) -> None:
        """每个测试前创建测试客户端."""
        try:
            from fastapi.testclient import TestClient
            from src.main import app
            self.client = TestClient(app)
            self._has_testclient = True
        except ImportError:
            self._has_testclient = False
            self.skipTest("fastapi.testclient 不可用")

    def test_mcp_post_no_key_returns_401(self) -> None:
        """测试 POST /mcp 无 API Key 返回 401（JSON-RPC 错误格式）."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        # MCP JSON-RPC 端点返回 200 但在 body 中包含错误
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], -32099)
        self.assertIn("Unauthorized", data["error"]["message"])

    def test_mcp_post_wrong_key_returns_401(self) -> None:
        """测试 POST /mcp 使用错误 API Key 返回 401（JSON-RPC 错误）."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.post(
            "/mcp",
            headers={"X-API-Key": "wrong-key"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], -32099)

    def test_mcp_post_valid_key_works(self) -> None:
        """测试 POST /mcp 使用正确 API Key 可以正常调用（initialize 方法）."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.post(
            "/mcp",
            headers={"X-API-Key": "test-mcp-key-integration"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("error", data)
        self.assertIn("result", data)
        self.assertEqual(data["result"]["protocolVersion"], "2024-11-05")

    def test_mcp_post_valid_key_via_bearer(self) -> None:
        """测试 POST /mcp 通过 Authorization: Bearer 传递 key."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.post(
            "/mcp",
            headers={"Authorization": "Bearer test-mcp-key-integration"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("error", data)
        self.assertIn("result", data)

    def test_mcp_post_valid_key_via_query(self) -> None:
        """测试 POST /mcp 通过 query 参数传递 key."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.post(
            "/mcp?api_key=test-mcp-key-integration",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn("error", data)
        self.assertIn("result", data)

    def test_mcp_sse_get_no_key_returns_401(self) -> None:
        """测试 GET /mcp/sse 无 API Key 返回 401."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.get("/mcp/sse")
        self.assertEqual(response.status_code, 401)

    def test_mcp_sse_get_wrong_key_returns_401(self) -> None:
        """测试 GET /mcp/sse 错误 API Key 返回 401."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.get(
            "/mcp/sse",
            headers={"X-API-Key": "wrong-sse-key"},
        )
        self.assertEqual(response.status_code, 401)

    def test_rest_tools_no_key_returns_401(self) -> None:
        """测试 GET /api/v1/tools 无 API Key 返回 401."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.get("/api/v1/tools")
        self.assertEqual(response.status_code, 401)

    def test_rest_tools_valid_key_works(self) -> None:
        """测试 GET /api/v1/tools 使用正确 API Key 返回 200."""
        if not self._has_testclient:
            self.skipTest("fastapi.testclient 不可用")

        response = self.client.get(
            "/api/v1/tools",
            headers={"X-API-Key": "test-mcp-key-integration"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("total", data)


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    unittest.main()
