"""
M12 安全盾 - 认证模块单元测试
覆盖：JWT Token 生成与验证、密码哈希、登录认证、角色权限控制
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# 将项目根目录加入路径，确保可以导入 backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 预先设置安全 JWT 密钥，避免默认空密钥触发启动失败
os.environ.setdefault("M12_JWT_SECRET", "test-jwt-secret-for-unit-tests-only-do-not-use-in-production")

from backend.auth import (
    # JWT 相关
    create_access_token,
    create_refresh_token,
    decode_token,
    # 密码哈希
    hash_password,
    verify_password,
    # API Key 相关
    generate_api_key,
    hash_api_key,
    get_api_key_prefix,
    validate_api_key,
    # 角色权限
    has_role,
    has_scope,
    has_any_scope,
    # 角色常量
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    ROLE_API,
    SCOPE_WAF_READ,
    SCOPE_WAF_WRITE,
    SCOPE_AUTH_READ,
)
from backend.config import get_settings


class TestJWTFunctions(unittest.TestCase):
    """JWT Token 相关功能测试"""

    def setUp(self):
        """测试前准备"""
        self.settings = get_settings()
        self.test_user = {
            "sub": "user_test001",
            "username": "testuser",
            "roles": ["admin"],
            "scopes": ["waf:read", "waf:write"],
        }

    def test_create_access_token_success(self):
        """测试：正确生成访问令牌"""
        token = create_access_token(data=self.test_user)
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 0)
        # JWT 格式：三段，用 . 分隔
        parts = token.split('.')
        self.assertEqual(len(parts), 3)

    def test_decode_valid_token(self):
        """测试：正确签名的 Token 可以成功解码"""
        token = create_access_token(data=self.test_user)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "user_test001")
        self.assertEqual(payload["username"], "testuser")
        self.assertEqual(payload["type"], "access")

    def test_token_contains_user_info(self):
        """测试：Token 中包含正确的用户信息（user_id、role 等）"""
        token = create_access_token(data=self.test_user)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        # user_id (sub)
        self.assertEqual(payload.get("sub"), "user_test001")
        # username
        self.assertEqual(payload.get("username"), "testuser")
        # roles
        self.assertIn("admin", payload.get("roles", []))
        # scopes
        self.assertIn("waf:read", payload.get("scopes", []))
        self.assertIn("waf:write", payload.get("scopes", []))

    def test_decode_expired_token_returns_none(self):
        """测试：过期 Token 验证失败，返回 None"""
        # 创建一个已经过期的 Token（过期时间设为过去）
        expired_delta = timedelta(seconds=-10)
        token = create_access_token(data=self.test_user, expires_delta=expired_delta)
        payload = decode_token(token)
        self.assertIsNone(payload)

    def test_decode_wrong_signature_token_returns_none(self):
        """测试：错误签名 Token 验证失败，返回 None"""
        # 生成一个正确的 token
        token = create_access_token(data=self.test_user)
        # 篡改 token 的签名部分（最后一段）
        parts = token.split('.')
        tampered_token = parts[0] + '.' + parts[1] + '.' + 'fake-signature-12345'
        payload = decode_token(tampered_token)
        self.assertIsNone(payload)

    def test_decode_invalid_format_token_returns_none(self):
        """测试：格式错误的 Token 返回 None"""
        payload = decode_token("not-a-valid-jwt-token")
        self.assertIsNone(payload)

    def test_create_refresh_token(self):
        """测试：创建刷新令牌"""
        token = create_refresh_token(data=self.test_user)
        self.assertIsInstance(token, str)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("type"), "refresh")
        self.assertEqual(payload.get("sub"), "user_test001")

    def test_access_token_has_expiration(self):
        """测试：生成的访问令牌包含过期时间声明"""
        token = create_access_token(data=self.test_user)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)
        # exp 应该是一个时间戳（数字）
        self.assertIsInstance(payload["exp"], int)
        # 过期时间应该晚于签发时间
        self.assertGreater(payload["exp"], payload["iat"])

    def test_custom_expires_delta(self):
        """测试：自定义过期时间增量生效"""
        # 设为 5 分钟过期
        custom_delta = timedelta(minutes=5)
        token = create_access_token(data=self.test_user, expires_delta=custom_delta)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        # 计算过期时间差，大约 5 分钟（300 秒）
        duration = payload["exp"] - payload["iat"]
        # 允许 5 秒误差
        self.assertAlmostEqual(duration, 300, delta=5)


class TestPasswordHashing(unittest.TestCase):
    """密码哈希相关功能测试
    注：由于环境中 bcrypt 5.x 与 passlib 存在版本兼容性问题，
    此处使用 unittest.mock 模拟 pwd_context 来验证函数调用逻辑的正确性。
    """

    def setUp(self):
        """测试前准备：mock pwd_context 以避免 bcrypt 版本兼容性问题"""
        # 使用 patch 模拟 pwd_context
        self.patcher = patch('backend.auth.pwd_context')
        self.mock_pwd = self.patcher.start()

        # 模拟 hash 方法：返回一个带 salt 的假哈希值
        import hashlib
        self._hash_counter = 0

        def fake_hash(password):
            self._hash_counter += 1
            salt = f"salt{self._hash_counter}"
            fake_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return f"$2b$12${salt}${fake_hash}"

        def fake_verify(password, hashed):
            # 从哈希中提取 salt
            parts = hashed.split('$')
            if len(parts) < 5:
                return False
            salt = parts[3]
            expected = hashlib.sha256((password + salt).encode()).hexdigest()
            return parts[4] == expected

        self.mock_pwd.hash.side_effect = fake_hash
        self.mock_pwd.verify.side_effect = fake_verify

    def tearDown(self):
        """测试后清理"""
        self.patcher.stop()

    def test_hash_password_returns_string(self):
        """测试：密码哈希生成，返回非空字符串"""
        hashed = hash_password("test_password_123")
        self.assertIsInstance(hashed, str)
        self.assertTrue(len(hashed) > 0)
        # 验证 pwd_context.hash 被调用
        self.mock_pwd.hash.assert_called_once()
        self.mock_pwd.hash.assert_called_with("test_password_123")

    def test_verify_correct_password(self):
        """测试：正确密码验证通过"""
        password = "my_secure_password"
        hashed = hash_password(password)
        result = verify_password(password, hashed)
        self.assertTrue(result)
        # 验证 verify 被调用
        self.mock_pwd.verify.assert_called_with(password, hashed)

    def test_verify_wrong_password(self):
        """测试：错误密码验证失败"""
        hashed = hash_password("correct_password")
        result = verify_password("wrong_password", hashed)
        self.assertFalse(result)

    def test_same_password_different_hashes(self):
        """测试：相同密码生成不同哈希（salt 机制）"""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        # 两个哈希值应该不同（因为 salt 随机）
        self.assertNotEqual(hash1, hash2)
        # 但都能验证同一个密码
        self.assertTrue(verify_password(password, hash1))
        self.assertTrue(verify_password(password, hash2))

    def test_verify_empty_password(self):
        """测试：空密码也可以被哈希和验证"""
        password = ""
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("not_empty", hashed))

    def test_hash_password_calls_pwd_context(self):
        """测试：hash_password 正确委托给 pwd_context.hash"""
        hash_password("mypassword")
        self.mock_pwd.hash.assert_called_once_with("mypassword")

    def test_verify_password_calls_pwd_context(self):
        """测试：verify_password 正确委托给 pwd_context.verify"""
        verify_password("pass123", "hashed_value")
        self.mock_pwd.verify.assert_called_once_with("pass123", "hashed_value")


class TestRoleAndScope(unittest.TestCase):
    """角色权限和范围控制测试"""

    def test_has_role_exact_match(self):
        """测试：角色完全匹配时通过"""
        self.assertTrue(has_role(["admin"], ROLE_ADMIN))

    def test_has_role_hierarchy_high_includes_low(self):
        """测试：角色层级中，高级别角色包含低级别权限"""
        # super_admin 级别高于 admin，应该通过
        self.assertTrue(has_role([ROLE_SUPER_ADMIN], ROLE_ADMIN))
        # admin 级别高于 operator，应该通过
        self.assertTrue(has_role([ROLE_ADMIN], ROLE_OPERATOR))

    def test_has_role_low_level_cannot_access_high(self):
        """测试：低级别角色无法访问高级别资源"""
        self.assertFalse(has_role([ROLE_VIEWER], ROLE_ADMIN))
        self.assertFalse(has_role([ROLE_API], ROLE_SUPER_ADMIN))

    def test_has_role_empty_list(self):
        """测试：空角色列表返回 False"""
        self.assertFalse(has_role([], ROLE_ADMIN))

    def test_has_scope_exact_match(self):
        """测试：权限范围精确匹配通过"""
        self.assertTrue(has_scope(["waf:read", "waf:write"], SCOPE_WAF_READ))

    def test_has_scope_missing_returns_false(self):
        """测试：缺少权限时返回 False"""
        self.assertFalse(has_scope(["waf:read"], SCOPE_WAF_WRITE))

    def test_has_scope_wildcard_matches_all(self):
        """测试：通配符权限（*）匹配所有"""
        self.assertTrue(has_scope(["*"], SCOPE_WAF_READ))
        self.assertTrue(has_scope(["*"], SCOPE_AUTH_READ))
        self.assertTrue(has_scope(["*"], "any:scope"))

    def test_has_any_scope_at_least_one(self):
        """测试：拥有任意一个需要的权限时通过"""
        user_scopes = ["waf:read", "ip:read"]
        required = ["waf:write", "waf:read"]
        self.assertTrue(has_any_scope(user_scopes, required))

    def test_has_any_scope_none_matching(self):
        """测试：没有任何匹配的权限时失败"""
        user_scopes = ["waf:read"]
        required = ["auth:write", "ip:write"]
        self.assertFalse(has_any_scope(user_scopes, required))


class TestLoginIntegration(unittest.TestCase):
    """登录功能集成测试（使用路由层接口）"""

    def setUp(self):
        """测试前准备：重置 auth_api 中的模拟存储"""
        # 导入后重置全局变量
        from backend.routers import auth_api
        auth_api._api_keys_storage = []
        auth_api._api_key_id_counter = 0

    def test_login_success_with_valid_credentials(self):
        """测试：正确用户名密码登录成功"""
        from backend.routers.auth_api import login
        result = login(username="admin", password="admin123", remember_me=False)
        self.assertEqual(result["code"], 0)
        self.assertIn("access_token", result["data"])
        self.assertIn("refresh_token", result["data"])
        self.assertEqual(result["data"]["token_type"], "bearer")
        self.assertIn("user", result["data"])

    def test_login_returns_valid_access_token(self):
        """测试：登录返回的 access_token 可以被正确解码"""
        from backend.routers.auth_api import login
        result = login(username="testuser", password="testpass", remember_me=False)
        access_token = result["data"]["access_token"]
        payload = decode_token(access_token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "access")
        self.assertEqual(payload["username"], "testuser")

    def test_login_empty_username_fails(self):
        """测试：空用户名登录失败"""
        from backend.routers.auth_api import login
        result = login(username="", password="pass123", remember_me=False)
        self.assertNotEqual(result["code"], 0)

    def test_login_empty_password_fails(self):
        """测试：空密码登录失败"""
        from backend.routers.auth_api import login
        result = login(username="admin", password="", remember_me=False)
        self.assertNotEqual(result["code"], 0)

    def test_refresh_token_success(self):
        """测试：Token 刷新机制正常工作"""
        from backend.routers.auth_api import login, refresh_token
        # 先登录获取 refresh_token
        login_result = login(username="user1", password="pass1", remember_me=False)
        old_refresh = login_result["data"]["refresh_token"]

        # 使用 refresh_token 刷新
        refresh_result = refresh_token(refresh_token=old_refresh)
        self.assertEqual(refresh_result["code"], 0)
        self.assertIn("access_token", refresh_result["data"])
        self.assertIn("refresh_token", refresh_result["data"])

        # 新的 access_token 应该有效
        new_access = refresh_result["data"]["access_token"]
        payload = decode_token(new_access)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "access")

    def test_refresh_with_invalid_token_fails(self):
        """测试：使用无效的刷新令牌刷新失败"""
        from backend.routers.auth_api import refresh_token
        result = refresh_token(refresh_token="invalid-refresh-token")
        self.assertNotEqual(result["code"], 0)

    def test_refresh_with_access_token_fails(self):
        """测试：使用 access_token 作为 refresh_token 刷新失败"""
        from backend.routers.auth_api import login, refresh_token
        login_result = login(username="user2", password="pass2", remember_me=False)
        access_token = login_result["data"]["access_token"]
        # access_token 的 type 是 "access"，不是 "refresh"，应该失败
        result = refresh_token(refresh_token=access_token)
        self.assertNotEqual(result["code"], 0)

    def test_logout_success(self):
        """测试：登出接口正常返回"""
        from backend.routers.auth_api import logout
        result = logout()
        self.assertEqual(result["code"], 0)
        self.assertTrue(result["data"]["success"])


if __name__ == "__main__":
    unittest.main()
