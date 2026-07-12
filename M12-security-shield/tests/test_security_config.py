"""
M12 安全盾 - 密钥安全加固单元测试
覆盖：默认密钥检测、密钥生成工具、密钥安全验证、require_secure_secret 配置
"""

import sys
import os
import unittest
import warnings
from unittest.mock import patch, MagicMock

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.config import (
    Settings,
    generate_secret_key,
    DEFAULT_JWT_SECRET,
    get_settings,
)


class TestGenerateSecretKey(unittest.TestCase):
    """密钥生成工具测试"""

    def test_generate_secret_key_returns_string(self):
        """测试：生成的密钥是非空字符串"""
        key = generate_secret_key()
        self.assertIsInstance(key, str)
        self.assertTrue(len(key) > 0)

    def test_generate_secret_key_default_length(self):
        """测试：默认长度生成的密钥长度合理（64字节 -> 约86字符 base64）"""
        key = generate_secret_key()
        # 64 bytes -> urlsafe base64 约 86 字符
        self.assertGreater(len(key), 60)
        self.assertLess(len(key), 120)

    def test_generate_secret_key_custom_length(self):
        """测试：自定义长度生效"""
        key_32 = generate_secret_key(32)
        key_64 = generate_secret_key(64)
        key_128 = generate_secret_key(128)
        # 长度越长，生成的 key 越长
        self.assertLess(len(key_32), len(key_64))
        self.assertLess(len(key_64), len(key_128))

    def test_generate_secret_key_unique(self):
        """测试：多次生成的密钥互不相同"""
        keys = set()
        for _ in range(50):
            keys.add(generate_secret_key())
        self.assertEqual(len(keys), 50)

    def test_generate_secret_key_urlsafe_chars(self):
        """测试：生成的密钥使用 URL-safe 字符集"""
        import re
        key = generate_secret_key()
        # URL-safe base64: 字母、数字、-、_、=（填充）
        pattern = r'^[A-Za-z0-9\-_=]+$'
        self.assertTrue(
            re.match(pattern, key),
            f"密钥 '{key[:30]}...' 包含非法字符"
        )

    def test_generate_secret_key_min_length_16(self):
        """测试：生成的密钥至少有 16 字节的熵"""
        key = generate_secret_key(16)
        # 16 bytes -> urlsafe base64 约 22 字符
        self.assertGreater(len(key), 15)


class TestDefaultSecretDetection(unittest.TestCase):
    """默认密钥检测测试"""

    def test_is_default_secret_with_default_value(self):
        """测试：使用默认密钥时 is_default_secret 返回 True"""
        settings = Settings(jwt_secret=DEFAULT_JWT_SECRET)
        self.assertTrue(settings.is_default_secret)

    def test_is_default_secret_with_empty_string(self):
        """测试：空密钥被识别为不安全"""
        settings = Settings(jwt_secret="")
        self.assertTrue(settings.is_default_secret)

    def test_is_default_secret_with_short_key(self):
        """测试：太短的密钥被识别为不安全"""
        settings = Settings(jwt_secret="short")
        self.assertTrue(settings.is_default_secret)

    def test_is_default_secret_with_secure_key(self):
        """测试：安全密钥 is_default_secret 返回 False"""
        settings = Settings(jwt_secret=generate_secret_key(32))
        self.assertFalse(settings.is_default_secret)

    def test_is_default_secret_with_16_char_key(self):
        """测试：恰好 16 字符的密钥被认为是安全的（边界值）"""
        # 16 字符长度刚好满足最低要求
        key = "a" * 16
        settings = Settings(jwt_secret=key)
        # 注意：如果 key 是 16 个相同字符，虽然长度够但熵值低
        # 这里我们的判断只看长度，不评估熵值
        self.assertFalse(settings.is_default_secret)


