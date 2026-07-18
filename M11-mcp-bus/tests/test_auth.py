"""M11 MCP Bus - 鉴权中间件单元测试.

测试 _hash_key、_is_public_path、默认公开路径、权限工厂函数等功能。
"""

import hashlib
import os
import sys
import unittest

# 确保项目根目录在 Python 路径中，使 src 作为包导入
# 这样源码中的相对导入（from ..config import ...）才能正确解析
from src.middleware.auth import (
    DEFAULT_PUBLIC_PATHS,
    _hash_key,
    _is_public_path,
    require_permission,
    security,
)


class TestHashKey(unittest.TestCase):
    """测试 _hash_key 哈希函数."""

    def test_hash_key_returns_string(self) -> None:
        """测试返回值为字符串类型."""
        result = _hash_key("test-key")
        self.assertIsInstance(result, str)

    def test_hash_key_is_sha256(self) -> None:
        """测试哈希算法为 SHA256（64 位十六进制字符）."""
        result = _hash_key("test-key")
        self.assertEqual(len(result), 64)
        # 验证是合法的十六进制字符串
        int(result, 16)  # 不抛异常则是合法的十六进制

    def test_hash_key_deterministic(self) -> None:
        """测试相同输入产生相同输出（确定性）."""
        key = "my-api-key-123"
        h1 = _hash_key(key)
        h2 = _hash_key(key)
        self.assertEqual(h1, h2)

    def test_hash_key_different_inputs(self) -> None:
        """测试不同输入产生不同输出."""
        h1 = _hash_key("key-a")
        h2 = _hash_key("key-b")
        self.assertNotEqual(h1, h2)

    def test_hash_key_empty_string(self) -> None:
        """测试空字符串也能正确哈希."""
        result = _hash_key("")
        self.assertEqual(len(result), 64)
        # 空字符串的 SHA256 是已知的
        expected = hashlib.sha256("".encode("utf-8")).hexdigest()
        self.assertEqual(result, expected)

    def test_hash_key_unicode(self) -> None:
        """测试包含 Unicode 字符的 key 也能正确哈希."""
        result = _hash_key("测试密钥🔑")
        self.assertEqual(len(result), 64)
        self.assertIsInstance(result, str)


class TestIsPublicPath(unittest.TestCase):
    """测试 _is_public_path 路径匹配."""

    def test_exact_match(self) -> None:
        """测试精确路径匹配."""
        self.assertTrue(_is_public_path("/health"))
        self.assertTrue(_is_public_path("/docs"))
        self.assertTrue(_is_public_path("/"))

    def test_non_public_path(self) -> None:
        """测试非公开路径返回 False."""
        self.assertFalse(_is_public_path("/api/v1/tools"))
        self.assertFalse(_is_public_path("/admin/servers"))
        self.assertFalse(_is_public_path("/mcp/sse/session123"))

    def test_wildcard_match(self) -> None:
        """测试通配符路径匹配（/m8/* 匹配 /m8/ 开头的路径）."""
        self.assertTrue(_is_public_path("/m8/health"))
        self.assertTrue(_is_public_path("/m8/tools/list"))
        self.assertTrue(_is_public_path("/m8/"))
        self.assertTrue(_is_public_path("/m8/anything/here"))

    def test_wildcard_no_match(self) -> None:
        """测试通配符不匹配的情况."""
        # /m8 不带斜杠不匹配 /m8/*
        self.assertFalse(_is_public_path("/m8"))
        # /mcp/sse 不匹配 /mcp（精确匹配）
        self.assertFalse(_is_public_path("/mcp/sse"))

    def test_custom_public_paths(self) -> None:
        """测试自定义公开路径列表."""
        custom_paths = ["/api/public/*", "/status"]
        self.assertTrue(_is_public_path("/status", custom_paths))
        self.assertTrue(_is_public_path("/api/public/info", custom_paths))
        self.assertFalse(_is_public_path("/health", custom_paths))

    def test_openapi_json_path(self) -> None:
        """测试 openapi.json 是公开路径."""
        self.assertTrue(_is_public_path("/openapi.json"))

    def test_favicon_path(self) -> None:
        """测试 favicon.ico 是公开路径."""
        self.assertTrue(_is_public_path("/favicon.ico"))

    def test_redoc_path(self) -> None:
        """测试 redoc 是公开路径."""
        self.assertTrue(_is_public_path("/redoc"))


class TestDefaultPublicPaths(unittest.TestCase):
    """测试默认公开路径列表."""

    def test_health_in_default_paths(self) -> None:
        """测试 /health 在默认公开路径中."""
        self.assertIn("/health", DEFAULT_PUBLIC_PATHS)

    def test_docs_in_default_paths(self) -> None:
        """测试 /docs 在默认公开路径中."""
        self.assertIn("/docs", DEFAULT_PUBLIC_PATHS)

    def test_root_in_default_paths(self) -> None:
        """测试 / 在默认公开路径中."""
        self.assertIn("/", DEFAULT_PUBLIC_PATHS)

    def test_openapi_in_default_paths(self) -> None:
        """测试 /openapi.json 在默认公开路径中."""
        self.assertIn("/openapi.json", DEFAULT_PUBLIC_PATHS)

    def test_m8_wildcard_in_default_paths(self) -> None:
        """测试 /m8/* 通配符在默认公开路径中."""
        self.assertIn("/m8/*", DEFAULT_PUBLIC_PATHS)


class TestRequirePermission(unittest.TestCase):
    """测试 require_permission 工厂函数."""

    def test_returns_callable(self) -> None:
        """测试 require_permission 返回可调用对象."""
        check = require_permission("admin:read")
        self.assertTrue(callable(check))

    def test_different_permissions_return_different_callables(self) -> None:
        """测试不同权限返回不同的可调用对象."""
        check1 = require_permission("admin:read")
        check2 = require_permission("admin:write")
        self.assertIsNot(check1, check2)

    def test_returned_function_is_coroutine(self) -> None:
        """测试返回的函数是异步函数（协程）."""
        import asyncio

        check = require_permission("test:perm")
        self.assertTrue(asyncio.iscoroutinefunction(check))


class TestSecurityObject(unittest.TestCase):
    """测试 HTTPBearer security 对象."""

    def test_security_is_http_bearer(self) -> None:
        """测试 security 是 HTTPBearer 实例."""
        from fastapi.security import HTTPBearer

        self.assertIsInstance(security, HTTPBearer)

    def test_security_auto_error_false(self) -> None:
        """测试 security 的 auto_error 为 False（不自动抛 401）."""
        self.assertFalse(security.auto_error)


class TestApiKeyAuthMiddleware(unittest.TestCase):
    """测试 ApiKeyAuthMiddleware 类."""

    def setUp(self) -> None:
        """每个测试前创建中间件实例."""
        from src.middleware.auth import ApiKeyAuthMiddleware

        self.middleware = ApiKeyAuthMiddleware()

    def test_extract_key_from_x_api_key(self) -> None:
        """测试从 X-API-Key 请求头提取 key."""
        headers = {"X-API-Key": "test-key-123"}
        key = self.middleware.extract_key_from_headers(headers)
        self.assertEqual(key, "test-key-123")

    def test_extract_key_from_lowercase_x_api_key(self) -> None:
        """测试从小写 x-api-key 请求头提取 key."""
        headers = {"x-api-key": "test-key-456"}
        key = self.middleware.extract_key_from_headers(headers)
        self.assertEqual(key, "test-key-456")

    def test_extract_key_from_authorization_bearer(self) -> None:
        """测试从 Authorization: Bearer 请求头提取 key."""
        headers = {"Authorization": "Bearer my-bearer-token"}
        key = self.middleware.extract_key_from_headers(headers)
        self.assertEqual(key, "my-bearer-token")

    def test_extract_key_from_lowercase_authorization(self) -> None:
        """测试从小写 authorization 请求头提取 key."""
        headers = {"authorization": "bearer my-token"}
        key = self.middleware.extract_key_from_headers(headers)
        self.assertEqual(key, "my-token")

    def test_extract_key_no_key_present(self) -> None:
        """测试没有 key 时返回 None."""
        headers = {"Content-Type": "application/json"}
        key = self.middleware.extract_key_from_headers(headers)
        self.assertIsNone(key)

    def test_extract_key_x_api_key_priority(self) -> None:
        """测试 X-API-Key 优先级高于 Authorization."""
        headers = {
            "X-API-Key": "from-x-api-key",
            "Authorization": "Bearer from-auth",
        }
        key = self.middleware.extract_key_from_headers(headers)
        self.assertEqual(key, "from-x-api-key")

    def test_is_public_path_method(self) -> None:
        """测试中间件的 is_public_path 方法."""
        self.assertTrue(self.middleware.is_public_path("/health"))
        self.assertFalse(self.middleware.is_public_path("/admin/users"))


if __name__ == "__main__":
    unittest.main()