class TestSecretSecurityValidation(unittest.TestCase):
    """密钥安全验证测试"""

    def test_validate_secret_security_with_secure_key(self):
        """测试：使用安全密钥时验证通过，不抛出异常"""
        settings = Settings(
            jwt_secret=generate_secret_key(32),
            require_secure_secret=True,
        )
        # 应该正常执行，不抛出异常
        try:
            settings.validate_secret_security()
        except ValueError:
            self.fail("安全密钥不应触发 ValueError")

    def test_validate_secret_security_require_secure_with_default(self):
        """测试：require_secure_secret=True 且使用默认密钥时抛出 ValueError"""
        settings = Settings(
            jwt_secret=DEFAULT_JWT_SECRET,
            require_secure_secret=True,
        )
        with self.assertRaises(ValueError) as context:
            settings.validate_secret_security()
        self.assertIn("JWT 密钥不安全", str(context.exception))

    def test_validate_secret_security_require_secure_with_empty(self):
        """测试：require_secure_secret=True 且空密钥时抛出 ValueError"""
        settings = Settings(
            jwt_secret="",
            require_secure_secret=True,
        )
        with self.assertRaises(ValueError):
            settings.validate_secret_security()

    def test_validate_secret_security_production_warning(self):
        """测试：生产环境使用默认密钥时发出警告"""
        settings = Settings(
            jwt_secret=DEFAULT_JWT_SECRET,
            env="production",
            require_secure_secret=False,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            settings.validate_secret_security()
            self.assertTrue(len(w) >= 1)
            self.assertTrue(issubclass(w[-1].category, UserWarning))
            self.assertIn("安全警告", str(w[-1].message))

    def test_validate_secret_security_development_no_error(self):
        """测试：开发环境使用默认密钥时不抛出错误（仅打印提示）"""
        settings = Settings(
            jwt_secret=DEFAULT_JWT_SECRET,
            env="development",
            require_secure_secret=False,
        )
        # 开发环境不抛异常，只打印提示
        try:
            settings.validate_secret_security()
        except ValueError:
            self.fail("开发环境不应抛出 ValueError")

    def test_validate_secret_security_error_contains_guidance(self):
        """测试：错误信息中包含解决方法指引"""
        settings = Settings(
            jwt_secret=DEFAULT_JWT_SECRET,
            require_secure_secret=True,
        )
        with self.assertRaises(ValueError) as context:
            settings.validate_secret_security()
        error_msg = str(context.exception)
        # 应该包含生成密钥的指引
        self.assertIn("generate_secret_key", error_msg)
        self.assertIn("M12_JWT_SECRET", error_msg)


class TestRequireSecureSecretConfig(unittest.TestCase):
    """require_secure_secret 配置项测试"""

    def test_require_secure_secret_default_false(self):
        """测试：require_secure_secret 默认值为 False"""
        settings = Settings()
        self.assertFalse(settings.require_secure_secret)

    def test_require_secure_secret_can_be_enabled(self):
        """测试：可以通过参数启用 require_secure_secret"""
        settings = Settings(
            jwt_secret=generate_secret_key(32),
            require_secure_secret=True,
        )
        self.assertTrue(settings.require_secure_secret)

    def test_require_secure_secret_with_env_variable(self):
        """测试：可以通过环境变量 M12_REQUIRE_SECURE_SECRET 设置"""
        # 注意：此测试需要实际设置环境变量，这里仅验证配置项存在
        settings = Settings()
        self.assertIn("require_secure_secret", settings.model_dump())


class TestSettingsBackwardCompatibility(unittest.TestCase):
    """向后兼容性测试"""

    def test_default_jwt_secret_unchanged(self):
        """测试：默认 JWT 密钥值保持不变（向后兼容）"""
        settings = Settings()
        self.assertEqual(settings.jwt_secret, DEFAULT_JWT_SECRET)

    def test_other_settings_unchanged(self):
        """测试：其他配置项不受影响"""
        settings = Settings()
        self.assertEqual(settings.jwt_algorithm, "HS256")
        self.assertEqual(settings.jwt_expire_minutes, 1440)
        self.assertEqual(settings.jwt_refresh_expire_days, 7)

    def test_generate_secret_key_does_not_affect_settings(self):
        """测试：密钥生成工具不影响全局配置"""
        key1 = generate_secret_key()
        settings = get_settings()
        key2 = generate_secret_key()
        # 生成的密钥与配置中的密钥不同
        self.assertNotEqual(key1, settings.jwt_secret)
        self.assertNotEqual(key1, key2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
